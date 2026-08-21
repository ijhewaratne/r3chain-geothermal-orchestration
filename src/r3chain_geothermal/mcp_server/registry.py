"""`GEO_REGISTRY` -- the bounded, concurrency-safe, `run_id`-keyed run store
(T5.1A).

Deliberately does NOT copy pandapipesAI's own `core/session.py` pattern
(`_SESSIONS: dict = {}`, no lock, random `uuid4()[:8]` IDs, unbounded,
comment: "In production: replace with Redis or file-based store" --
confirmed by direct read-only inspection of `repos/pandapipesAI`). Two
things make a stricter design both necessary and cheap here:

1. `run_id` is already a CONTENT hash (`workflow.core.compute_run_id` --
   unchanged, reused as-is), not a random session token -- identical
   inputs always resolve to the identical `run_id`. That determinism is
   what makes "safely reconcile the same run rather than overwrite
   silently" possible without inventing new identity logic, and what
   makes bounded eviction lossless: an evicted entry is always
   byte-identically reconstructable by calling `geo_run_workflow` again
   with the same two inputs.
2. Two threads calling `geo_run_workflow` with IDENTICAL input
   concurrently must never both execute `run_workflow()` +
   `write_workflow_artifacts()` (wasted duplicate physics, and a real race
   writing to the same artifact directory) -- `get_or_run()` groups every
   concurrent caller for the same `run_id` into one shared, REFERENCE-
   COUNTED `_InFlightRun` attempt (see `get_or_run`'s own docstring for
   why a plain per-`run_id` lock, released as soon as the first caller's
   `factory()` raises, is NOT enough on its own: a waiter that arrives in
   the narrow window right after that release could start a SECOND,
   genuinely concurrent `factory()` execution under a freshly-created
   replacement lock, racing the very waiters still queued on the first
   one).

Artifact reads (`read_artifact_text`) are similarly guarded: a read PINS
its `run_id` for the duration of the read, and eviction skips any
currently-pinned entry (falling through to the next-oldest unpinned one)
-- a concurrent `get_or_run` insertion can never delete a directory out
from under a read in progress. The bound is still HARD, though: if the
registry is already at `max_size` and every current entry happens to be
pinned, a new insertion BLOCKS (on a `threading.Condition` sharing the
master lock) until a pin is released, rather than being allowed to push
`len(entries)` past `max_size` -- eviction always runs, and completes,
BEFORE the new entry is published, so `len(entries) <= max_size` is an
invariant that holds at every observable point, never merely "usually."

`close()` (server shutdown, `atexit`/`SIGTERM`) must be able to interrupt
an insertion currently blocked waiting for room -- otherwise `close()`
could delete `root_dir` out from under a still-waiting insertion, or the
insertion could sit blocked forever after the registry it is waiting on
is already gone. `close()` therefore sets a lock-protected `_closed` flag
and wakes every waiter via the SAME condition variable; a waiter checks
`_closed` both before starting to wait and immediately upon every wake,
and unwinds cleanly (raising `RegistryClosedError`, never publishing its
entry) the moment it sees the registry closed -- removing its own
factory's now-unregistered `artifact_dir` itself, since `close()`'s own
`root_dir` removal races it and must not be relied on for that cleanup.
`new_artifact_dir()`/`get_or_run()` both refuse outright once `_closed`
is set -- no insertion or artifact-directory creation ever starts after
closure. `close()` itself is idempotent: a second call is a no-op.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..workflow import WorkflowAuditRecord
from .schemas import RunSummary

DEFAULT_MAX_REGISTRY_SIZE = 50


class RegistryClosedError(Exception):
    """Raised by `get_or_run()`/`new_artifact_dir()` once `close()` has
    been called -- including to a caller that was already blocked inside
    `_make_room_for_new_entry_locked()` waiting for room, which unwinds
    with this exception (and cleans up its own now-unregistered
    `artifact_dir`) rather than ever publishing its entry."""


@dataclass(frozen=True)
class RunEntry:
    run_id: str
    summary: RunSummary
    audit: WorkflowAuditRecord
    artifact_dir: Path
    """This run's own directory, server-owned -- `run_id` is always
    server-computed (a hash), never a caller-supplied path fragment, so
    there is no path-traversal surface here even though the directory
    name is derived from tool-call content. Never returned to a caller as
    a path -- only bare filenames are ever exposed (geo_get_artifact)."""
    artifact_filenames: frozenset[str]
    created_at: datetime


class _InFlightRun:
    """One shared attempt at producing `run_id`'s entry, referenced by
    every caller that arrived while it was in progress. `lock` serializes
    who actually calls `factory()` (the first arrival) versus who merely
    observes its outcome (every later arrival, which blocks on `lock`
    until the first is done, then reads the cached result/exception
    instead of calling `factory()` itself). `ref_count` is the number of
    callers still holding a reference to THIS specific attempt -- the
    attempt (and its table entry) is only ever removed once every one of
    them has been served, so a late-arriving waiter can never be handed a
    replacement/second attempt while earlier waiters are still queued on
    this one."""

    __slots__ = ("lock", "ref_count", "has_exception", "exception")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ref_count = 0
        self.has_exception = False
        self.exception: BaseException | None = None


class RunRegistry:
    """`OrderedDict[str, RunEntry]` under one master lock (guards ALL
    structural state: the entries table, the in-flight-attempt table, and
    the pinned-run-id table). Different `run_id`s never block each other
    for the EXPENSIVE part of the work -- `factory()` itself, and artifact
    file reads, both run OUTSIDE the master lock, guarded only by their
    own per-`run_id` coordination object."""

    def __init__(self, max_size: int = DEFAULT_MAX_REGISTRY_SIZE, root_dir: Path | None = None):
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size!r}")
        self._max_size = max_size
        self._root_dir = Path(root_dir) if root_dir is not None else Path(tempfile.mkdtemp(prefix="r3chain-mcp-"))
        self._root_dir.mkdir(parents=True, exist_ok=True)
        self._entries: "OrderedDict[str, RunEntry]" = OrderedDict()
        self._in_flight: dict[str, _InFlightRun] = {}
        self._pinned: dict[str, int] = {}
        """run_id -> number of reads currently in progress against it --
        eviction skips any run_id present here (module docstring)."""
        self._master_lock = threading.Lock()
        self._room_available = threading.Condition(self._master_lock)
        """Notified whenever a pin is released (`read_artifact_text`'s
        `finally`) OR the registry is closed -- wakes any insertion
        currently blocked in `_make_room_for_new_entry_locked` waiting for
        an evictable (unpinned) entry to appear, or for shutdown."""
        self._closed = False

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def __len__(self) -> int:
        with self._master_lock:
            return len(self._entries)

    def get(self, run_id: str) -> RunEntry | None:
        with self._master_lock:
            return self._entries.get(run_id)

    def new_artifact_dir(self, run_id: str) -> Path:
        """Allocates (creates) this run's own artifact directory under the
        registry's root -- called by a tool's factory BEFORE running the
        workflow, so write_workflow_artifacts() always has somewhere valid
        to write. Idempotent: safe to call again for a run_id whose
        directory already exists (the concurrent-duplicate-call path).

        Raises `RegistryClosedError` if the registry is already closed --
        no artifact directory is ever created after `close()`."""
        with self._master_lock:
            if self._closed:
                raise RegistryClosedError("registry is closed")
        run_dir = self._root_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def get_or_run(self, run_id: str, factory: Callable[[], RunEntry]) -> tuple[RunEntry, bool]:
        """Returns (entry, reused_existing_run). If `run_id` is already
        stored, returns it immediately without calling `factory`.

        Otherwise every concurrent caller for this `run_id` shares ONE
        `_InFlightRun` attempt (looked up/created atomically under the
        master lock, ref-counted so it is torn down only once every
        caller referencing it has been served): the first caller to
        acquire the attempt's own lock calls `factory()`; every other
        caller blocks on that SAME lock, then -- once it is free -- checks
        for a stored entry (the first caller succeeded) or a cached
        exception (the first caller's `factory()` raised) and returns/
        re-raises that SAME outcome WITHOUT calling `factory()` itself.
        This is what makes a failing factory execute exactly once per
        concurrent wave, with every waiter observing the identical
        failure, rather than each waiter retrying it independently as
        soon as the previous holder's lock is released."""
        while True:
            with self._master_lock:
                if self._closed:
                    raise RegistryClosedError("registry is closed")
                entry = self._entries.get(run_id)
                if entry is not None:
                    return entry, True
                in_flight = self._in_flight.get(run_id)
                if in_flight is None:
                    in_flight = _InFlightRun()
                    self._in_flight[run_id] = in_flight
                in_flight.ref_count += 1

            with in_flight.lock:
                with self._master_lock:
                    if self._closed:
                        self._release_in_flight_locked(run_id, in_flight)
                        raise RegistryClosedError("registry is closed")
                    entry = self._entries.get(run_id)
                    if entry is not None:
                        self._release_in_flight_locked(run_id, in_flight)
                        return entry, True
                    if in_flight.has_exception:
                        cached_exception = in_flight.exception
                        self._release_in_flight_locked(run_id, in_flight)
                        raise cached_exception
                    # Neither an entry nor a cached exception exists yet --
                    # we are the first (and only, by virtue of holding
                    # in_flight.lock) caller to actually invoke factory()
                    # for this attempt.

                try:
                    entry = factory()
                except Exception as exc:
                    with self._master_lock:
                        in_flight.has_exception = True
                        in_flight.exception = exc
                        self._release_in_flight_locked(run_id, in_flight)
                    raise

                try:
                    with self._master_lock:
                        # Room is made -- evicting as many unpinned entries
                        # as needed, BLOCKING if the registry is full and
                        # every current entry is pinned -- BEFORE the new
                        # entry is published, so len(self._entries) never
                        # exceeds max_size at any observable point (module
                        # docstring). The in-flight attempt (and this
                        # run_id's own in_flight.lock) stays held
                        # throughout the wait, so a fourth caller for the
                        # SAME run_id still reuses this attempt rather than
                        # starting a redundant one. Raises
                        # RegistryClosedError -- checked both before AND
                        # after every wait -- if the registry is closed
                        # while we are blocked here.
                        self._make_room_for_new_entry_locked()
                        self._entries[run_id] = entry
                        self._entries.move_to_end(run_id, last=True)
                except RegistryClosedError:
                    # This factory's own artifact_dir was never published
                    # (never added to self._entries) -- it is unregistered
                    # and must be cleaned up here; close()'s own root_dir
                    # removal races this and must not be relied on for it.
                    shutil.rmtree(entry.artifact_dir, ignore_errors=True)
                    raise
                finally:
                    with self._master_lock:
                        self._release_in_flight_locked(run_id, in_flight)
                return entry, False

    def _release_in_flight_locked(self, run_id: str, in_flight: "_InFlightRun") -> None:
        """Must be called with `_master_lock` held. Decrements the
        attempt's ref count; once it reaches zero -- meaning every caller
        that ever referenced THIS specific attempt has now been served,
        one way or another -- removes it from the in-flight table so a
        later, genuinely independent call starts a fresh attempt rather
        than ever observing a stale cached exception."""
        in_flight.ref_count -= 1
        if in_flight.ref_count <= 0 and self._in_flight.get(run_id) is in_flight:
            del self._in_flight[run_id]

    def read_artifact_text(self, run_id: str, filename: str) -> str | None:
        """Reads `filename`'s full text from `run_id`'s artifact directory
        with eviction of THIS `run_id` excluded for the duration of the
        read (module docstring's "pinning"). Returns `None` if `run_id`
        is not (or no longer) present -- never raises for that case; a
        genuine I/O error on an existing, non-evicted file still
        propagates normally."""
        with self._master_lock:
            entry = self._entries.get(run_id)
            if entry is None:
                return None
            self._pinned[run_id] = self._pinned.get(run_id, 0) + 1
        try:
            return (entry.artifact_dir / filename).read_text(encoding="utf-8")
        finally:
            with self._master_lock:
                remaining = self._pinned.get(run_id, 0) - 1
                if remaining <= 0:
                    self._pinned.pop(run_id, None)
                    # A pin was just fully released -- wake any insertion
                    # blocked in _make_room_for_new_entry_locked() waiting
                    # for an evictable entry to appear.
                    self._room_available.notify_all()
                else:
                    self._pinned[run_id] = remaining

    def _make_room_for_new_entry_locked(self) -> None:
        """Must be called with `_master_lock` held (the SAME lock backs
        `_room_available`, so `.wait()` below correctly releases it while
        blocked and reacquires it before returning). Evicts the
        least-recently-INSERTED entry (FIFO by insertion order, not LRU by
        access) as many times as needed to bring `len(self._entries)`
        strictly below `max_size` -- so the entry about to be inserted by
        the caller never pushes the registry past its bound -- skipping
        any entry currently PINNED by an in-progress `read_artifact_text()`
        call. If the registry is already full AND every current entry is
        pinned, this method BLOCKS on `_room_available` until a pin is
        released (notified by `read_artifact_text`'s `finally`) or the
        registry is closed (notified by `close()`), then retries -- the
        bound is a hard invariant, never merely "usually" respected, and
        eviction always completes before this method returns, i.e.
        strictly before the new entry is published. Removes each evicted
        entry's artifact_dir from disk too -- disk usage stays bounded,
        not only the in-memory count. Safe: an evicted entry is always
        reconstructable by calling geo_run_workflow again (module
        docstring).

        Raises `RegistryClosedError` -- checked both BEFORE and AFTER
        every `.wait()` (the top-of-loop check on each iteration serves
        both roles) -- if the registry is (or becomes) closed. Never
        blocks forever past a `close()` call."""
        while True:
            if self._closed:
                raise RegistryClosedError("registry is closed")
            while len(self._entries) >= self._max_size:
                evictable_run_id = next((rid for rid in self._entries if rid not in self._pinned), None)
                if evictable_run_id is None:
                    break
                evicted_entry = self._entries.pop(evictable_run_id)
                shutil.rmtree(evicted_entry.artifact_dir, ignore_errors=True)
            if len(self._entries) < self._max_size:
                return
            # Still full and every remaining entry is pinned -- block
            # until a pin is released or the registry is closed, then
            # re-check (_closed first) from the top.
            self._room_available.wait()

    def close(self) -> None:
        """Marks the registry closed and wakes every waiter blocked in
        `_make_room_for_new_entry_locked()` -- each observes `_closed` on
        its next wake and unwinds cleanly (`RegistryClosedError`, removing
        its own unregistered `artifact_dir`) rather than being deleted out
        from under it. Only then removes `root_dir` itself. Idempotent: a
        second call is a no-op (never raises, never double-removes)."""
        with self._master_lock:
            if self._closed:
                return
            self._closed = True
            self._room_available.notify_all()
        shutil.rmtree(self._root_dir, ignore_errors=True)
