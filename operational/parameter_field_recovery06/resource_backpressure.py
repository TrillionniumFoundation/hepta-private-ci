"""Execution06 precommit resource backpressure; reconstructed from conversation.

Reconstructed after the workspace loss on 2026-10-30. The earlier file hashes
and test receipts do not validate these reconstructed bytes. Only fresh tests
and externally registered source pins may validate this revision.

Only this adapter's explicit CapacityDenied can pause a pending operation.
Allocator failures and attempted physical writes are never retried. Frozen
scientific files remain unchanged. Linux flock/cgroup v2 is required.
"""

import builtins
from contextlib import contextmanager, nullcontext
import fcntl
import hashlib
import importlib
import io
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import threading
import time


PACKAGE = "experiments.parameter_field_fullstudy_20261029"
RESOURCE = importlib.import_module(PACKAGE + ".resource_v2")
IO = importlib.import_module(PACKAGE + ".resource_io_v2")
ORIGINAL_BUDGET = RESOURCE.StorageBudget
ORIGINAL_CHECKED_FILE = IO.CheckedFile
RAW_OPEN = RESOURCE.RAW_OPEN
RAW_REPLACE = os.replace
MiB, GiB = RESOURCE.MiB, RESOURCE.GiB
SOURCE_PREFIX = "experiments/parameter_field_fullstudy_20261029/"
MODULES = (
    "resource_v2", "resource_io_v2", "run_v2", "architecture_run_v2",
    "endpoint_v2", "launch_v2", "controller_envelope_v2",
    "analysis_launch_v2", "finalize_v2",
)
REQUIRED_SOURCES = tuple(SOURCE_PREFIX + name + ".py" for name in MODULES) + (
    SOURCE_PREFIX + "architecture_store.py",
    SOURCE_PREFIX + "replay_terminals.py",
    "operational/parameter_field_recovery06/resource_backpressure.py",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    with RAW_OPEN(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_pins(source_root, expected):
    """Validate externally supplied pins, never a self-derived trust root."""
    root = Path(source_root).resolve()
    require(set(REQUIRED_SOURCES) <= set(expected), "Backpressure source closure is incomplete")
    result = {}
    for name in REQUIRED_SOURCES:
        target = (root / name).resolve()
        require(target.is_relative_to(root) and not Path(name).is_absolute()
                and ".." not in Path(name).parts, "Unsafe backpressure source path")
        actual = file_hash(target)
        require(actual == expected[name], "Backpressure source bytes differ: " + name)
        result[name] = actual
    require(Path(__file__).resolve() == root / REQUIRED_SOURCES[-1],
            "Backpressure adapter loaded from a different source root")
    return result


def path_identity(path):
    path = Path(path)
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    require(stat.S_ISREG(value.st_mode) and not path.is_symlink(),
            "Resource target is not a regular nonsymlink file")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_nlink)


def fd_identity(stream):
    value = os.fstat(stream.fileno())
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_nlink, stream.tell())


class CapacityDenied(Exception):
    """An explicit precommit reserve rejection, never allocator failure."""

    def __init__(self, profile):
        super().__init__("Registered cgroup margin/pending-growth reserve exhausted")
        self.profile = profile


class BackpressurePolicy:
    """One live process, external deadline/baseline, and bounded private logs.

    health_check preserves the caller's original outer process/source checks.
    No model, RNG, scientific cursor, deadline, or OOM baseline is reset.
    """

    def __init__(self, *, root, journal_directory, source_root, expected_sources,
                 deadline_monotonic, oom_baseline, health_check,
                 max_wait_seconds, poll_seconds=0.25, test_profile_reader=None):
        self.root = Path(root).resolve()
        self.journal_directory = Path(journal_directory).resolve()
        require(self.journal_directory != self.root
                and not self.journal_directory.is_relative_to(self.root)
                and not self.journal_directory.is_relative_to(
                    self.root.parent / (self.root.name + "_cas")),
                "Backpressure receipts must be outside RAW and CAS")
        require(callable(health_check), "An explicit original health/deadline callback is required")
        require(math.isfinite(deadline_monotonic) and deadline_monotonic > time.monotonic(),
                "A future externally fixed deadline is required")
        require(math.isfinite(max_wait_seconds) and 0 < max_wait_seconds <= 12 * 3600,
                "Invalid bounded capacity wait")
        require(math.isfinite(poll_seconds) and 0 < poll_seconds <= 1,
                "Wait polling must be positive and at most one second")
        require(set(oom_baseline) == {"oom", "oom_kill"}
                and all(type(v) is int and v >= 0 for v in oom_baseline.values()),
                "An externally fixed OOM baseline is required")
        self.pins = source_pins(source_root, expected_sources)
        self.source_root = Path(source_root).resolve()
        self.deadline = float(deadline_monotonic)
        self.baseline = dict(oom_baseline)
        self.health_check = health_check
        self.max_wait = float(max_wait_seconds)
        self.poll_seconds = float(poll_seconds)
        self.profile_reader = test_profile_reader or RESOURCE.memory_profile
        self.test_only = test_profile_reader is not None
        self.limits = []
        self.wait_count = 0
        self.wait_wall_seconds = 0.0
        self.journal_limit = 1024 * 1024
        self._journal_mutex = threading.Lock()
        self.journal_directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.journal_path = self.journal_directory / "CAPACITY_EVENTS.jsonl"
        self.record({"event": "policy_started", "root": str(self.root),
                     "deadline_monotonic": self.deadline, "max_wait_seconds": self.max_wait,
                     "oom_baseline": self.baseline, "source_files": self.pins,
                     "test_only": self.test_only, "scientific_work_retry": False})

    def record(self, value):
        record = {"schema": "hepta.execution06.resource-backpressure-event.1",
                  "pid": os.getpid(), "monotonic": time.monotonic(), **value}
        payload = (json.dumps(record, sort_keys=True, allow_nan=False) + "\n").encode()
        require(len(payload) <= 64 * 1024, "Backpressure event exceeded its bounded size")
        with self._journal_mutex:
            size = self.journal_path.stat().st_size if self.journal_path.exists() else 0
            require(size + len(payload) <= self.journal_limit,
                    "Backpressure event budget exhausted; refusing to drop evidence")
            space = os.statvfs(self.journal_directory)
            allocation = ((len(payload) + space.f_frsize - 1) // space.f_frsize) * space.f_frsize
            require(space.f_bavail * space.f_frsize >= 256 * MiB + allocation and space.f_favail >= 2000,
                    "Backpressure journal would consume the registered physical reserve")
            with RAW_OPEN(self.journal_path, "ab", buffering=0) as stream:
                count = stream.write(payload)
                require(count == len(payload), "Partial backpressure journal write")
                os.fsync(stream.fileno())

    def add_limit(self, callback):
        require(callable(callback), "Phase limit callback is not callable")
        self.limits.append(callback)

    def health(self):
        require(time.monotonic() <= self.deadline, "Original absolute execution deadline exhausted")
        profile = self.profile_reader()
        require(all(profile[name] <= self.baseline[name] for name in self.baseline),
                "OOM counter increased during resource backpressure")
        self.health_check()
        for callback in tuple(self.limits):
            callback()
        return profile

    def denied_profile(self, storage, additional, allocation, pending, profile, context):
        required = allocation + storage.margin + pending
        return {"context": context, "additional_logical_bytes": additional,
                "rounded_pending_allocation_bytes": allocation,
                "memory_margin_bytes": storage.margin, "pending_growth_bytes": pending,
                "required_headroom": required, "memory": profile,
                "allowed": profile["effective_current"] + required <= profile["limit"]}

    def pause(self, storage, rejection, state):
        require(getattr(storage._local, "depth", 0) == 0,
                "Cannot wait while any StorageBudget writer lock is held")
        now = time.monotonic()
        if state is None:
            state = {"started": now, "last": rejection.profile, "checks": 0}
            self.wait_count += 1
            self.record({"event": "capacity_wait_started", "rejection": rejection.profile,
                         "writer_lock_depth": 0, "scientific_work_repeated": False})
        state["last"], state["checks"] = rejection.profile, state["checks"] + 1
        try:
            self.health()
            require(now - state["started"] <= self.max_wait, "Bounded resource wait exhausted")
            remaining = min(self.deadline - now, self.max_wait - (now - state["started"]))
            require(remaining > 0, "Bounded resource wait exhausted")
            time.sleep(min(self.poll_seconds, remaining))
            self.health()
            return state
        except BaseException as error:
            try:
                self.finish_wait(state, "capacity_wait_failed", error)
            except BaseException as journal_error:
                error.add_note("Backpressure failure-journal write also failed: " + type(journal_error).__name__)
            raise

    def finish_wait(self, state, event, error=None):
        if state is None:
            return
        wall = time.monotonic() - state["started"]
        self.wait_wall_seconds += wall
        value = {"event": event, "wait_wall_seconds": wall,
                 "denied_checks": state["checks"], "last_rejection": state["last"],
                 "scientific_work_repeated": False}
        if event == "capacity_wait_committed":
            value["committed_admission"] = state["committed_admission"]
        if error is not None:
            value.update(error_type=type(error).__name__, message=str(error)[:4096])
        self.record(value)


class BackpressureBudget(ORIGINAL_BUDGET):
    """Original resource inequality plus explicitly eligible atomic waiting."""

    def __init__(self, root, registration, policy):
        super().__init__(root, registration)
        require(self.root == policy.root, "Backpressure policy root differs from registration")
        require((self.cap, self.reserve, self.c_cap, self.margin) ==
                (2 * GiB, 256 * MiB, 350 * MiB, GiB), "Registered resource limits changed")
        require(registration["concurrency"]["max_workers"] == 2
                and registration["concurrency"]["worker_reservation_bytes"] == 768 * MiB,
                "Registered worker concurrency/reservation changed")
        self.policy = policy

    def _check_locked(self, additional=0, c_training=False, check_memory=True, context=None, physical_additional=None):
        require(getattr(self._local, "depth", 0) > 0, "Budget must be checked under writer lock")
        if type(additional) is not int or additional < 0:
            raise ValueError("Pending byte count must be a nonnegative integer")
        physical = additional if physical_additional is None else physical_additional
        require(type(physical) is int and physical >= additional, "Invalid physical pending allocation")
        space = os.statvfs(self.root)
        allocation = ((physical + space.f_frsize - 1) // space.f_frsize) * space.f_frsize
        if space.f_bavail * space.f_frsize < self.reserve + allocation or space.f_favail < 2000:
            raise RuntimeError("Registered attempt02 physical reserve/inodes exhausted")
        inventory = self._inventory_unlocked()
        if inventory["logical_bytes"] + additional > self.cap:
            raise RuntimeError("Registered cumulative logical raw cap exhausted")
        if c_training:
            directory = self.root / "stage_C"
            c_bytes = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()
                          and "endpoint_evaluation" not in p.relative_to(directory).parts)
            if c_bytes + additional > self.c_cap:
                raise RuntimeError("Registered C training evidence cap exhausted")
        if check_memory:
            pending = RESOURCE.pending_growth(self.root)
            profile = self.policy.profile_reader()
            require(all(profile[name] <= self.policy.baseline[name] for name in self.policy.baseline),
                    "OOM counter increased during resource admission")
            detail = self.policy.denied_profile(self, additional, allocation, pending, profile, context)
            self._local.last_admission = detail
            if not detail["allowed"]:
                raise CapacityDenied(detail)
        return inventory

    def atomic(self, prepare, commit, *, context, emergency=False, outer_lock=None):
        """prepare returns budget kwargs and guard; commit is never retried."""
        require(getattr(self._local, "depth", 0) == 0,
                "Atomic resource boundary entered under an outer writer lock")
        waiting, guard, guard_set = None, None, False
        while True:
            committed = False
            try:
                if not emergency:
                    self.policy.health()
                with outer_lock() if outer_lock is not None else nullcontext():
                    with self.writer_lock():
                        kwargs, current_guard = prepare()
                        if guard_set:
                            require(current_guard == guard, "Pending resource target/cursor/payload changed during wait")
                        else:
                            guard, guard_set = current_guard, True
                        inventory = self._check_locked(context=context, **kwargs)
                        if waiting is not None:
                            waiting["committed_admission"] = self._local.last_admission
                        committed = True
                        result = commit(inventory)
            except CapacityDenied as rejection:
                if committed:
                    error = RuntimeError("Reserve rejection after commit began; no operation retry")
                    try:
                        self.policy.finish_wait(waiting, "capacity_wait_failed", error)
                    except BaseException as journal_error:
                        error.add_note("Backpressure failure-journal write also failed: " + type(journal_error).__name__)
                    raise error from rejection
                require(not emergency, "Emergency bounded write unexpectedly requested a memory wait")
                waiting = self.policy.pause(self, rejection, waiting)
            except BaseException as error:
                try:
                    self.policy.finish_wait(waiting, "capacity_wait_failed", error)
                except BaseException as journal_error:
                    error.add_note("Backpressure failure-journal write also failed: " + type(journal_error).__name__)
                raise
            else:
                self.policy.finish_wait(waiting, "capacity_wait_committed")
                return result

    def check(self, additional=0, c_training=False, check_memory=True):
        if getattr(self._local, "depth", 0):
            # Unknown caller-held locks are not guessed or unwound. No sleep.
            return self._check_locked(additional, c_training, check_memory,
                                      {"operation": "caller_locked_check"})
        return self.atomic(lambda: ({"additional": additional, "c_training": c_training,
                                    "check_memory": check_memory}, None), lambda result: result,
                           context={"operation": "budget_check"})

    def write_bytes(self, path, payload, allow_replace=False, failure_record=False):
        target = self._target(path)
        require(isinstance(payload, bytes), "Operational payload must be immutable bytes")
        emergency = failure_record and len(payload) <= 64 * 1024 and "FAIL" in target.name.upper()
        if failure_record and not emergency:
            raise ValueError("Only bounded failure receipts may use the emergency memory exemption")
        destination = target.with_name(target.name + ".ops-pending") if allow_replace else target
        def prepare():
            if not allow_replace and target.exists():
                raise FileExistsError(str(target))
            require(not destination.exists() if allow_replace else True, "Pending destination already exists")
            return ({"additional": len(payload), "check_memory": not emergency},
                    (path_identity(target), path_identity(destination), hashlib.sha256(payload).hexdigest()))
        def commit(unused):
            target.parent.mkdir(parents=True, exist_ok=True)
            with RAW_OPEN(destination, "xb") as stream:
                count = stream.write(payload)
                require(count == len(payload), "Partial operational write; no retry")
                stream.flush()
                os.fsync(stream.fileno())
            if allow_replace:
                RAW_REPLACE(destination, target)
            return {"path": str(target.relative_to(self.root)), "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest()}
        return self.atomic(prepare, commit, context={"operation": "write_bytes", "path": str(target)},
                           emergency=emergency)

    def append_bytes(self, path, payload):
        target = self._target(path)
        require(isinstance(payload, bytes), "Operational append must retain immutable bytes")
        def prepare():
            return ({"additional": len(payload)},
                    (path_identity(target), hashlib.sha256(payload).hexdigest()))
        def commit(unused):
            target.parent.mkdir(parents=True, exist_ok=True)
            with RAW_OPEN(target, "ab") as stream:
                count = stream.write(payload)
                require(count == len(payload), "Partial operational append; no retry")
                stream.flush()
                os.fsync(stream.fileno())
        return self.atomic(prepare, commit, context={"operation": "append_bytes", "path": str(target)})


class CheckedFile(ORIGINAL_CHECKED_FILE):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._write_failed = False

    def __exit__(self, kind, value, traceback):
        if value is not None:
            self._write_failed = True
            try:
                self.close()
            except BaseException as closing_error:
                value.add_note("Raw close also failed: " + type(closing_error).__name__)
            return False
        self.close()
        return False

    def close(self):
        if self._closed:
            return
        try:
            if not self._write_failed:
                self.flush()
        finally:
            self._closed = True
            self._wrapped.close()
        if not self._write_failed and "a" not in self._mode and not self._path.name.endswith((".log", ".jsonl")):
            self._storage.deduplicate_closed(self._path)

    def write(self, data):
        require(not self._write_failed and not self._closed, "Guarded file is closed or a prior persistence attempt failed")
        return super().write(data)

    def flush(self):
        require(not self._write_failed and not self._closed, "Guarded file is closed or a prior persistence attempt failed")
        return super().flush()

    def _physical_write(self, data):
        require(not self._write_failed and not self._closed, "Guarded file is closed or a prior persistence attempt failed")
        storage, path = self._storage, self._path
        def describe():
            raw = data.encode(self._wrapped.encoding or "utf-8") if isinstance(data, str) else memoryview(data)
            size = len(raw) if isinstance(raw, bytes) else raw.nbytes
            position = self._wrapped.tell()
            current = os.fstat(self._wrapped.fileno()).st_size
            if "a" in self._mode:
                position = current
            relative = path.relative_to(storage.root)
            emergency = ("FAIL" in path.name.upper() and path.name.endswith(".json")
                         and position + size <= 64 * 1024)
            kwargs = {"additional": max(0, position + size - current),
                      "c_training": relative.parts[0] == "stage_C" and "endpoint_evaluation" not in relative.parts,
                      "check_memory": not emergency}
            return kwargs, (fd_identity(self._wrapped), path_identity(path), hashlib.sha256(raw).hexdigest()), emergency
        initial = describe()
        def prepare():
            kwargs, identity, emergency = describe()
            require(emergency == initial[2], "Pending failure-write eligibility changed")
            return kwargs, identity
        def commit(unused):
            try:
                result = self._wrapped.write(data)
                expected = len(data) if isinstance(data, str) else memoryview(data).nbytes
                require(result == expected, "Partial guarded write; no retry")
                self._wrapped.flush()
                os.fsync(self._wrapped.fileno())
                return result
            except BaseException:
                self._write_failed = True
                raise
        try:
            return storage.atomic(prepare, commit, context={"operation": "guarded_write", "path": str(path)},
                                  emergency=initial[2])
        except BaseException:
            # A receipt failure after commit must not replay the text buffer.
            self._write_failed = True
            raise

    def truncate(self, size=None):
        self.flush()
        target = self._wrapped.tell() if size is None else size
        def prepare():
            current = os.fstat(self._wrapped.fileno()).st_size
            require(target >= current, "Registered raw artifacts cannot be silently truncated")
            return {"additional": target - current}, (fd_identity(self._wrapped), path_identity(self._path), target)
        def commit(unused):
            result = self._wrapped.truncate(target)
            self._wrapped.flush()
            os.fsync(self._wrapped.fileno())
            return result
        try:
            return self._storage.atomic(prepare, commit,
                                        context={"operation": "truncate_growth", "path": str(self._path)})
        except BaseException:
            self._write_failed = True
            raise


@contextmanager
def guarded_writes(storage, registration=None):
    require(isinstance(storage, BackpressureBudget) and registration is None,
            "Explicit registered BackpressureBudget instance is required")
    old_builtin, old_io = builtins.open, io.open
    old_rename, old_replace = os.rename, os.replace
    def guard(original):
        def open_file(file, mode="r", *args, **kwargs):
            if not isinstance(file, (str, bytes, os.PathLike)) or not any(flag in mode for flag in "wax+"):
                return original(file, mode, *args, **kwargs)
            target = Path(os.fsdecode(file)).resolve()
            if (not target.is_relative_to(storage.root) or target.suffix == ".lock"
                    or target.name.startswith(".ops-") or target.name == "ACTIVE_WORKERS.json"):
                return original(file, mode, *args, **kwargs)
            emergency = "FAIL" in target.name.upper() and target.name.endswith(".json")
            def prepare():
                identity = path_identity(target)
                if identity is not None and any(flag in mode for flag in "wx+"):
                    raise FileExistsError("Refusing to replace a persisted scientific artifact: " + str(target))
                if identity is not None and "a" in mode and identity[5] > 1:
                    raise RuntimeError("Cannot append to an already content-addressed artifact")
                return {"check_memory": not emergency}, identity
            def commit(unused):
                return CheckedFile(original(file, mode, *args, **kwargs), storage, target, mode)
            return storage.atomic(prepare, commit, context={"operation": "guarded_open", "path": str(target), "mode": mode},
                                  emergency=emergency)
        return open_file
    def rename_guard(original):
        def perform(source, destination, *args, **kwargs):
            left, right = Path(os.fsdecode(source)).resolve(), Path(os.fsdecode(destination)).resolve()
            source_inside, destination_inside = left.is_relative_to(storage.root), right.is_relative_to(storage.root)
            if not source_inside and not destination_inside:
                return original(source, destination, *args, **kwargs)
            if not source_inside or not destination_inside or args or kwargs:
                raise ValueError("Unregistered cross-root or descriptor-relative raw rename")
            with storage.writer_lock():
                if right.exists() and not left.name.endswith((".cas-link", ".ops-pending")):
                    raise FileExistsError("Refusing to overwrite a persisted scientific artifact")
                return original(source, destination)
        return perform
    builtins.open, io.open = guard(old_builtin), guard(old_io)
    os.rename, os.replace = rename_guard(old_rename), rename_guard(old_replace)
    try:
        yield storage
    finally:
        builtins.open, io.open = old_builtin, old_io
        os.rename, os.replace = old_rename, old_replace


def phase_budget_type(original_factory, check_work, storage, expected_root, phase):
    original = original_factory(storage, expected_root, phase)
    class PhaseBudget(original):
        def __init__(self, root, costs, selected_phase):
            super().__init__(root, costs, selected_phase)
            storage.policy.add_limit(lambda: check_work(self.costs, self.phase, self.wall, self.cpu))
    return PhaseBudget


def replay_budget_type(original_factory, check_work, original, storage, expected_root):
    base = original_factory(original, storage, expected_root)
    class ReplayBudget(base):
        def __init__(self, root, costs):
            super().__init__(root, costs)
            storage.policy.add_limit(lambda: check_work(self.costs, "R", self.wall, self.cpu))

        def write(self, path, payload):
            path = Path(path).resolve()
            require(path.is_relative_to(self.root) and path != self.root, "R evidence escapes the shared raw root")
            require(isinstance(payload, bytes), "R persistence must retain immutable serialized bytes")
            self.check()
            def prepare():
                check_work(self.costs, "R", self.wall, self.cpu)
                require(not path.exists(), "Refusing to replace a persisted R artifact")
                return {"additional": len(payload)}, (path_identity(path), hashlib.sha256(payload).hexdigest())
            def commit(unused):
                path.parent.mkdir(parents=True, exist_ok=True)
                with RAW_OPEN(path, "xb") as stream:
                    count = stream.write(payload)
                    require(count == len(payload), "Partial R persistence write; no retry")
                    stream.flush()
                    os.fsync(stream.fileno())
                storage.deduplicate_closed(path)
                digest = hashlib.sha256(payload).hexdigest()
                require(path.stat().st_size == len(payload) and file_hash(path) == digest,
                        "R literal file readback differs")
                return {"path": path.relative_to(self.root).as_posix(), "bytes": len(payload), "sha256": digest}
            artifact = storage.atomic(prepare, commit,
                context={"operation": "R_persisted_write", "path": str(path)},
                outer_lock=lambda: RESOURCE._flock(self.root / "R_WRITE.lock", fcntl.LOCK_EX))
            self.costs.add("R_persisted_bytes", len(payload))
            return artifact
    return ReplayBudget


def store_type(original, storage):
    class RegisteredEvidenceStore(original):
        def __init__(self, root, work, raw_root=None):
            require(raw_root is not None and Path(raw_root).resolve() == storage.root, "C storage root differs")
            require(Path(root).resolve() == storage.root / "stage_C", "C stage directory differs")
            super().__init__(root, work, raw_root=raw_root, cap_bytes=350 * MiB,
                             global_cap_bytes=storage.cap, reserve_bytes=storage.reserve,
                             cpu_limit=43200, wall_limit=21600, microstep_limit=57536)
            storage.policy.add_limit(lambda: original.check(self, additional=0, failure_record=False))
        def check(self, additional=0, failure_record=False):
            def prepare():
                original.check(self, additional=additional, failure_record=failure_record)
                return {"additional": additional, "c_training": True, "check_memory": not failure_record}, None
            return storage.atomic(prepare, lambda unused: None,
                                  context={"operation": "C_evidence_check"}, emergency=failure_record)
    return RegisteredEvidenceStore


def endpoint_budget_type(original):
    class EndpointBudget(original):
        def __init__(self, root, costs, phase, registration):
            super().__init__(root, costs, phase, registration)
            def limits():
                cpu = time.process_time() - self.cpu + self.training_work.get("cpu_seconds", 0.0)
                wall = time.monotonic() - self.wall + self.training_work.get("wall_seconds", 0.0)
                require(cpu <= (43200 if self.phase == "C" else 7200)
                        and wall <= (21600 if self.phase == "C" else 10800),
                        "Original endpoint CPU/wall ceiling exhausted")
                if self.phase in ("A", "B"):
                    require(self.costs.values.get("scheduled_gradient_microsteps", 0)
                            <= (39168 if self.phase == "A" else 23040),
                            "Original scheduled gradient ceiling exceeded")
            self.storage.policy.add_limit(limits)
    return EndpointBudget


def analysis_monitor(original):
    """Keep the unchanged monitor's one-hour/OOM gates active during log waits."""
    def monitor(process, storage, log, baseline):
        started = time.monotonic()  # No later than the unchanged monitor's start.
        def limits():
            require(time.monotonic() - started <= 3600, "One-hour aggregate analysis window exhausted")
            profile = storage.policy.profile_reader()
            require(all(profile[name] <= baseline[name] for name in ("oom", "oom_kill")),
                    "OOM counter increased during analysis")
        storage.policy.add_limit(limits)
        try:
            return original(process, storage, log, baseline)
        finally:
            storage.policy.limits.remove(limits)
    return monitor


def training_slot(root, registration, policy):
    """Original PID/slot/quiescence rules; only pre-yield admission can wait."""
    @contextmanager
    def slot():
        root_path = Path(root).resolve()
        require(root_path == policy.root == Path(registration["raw_root"]).resolve(), "Worker root differs")
        root_path.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 5.0
        while True:
            active = root_path / "ACTIVE_WORKERS.json"
            try:
                with RAW_OPEN(active) as stream:
                    workers = json.load(stream).get("workers", [])
                if any(int(row["pid"]) == os.getpid() for row in workers):
                    break
            except (OSError, ValueError):
                pass
            require(time.monotonic() < deadline, "Worker PID was not registered within five seconds")
            time.sleep(0.05)
        with RESOURCE._flock(root_path / ".ops-phase.lock", fcntl.LOCK_SH | fcntl.LOCK_NB):
            selected = None
            for index in range(2):
                candidate = RAW_OPEN(root_path / f".ops-slot-{index}.lock", "a+b")
                try:
                    fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    selected = candidate
                    break
                except BlockingIOError:
                    candidate.close()
            require(selected is not None, "Both registered worker slots are occupied")
            try:
                budget = BackpressureBudget(root_path, registration, policy)
                budget.check()
                yield
            finally:
                fcntl.flock(selected.fileno(), fcntl.LOCK_UN)
                selected.close()
    return slot()


def verify_logical_paths(storage, entries):
    """Original one-file literal restore; each not-yet-written chunk is gated."""
    require(isinstance(storage, BackpressureBudget), "Literal verification requires backpressure budget")
    temporary = Path(tempfile.mkdtemp(prefix="literal-verify-", dir=storage.cas_root))
    verified, physical_written, peak_temporary = [], 0, 0
    current_relative, destination, written = None, None, 0
    try:
        for index, (relative, expected) in enumerate(sorted(entries.items())):
            current_relative, destination, written = relative, None, 0
            path = Path(relative)
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe logical artifact path")
            source = storage.cas_root / expected["blob"] if expected["storage"] == "cas" else storage.root / path
            require(source.is_file() and not source.is_symlink(), "Missing canonical/direct artifact")
            source_identity = path_identity(source)
            destination = temporary / f"{index:08}.literal"
            with RAW_OPEN(source, "rb") as original, RAW_OPEN(destination, "xb", buffering=0) as restored:
                while True:
                    chunk = original.read(MiB)
                    if not chunk:
                        break
                    def prepare():
                        require(path_identity(source) == source_identity, "Literal source changed")
                        return ({"additional": 0, "physical_additional": len(chunk)},
                                (fd_identity(restored), path_identity(source), hashlib.sha256(chunk).hexdigest()))
                    def commit(unused):
                        count = restored.write(chunk)
                        require(count == len(chunk), "Partial literal-verification write")
                        restored.flush()
                        os.fsync(restored.fileno())
                        return count
                    count = storage.atomic(prepare, commit, context={"operation": "literal_chunk", "path": str(destination)})
                    written += count
                    physical_written += count
                    peak_temporary = max(peak_temporary, written)
            require(written == expected["bytes"] and file_hash(destination) == expected["sha256"],
                    "Literal artifact bytes differ from the manifest")
            require((storage.root / path).stat().st_size == expected["bytes"]
                    and file_hash(storage.root / path) == expected["sha256"],
                    "Original logical path changed during literal verification")
            verified.append(relative)
            destination.unlink()
        temporary.rmdir()
    except BaseException as error:
        partial_bytes = destination.stat().st_size if destination is not None and destination.exists() else 0
        physical_written += max(0, partial_bytes - written)
        error.verification_progress = {
            "temporary_failure_directory": str(temporary), "logical_paths_verified": verified,
            "logical_files_verified": len(verified),
            "logical_bytes_verified": sum(entries[name]["bytes"] for name in verified),
            "physical_verification_bytes_written": physical_written,
            "peak_single_temporary_file_bytes": max(peak_temporary, partial_bytes),
            "current_logical_path": current_relative,
            "current_partial_path": str(destination) if destination is not None else None,
            "current_partial_bytes": partial_bytes, "temporary_directory_removed_after_success": False,
            "residue_counts_toward_physical_storage": True}
        raise
    return {"logical_paths_verified": verified, "logical_files_restored": len(verified),
            "logical_bytes_restored": sum(row["bytes"] for row in entries.values()),
            "physical_verification_bytes_written": physical_written,
            "peak_single_temporary_file_bytes": peak_temporary,
            "temporary_failure_directory": str(temporary),
            "temporary_directory_removed_after_success": True}


@contextmanager
def installed(policy, *, allow_test_policy=False):
    """Scoped source-pinned aliases; the caller retains its normal entrypoint."""
    require(not policy.test_only or allow_test_policy, "Synthetic capacity policy cannot enter production")
    require(RESOURCE.StorageBudget is ORIGINAL_BUDGET and IO.CheckedFile is ORIGINAL_CHECKED_FILE,
            "Nested installation or unknown resource aliases are unsupported")
    source_pins(policy.source_root, policy.pins)
    modules = {name: importlib.import_module(PACKAGE + "." + name) for name in MODULES}
    for name, module in modules.items():
        require(Path(module.__file__).resolve() == policy.source_root / (SOURCE_PREFIX + name + ".py"),
                "Loaded operational module is outside the pinned source root")
    class BoundBudget(BackpressureBudget):
        def __init__(self, root, registration):
            super().__init__(root, registration, policy)
    def bound_guarded_writes(root, registration=None):
        storage = root if isinstance(root, BackpressureBudget) else BoundBudget(root, registration)
        return guarded_writes(storage)
    saved = []
    def replace(module, name, value):
        saved.append((module, name, getattr(module, name)))
        setattr(module, name, value)
    run = modules["run_v2"]
    original_phase, original_replay = run.phase_budget_type, run.replay_budget_type
    original_endpoint = modules["endpoint_v2"].EndpointBudget
    original_analysis_monitor = modules["analysis_launch_v2"].monitor
    try:
        for module in modules.values():
            if hasattr(module, "StorageBudget"):
                replace(module, "StorageBudget", BoundBudget)
            if hasattr(module, "guarded_writes"):
                replace(module, "guarded_writes", bound_guarded_writes)
            if hasattr(module, "training_slot"):
                replace(module, "training_slot", lambda root, registration: training_slot(root, registration, policy))
        replace(modules["resource_io_v2"], "CheckedFile", CheckedFile)
        replace(run, "phase_budget_type", lambda storage, root, phase: phase_budget_type(
            original_phase, run.check_work, storage, root, phase))
        replace(run, "replay_budget_type", lambda original, storage, root: replay_budget_type(
            original_replay, run.check_work, original, storage, root))
        replace(modules["architecture_run_v2"], "store_type", store_type)
        replace(modules["endpoint_v2"], "EndpointBudget", endpoint_budget_type(original_endpoint))
        replace(modules["analysis_launch_v2"], "monitor", analysis_monitor(original_analysis_monitor))
        replace(modules["finalize_v2"], "verify_logical_paths", verify_logical_paths)
        yield {"policy": policy, "budget_type": BoundBudget,
               "source_files": policy.pins, "mutated_module_aliases": len(saved)}
    finally:
        for module, name, original in reversed(saved):
            setattr(module, name, original)
