"""Local byte-only checkpoint lifecycle and synchronous observation/cost contracts.

No workers, network I/O, or pickle loading. Deadlines reject late results;
callers must bound/preempt external computations and loader I/O themselves.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import time

KINDS = frozenset(
    {
        "observation",
        "residency",
        "recompute",
        "reuse",
        "coordination",
        "generate",
        "control",
        "submit",
    }
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("expected full lowercase SHA-256")
    return value


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _finite(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def _json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _read(path, maximum):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise ValueError("expected bounded regular file")
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum or len(data) != info.st_size:
        raise ValueError("file changed size during read")
    return data


@dataclass(frozen=True)
class Packet:
    packet_id: str
    modality: str
    event_ns: int
    arrival_ns: int
    deadline_ns: int
    sha256: str
    resident_bytes: int
    sequence: int = 0
    media_clock: str | None = None
    media_time_ns: int | None = None
    sync_group: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        if self.schema_version != 1 or type(self.schema_version) is not int:
            raise ValueError("unsupported packet schema")
        if not isinstance(self.packet_id, str) or not 1 <= len(self.packet_id) <= 128:
            raise ValueError("invalid packet identifier")
        if self.modality not in {"text", "image", "audio", "video"}:
            raise ValueError("unknown modality")
        for name in (
            "event_ns",
            "arrival_ns",
            "deadline_ns",
            "resident_bytes",
            "sequence",
        ):
            _integer(getattr(self, name), name)
        if not self.event_ns <= self.arrival_ns <= self.deadline_ns:
            raise ValueError("packet timestamps are not ordered")
        _sha(self.sha256)
        for name in ("media_clock", "sync_group"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not 1 <= len(value) <= 128
            ):
                raise ValueError(f"invalid {name}")
        if self.media_time_ns is not None:
            _integer(self.media_time_ns, "media_time_ns")
        if (self.media_clock is None) != (self.media_time_ns is None):
            raise ValueError("media clock and media time must be paired")
        if self.modality in {"audio", "video"} and self.media_clock is None:
            raise ValueError("audio/video require a media clock")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - set(cls.__dataclass_fields__):
            raise ValueError("packet contains unknown/private fields")
        try:
            return cls(**value)
        except TypeError as exc:
            raise ValueError("incomplete packet descriptor") from exc

    def public(self):
        return asdict(self)


@dataclass(frozen=True)
class Limits:
    max_candidate_bytes: int
    max_calls: int
    max_seconds: float
    finalization_seconds: float = 0.0
    finalization_calls: int = 0

    def __post_init__(self):
        for name in ("max_candidate_bytes", "max_calls", "finalization_calls"):
            _integer(getattr(self, name), name)
        for name in ("max_seconds", "finalization_seconds"):
            _finite(getattr(self, name), name)
        if (
            self.finalization_seconds > self.max_seconds
            or self.finalization_calls > self.max_calls
        ):
            raise ValueError("finalization reserve exceeds total budget")


@dataclass(frozen=True)
class Prices:
    wall_second: float | None = None
    cpu_second: float | None = None
    byte_second: float | None = None
    call: float | None = None

    def __post_init__(self):
        for name, value in asdict(self).items():
            if value is not None:
                _finite(value, name)


class CostLedger:
    """Sequential timing and nonoverlapping resident-byte integrals.

    Zero prices must be explicit. Unknown prices for positive quantities yield
    monetary=None. Limits are independent of prices. Residency includes input
    packets and candidates retained by the caller.
    """

    def __init__(
        self,
        limits,
        prices=None,
        clock=time.monotonic,
        cpu_clock=time.process_time,
    ):
        self.limits, self.clock, self.cpu_clock = limits, clock, cpu_clock
        self.prices = dict(prices or {})
        if set(self.prices) - KINDS or any(
            not isinstance(p, Prices) for p in self.prices.values()
        ):
            raise ValueError("invalid price table")
        self.started = self._last = clock()
        self.calls, self.events, self.resident = 0, [], {}
        self._operation_lock = threading.Lock()

    def _event(
        self,
        kind,
        status,
        wall=0.0,
        cpu=0.0,
        byte_seconds=0.0,
        calls=0,
        detail="",
    ):
        price = self.prices.get(kind, Prices())
        rates = (price.wall_second, price.cpu_second, price.byte_second, price.call)
        quantities = (wall, cpu, byte_seconds, calls)
        products = [
            None if q > 0 and p is None else q * (p or 0)
            for q, p in zip(quantities, rates)
        ]
        money = None if None in products else sum(products)
        self.events.append(
            dict(
                kind=kind,
                status=status,
                wall_seconds=wall,
                cpu_seconds=cpu,
                byte_seconds=byte_seconds,
                calls=calls,
                monetary=money,
                detail=detail,
            )
        )

    def _residency(self):
        now = self.clock()
        if now < self._last:
            raise ValueError("ledger clock moved backwards")
        amount = (now - self._last) * sum(self.resident.values())
        if amount:
            self._event("residency", "ok", byte_seconds=amount)
        self._last = now

    def remaining_seconds(self, finalization=False):
        reserve = 0 if finalization else self.limits.finalization_seconds
        return max(
            0.0,
            self.limits.max_seconds - reserve - (self.clock() - self.started),
        )

    def retain(self, key, size):
        _integer(size, "resident size")
        self._residency()
        total = sum(self.resident.values()) - self.resident.get(key, 0) + size
        if total > self.limits.max_candidate_bytes:
            raise RuntimeError("resident/candidate byte budget exceeded")
        self.resident[key] = size

    def release(self, key):
        self._residency()
        self.resident.pop(key, None)

    @contextmanager
    def operation(self, kind, calls=0, finalization=False, detail=""):
        if kind not in KINDS or kind == "residency":
            raise ValueError("invalid operation kind")
        _integer(calls, "calls")
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("overlapping/nested operations are not billable")
        start, cpu = self.clock(), self.cpu_clock()
        used, status = 0, "rejected"
        try:
            self._residency()
            reserve = 0 if finalization else self.limits.finalization_calls
            if self.calls + calls > self.limits.max_calls - reserve:
                raise RuntimeError("call budget/finalization reserve exhausted")
            if self.remaining_seconds(finalization) <= 0:
                raise TimeoutError("runtime/finalization reserve exhausted")
            self.calls += calls
            used, status = calls, "failed"
            yield
            if self.remaining_seconds(finalization) <= 0:
                raise TimeoutError("late result rejected")
            status = "ok"
        except BaseException as exc:
            if isinstance(exc, TimeoutError):
                status = "timeout"
            raise
        finally:
            try:
                self._residency()
                self._event(
                    kind,
                    status,
                    max(0, self.clock() - start),
                    max(0, self.cpu_clock() - cpu),
                    calls=used,
                    detail=detail,
                )
            finally:
                self._operation_lock.release()

    def summary(self):
        self._residency()
        keys = ("wall_seconds", "cpu_seconds", "byte_seconds", "calls")
        totals = {key: sum(e[key] for e in self.events) for key in keys}
        totals["monetary"] = (
            None
            if any(e["monetary"] is None for e in self.events)
            else sum(e["monetary"] for e in self.events)
        )
        return dict(
            totals,
            elapsed_seconds=self.clock() - self.started,
            resident_bytes=sum(self.resident.values()),
            events=[dict(e) for e in self.events],
        )


class PacketInbox:
    """Loader(id, maximum_bytes) is invoked only by an admitted READ.

    The loader must bound its I/O and allocation. Late results are not returned.
    Repeated READs are paid; explicit reuse is the adapter's responsibility.
    """

    def __init__(
        self,
        packets,
        loader,
        ledger,
        clock_ns=time.time_ns,
        sleeper=time.sleep,
    ):
        packets = tuple(packets)
        if len(packets) > 1024 or any(not isinstance(p, Packet) for p in packets):
            raise ValueError("invalid/excessive packet descriptors")
        self.packets = {p.packet_id: p for p in packets}
        if len(self.packets) != len(packets):
            raise ValueError("duplicate packet identifiers")
        self.loader, self.ledger = loader, ledger
        self.clock_ns, self.sleeper = clock_ns, sleeper

    def read(self, packet_id):
        with self.ledger.operation("control", detail="READ admission"):
            packet = self.packets[packet_id]
            now = self.clock_ns()
            if now < packet.arrival_ns:
                raise RuntimeError("future observation is unavailable")
            if now > packet.deadline_ns:
                raise TimeoutError("packet deadline expired")
            key = "packet:" + packet_id
            previous = self.ledger.resident.get(key)
            total = sum(self.ledger.resident.values()) - (previous or 0)
            if total + packet.resident_bytes > self.ledger.limits.max_candidate_bytes:
                raise RuntimeError("packet exceeds residency budget")
        try:
            with self.ledger.operation("observation", calls=1, detail=packet_id):
                data = self.loader(packet_id, packet.resident_bytes)
                if not isinstance(data, bytes) or len(data) != packet.resident_bytes:
                    raise ValueError("packet size/type differs from descriptor")
                self.ledger.retain(key, len(data))
                if digest(data) != packet.sha256:
                    raise ValueError("packet digest differs from descriptor")
                if self.clock_ns() > packet.deadline_ns:
                    raise TimeoutError("packet returned after its deadline")
        except BaseException:
            if previous is None:
                self.ledger.release(key)
            else:
                self.ledger.retain(key, previous)
            raise
        return data

    def wait(self, packet_id, max_sleep_s):
        with self.ledger.operation("coordination", detail="WAIT admission"):
            _finite(max_sleep_s, "max sleep")
            packet = self.packets[packet_id]
            now = self.clock_ns()
            if not now < packet.arrival_ns <= packet.deadline_ns:
                raise RuntimeError("WAIT requires a declared pending observation")
            seconds = min(
                max_sleep_s,
                (packet.arrival_ns - now) / 1e9,
                self.ledger.remaining_seconds(),
            )
            if seconds <= 0:
                raise TimeoutError("no WAIT budget")
            self.sleeper(seconds)
            if self.clock_ns() > packet.deadline_ns:
                raise TimeoutError("WAIT missed packet deadline")
        return self.clock_ns() >= packet.arrival_ns


def no_update_gate(evidence, candidate_sha):
    """Check declarations; external provenance truth is caller-verified.

    Fixture, synthetic, missing or nonprospective declarations never qualify.
    Thresholds and evidence must be frozen by the independent evaluation layer.
    """
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be a mapping")
    reasons = []
    if (
        evidence.get("kind") != "prospective_measured"
        or evidence.get("fixture") is not False
        or evidence.get("synthetic") is not False
    ):
        reasons.append("nonprospective_or_fixture_evidence")
    if evidence.get("candidate_sha256") != _sha(candidate_sha):
        reasons.append("candidate_binding_missing")
    try:
        _sha(evidence.get("evidence_sha256"))
    except ValueError:
        reasons.append("evidence_digest_missing")
    for lower, threshold in (
        ("net_gain_lcb", "minimum_gain"),
        ("retention_lcb", "minimum_retention"),
    ):
        a, b = evidence.get(lower), evidence.get(threshold)
        valid = all(
            not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)
            for x in (a, b)
        )
        passed = valid and (a > b >= 0 if lower == "net_gain_lcb" else a >= b)
        if not passed:
            reasons.append(lower + "_not_passed")
    for name in (
        "constraints_pass",
        "parity_pass",
        "future_sample_pass",
        "unknown_rejection_pass",
    ):
        if evidence.get(name) is not True:
            reasons.append(name + "_missing")
    return {"decision": "no-update" if reasons else "activate", "reasons": reasons}


class CheckpointStore:
    """Full byte manifests with revisioned local pointers and cooperative locks.

    Requires a private caller-owned root. This is not a privilege boundary
    against a process already able to rewrite that root.
    """

    def __init__(self, root, max_bytes=64 * 1024 * 1024):
        self.root = Path(root).absolute()
        self.max_bytes = _integer(max_bytes, "max_bytes")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.resolve() != self.root:
            raise ValueError("root must be a physical directory")
        objects = self.root / "objects"
        objects.mkdir(exist_ok=True)
        if objects.resolve() != objects:
            raise ValueError("objects directory must not be a symlink")

    @contextmanager
    def _lock(self):
        lock = self.root / ".mutation-lock"
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise RuntimeError(
                "mutation active/orphaned; inspect before recovery"
            ) from exc
        try:
            yield
        finally:
            lock.rmdir()

    def _write(self, name, data):
        fd, temporary = tempfile.mkstemp(prefix=".staged-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.root / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not 1 <= len(name) <= 240 or "\\" in name:
            raise ValueError("invalid checkpoint file name")
        path = PurePosixPath(name)
        if (
            not path.parts
            or path.is_absolute()
            or str(path) != name
            or any(p in {".", ".."} for p in path.parts)
            or path.parts[0] == "manifest.json"
        ):
            raise ValueError("expected normalized relative payload name")
        return name

    def _manifest(self, identity):
        directory = self.root / "objects" / _sha(identity)
        if directory.resolve() != directory:
            raise ValueError("checkpoint directory contains a symlink")
        raw = _read(directory / "manifest.json", 65536)
        if digest(raw) != identity:
            raise ValueError("checkpoint manifest mismatch")
        manifest = json.loads(raw)
        if (
            set(manifest) != {"schema", "provenance", "files"}
            or manifest["schema"] != "ndu_checkpoint_v1"
            or manifest["provenance"] not in {"fixture", "measured", "baseline"}
            or not isinstance(manifest["files"], dict)
            or not 0 < len(manifest["files"]) <= 64
        ):
            raise ValueError("invalid checkpoint manifest")
        return directory, manifest

    def install(self, files, provenance="fixture"):
        if (
            not files
            or len(files) > 64
            or provenance not in {"fixture", "measured", "baseline"}
        ):
            raise ValueError("invalid bundle/provenance")
        entries = {}
        for name, data in files.items():
            self._name(name)
            if not isinstance(data, bytes):
                raise TypeError("checkpoint payloads must be bytes")
            entries[name] = {"sha256": digest(data), "bytes": len(data)}
        if any(
            str(parent) in entries
            for name in entries
            for parent in PurePosixPath(name).parents
        ):
            raise ValueError("payload names overlap directories")
        if sum(x["bytes"] for x in entries.values()) > self.max_bytes:
            raise ValueError("checkpoint exceeds byte budget")
        manifest = _json(
            dict(schema="ndu_checkpoint_v1", provenance=provenance, files=entries)
        )
        identity = digest(manifest)
        with self._lock():
            target = self.root / "objects" / identity
            if target.exists():
                self.load(identity)
                return identity
            staged = Path(tempfile.mkdtemp(prefix=".bundle-", dir=self.root))
            try:
                for name, data in files.items():
                    destination = staged / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                (staged / "manifest.json").write_bytes(manifest)
                os.rename(staged, target)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
        return identity

    def load(self, identity):
        directory, manifest = self._manifest(identity)
        present = set()
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError("checkpoint contains a symlink")
            if not path.is_dir():
                present.add(path.relative_to(directory).as_posix())
            if len(present) > 65:
                raise ValueError("checkpoint contains excessive files")
        if present != set(manifest["files"]) | {"manifest.json"}:
            raise ValueError("checkpoint file list differs from manifest")
        files, total = {}, 0
        for name, entry in manifest["files"].items():
            if not isinstance(entry, dict) or set(entry) != {"sha256", "bytes"}:
                raise ValueError("invalid file manifest")
            path = directory / self._name(name)
            size = _integer(entry["bytes"], "file bytes")
            total += size
            if total > self.max_bytes or path.resolve() != path:
                raise ValueError("invalid checkpoint path/size")
            data = _read(path, size)
            if len(data) != size or digest(data) != _sha(entry["sha256"]):
                raise ValueError("checkpoint payload mismatch")
            files[name] = data
        return files

    def pointer(self):
        raw = _read(self.root / "active.json", 2048)
        value = json.loads(raw)
        if (
            set(value) != {"schema", "revision", "active", "previous"}
            or value["schema"] != "ndu_active_v1"
        ):
            raise ValueError("invalid active pointer")
        _integer(value["revision"], "revision")
        _sha(value["active"])
        if value["previous"] is not None:
            _sha(value["previous"])
        return dict(value, pointer_sha256=digest(raw))

    def initialize(self, identity):
        with self._lock():
            self.load(identity)
            if self._manifest(identity)[1]["provenance"] != "baseline":
                raise ValueError("initial active bundle must be an explicit baseline")
            if (self.root / "active.json").exists():
                raise RuntimeError("active pointer already initialized")
            self._write(
                "active.json",
                _json(
                    dict(
                        schema="ndu_active_v1",
                        revision=0,
                        active=identity,
                        previous=None,
                    )
                ),
            )
        return self.pointer()

    def stage(self, identity):
        with self._lock():
            self.load(identity)
            self._write(
                "candidate.json",
                _json({"schema": "ndu_candidate_v1", "candidate": identity}),
            )

    def _move(self, identity, expected_pointer_sha256, rollback):
        current = self.pointer()
        if current["pointer_sha256"] != _sha(expected_pointer_sha256):
            raise RuntimeError("active pointer compare-and-swap conflict")
        if identity == current["active"]:
            raise ValueError("requested version is already active")
        if rollback and identity != current["previous"]:
            raise ValueError("rollback target is not the immediately previous version")
        self.load(identity)
        self._write(
            "active.json",
            _json(
                dict(
                    schema="ndu_active_v1",
                    revision=current["revision"] + 1,
                    active=identity,
                    previous=current["active"],
                )
            ),
        )
        return self.pointer()

    def activate(self, evidence, expected_pointer_sha256):
        with self._lock():
            staged = json.loads(_read(self.root / "candidate.json", 1024))
            if (
                set(staged) != {"schema", "candidate"}
                or staged["schema"] != "ndu_candidate_v1"
            ):
                raise ValueError("invalid candidate pointer")
            candidate = staged["candidate"]
            self.load(candidate)
            result = no_update_gate(evidence, candidate)
            if self._manifest(candidate)[1]["provenance"] != "measured":
                result = {
                    "decision": "no-update",
                    "reasons": result["reasons"] + ["candidate_not_measured"],
                }
            if result["decision"] != "activate":
                return result
            return dict(
                result,
                pointer=self._move(candidate, expected_pointer_sha256, rollback=False),
            )

    def rollback(self, identity, expected_pointer_sha256):
        with self._lock():
            return self._move(identity, expected_pointer_sha256, rollback=True)
