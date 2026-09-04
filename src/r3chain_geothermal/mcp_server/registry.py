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

import hashlib
import json
import re
import shutil
import tempfile
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..workflow import (
    MANIFEST_FILENAME,
    WORKFLOW_RESULT_FILENAME,
    ManifestRecord,
    WorkflowAuditRecord,
    parse_workflow_result_json,
)
from ..workflow.joint_workflow_v2 import (
    JOINT_RESULT_FILENAME,
    JointWorkflowV2ManifestRecord,
    parse_joint_workflow_v2_result_json,
)
from .schemas import JointWorkflowSummary, RunSummary, summarize_joint_workflow_v2_result, summarize_workflow_result

DEFAULT_MAX_REGISTRY_SIZE = 50

_RUN_ID_PATTERN = re.compile(r"^r3chain-run-[0-9a-f]{16}$")
"""The exact shape workflow.core.compute_run_id() always produces --
docs/issues/mcp-persistent-run-registry.md (RR-003): the primary
path-traversal defense during rehydration is that a directory name failing
this pattern is never even considered a candidate run, let alone joined
into a filesystem path. Also reused by new_artifact_dir()/publish_
artifact_dir() as a defense-in-depth check on every run_id this class
itself ever turns into a path, not just ones read back from disk."""

_STAGING_DIR_PREFIX = ".staging-"


def _is_traversal_safe_path_component(value: str) -> bool:
    """A DELIBERATELY WEAKER check than `_RUN_ID_PATTERN` -- used by
    `new_artifact_dir`/`publish_artifact_dir`, where `run_id` is always
    either server-computed (`compute_run_id()`'s own real output) or, in
    this project's own unit tests, a simple synthetic string exercising
    the locking/eviction mechanics in isolation (e.g. `"x"`) -- neither
    case is untrusted external input, so the FULL `_RUN_ID_PATTERN` shape
    requirement would be needlessly restrictive here. What actually
    matters at this boundary is that `run_id` can never escape
    `root_dir` when joined into a path. `_rehydrate()` is the boundary
    that reads directory names back from disk (genuinely arbitrary,
    RR-003) and applies the FULL `_RUN_ID_PATTERN` there instead."""
    return bool(value) and "/" not in value and "\\" not in value and value not in (".", "..") and not value.startswith(".")


class RegistryClosedError(Exception):
    """Raised by `get_or_run()`/`new_artifact_dir()` once `close()` has
    been called -- including to a caller that was already blocked inside
    `_make_room_for_new_entry_locked()` waiting for room, which unwinds
    with this exception (and cleans up its own now-unregistered
    `artifact_dir`) rather than ever publishing its entry."""


@dataclass(frozen=True)
class RunEntry:
    run_id: str
    summary: "RunSummary | JointWorkflowSummary"
    audit: WorkflowAuditRecord
    artifact_dir: Path
    """This run's own directory, server-owned -- `run_id` is always
    server-computed (a hash), never a caller-supplied path fragment, so
    there is no path-traversal surface here even though the directory
    name is derived from tool-call content. Never returned to a caller as
    a path -- only bare filenames are ever exposed (geo_get_artifact)."""
    artifact_filenames: frozenset[str]
    created_at: datetime
    run_type: str = "canonical"
    """MCP-006 (docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
    Phase 6): `"canonical"` or `"joint_site_connection"` -- copied
    straight from the published bundle's own `manifest.json::run_type`
    field (`ManifestRecord`/`JointWorkflowV2ManifestRecord`), so a caller
    holding a `RunEntry` can always tell which kind of run it is without
    inspecting `summary`'s own type. Defaults to `"canonical"` so every
    existing keyword-argument construction call site (which never
    mentions this field) is completely unaffected."""


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

    def __init__(
        self, max_size: int = DEFAULT_MAX_REGISTRY_SIZE, root_dir: Path | None = None, *, persistent: bool = False,
        max_age_days: float | None = None,
    ):
        """`persistent=False` (the default) is the ORIGINAL, unchanged
        behavior for every existing caller: an ephemeral root (a fresh
        `tempfile.mkdtemp()` if `root_dir` is omitted, or a caller-supplied
        directory used for this process's lifetime only), deleted by
        `close()`, no rehydration attempted.

        `persistent=True` (docs/issues/mcp-persistent-run-registry.md,
        RR-001..RR-003) requires an explicit `root_dir` (raises ValueError
        otherwise -- a persistent registry needs a STABLE location, never
        an auto-generated temp path) and:
        - `close()` does NOT delete `root_dir` -- completed runs survive
          the process.
        - `__init__` scans `root_dir`'s existing children and rehydrates
          any that validate as complete, correctly-named, hash-consistent
          run bundles into `self._entries` (RR-003) -- see
          `_rehydrate` for the exact validation steps. Anything
          that fails validation is skipped, never raises, and is recorded
          in `self.rehydration_warnings` (RR-003 point 6).

        `max_age_days` (R3CHAIN_GEOTHERMAL_PROTOTYPE_COMPLETION_SPEC.md
        Phase 6, RR-005): an OPTIONAL age-based retention control,
        orthogonal to `max_size`'s own count-based LRU bound (already the
        registry's "max retained runs" control -- eviction under that
        bound already removes the evicted run's on-disk directory too,
        module docstring). `None` (the default) disables age-based
        retention entirely -- every existing caller, and every run this
        session has already produced, is completely unaffected; this
        control MUST NOT unexpectedly destroy acceptance evidence, so it
        never activates unless a caller explicitly opts in with a
        positive value. When set, pruning happens ONLY during
        `_rehydrate()` at startup (never a running background timer that
        could delete a run out from under a concurrent reader): a
        rehydration candidate whose OWN `manifest.created_at` is older
        than `max_age_days` days (compared against `datetime.now(timezone
        .utc)` at construction time) is deleted from disk and never
        registered, rather than skipped-but-left-behind the way a
        genuinely corrupt candidate is -- recorded in
        `self.rehydration_warnings` all the same, so a caller can always
        see what happened and why, never a silent deletion."""
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size!r}")
        if persistent and root_dir is None:
            raise ValueError("persistent=True requires an explicit root_dir -- a stable location, not a temp path")
        if max_age_days is not None and max_age_days <= 0:
            raise ValueError(f"max_age_days must be > 0 when set, got {max_age_days!r}")
        self._max_size = max_size
        self._persistent = persistent
        self._max_age_days = max_age_days
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
        self.rehydration_warnings: list[str] = []
        """One human-readable entry per skipped/corrupt candidate found
        during startup rehydration (RR-003 point 6) -- empty for a
        non-persistent registry, or a persistent one whose root_dir was
        previously empty. Never raises; a diagnostic, not an error."""
        if self._persistent:
            self._rehydrate()

    @property
    def max_age_days(self) -> float | None:
        return self._max_age_days

    @property
    def persistent(self) -> bool:
        return self._persistent

    def _rehydrate(self) -> None:
        """Called exactly once, from `__init__`, before this instance is
        ever shared with another thread -- no locking needed here (module
        docstring's concurrency guarantees only apply once a registry is
        actually in use). Scans `root_dir`'s immediate children (RR-003
        point 1: ONLY direct children, never recursing) and:

        - removes any leftover `.staging-*`-prefixed directory outright
          (RR-004: identifiable, safely cleanable -- a staging directory
          is by construction never a published run, whatever it contains).
        - skips (silently, no warning -- not a candidate at all) anything
          whose name does not match `_RUN_ID_PATTERN` exactly.
        - for everything else, attempts full validation via
          `_load_run_entry` (manifest schema + run_id match + per-file
          hash verification + workflow_result.json parseability); any
          failure is caught, recorded in `self.rehydration_warnings`, and
          that directory is left untouched on disk (never deleted merely
          for failing to rehydrate -- only `.staging-*` leftovers are
          ever removed here) but never registered as a valid run.
        Never raises -- a corrupt bundle must never crash server startup
        (RR-003 point 5)."""
        for child in sorted(self._root_dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(_STAGING_DIR_PREFIX):
                shutil.rmtree(child, ignore_errors=True)
                continue
            if not _RUN_ID_PATTERN.match(child.name):
                continue
            run_id = child.name
            try:
                entry = self._load_run_entry(run_id, child)
            except Exception as exc:  # noqa: BLE001 -- must never crash server startup
                self.rehydration_warnings.append(f"{run_id}: skipped during rehydration ({exc})")
                continue
            if self._max_age_days is not None:
                age_days = (datetime.now(timezone.utc) - entry.created_at).total_seconds() / 86400.0
                if age_days > self._max_age_days:
                    shutil.rmtree(child, ignore_errors=True)
                    self.rehydration_warnings.append(
                        f"{run_id}: pruned during rehydration (age {age_days:.2f} days exceeds "
                        f"max_age_days={self._max_age_days!r})"
                    )
                    continue
            self._entries[run_id] = entry
            self._entries.move_to_end(run_id, last=True)

    def _load_run_entry(self, run_id: str, run_dir: Path) -> RunEntry:
        """Raises (never caught here -- `_rehydrate` is the one caller
        and does the catching) on any validation failure. Every raised
        message is specific enough to be useful in
        `self.rehydration_warnings` without ever including file content.

        MCP-007 (docs/specifications/R3CHAIN_CORRECTED_JOINT_SITE_CONNECTION_IMPLEMENTATION_SPEC.md
        Phase 6): the raw manifest JSON is read ONCE, and its own
        `run_type` field (defaulting to `"canonical"` for a bundle written
        before this field existed) decides which typed manifest model,
        result-parser and summarizer to use -- never inferred from which
        files happen to be present."""
        manifest_path = run_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise ValueError(f"missing {MANIFEST_FILENAME}")
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        run_type = manifest_raw.get("run_type", "canonical")
        if run_type == "joint_site_connection":
            return self._load_joint_run_entry(run_id, run_dir, manifest_raw)
        return self._load_canonical_run_entry(run_id, run_dir, manifest_raw)

    def _load_canonical_run_entry(self, run_id: str, run_dir: Path, manifest_raw: dict) -> RunEntry:
        manifest = ManifestRecord(**manifest_raw)
        if manifest.run_id != run_id:
            raise ValueError(f"manifest run_id {manifest.run_id!r} does not match directory name {run_id!r}")
        for filename, record in manifest.files.items():
            file_path = run_dir / filename
            if not file_path.is_file():
                raise ValueError(f"declared file {filename!r} is missing on disk")
            actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_hash != record.byte_sha256:
                raise ValueError(f"{filename!r} on-disk byte hash does not match the manifest's own record")
        workflow_result_path = run_dir / WORKFLOW_RESULT_FILENAME
        if not workflow_result_path.is_file():
            raise ValueError(f"missing {WORKFLOW_RESULT_FILENAME}")
        boundary = parse_workflow_result_json(workflow_result_path.read_text(encoding="utf-8"))
        artifact_filenames = frozenset(manifest.files) | {MANIFEST_FILENAME}
        summary = summarize_workflow_result(boundary, artifact_filenames, reused_existing_run=True)
        summary = summary.model_copy(update={"bundle_scientific_sha256": manifest.bundle_scientific_sha256})
        return RunEntry(
            run_id=run_id, summary=summary, audit=boundary.audit,
            artifact_dir=run_dir, artifact_filenames=artifact_filenames, created_at=manifest.created_at,
            run_type="canonical",
        )

    def _load_joint_run_entry(self, run_id: str, run_dir: Path, manifest_raw: dict) -> RunEntry:
        manifest = JointWorkflowV2ManifestRecord(**manifest_raw)
        if manifest.run_id != run_id:
            raise ValueError(f"manifest run_id {manifest.run_id!r} does not match directory name {run_id!r}")
        for filename, record in manifest.files.items():
            file_path = run_dir / filename
            if not file_path.is_file():
                raise ValueError(f"declared file {filename!r} is missing on disk")
            actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_hash != record.byte_sha256:
                raise ValueError(f"{filename!r} on-disk byte hash does not match the manifest's own record")
        joint_result_path = run_dir / JOINT_RESULT_FILENAME
        if not joint_result_path.is_file():
            raise ValueError(f"missing {JOINT_RESULT_FILENAME}")
        boundary = parse_joint_workflow_v2_result_json(joint_result_path.read_text(encoding="utf-8"))
        artifact_filenames = frozenset(manifest.files) | {MANIFEST_FILENAME}
        summary = summarize_joint_workflow_v2_result(boundary, artifact_filenames, reused_existing_run=True)
        summary = summary.model_copy(update={"bundle_scientific_sha256": manifest.bundle_scientific_sha256})
        return RunEntry(
            run_id=run_id, summary=summary, audit=boundary.audit,
            artifact_dir=run_dir, artifact_filenames=artifact_filenames, created_at=manifest.created_at,
            run_type="joint_site_connection",
        )

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
        """Allocates (creates) a STAGING directory for this run under the
        registry's root -- called by a tool's factory BEFORE running the
        workflow, so write_workflow_artifacts() always has somewhere valid
        to write. NOT the run's final, `run_id`-named directory (RR-002,
        docs/issues/mcp-persistent-run-registry.md): the caller must call
        `publish_artifact_dir(run_id, this_path)` once every file
        (including manifest.json, written last by write_workflow_artifacts)
        exists, to atomically rename staging -> final. A crash or
        exception between this call and that one leaves only an orphaned
        `.staging-*`-prefixed directory -- never anything visible under
        the real `run_id` name, and never returned as a completed run by
        rehydration (`_rehydrate` skips anything not matching
        `_RUN_ID_PATTERN` outright).

        Each call gets a fresh, uniquely-suffixed staging directory (even
        for the same `run_id`) so a leftover staging directory from a
        previous crashed attempt is never reused/collided with.

        Raises `RegistryClosedError` if the registry is already closed --
        no artifact directory is ever created after `close()`. Raises
        `ValueError` if `run_id` is not a safe single path component
        (empty, contains a path separator, or is `.`/`..`/dotfile-shaped)
        -- defense in depth, since this method turns `run_id` directly
        into a path component."""
        if not _is_traversal_safe_path_component(run_id):
            raise ValueError(f"run_id {run_id!r} is not a safe path component")
        with self._master_lock:
            if self._closed:
                raise RegistryClosedError("registry is closed")
        staging_dir = self._root_dir / f"{_STAGING_DIR_PREFIX}{run_id}-{uuid.uuid4().hex[:8]}"
        staging_dir.mkdir(parents=True, exist_ok=False)
        return staging_dir

    def publish_artifact_dir(self, run_id: str, staging_dir: Path) -> Path:
        """Validates `staging_dir` contains a complete, self-consistent
        bundle (a real `manifest.json` whose own `ManifestRecord` model
        validation passes, run_id matching, every declared file present)
        and then ATOMICALLY renames it to `root_dir / run_id` (RR-002) --
        a single filesystem rename on the same volume, so any observer
        either sees no `run_id`-named directory at all, or the complete,
        already-fully-written one; never a partial one. Returns the final
        path.

        Raises `ValueError` if `staging_dir` fails validation (never
        renamed in that case -- the caller's own factory exception
        propagates normally; the staging directory is left in place for
        forensic inspection, exactly the "identifiable, safely cleanable"
        abandoned-staging-directory case RR-004 describes). Raises
        `RegistryClosedError` if the registry is already closed.

        MCP-007: `manifest.json`'s own `run_type` field selects whether
        this is validated as a canonical `ManifestRecord` or a
        `JointWorkflowV2ManifestRecord` -- exactly the same branch
        `_load_run_entry` uses for rehydration, so a staged joint-workflow
        bundle (whose manifest legitimately carries fields/values a
        canonical `ManifestRecord` would reject) is validated against its
        own correct contract."""
        if not _is_traversal_safe_path_component(run_id):
            raise ValueError(f"run_id {run_id!r} is not a safe path component")
        with self._master_lock:
            if self._closed:
                raise RegistryClosedError("registry is closed")
        manifest_path = staging_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise ValueError(f"staging directory for {run_id!r} has no {MANIFEST_FILENAME} -- refusing to publish")
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_cls = JointWorkflowV2ManifestRecord if manifest_raw.get("run_type") == "joint_site_connection" else ManifestRecord
        manifest = manifest_cls(**manifest_raw)
        if manifest.run_id != run_id:
            raise ValueError(f"manifest.json run_id {manifest.run_id!r} does not match expected {run_id!r}")
        for filename in manifest.files:
            if not (staging_dir / filename).is_file():
                raise ValueError(f"staging directory for {run_id!r} is missing declared file {filename!r}")
        final_dir = self._root_dir / run_id
        staging_dir.rename(final_dir)
        return final_dir

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
        from under it. Idempotent: a second call is a no-op (never raises,
        never double-removes).

        For a `persistent=False` registry (the original, unchanged
        behavior): removes `root_dir` itself -- the ephemeral root belongs
        entirely to this instance.

        For `persistent=True` (RR-001): does NOT remove `root_dir` --
        completed runs are meant to survive this process, that is the
        entire point. Any per-run cleanup (retention/eviction) is handled
        by `_make_room_for_new_entry_locked`'s existing bound, not by
        `close()`."""
        with self._master_lock:
            if self._closed:
                return
            self._closed = True
            self._room_available.notify_all()
        if not self._persistent:
            shutil.rmtree(self._root_dir, ignore_errors=True)
