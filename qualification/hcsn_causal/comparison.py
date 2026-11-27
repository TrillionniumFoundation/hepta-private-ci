"""Paired four-arm analysis that preserves denominators and attempt costs.

This is an offline result reader, never a training launcher. The frozen design
must be fixed before confirmation. Hashes bind supplied artifacts but do not
attest that an external executor really used them; verify original receipts.
"""

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np
from scipy.stats import t as student_t


ARMS = {"A": ("smooth", "fixed"), "B": ("smooth", "feedback"),
        "C": ("analytic", "fixed"), "D": ("analytic", "feedback")}
CONTRASTS = {"feedback_smooth_B_minus_A": ("B", "A"),
             "feedback_analytic_D_minus_C": ("D", "C"),
             "kernel_fixed_C_minus_A": ("C", "A"),
             "kernel_feedback_D_minus_B": ("D", "B")}


def _hash(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("artifact SHA256 required")
    return value


def _positive_integer(value):
    if type(value) is not int or value <= 0:
        raise ValueError("positive integer required")
    return value


def _nonnegative(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative measurement required")
    return float(value)


@dataclass(frozen=True)
class Design:
    """One task/scale stratum; run more strata instead of pooling unlike scales.

    Capacity is active trainable and persistent-state capacity, not the count
    of dummy/frozen parameters. All four arms share the same frontend, input
    projection, addressor, head, examples, steps and search allowance.
    """

    task: str
    scale: str
    seeds: tuple[int, ...]
    frontend_sha256: str
    data_sha256: str
    common_architecture_sha256: str
    numerical_profile_sha256: str
    measurement_profile_sha256: str
    active_parameters: int
    state_scalars: int
    train_updates: int
    examples_per_update: int
    tuning_updates: int
    minimum_quality_gain: float

    def __post_init__(self):
        if (not isinstance(self.task, str) or not self.task
                or not isinstance(self.scale, str) or not self.scale):
            raise ValueError("named task and scale required")
        if (not isinstance(self.seeds, tuple) or len(self.seeds) < 2
                or len(set(self.seeds)) != len(self.seeds)
                or any(type(s) is not int or s < 0 for s in self.seeds)):
            raise ValueError("two or more distinct preregistered seeds required")
        for value in (self.frontend_sha256, self.data_sha256,
                      self.common_architecture_sha256, self.numerical_profile_sha256,
                      self.measurement_profile_sha256):
            _hash(value)
        for value in (self.active_parameters, self.state_scalars,
                      self.train_updates, self.examples_per_update):
            _positive_integer(value)
        if type(self.tuning_updates) is not int or self.tuning_updates < 0:
            raise ValueError("exact nonnegative tuning allowance required")
        _nonnegative(self.minimum_quality_gain)

    def identity(self):
        return hashlib.sha256(json.dumps(self.__dict__, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Attempt:
    """All submitted attempts count, including OOM, failure and uncertainty."""

    arm: str
    seed: int
    attempt_id: str
    design_sha256: str
    shared_initialization_sha256: str
    status: str
    active_parameters: int
    state_scalars: int
    optimizer_updates: int | None
    submitted_examples: int | None
    tuning_updates: int | None
    total_wall_seconds: float | None
    energy_joules: float | None
    higher_is_better_quality: float | None = None
    inference_p95_seconds: float | None = None

    def __post_init__(self):
        if self.arm not in ARMS or type(self.seed) is not int or self.seed < 0:
            raise ValueError("unknown arm/seed")
        if not isinstance(self.attempt_id, str) or not self.attempt_id:
            raise ValueError("immutable attempt ID required")
        if self.status not in {"completed", "failed", "oom", "unavailable", "unknown"}:
            raise ValueError("explicit attempt outcome required")
        for value in (self.design_sha256, self.shared_initialization_sha256):
            _hash(value)
        _positive_integer(self.active_parameters)
        _positive_integer(self.state_scalars)
        for value in (self.optimizer_updates, self.submitted_examples, self.tuning_updates):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("exact nonnegative cost counter required")
        for value in (self.total_wall_seconds, self.energy_joules, self.inference_p95_seconds):
            if value is not None:
                _nonnegative(value)
        if self.higher_is_better_quality is not None and (
                type(self.higher_is_better_quality) not in (int, float)
                or not math.isfinite(self.higher_is_better_quality)):
            raise ValueError("finite quality required")
        if self.status == "completed" and (self.higher_is_better_quality is None
                or self.inference_p95_seconds is None or self.inference_p95_seconds <= 0):
            raise ValueError("completed attempt needs quality and latency")
        if self.status == "completed" and self.total_wall_seconds == 0:
            raise ValueError("completed training cannot have zero measured wall time")
        if self.status != "completed" and (self.higher_is_better_quality is not None
                or self.inference_p95_seconds is not None):
            raise ValueError("nonterminal quality cannot be used for selection")


def _interval(values, *, simultaneous_tests=1):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise FloatingPointError("contrast cannot be represented as a finite paired vector")
    scale = float(np.max(np.abs(values)))
    normalized = values/scale if scale else values
    mean = float(normalized.mean())
    radius = float(student_t.ppf(1-0.05/(2*simultaneous_tests), len(values)-1)
                   * normalized.std(ddof=1)/math.sqrt(len(values)))
    result = {"n": len(values), "mean": mean*scale,
              "lower": (mean-radius)*scale, "upper": (mean+radius)*scale}
    if not all(math.isfinite(result[key]) for key in ("mean", "lower", "upper")):
        raise FloatingPointError("paired interval is unresolved in FP64")
    return result


def compare(design, attempts, *, inventory=None):
    """Require every paired identity and matching budgets before any contrast.

    Confidence intervals use paired seeds. The four kernel/feedback contrasts
    and their interaction use a Bonferroni family of five. The strict net gate
    intersects prespecified D-B quality, latency and total physical-energy tests.
    Historical records with unknown cost/energy remain unknown, never zero.
    """
    if not isinstance(design, Design):
        raise ValueError("validated frozen design required")
    attempts = tuple(attempts)
    if inventory is not None:
        from .inventory import AttemptInventory
        if not isinstance(inventory, AttemptInventory):
            raise ValueError("a scanned owner attempt inventory is required")
        inventory.verify(design, attempts)
    roster = {(arm, seed): [] for arm in ARMS for seed in design.seeds}
    ids = set()
    for record in attempts:
        if not isinstance(record, Attempt) or record.attempt_id in ids:
            raise ValueError("duplicate/invalid attempt")
        ids.add(record.attempt_id)
        key = record.arm, record.seed
        if key not in roster or record.design_sha256 != design.identity():
            raise ValueError("attempt outside the frozen design")
        if (record.active_parameters != design.active_parameters
                or record.state_scalars != design.state_scalars):
            raise ValueError("active capacity differs between arms")
        roster[key].append(record)
    report = {"design_sha256": design.identity(), "expected_identities": len(roster),
              "observed_attempts": len(attempts), "outcomes": {}, "missing": [],
              "unknown_costs": [], "budget_errors": [], "contrasts": None,
              "quality_latency_energy_gain": False, "status": "HOLD"}
    report["attempt_inventory"] = inventory.as_dict() if inventory is not None else None
    report["complete_attempt_costs_verified"] = inventory is not None
    for status in ("completed", "failed", "oom", "unavailable", "unknown"):
        report["outcomes"][status] = sum(r.status == status for r in attempts)
    completed, costs = {}, {}
    for key, records in roster.items():
        done = [r for r in records if r.status == "completed"]
        if len(done) > 1:
            raise ValueError("multiple completed attempts would allow result selection")
        if not done:
            report["missing"].append(list(key))
        else:
            completed[key] = done[0]
        identity_cost = {}
        for field in ("optimizer_updates", "submitted_examples", "tuning_updates",
                      "total_wall_seconds", "energy_joules"):
            value = None if not records or any(getattr(r, field) is None for r in records) else sum(
                getattr(r, field) for r in records)
            if value is not None and field in ("total_wall_seconds", "energy_joules"):
                _nonnegative(value)
            identity_cost[field] = value
            if value is None:
                report["unknown_costs"].append([*key, field])
        costs[key] = identity_cost
        if done and (done[0].optimizer_updates != design.train_updates or
                     done[0].submitted_examples != design.train_updates*design.examples_per_update):
            report["budget_errors"].append([*key, "incomplete final training"])
        for field, limit in (("optimizer_updates", design.train_updates),
                             ("submitted_examples", design.train_updates*design.examples_per_update),
                             ("tuning_updates", design.tuning_updates)):
            if identity_cost[field] is not None and identity_cost[field] > limit:
                report["budget_errors"].append([*key, field, identity_cost[field], limit])
    report["costs_by_identity"] = [{"arm": arm, "seed": seed, **costs[arm, seed]}
                                   for arm, seed in roster]
    # Pair shared initialization per seed, without requiring different seeds
    # to have identical draws. This binds only common parameters, not kernels.
    for seed in design.seeds:
        initializations = {r.shared_initialization_sha256 for (arm, s), rows in roster.items()
                           if s == seed for r in rows}
        if len(initializations) > 1:
            raise ValueError("unmatched shared initialization for a paired seed")
    unknown_training = any(row[2] != "energy_joules" for row in report["unknown_costs"])
    if (report["missing"] or report["budget_errors"] or unknown_training
            or report["outcomes"]["unknown"]):
        return report
    # Matching maximum search allowance is insufficient: verify realized search
    # use is equal too. The wall/energy of the search belongs in total costs.
    for seed in design.seeds:
        if len({costs[arm, seed]["tuning_updates"] for arm in ARMS}) != 1:
            report["budget_errors"].append([seed, "unmatched realized tuning"])
    if report["budget_errors"]:
        return report
    qualities = {arm: np.array([completed[arm, seed].higher_is_better_quality
                               for seed in design.seeds]) for arm in ARMS}
    with np.errstate(over="raise", invalid="raise"):
        effects = {name: qualities[left]-qualities[right]
                   for name, (left, right) in CONTRASTS.items()}
        interaction = effects["kernel_feedback_D_minus_B"]-effects["kernel_fixed_C_minus_A"]
    contrasts = {name: _interval(effect, simultaneous_tests=5) for name, effect in effects.items()}
    contrasts["interaction_D_minus_C_minus_B_plus_A"] = _interval(interaction, simultaneous_tests=5)
    report["contrasts"] = contrasts
    report["status"] = ("complete_paired_analysis" if inventory is not None
                        else "unqualified_paired_analysis")
    quality = contrasts["kernel_feedback_D_minus_B"]
    latency = _interval([math.log(completed["D", seed].inference_p95_seconds)-
                         math.log(completed["B", seed].inference_p95_seconds)
                         for seed in design.seeds], simultaneous_tests=3)
    report["D_over_B_latency_log_ratio"] = latency
    energy = None
    if all(costs[arm, seed]["energy_joules"] is not None and
           costs[arm, seed]["energy_joules"] > 0 for arm in ("B", "D") for seed in design.seeds):
        energy = _interval([math.log(costs["D", seed]["energy_joules"])-
                            math.log(costs["B", seed]["energy_joules"])
                            for seed in design.seeds], simultaneous_tests=3)
    report["D_over_B_total_energy_log_ratio"] = energy
    report["quality_latency_energy_gain"] = bool(
        inventory is not None and quality["lower"] > design.minimum_quality_gain and latency["upper"] < 0
        and energy is not None and energy["upper"] < 0)
    return report
