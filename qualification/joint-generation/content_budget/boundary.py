"""Prospective method/research accounting primitives. No training capability."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math


METHOD_PHASES = frozenset(("prepare", "train", "selection", "validation", "export", "self_check", "service"))
REVIEW_PHASES = frozenset(("independent_review", "posthoc_diagnosis", "manuscript"))


def nonnegative(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative resource amount required")
    return value


@dataclass(frozen=True)
class Plan:
    cap_CPU: float
    cap_units: int
    common_CPU: float
    common_units: int
    slots: int = 6
    tail_CPU: float = 2.5
    tail_units: int = 500_000_000
    global_guard_CPU: float = .5

    def __post_init__(self):
        for value in (self.cap_CPU, self.cap_units, self.common_CPU, self.common_units,
                      self.tail_CPU, self.tail_units, self.global_guard_CPU):
            nonnegative(value)
        if any(type(value) is not int for value in (self.cap_units, self.common_units, self.tail_units)):
            raise ValueError("integer operator-unit accounting required")
        if type(self.slots) is not int or self.slots < 1:
            raise ValueError("fixed positive slot count required")
        if self.training_CPU_per_slot <= 0 or self.training_units_per_slot <= 0:
            raise ValueError("no affordable complete training slot; do not launch")

    @property
    def training_CPU_per_slot(self):
        return (self.cap_CPU - self.common_CPU - self.tail_CPU - self.global_guard_CPU) / self.slots

    @property
    def training_units_per_slot(self):
        return (self.cap_units - self.common_units - self.tail_units) // self.slots

    def snapshot(self):
        return dict(asdict(self), training_CPU_per_slot=self.training_CPU_per_slot,
                    training_units_per_slot=self.training_units_per_slot)


class BoundaryLedger:
    """Pure receipt state machine, intended for a future frozen runner.

    The external meter supplies complete process-tree CPU after each measured
    action. This class does not time, execute or authorize a model operation.
    All observed overages are retained; neither a review nor a later report can
    rewrite a sealed method snapshot. Actual hidden method work discovered by
    review requires invalidating/reconciling the claim, never a retroactive pass.
    """

    def __init__(self, plan, *, architectures=("independent", "native")):
        self.plan = plan
        self.architectures = frozenset(architectures)
        self.method = [dict(phase="prepare", name="actual_shared_provenance",
                            CPU=plan.common_CPU, units=plan.common_units)]
        self.research = []
        self.sealed = None
        self.slot_spend = {}
        self.failure_reasons = []

    def totals(self):
        return dict(CPU=sum(x["CPU"] for x in self.method), units=sum(x["units"] for x in self.method))

    def admit(self, *, worst_CPU, worst_units, training=False):
        if self.sealed is not None or self.failure_reasons:
            return False
        nonnegative(worst_CPU)
        nonnegative(worst_units)
        used = self.totals()
        escrow_CPU = self.plan.global_guard_CPU + (self.plan.tail_CPU if training else 0)
        escrow_units = self.plan.tail_units if training else 0
        return (used["CPU"] + worst_CPU + escrow_CPU <= self.plan.cap_CPU
                and used["units"] + worst_units + escrow_units <= self.plan.cap_units)

    def charge_method(self, phase, name, CPU, units, *, architecture=None, slot=None):
        if self.sealed is not None:
            raise ValueError("sealed method cannot be extended; retain a separate research receipt")
        if phase not in METHOD_PHASES:
            raise ValueError("research phases cannot be silently charged as method or used for selection")
        if architecture is not None and architecture not in self.architectures:
            raise ValueError("unused architecture-specific preparation cannot be billed to this method")
        nonnegative(CPU)
        nonnegative(units)
        if phase == "train":
            if type(slot) is not int or not 0 <= slot < self.plan.slots:
                raise ValueError("one of the fixed training slots required")
            spend = self.slot_spend.setdefault(slot, dict(CPU=0., units=0))
            spend["CPU"] += CPU
            spend["units"] += units
            if spend["CPU"] > self.plan.training_CPU_per_slot or spend["units"] > self.plan.training_units_per_slot:
                self.failure_reasons.append("actual_slot_allowance_exceeded")
        self.method.append(dict(phase=phase, name=name, CPU=CPU, units=units,
                                architecture=architecture, slot=slot))
        used = self.totals()
        if used["CPU"] > self.plan.cap_CPU or used["units"] > self.plan.cap_units:
            self.failure_reasons.append("actual_method_cap_exceeded")

    def seal_method(self, outputs_digest):
        if self.sealed is not None:
            raise ValueError("method already sealed")
        if not METHOD_PHASES.issubset({x["phase"] for x in self.method}):
            raise ValueError("mandatory method output/self-check/service phases incomplete")
        if set(self.slot_spend) != set(range(self.plan.slots)):
            raise ValueError("fixed candidate portfolio incomplete; no subset pass")
        if not isinstance(outputs_digest, str) or not outputs_digest:
            raise ValueError("immutable output manifest digest required")
        payload = dict(plan=self.plan.snapshot(), method=[dict(x) for x in self.method], totals=self.totals(),
                       outputs_digest=outputs_digest, failures=list(self.failure_reasons))
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.sealed = dict(payload, receipt_sha256=hashlib.sha256(encoded).hexdigest(),
                           resource_eligible=not self.failure_reasons)
        return json.loads(json.dumps(self.sealed))

    def charge_review(self, phase, name, CPU, units, *, uses_for_method=False):
        if self.sealed is None:
            raise ValueError("independent output review must consume a sealed method result")
        if phase not in REVIEW_PHASES or uses_for_method:
            raise ValueError("review information cannot be a free training/selection dependency")
        nonnegative(CPU)
        nonnegative(units)
        self.research.append(dict(phase=phase, name=name, CPU=CPU, units=units,
                                  method_receipt=self.sealed["receipt_sha256"]))


def tail_unit_admission_quote():
    """Conservative frozen-geometry quote, not consumed work or hardware FLOPs.

    Original144-cell scorer's expensive CE branch, all possible exact support
    fallbacks and original2-full-equivalent service cap are included. One million
    initialization/export scalar units and25M self-check units are reservations.
    A future implementation must rederive this quote if its actual code changes.
    """
    n = 768
    native_final = 24182 * n + 312
    independent_final = 39178 * n + 576
    final_observation = 3 * (native_final + independent_final)
    service = 9 * 64 * (2 * 19236)
    return dict(final_observation=final_observation, service=service,
        setup_and_final_delta_envelope=1_000_000, mandatory_self_check_envelope=25_000_000,
        final_summary_envelope=5_000,
        total=final_observation + service + 1_000_000 + 25_000_000 + 5_000)
