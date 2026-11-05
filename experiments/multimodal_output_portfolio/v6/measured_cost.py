"""Measured serial research costs; abstract v6 work units remain unchanged.

The whole-request meter includes unclassified Python overhead. Stage totals are
attribution only: they are never added to whole-request CPU or elapsed time.
Explicit owned resident objects accrue byte-seconds until release or finish.
This does not measure device memory, energy, or unregistered allocations.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import math
import time


STAGES = ("observe", "encode", "control", "candidate", "execute", "decode",
          "output_io", "score", "coordinate", "checkpoint", "recover")


def nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)


def validate_receipt(receipt):
    if receipt.get("schema") != "hepta.v6.measured-cost.v1":
        raise ValueError("Unknown measured cost schema")
    physical = receipt["physical"]
    for name in ("cpu_seconds", "wall_seconds", "resident_byte_seconds"):
        nonnegative(physical[name], name)
    for name in ("gpu_seconds", "joules"):
        if physical[name] is not None:
            nonnegative(physical[name], name)
    if type(physical["peak_owned_bytes"]) is not int or physical["peak_owned_bytes"] < 0:
        raise ValueError("Owned byte peak must be a nonnegative integer")
    nonnegative(receipt["service_cost"], "service cost")
    if set(receipt["counters"]) != {"cache_hits", "cache_misses", "recomputations", "candidate_reuses"}:
        raise ValueError("Invalid counter scope")
    if any(type(v) is not int or v < 0 for v in receipt["counters"].values()):
        raise ValueError("Execution counters must be nonnegative integers")
    if not isinstance(receipt["stages"], list):
        raise ValueError("Attribution stages must be explicit")
    for stage in receipt["stages"]:
        if stage["name"] not in STAGES or type(stage["failed"]) is not bool:
            raise ValueError("Invalid attribution stage")
        nonnegative(stage["cpu_seconds"], "stage CPU")
        nonnegative(stage["wall_seconds"], "stage wall")
    for metric in ("cpu_seconds", "wall_seconds"):
        if sum(stage[metric] for stage in receipt["stages"]) > physical[metric] + 1e-8:
            raise ValueError("Serial attribution exceeds whole-request time")


@dataclass(frozen=True)
class Tariff:
    """Frozen utility conversion; zero excludes a metric, never measures it."""

    cpu_second: float = 0.0
    wall_second: float = 0.0
    resident_byte_second: float = 0.0
    gpu_second: float = 0.0
    joule: float = 0.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            nonnegative(value, name)

    def amount(self, receipt):
        validate_receipt(receipt)
        values = receipt["physical"]
        mappings = {"cpu_second": "cpu_seconds", "wall_second": "wall_seconds",
                    "resident_byte_second": "resident_byte_seconds",
                    "gpu_second": "gpu_seconds", "joule": "joules"}
        amount = nonnegative(receipt["service_cost"], "service cost")
        for tariff, metric in mappings.items():
            coefficient = getattr(self, tariff)
            value = values[metric]
            if value is None:
                if coefficient:
                    raise ValueError(f"Required physical metric is unmeasured: {metric}")
                continue
            amount += coefficient * nonnegative(value, metric)
        return nonnegative(amount, "total cost")


class CostMeter:
    """One serial request; all nested executors must report their CPU separately.

    Device telemetry is supplied only by a real external meter. Pending worker
    CPU is not inferred from elapsed time. A failed action's time is retained.
    The caller writes the returned receipt after finish; that final write and
    offline training/analysis belong to a separately reported outer ledger.
    """

    def __init__(self):
        self.started = (time.process_time(), time.perf_counter())
        self.stages = []
        self.residents = {}
        self.resident_byte_seconds = 0.0
        self.peak_owned_bytes = 0
        self.counters = {"cache_hits": 0, "cache_misses": 0,
                         "recomputations": 0, "candidate_reuses": 0}
        self.service_cost = 0.0
        self.child_cpu = 0.0
        self.active_stage = None
        self.finished = False

    def _open(self):
        if self.finished:
            raise ValueError("Meter is already finished")

    @contextmanager
    def stage(self, name):
        self._open()
        if name not in STAGES or self.active_stage is not None:
            raise ValueError("Unknown or overlapping attribution stage")
        self.active_stage = name
        started = (time.process_time(), time.perf_counter())
        failed = True
        try:
            yield
            failed = False
        finally:
            self.stages.append({"name": name, "cpu_seconds": time.process_time() - started[0],
                                "wall_seconds": time.perf_counter() - started[1], "failed": failed})
            self.active_stage = None

    def retain(self, identity, byte_count):
        self._open()
        if not isinstance(identity, str) or not identity or identity in self.residents:
            raise ValueError("Resident objects require unique nonempty identities")
        if type(byte_count) is not int or byte_count < 0:
            raise ValueError("Resident byte count must be a nonnegative integer")
        self.residents[identity] = (byte_count, time.perf_counter())
        self.peak_owned_bytes = max(self.peak_owned_bytes,
                                    sum(value[0] for value in self.residents.values()))

    def release(self, identity):
        self._open()
        size, started = self.residents.pop(identity)
        self.resident_byte_seconds += size * (time.perf_counter() - started)

    def count(self, name, amount=1):
        self._open()
        if name not in self.counters or type(amount) is not int or amount < 0:
            raise ValueError("Unknown or invalid execution counter")
        self.counters[name] += amount

    def charge_service(self, amount):
        self._open()
        self.service_cost += nonnegative(amount, "service cost")

    def report_reaped_child_cpu(self, seconds):
        self._open()
        self.child_cpu += nonnegative(seconds, "reaped child CPU")

    def finish(self, *, gpu_seconds=None, joules=None):
        self._open()
        if self.active_stage is not None:
            raise ValueError("Cannot finish inside an attribution stage")
        gpu_seconds = None if gpu_seconds is None else nonnegative(gpu_seconds, "GPU seconds")
        joules = None if joules is None else nonnegative(joules, "joules")
        for identity in tuple(self.residents):
            self.release(identity)
        ended = (time.process_time(), time.perf_counter())
        self.finished = True
        return {"schema": "hepta.v6.measured-cost.v1", "physical": {
            "cpu_seconds": ended[0] - self.started[0] + self.child_cpu,
            "wall_seconds": ended[1] - self.started[1],
            "resident_byte_seconds": self.resident_byte_seconds,
            "peak_owned_bytes": self.peak_owned_bytes,
            "gpu_seconds": gpu_seconds, "joules": joules},
            "service_cost": self.service_cost, "stages": self.stages, "counters": self.counters,
            "residency_scope": "explicit owned candidate/cache bytes only",
            "timing_scope": "serial parent plus explicitly reaped child CPU; whole elapsed interval",
            "excluded": ["final receipt write", "training", "calibration", "offline DP solve", "archiving"]}
