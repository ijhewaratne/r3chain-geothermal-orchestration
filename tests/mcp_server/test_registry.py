"""Full test matrix for mcp_server/registry.py -- GEO_REGISTRY's bound,
concurrency-safety, and reuse-instead-of-rerun lifecycle (T5.1A)."""
from __future__ import annotations

import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from r3chain_geothermal.mcp_server.registry import RegistryClosedError, RunEntry, RunRegistry
from r3chain_geothermal.mcp_server.schemas import RunSummary


def _summary(run_id: str) -> RunSummary:
    return RunSummary(
        run_id=run_id, workflow_status="completed", preferred_candidate_id="C1",
        ranked=[], infeasible=[], stopping_failure_code=None, warnings=[],
        artifact_filenames=[], bundle_scientific_sha256="x" * 64, reused_existing_run=False,
    )


def _entry(registry: RunRegistry, run_id: str) -> RunEntry:
    run_dir = registry.new_artifact_dir(run_id)
    return RunEntry(
        run_id=run_id, summary=_summary(run_id), audit=None,  # type: ignore[arg-type]
        artifact_dir=run_dir, artifact_filenames=frozenset(), created_at=datetime.now(timezone.utc),
    )


def _entry_with_file(registry: RunRegistry, run_id: str, filename: str, content: str) -> RunEntry:
    run_dir = registry.new_artifact_dir(run_id)
    (run_dir / filename).write_text(content, encoding="utf-8")
    return RunEntry(
        run_id=run_id, summary=_summary(run_id), audit=None,  # type: ignore[arg-type]
        artifact_dir=run_dir, artifact_filenames=frozenset({filename}), created_at=datetime.now(timezone.utc),
    )


def _wait_until_ref_count(registry: RunRegistry, run_id: str, expected: int, timeout: float = 5.0) -> None:
    """Polls the registry's internal in-flight ref count for `run_id`
    until it reaches `expected` -- avoids sleep-based flakiness when a
    test needs to know "every waiter has actually queued up" before
    releasing them."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        in_flight = registry._in_flight.get(run_id)
        if in_flight is not None and in_flight.ref_count >= expected:
            return
        time.sleep(0.005)
    actual = registry._in_flight.get(run_id)
    raise AssertionError(f"ref_count for {run_id!r} never reached {expected}; last seen: {actual}")


def test_get_returns_none_for_unknown_run_id():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td))
        assert registry.get("does-not-exist") is None


def test_get_or_run_stores_and_returns_a_new_entry():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td))
        entry, reused = registry.get_or_run("run-a", lambda: _entry(registry, "run-a"))
        assert reused is False
        assert entry.run_id == "run-a"
        assert registry.get("run-a") is entry


def test_get_or_run_reuses_an_existing_entry_without_calling_factory_again():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td))
        call_count = {"n": 0}

        def factory():
            call_count["n"] += 1
            return _entry(registry, "run-a")

        entry1, reused1 = registry.get_or_run("run-a", factory)
        entry2, reused2 = registry.get_or_run("run-a", factory)
        assert reused1 is False
        assert reused2 is True
        assert entry1 is entry2
        assert call_count["n"] == 1


def test_bound_evicts_least_recently_inserted_entry():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=2, root_dir=Path(td))
        registry.get_or_run("a", lambda: _entry(registry, "a"))
        registry.get_or_run("b", lambda: _entry(registry, "b"))
        registry.get_or_run("c", lambda: _entry(registry, "c"))
        assert len(registry) == 2
        assert registry.get("a") is None  # evicted (inserted first)
        assert registry.get("b") is not None
        assert registry.get("c") is not None


def test_eviction_removes_the_evicted_entrys_artifact_directory_from_disk():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=1, root_dir=Path(td))
        entry_a, _ = registry.get_or_run("a", lambda: _entry(registry, "a"))
        assert entry_a.artifact_dir.exists()
        registry.get_or_run("b", lambda: _entry(registry, "b"))
        assert not entry_a.artifact_dir.exists()


def test_re_running_an_evicted_run_id_recreates_it_cleanly():
    """The determinism argument this eviction policy relies on: an evicted
    run_id is always safely reconstructable by calling get_or_run again."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=1, root_dir=Path(td))
        registry.get_or_run("a", lambda: _entry(registry, "a"))
        registry.get_or_run("b", lambda: _entry(registry, "b"))  # evicts "a"
        assert registry.get("a") is None
        entry_a_again, reused = registry.get_or_run("a", lambda: _entry(registry, "a"))
        assert reused is False
        assert entry_a_again.run_id == "a"


def test_max_size_must_be_at_least_one():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(ValueError):
            RunRegistry(max_size=0, root_dir=Path(td))


def test_concurrent_duplicate_calls_run_the_factory_exactly_once():
    """N threads calling get_or_run with the IDENTICAL run_id concurrently
    -- the factory (a call-counted stand-in for run_workflow() +
    write_workflow_artifacts()) must execute exactly once; every thread
    must receive the SAME RunEntry."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=10, root_dir=Path(td))
        call_count = {"n": 0}
        call_lock = threading.Lock()

        def factory():
            with call_lock:
                call_count["n"] += 1
            time.sleep(0.05)  # widen the race window
            return _entry(registry, "shared-run-id")

        results: list[RunEntry] = []
        results_lock = threading.Lock()

        def worker():
            entry, _reused = registry.get_or_run("shared-run-id", factory)
            with results_lock:
                results.append(entry)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert call_count["n"] == 1
        assert len(results) == 12
        assert all(r is results[0] for r in results)


def test_concurrent_calls_for_distinct_run_ids_do_not_block_each_other():
    """Different run_ids must never contend for the same lock -- proven by
    running several DISTINCT slow factories concurrently and asserting the
    wall-clock time is close to one factory's duration, not the sum."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=10, root_dir=Path(td))

        def slow_factory(run_id: str):
            def _factory():
                time.sleep(0.2)
                return _entry(registry, run_id)
            return _factory

        threads = [
            threading.Thread(target=lambda i=i: registry.get_or_run(f"distinct-{i}", slow_factory(f"distinct-{i}")))
            for i in range(5)
        ]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        elapsed = time.monotonic() - start
        assert elapsed < 0.6, f"distinct run_ids appear to have serialized: {elapsed:.2f}s for 5x0.2s factories"
        for i in range(5):
            assert registry.get(f"distinct-{i}") is not None


def test_a_raising_factory_does_not_store_an_entry_and_does_not_leak_its_lock():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td))

        def failing_factory():
            raise RuntimeError("simulated defect")

        with pytest.raises(RuntimeError):
            registry.get_or_run("will-fail", failing_factory)
        assert registry.get("will-fail") is None
        assert "will-fail" not in registry._in_flight  # no stale in-flight entry

        # A second attempt for the SAME run_id must be able to retry cleanly
        # (proving no leaked/stuck lock from the first, failed attempt).
        entry, reused = registry.get_or_run("will-fail", lambda: _entry(registry, "will-fail"))
        assert reused is False
        assert entry.run_id == "will-fail"


def test_registry_root_dir_is_created_and_used():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "nested" / "root"
        registry = RunRegistry(max_size=5, root_dir=root)
        assert root.exists()
        entry, _ = registry.get_or_run("a", lambda: _entry(registry, "a"))
        assert entry.artifact_dir.parent == root


def test_close_removes_the_entire_root_directory():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "root"
        registry = RunRegistry(max_size=5, root_dir=root)
        registry.get_or_run("a", lambda: _entry(registry, "a"))
        assert root.exists()
        registry.close()
        assert not root.exists()


# ── Hardening: a failed factory's concurrent wave, deterministic ────────────
def test_concurrent_wave_against_a_blocking_failing_factory_runs_it_exactly_once_and_every_waiter_gets_the_same_failure():
    """The scenario the earlier finally-pop-then-release design got wrong:
    N threads call get_or_run for the SAME run_id, whose factory blocks
    (deterministically released only once every thread has queued up,
    proven via ref-count polling, not a sleep guess) and then fails.
    Requirements: the factory executes exactly once; every waiter observes
    the IDENTICAL failure (same exception instance); no stale in-flight
    entry remains afterward; a later, independent call can retry cleanly."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=10, root_dir=Path(td))
        call_count = {"n": 0}
        call_lock = threading.Lock()
        release_event = threading.Event()
        thread_count = 8

        def blocking_failing_factory():
            with call_lock:
                call_count["n"] += 1
            assert release_event.wait(timeout=5), "factory was not released in time"
            raise RuntimeError("simulated deterministic failure")

        results: list[Exception] = []
        results_lock = threading.Lock()

        def worker():
            try:
                registry.get_or_run("shared-failing-run", blocking_failing_factory)
            except RuntimeError as exc:
                with results_lock:
                    results.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()

        _wait_until_ref_count(registry, "shared-failing-run", thread_count)
        release_event.set()

        for t in threads:
            t.join(timeout=5)

        assert call_count["n"] == 1, "the blocking factory must execute exactly once for the whole wave"
        assert len(results) == thread_count
        assert all(exc is results[0] for exc in results), "every waiter must observe the SAME exception instance"

        # No stale in-flight entry remains.
        assert registry.get("shared-failing-run") is None
        assert "shared-failing-run" not in registry._in_flight

        # A later, independent request can retry.
        entry, reused = registry.get_or_run("shared-failing-run", lambda: _entry(registry, "shared-failing-run"))
        assert reused is False
        assert entry.run_id == "shared-failing-run"


def test_a_second_independent_wave_after_a_failure_does_not_see_the_stale_exception():
    """A follow-up wave (not part of the original failing one) must get a
    fresh factory execution, never the old cached exception."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=10, root_dir=Path(td))

        with pytest.raises(RuntimeError):
            registry.get_or_run("x", lambda: (_ for _ in ()).throw(RuntimeError("first failure")))
        assert "x" not in registry._in_flight

        call_count = {"n": 0}

        def second_wave_factory():
            call_count["n"] += 1
            return _entry(registry, "x")

        threads_results = []

        def worker():
            threads_results.append(registry.get_or_run("x", second_wave_factory))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert call_count["n"] == 1, "the second wave's factory must also run exactly once"
        assert len(threads_results) == 5
        assert all(entry.run_id == "x" for entry, _ in threads_results)


# ── Hardening: artifact reads pinned against concurrent eviction ────────────
def test_read_artifact_text_returns_the_correct_content():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td))
        registry.get_or_run("a", lambda: _entry_with_file(registry, "a", "test.txt", "hello world"))
        assert registry.read_artifact_text("a", "test.txt") == "hello world"


def test_read_artifact_text_returns_none_for_unknown_run_id():
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=5, root_dir=Path(td))
        assert registry.read_artifact_text("does-not-exist", "test.txt") is None


def test_artifact_read_pins_its_run_id_and_eviction_skips_it_while_pinned(monkeypatch):
    """Deterministic regression test for the TOCTOU bug this hardening
    round closes: a read in progress must never have its directory
    deleted by a concurrent get_or_run() insertion pushing the registry
    over its bound."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=2, root_dir=Path(td))
        entry_a, _ = registry.get_or_run("a", lambda: _entry_with_file(registry, "a", "test.txt", "hello world"))
        registry.get_or_run("b", lambda: _entry_with_file(registry, "b", "test.txt", "b content"))
        assert len(registry) == 2  # within bound, nothing evicted yet

        read_started = threading.Event()
        release_read = threading.Event()
        real_read_text = Path.read_text

        def paused_read_text(self, *args, **kwargs):
            if self == entry_a.artifact_dir / "test.txt":
                read_started.set()
                assert release_read.wait(timeout=5), "read was not released in time"
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", paused_read_text)

        result_holder: dict[str, str] = {}

        def reader():
            result_holder["text"] = registry.read_artifact_text("a", "test.txt")

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()
        assert read_started.wait(timeout=5)

        # Insert a THIRD run while "a"'s read is in progress and the
        # registry is already at its bound (2) -- eviction must skip the
        # pinned "a" and remove "b" (the next-oldest unpinned entry)
        # instead, never deleting "a"'s directory mid-read.
        registry.get_or_run("c", lambda: _entry_with_file(registry, "c", "test.txt", "c content"))

        assert entry_a.artifact_dir.exists(), "the pinned entry's directory must survive eviction pressure"
        assert registry.get("a") is not None

        release_read.set()
        reader_thread.join(timeout=5)

        assert result_holder["text"] == "hello world"


def test_concurrent_reads_and_evictions_never_raise_or_return_corrupt_content():
    """A broader concurrency regression sweep: many threads simultaneously
    reading artifacts for several run_ids while other threads insert new
    runs (triggering eviction) -- no exception, no truncated/mismatched
    content ever observed."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=3, root_dir=Path(td))
        run_ids = [f"run-{i}" for i in range(6)]
        expected_content = {run_id: f"content-for-{run_id}" * 50 for run_id in run_ids}
        for run_id in run_ids:
            registry.get_or_run(
                run_id, lambda rid=run_id: _entry_with_file(registry, rid, "test.txt", expected_content[rid]),
            )

        errors: list[BaseException] = []
        errors_lock = threading.Lock()

        def reader(run_id: str):
            try:
                for _ in range(20):
                    text = registry.read_artifact_text(run_id, "test.txt")
                    if text is not None:
                        assert text == expected_content[run_id], f"corrupt content for {run_id}"
            except BaseException as exc:  # noqa: BLE001 -- record any failure, don't let a thread die silently
                with errors_lock:
                    errors.append(exc)

        def inserter(i: int):
            try:
                run_id = f"run-extra-{i}"
                content = f"extra-content-{i}" * 50
                registry.get_or_run(run_id, lambda: _entry_with_file(registry, run_id, "test.txt", content))
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=reader, args=(rid,)) for rid in run_ids]
        threads += [threading.Thread(target=inserter, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"unexpected errors during concurrent read/evict: {errors}"


# ── Hardening round 3: the bound is a hard invariant, never deferred ────────
def test_insertion_blocks_when_full_and_the_only_entry_is_pinned_then_proceeds_after_release(monkeypatch):
    """The exact deterministic scenario requested: pin run A, begin
    inserting B (max_size=1, so A is the only eviction candidate and it is
    pinned) -- prove B blocks and the registry stays at size 1, release
    A's pin, then prove B completes and A's directory is removed."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=1, root_dir=Path(td))
        entry_a, _ = registry.get_or_run("a", lambda: _entry_with_file(registry, "a", "test.txt", "A content"))
        assert len(registry) == 1

        read_started = threading.Event()
        release_read = threading.Event()
        real_read_text = Path.read_text

        def paused_read_text(self, *args, **kwargs):
            if self == entry_a.artifact_dir / "test.txt":
                read_started.set()
                assert release_read.wait(timeout=5), "read was not released in time"
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", paused_read_text)

        # Pin A via a slow read, running in its own thread.
        reader_thread = threading.Thread(target=lambda: registry.read_artifact_text("a", "test.txt"))
        reader_thread.start()
        assert read_started.wait(timeout=5)

        # Begin inserting B concurrently -- must BLOCK: max_size=1, A is
        # the only entry, and A is pinned, so there is no room.
        b_started = threading.Event()
        b_done = threading.Event()
        b_result: dict = {}

        def insert_b():
            b_started.set()
            entry, reused = registry.get_or_run("b", lambda: _entry_with_file(registry, "b", "test.txt", "B content"))
            b_result["entry"] = entry
            b_result["reused"] = reused
            b_done.set()

        b_thread = threading.Thread(target=insert_b)
        b_thread.start()
        assert b_started.wait(timeout=5)

        # Prove B waits and the registry remains size 1 -- checked
        # several times over a real interval, not just once immediately
        # after starting the thread.
        for _ in range(5):
            assert not b_done.is_set(), "insertion of B must block while A is pinned and the registry is full"
            assert len(registry) == 1
            assert registry.get("a") is not None
            assert entry_a.artifact_dir.exists()
            time.sleep(0.05)

        # Release A's pin.
        release_read.set()
        reader_thread.join(timeout=5)

        # B must now complete.
        assert b_done.wait(timeout=5), "B never completed after A's pin was released"
        b_thread.join(timeout=5)
        assert b_result["reused"] is False
        assert b_result["entry"].run_id == "b"

        # A's directory must be removed; B is the sole entry; bound held.
        assert len(registry) == 1
        assert registry.get("a") is None
        assert not entry_a.artifact_dir.exists()
        assert registry.get("b") is not None


def test_bound_is_never_exceeded_even_transiently_under_concurrent_pinned_inserts():
    """A broader stress variant: with max_size=1, repeatedly pin the
    current sole entry while inserting new ones from several threads --
    len(registry) must never be observed above max_size at any point."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=1, root_dir=Path(td))
        registry.get_or_run("seed", lambda: _entry_with_file(registry, "seed", "test.txt", "seed content"))

        stop = threading.Event()
        violations: list[int] = []
        violations_lock = threading.Lock()

        def size_watcher():
            while not stop.is_set():
                size = len(registry)
                if size > registry.max_size:
                    with violations_lock:
                        violations.append(size)

        def inserter(i: int):
            run_id = f"run-{i}"
            registry.get_or_run(run_id, lambda: _entry_with_file(registry, run_id, "test.txt", f"content-{i}"))

        watcher_thread = threading.Thread(target=size_watcher)
        watcher_thread.start()
        inserter_threads = [threading.Thread(target=inserter, args=(i,)) for i in range(15)]
        for t in inserter_threads:
            t.start()
        for t in inserter_threads:
            t.join(timeout=10)
        stop.set()
        watcher_thread.join(timeout=5)

        assert violations == [], f"registry exceeded max_size={registry.max_size}: observed sizes {violations}"
        assert len(registry) == 1


def _wait_until_condition_has_waiters(condition: threading.Condition, expected: int, timeout: float = 5.0) -> None:
    """Polls a Condition's internal waiter queue until it holds at least
    `expected` entries -- lets a test know a thread is genuinely blocked
    inside `.wait()`, not merely "the thread has started", without
    relying on a sleep-based guess."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(condition._waiters) >= expected:  # CPython implementation detail, stable across 3.x
            return
        time.sleep(0.005)
    raise AssertionError(f"condition never reached {expected} waiter(s); last seen: {len(condition._waiters)}")


def test_close_wakes_a_blocked_insertion_root_is_removed_and_close_is_idempotent(monkeypatch):
    """The exact deterministic scenario requested: pin A, block B (via
    max_size=1 with A pinned, leaving no room), call close() WHILE B is
    still blocked -- verify B terminates within a bounded timeout with
    RegistryClosedError, no worker thread remains alive, the registry's
    root directory (including B's own unregistered artifact_dir, which
    get_or_run() itself cleans up on this path) is removed, and a second
    close() is harmless."""
    with tempfile.TemporaryDirectory() as td:
        registry = RunRegistry(max_size=1, root_dir=Path(td))
        entry_a, _ = registry.get_or_run("a", lambda: _entry_with_file(registry, "a", "test.txt", "A content"))

        read_started = threading.Event()
        release_read = threading.Event()
        real_read_text = Path.read_text

        def paused_read_text(self, *args, **kwargs):
            if self == entry_a.artifact_dir / "test.txt":
                read_started.set()
                release_read.wait(timeout=5)
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", paused_read_text)

        def reader_worker():
            try:
                registry.read_artifact_text("a", "test.txt")
            except Exception:
                pass  # root_dir may already be gone once close() has run -- not this test's concern

        reader_thread = threading.Thread(target=reader_worker)
        reader_thread.start()
        assert read_started.wait(timeout=5)

        b_error: dict = {}
        b_finished = threading.Event()

        def insert_b():
            try:
                registry.get_or_run("b", lambda: _entry_with_file(registry, "b", "test.txt", "B content"))
            except BaseException as exc:  # noqa: BLE001
                b_error["exc"] = exc
            finally:
                b_finished.set()

        b_thread = threading.Thread(target=insert_b)
        b_thread.start()

        # Deterministically wait until B is genuinely blocked inside
        # _room_available.wait() -- max_size=1 and A is the only entry,
        # currently pinned, so there is no room for B yet.
        _wait_until_condition_has_waiters(registry._room_available, expected=1)
        assert not b_finished.is_set()
        assert len(registry) == 1  # still just A -- bound intact

        # Close the registry WHILE B is still blocked.
        registry.close()

        # B must terminate within a bounded timeout, with RegistryClosedError.
        assert b_finished.wait(timeout=5), "B did not terminate after close()"
        b_thread.join(timeout=5)
        assert not b_thread.is_alive(), "no worker thread may remain alive"
        assert isinstance(b_error.get("exc"), RegistryClosedError)

        # Release A's read and confirm that worker also terminates cleanly
        # (no worker remains alive after close()).
        release_read.set()
        reader_thread.join(timeout=5)
        assert not reader_thread.is_alive()

        # The registry's root directory is removed.
        assert not registry.root_dir.exists()

        # A second close() is harmless (idempotent: no error, no re-removal issue).
        registry.close()
