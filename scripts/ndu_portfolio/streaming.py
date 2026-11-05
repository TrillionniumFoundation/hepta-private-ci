"""Exact resource and irreversible delivery invariants for streaming research.

Compute timestamps are wall times since run start; chunk timestamps belong to a
separate media presentation timeline. Both use integer microseconds. Decoders
are external: accounting/prefix guarantees do not establish media quality,
perceptual synchronization, or successful real audio/video generation.
"""

from dataclasses import dataclass
import hashlib
from threading import RLock


MODALITIES = frozenset(("text", "image", "audio", "video"))
KINDS = frozenset(("inference", "controller", "verification", "training", "evaluation"))


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative exact integer")


@dataclass(frozen=True)
class ComputeCharge:
    """Actual physical work; start/end refer to run-relative wall timestamps."""

    work_id: str
    compute_units: int
    start_us: int
    end_us: int
    kind: str
    succeeded: bool = True

    def __post_init__(self):
        if not isinstance(self.work_id, str) or not self.work_id or self.kind not in KINDS:
            raise ValueError("work id and registered cost kind required")
        for name in ("compute_units", "start_us", "end_us"):
            _integer(getattr(self, name), name)
        if self.end_us < self.start_us or not isinstance(self.succeeded, bool):
            raise ValueError("invalid physical work interval or outcome")


@dataclass(frozen=True)
class ComputeReservation:
    """Worst-case physical work limits; reservation is local to one ledger."""

    work_id: str
    worst_case_compute_units: int
    worst_case_end_us: int

    def __post_init__(self):
        if not isinstance(self.work_id, str) or not self.work_id:
            raise ValueError("work id required")
        _integer(self.worst_case_compute_units, "worst_case_compute_units")
        _integer(self.worst_case_end_us, "worst_case_end_us")


@dataclass(frozen=True)
class StreamChunk:
    """Artifact digest and presentation interval, independent of compute time."""

    modality: str
    sequence: int
    start_us: int
    end_us: int
    payload_sha256: str
    work_ids: tuple


class StreamingLedger:
    """Thread-safe bounded run-local accounting, admission, and prefix ledger.

    The lock covers one in-process run. It is not a distributed reservation or a
    crash-recovery store. Long streams require a separately specified checkpoint
    rollover; this implementation rejects chunks beyond its declared horizon.
    """

    def __init__(self, compute_budget, deadline_us, *, max_physical_work=4096,
                 max_chunks_per_modality=4096):
        for value, name in ((compute_budget, "compute_budget"), (deadline_us, "deadline_us"),
                            (max_physical_work, "max_physical_work"),
                            (max_chunks_per_modality, "max_chunks_per_modality")):
            _integer(value, name)
        if max_physical_work == 0 or max_chunks_per_modality == 0:
            raise ValueError("positive ledger capacity required")
        self._compute_budget, self._deadline_us = compute_budget, deadline_us
        self._max_physical_work, self._max_chunks = max_physical_work, max_chunks_per_modality
        self._lock = RLock()
        self._charges, self._reservations, self._admissions = {}, {}, {}
        self._chunks = {m: {} for m in MODALITIES}
        self._delivered = {m: -1 for m in MODALITIES}

    @property
    def compute_budget(self):
        return self._compute_budget

    @property
    def deadline_us(self):
        return self._deadline_us

    @property
    def consumed(self):
        with self._lock:
            return sum(c.compute_units for c in self._charges.values())

    @property
    def reserved(self):
        with self._lock:
            return sum(r.worst_case_compute_units for r in self._reservations.values())

    @property
    def elapsed_us(self):
        with self._lock:
            return max((c.end_us for c in self._charges.values()), default=0)

    def can_start(self, worst_case_compute, worst_case_end_us):
        """Advisory snapshot only. reserve_compute is required before dispatch."""
        _integer(worst_case_compute, "worst_case_compute")
        _integer(worst_case_end_us, "worst_case_end_us")
        with self._lock:
            maximum_end = max((r.worst_case_end_us for r in self._reservations.values()), default=0)
            return (len(self._charges.keys() | self._admissions.keys()) < self._max_physical_work
                    and self.consumed + self.reserved + worst_case_compute <= self.compute_budget
                    and max(self.elapsed_us, maximum_end, worst_case_end_us) <= self.deadline_us)

    def reserve_compute(self, work_id, worst_case_compute_units, worst_case_end_us):
        """Atomically reserve before dispatch; True means a newly admitted job.

        Identical replay returns False even after completion and never authorizes
        re-execution. A changed reservation under the same identity is rejected.
        Completion, including failed execution, releases only its own reservation.
        """
        reservation = ComputeReservation(work_id, worst_case_compute_units, worst_case_end_us)
        with self._lock:
            old = self._admissions.get(work_id)
            if old is not None:
                if old != reservation:
                    raise ValueError("work id reused with incompatible reservation")
                return False
            if work_id in self._charges:
                raise ValueError("observed work cannot be reserved retroactively")
            if not self.can_start(worst_case_compute_units, worst_case_end_us):
                raise ValueError("reservation exceeds remaining budget, deadline, or work capacity")
            self._admissions[work_id] = reservation
            self._reservations[work_id] = reservation
            return True

    def complete_compute(self, charge):
        """Record actual cost even on overrun/failure, and release its reservation."""
        if not isinstance(charge, ComputeCharge):
            raise TypeError("typed compute receipt required")
        with self._lock:
            existing = self._charges.get(charge.work_id)
            if existing is not None:
                if existing != charge:
                    raise ValueError("work id reused with incompatible accounting")
                return False
            if charge.work_id not in self._reservations:
                raise ValueError("completion requires an outstanding reservation")
            self._charges[charge.work_id] = charge
            del self._reservations[charge.work_id]
            return True

    def charge_compute(self, charge):
        """Import observed work without authorizing execution.

        A new import must fit the declared work-record capacity, but its actual
        cost/time is never clipped to the budget. Reserved jobs must use
        complete_compute. Identical imported receipts count once.
        """
        if not isinstance(charge, ComputeCharge):
            raise TypeError("typed compute receipt required")
        with self._lock:
            existing = self._charges.get(charge.work_id)
            if existing is not None:
                if existing != charge:
                    raise ValueError("work id reused with incompatible accounting")
                return False
            if charge.work_id in self._reservations:
                raise ValueError("reserved work must use complete_compute")
            if len(self._charges.keys() | self._admissions.keys()) >= self._max_physical_work:
                raise ValueError("observed-work import exceeds declared ledger capacity")
            self._charges[charge.work_id] = charge
            return True

    def prepare_chunk(self, modality, sequence, start_us, end_us, payload, work_ids):
        if modality not in MODALITIES or not isinstance(payload, bytes) or not payload:
            raise ValueError("registered modality and nonempty artifact bytes required")
        for value, name in ((sequence, "sequence"), (start_us, "start_us"), (end_us, "end_us")):
            _integer(value, name)
        if end_us <= start_us or sequence >= self._max_chunks:
            raise ValueError("positive presentation interval within declared chunk horizon required")
        if not isinstance(work_ids, (list, tuple)) or not 0 < len(work_ids) <= self._max_physical_work:
            raise ValueError("bounded physical work references required")
        ids = tuple(work_ids)
        with self._lock:
            if len(set(ids)) != len(ids) or any(i not in self._charges for i in ids):
                raise ValueError("chunk requires unique recorded physical work references")
            if any(not self._charges[i].succeeded for i in ids):
                raise ValueError("failed work cannot establish a delivered artifact")
            chunk = StreamChunk(modality, sequence, start_us, end_us, hashlib.sha256(payload).hexdigest(), ids)
            if sequence <= self._delivered[modality]:
                if self._chunks[modality][sequence] != chunk:
                    raise ValueError("already delivered prefix is irreversible")
                return chunk
            self._chunks[modality][sequence] = chunk
            return chunk

    def deliver(self, modality, through_sequence):
        if modality not in MODALITIES:
            raise ValueError("unknown modality")
        _integer(through_sequence, "through_sequence")
        if through_sequence >= self._max_chunks:
            raise ValueError("delivery exceeds declared chunk horizon")
        with self._lock:
            previous = self._delivered[modality]
            if through_sequence < previous:
                raise ValueError("delivery frontier cannot move backwards")
            if through_sequence == previous:
                return tuple(self._chunks[modality][i] for i in range(previous + 1))
            if self.consumed + self.reserved > self.compute_budget or self.elapsed_us > self.deadline_us:
                raise ValueError("resource or deadline failure must be resolved before delivery")
            chunks = self._chunks[modality]
            previous_end = chunks[previous].end_us if previous >= 0 else 0
            for sequence in range(previous + 1, through_sequence + 1):
                chunk = chunks.get(sequence)
                if chunk is None or chunk.start_us != previous_end:
                    raise ValueError("delivery must extend a complete contiguous prefix from time zero")
                previous_end = chunk.end_us
            self._delivered[modality] = through_sequence
            return tuple(chunks[i] for i in range(through_sequence + 1))

    def check_av_sync(self, tolerance_us):
        """Compare presentation coverage frontiers; perceptual sync is external."""
        _integer(tolerance_us, "tolerance_us")
        with self._lock:
            frontiers = {m: (self._chunks[m][n].end_us if n >= 0 else None)
                         for m, n in self._delivered.items() if m in ("audio", "video")}
            present = all(v is not None for v in frontiers.values())
            skew = abs(frontiers["audio"] - frontiers["video"]) if present else None
            return {"audio_frontier_us": frontiers["audio"], "video_frontier_us": frontiers["video"],
                    "frontier_skew_us": skew, "timestamp_sync_pass": present and skew <= tolerance_us,
                    "perceptual_sync": "NOT_EVALUATED"}

    def report(self):
        with self._lock:
            by_kind = {k: sum(c.compute_units for c in self._charges.values() if c.kind == k) for k in sorted(KINDS)}
            delivered = {m: n + 1 for m, n in sorted(self._delivered.items())}
            breaches = [work_id for work_id, r in self._admissions.items()
                        if work_id in self._charges
                        and (self._charges[work_id].compute_units > r.worst_case_compute_units
                             or self._charges[work_id].end_us > r.worst_case_end_us)]
            return {"compute_units": self.consumed, "remaining_compute_units": self.compute_budget-self.consumed,
                    "reserved_compute_units": self.reserved,
                    "available_after_reservations": self.compute_budget-self.consumed-self.reserved,
                    "outstanding_reservations": len(self._reservations),
                    "reservation_breaches": sorted(breaches),
                    "elapsed_us": self.elapsed_us, "physical_work_count": len(self._charges),
                    "max_physical_work": self._max_physical_work, "max_chunks_per_modality": self._max_chunks,
                    "compute_by_kind": by_kind,
                    "failed_work_compute_units": sum(c.compute_units for c in self._charges.values() if not c.succeeded),
                    "budget_pass": self.consumed + self.reserved <= self.compute_budget,
                    "deadline_pass": self.elapsed_us <= self.deadline_us,
                    "delivered_chunks": delivered, "real_stage_4": "HOLD",
                    "non_claim": "Run-local accounting and presentation timestamps do not establish real audio/video quality or perceptual synchronization."}


def run_streaming_experiment():
    """Synthetic timestamp fixture with shared inference and separate overhead."""
    ledger = StreamingLedger(100, 200_000)
    shared = ComputeCharge("shared-encoder", 30, 0, 50_000, "inference")
    ledger.reserve_compute("shared-encoder", 35, 55_000)
    ledger.complete_compute(shared)
    ledger.complete_compute(shared)
    ledger.reserve_compute("controller", 5, 56_000)
    ledger.complete_compute(ComputeCharge("controller", 4, 50_000, 55_000, "controller"))
    ledger.reserve_compute("verification", 6, 65_000)
    ledger.complete_compute(ComputeCharge("verification", 5, 55_000, 60_000, "verification"))
    for sequence in range(4):
        ledger.prepare_chunk("audio", sequence, sequence*20_000, (sequence+1)*20_000,
                             f"synthetic-audio-{sequence}".encode(), ("shared-encoder",))
    for sequence in range(2):
        ledger.prepare_chunk("video", sequence, sequence*40_000, (sequence+1)*40_000,
                             f"synthetic-video-{sequence}".encode(), ("shared-encoder",))
    ledger.deliver("audio", 3)
    ledger.deliver("video", 1)
    prefix_rewrite_rejected = False
    try:
        ledger.prepare_chunk("audio", 0, 0, 20_000, b"replacement", ("shared-encoder",))
    except ValueError:
        prefix_rewrite_rejected = True
    return {"evidence_kind": "synthetic_timestamp_and_accounting_fixture",
            "ledger": ledger.report(), "synchronization": ledger.check_av_sync(5_000),
            "delivered_prefix_rewrite_rejected": prefix_rewrite_rejected,
            "shared_compute_charged_once": ledger.consumed == 39,
            "actual_audio_video_generated": False}
