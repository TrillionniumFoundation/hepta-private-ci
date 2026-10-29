"""Registered attempt02 resources; original scientific source is unchanged.

Logical bytes count every artifact path. Physical content-addressed sharing is
reported separately. The host path survives executor-process reset, not host loss.
"""

import builtins
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
import time


MiB, GiB = 1024 ** 2, 1024 ** 3
RAW_OPEN = builtins.open
_LOCK_REGISTRY = {}
_REGISTRY_MUTEX = threading.Lock()


def file_hash(path):
    with RAW_OPEN(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_registration(path, expected_sha256):
    path = Path(path).resolve()
    if file_hash(path) != expected_sha256:
        raise ValueError("Operational amendment bytes differ")
    with RAW_OPEN(path) as stream:
        record = json.load(stream)
    contract = record["proposed_resource_contract"]
    if (record.get("status") != "REGISTERED_PRE_ENDPOINT" or record.get("execution_ready") is not True
            or record.get("attempt_id") != "attempt02"
            or contract["global_raw_logical_bytes"] != 2 * GiB
            or contract["minimum_private_allocatable_bytes"] != 256 * MiB
            or contract["C_training_evidence_bytes"] != 350 * MiB
            or record["concurrency"]["max_workers"] != 2
            or record["concurrency"]["memory_margin_bytes"] != GiB
            or record["concurrency"]["worker_reservation_bytes"] != 768 * MiB):
        raise ValueError("Unregistered or different attempt02 resource contract")
    record.update(_path=str(path), _sha256=expected_sha256)
    return record


def memory_profile():
    root = Path("/sys/fs/cgroup")
    values = {}
    for name in ("memory.stat", "memory.events"):
        with RAW_OPEN(root / name) as stream:
            values.update({key: int(value) for key, value in (line.split() for line in stream)})
    with RAW_OPEN(root / "memory.current") as stream:
        current = int(stream.read())
    with RAW_OPEN(root / "memory.max") as stream:
        limit_text = stream.read().strip()
    if limit_text == "max":
        raise RuntimeError("A finite cgroup memory limit is required")
    clean = max(0, values.get("inactive_file", 0)
                - values.get("file_dirty", 0) - values.get("file_writeback", 0))
    return {"current": current, "limit": int(limit_text),
            "inactive_file": values.get("inactive_file", 0),
            "file_dirty": values.get("file_dirty", 0), "file_writeback": values.get("file_writeback", 0),
            "clean_inactive_file": clean, "effective_current": max(0, current - clean),
            "oom": values.get("oom", 0), "oom_kill": values.get("oom_kill", 0)}


def memory_admission(worker_reservation_bytes=768 * MiB, margin_bytes=GiB, pending_growth_bytes=0):
    profile = memory_profile()
    required = int(worker_reservation_bytes) + int(margin_bytes) + int(pending_growth_bytes)
    profile.update(required_headroom=required,
                   allowed=profile["effective_current"] + required <= profile["limit"])
    return profile


def pending_growth(root):
    path = Path(root) / "ACTIVE_WORKERS.json"
    if not path.exists():
        return 0
    with RAW_OPEN(path) as stream:
        record = json.load(stream)
    pending = 0
    for row in record.get("workers", []):
        try:
            with RAW_OPEN(f"/proc/{int(row['pid'])}/status") as stream:
                rss = next(int(line.split()[1]) * 1024 for line in stream if line.startswith("VmRSS:"))
        except (OSError, StopIteration):
            continue
        pending += max(0, int(row["reservation_bytes"]) - rss)
    return pending


@contextmanager
def _flock(path, kind):
    path.parent.mkdir(parents=True, exist_ok=True)
    with RAW_OPEN(path, "a+b") as stream:
        fcntl.flock(stream.fileno(), kind)
        try:
            yield stream
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def whole_phase_lock(root):
    """Exclusive quiescence for final archive/dedup; do not nest inside a slot."""
    with _flock(Path(root) / ".ops-phase.lock", fcntl.LOCK_EX | fcntl.LOCK_NB):
        yield


@contextmanager
def training_slot(root, registration):
    """At most two workers; controller separately reserves pending worker growth."""
    root = Path(root).resolve()
    if str(root) != str(Path(registration["raw_root"]).resolve()):
        raise ValueError("Worker raw root differs from the registered attempt")
    root.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 5.
    while True:
        active = root / "ACTIVE_WORKERS.json"
        try:
            with RAW_OPEN(active) as stream:
                workers = json.load(stream).get("workers", [])
            if any(int(row["pid"]) == os.getpid() for row in workers):
                break
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Worker PID was not registered by the controller within five seconds")
        time.sleep(.05)
    with _flock(root / ".ops-phase.lock", fcntl.LOCK_SH | fcntl.LOCK_NB):
        selected = None
        for index in range(2):
            candidate = RAW_OPEN(root / f".ops-slot-{index}.lock", "a+b")
            try:
                fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                selected = candidate
                break
            except BlockingIOError:
                candidate.close()
        if selected is None:
            raise RuntimeError("Both registered worker slots are occupied")
        try:
            profile = memory_admission(0, registration["concurrency"]["memory_margin_bytes"], pending_growth(root))
            if not profile["allowed"]:
                raise MemoryError("Registered worker memory margin exhausted")
            yield
        finally:
            fcntl.flock(selected.fileno(), fcntl.LOCK_UN)
            selected.close()


class StorageBudget:
    def __init__(self, root, registration):
        self.root, self.registration = Path(root).resolve(), registration
        if str(self.root) != str(Path(registration["raw_root"]).resolve()):
            raise ValueError("Resource root differs from attempt02 registration")
        self.root.mkdir(parents=True, exist_ok=True)
        contract = registration["proposed_resource_contract"]
        self.cap = int(contract["global_raw_logical_bytes"])
        self.reserve = int(contract["minimum_private_allocatable_bytes"])
        self.c_cap = int(contract["C_training_evidence_bytes"])
        self.margin = int(registration["concurrency"]["memory_margin_bytes"])
        self.cas_root = self.root.parent / (self.root.name + "_cas")
        self.cas_root.mkdir(exist_ok=True)
        if self.root.stat().st_dev != self.cas_root.stat().st_dev:
            raise ValueError("CAS hardlinks require the same filesystem")
        with _REGISTRY_MUTEX:
            self._mutex, self._local = _LOCK_REGISTRY.setdefault(
                str(self.root), (threading.RLock(), threading.local()))

    @contextmanager
    def writer_lock(self):
        with self._mutex:
            depth = getattr(self._local, "depth", 0)
            if depth:
                self._local.depth = depth + 1
                try:
                    yield
                finally:
                    self._local.depth = depth
            else:
                with _flock(self.root / ".ops-write.lock", fcntl.LOCK_EX):
                    self._local.depth = 1
                    try:
                        yield
                    finally:
                        self._local.depth = 0

    def inventory(self):
        logical, allocated, seen = 0, 0, set()
        for base in (self.root, self.cas_root):
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                stat = path.stat()
                if base == self.root:
                    logical += stat.st_size
                identity = (stat.st_dev, stat.st_ino)
                if identity not in seen:
                    allocated += stat.st_blocks * 512
                    seen.add(identity)
        return {"logical_bytes": logical, "allocated_unique_inode_bytes": allocated, "unique_inodes": len(seen)}

    def check(self, additional=0, c_training=False, check_memory=True):
        if type(additional) is not int or additional < 0:
            raise ValueError("Pending byte count must be a nonnegative integer")
        with self.writer_lock():
            stat = os.statvfs(self.root)
            allocation = ((additional + stat.f_frsize - 1) // stat.f_frsize) * stat.f_frsize
            if stat.f_bavail * stat.f_frsize < self.reserve + allocation or stat.f_favail < 2000:
                raise RuntimeError("Registered attempt02 physical reserve/inodes exhausted")
            inventory = self.inventory()
            if inventory["logical_bytes"] + additional > self.cap:
                raise RuntimeError("Registered cumulative logical raw cap exhausted")
            if c_training:
                directory = self.root / "stage_C"
                c_bytes = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file()
                              and "endpoint_evaluation" not in p.relative_to(directory).parts)
                if c_bytes + additional > self.c_cap:
                    raise RuntimeError("Registered C training evidence cap exhausted")
            if check_memory:
                profile = memory_admission(allocation, self.margin, pending_growth(self.root))
                if not profile["allowed"]:
                    raise MemoryError("Registered cgroup margin/pending-growth reserve exhausted")
            return inventory

    def _target(self, path):
        path = Path(path)
        target = (self.root / path).resolve() if not path.is_absolute() else path.resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Evidence path escapes the registered raw root")
        return target

    def write_bytes(self, path, payload, allow_replace=False, failure_record=False):
        target = self._target(path)
        emergency = failure_record and len(payload) <= 64 * 1024 and "FAIL" in target.name.upper()
        if failure_record and not emergency:
            raise ValueError("Only bounded failure receipts may use the emergency memory exemption")
        with self.writer_lock():
            self.check(len(payload), check_memory=not emergency)
            target.parent.mkdir(parents=True, exist_ok=True)
            destination = target.with_name(target.name + ".ops-pending") if allow_replace else target
            with RAW_OPEN(destination, "xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if allow_replace:
                destination.replace(target)
        return {"path": str(target.relative_to(self.root)), "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest()}

    def append_bytes(self, path, payload):
        target = self._target(path)
        with self.writer_lock():
            self.check(len(payload))
            target.parent.mkdir(parents=True, exist_ok=True)
            with RAW_OPEN(target, "ab") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())

    def write_json(self, path, value, allow_replace=False, failure_record=False):
        payload = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        return self.write_bytes(path, payload, allow_replace=allow_replace, failure_record=failure_record)

    def deduplicate_closed(self, path):
        """Uniform whole-file CAS; logical original paths and exact bytes are retained."""
        path = self._target(path)
        if path.name.startswith(".ops-") or path.suffix == ".lock" or path.name == "ACTIVE_WORKERS.json" or path.is_symlink():
            return
        with self.writer_lock():
            if not path.is_file():
                return
            before = path.stat()
            digest = file_hash(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError("A closed artifact changed while hashing")
            canonical = self.cas_root / digest
            if not canonical.exists():
                os.link(path, canonical)
                return
            if canonical.is_symlink() or canonical.stat().st_size != before.st_size:
                raise RuntimeError("CAS identity/type collision")
            with RAW_OPEN(path, "rb") as left, RAW_OPEN(canonical, "rb") as right:
                while True:
                    a, b = left.read(MiB), right.read(MiB)
                    if a != b:
                        raise RuntimeError("CAS SHA256 collision or corrupted canonical bytes")
                    if not a:
                        break
            if path.stat().st_ino != canonical.stat().st_ino:
                temporary = path.with_name(path.name + ".cas-link")
                os.link(canonical, temporary)
                temporary.replace(path)
