"""Independent paired utility gate for Group reasoning research.

No model imports, hidden-label access, topology writes or capability grants.
Each row represents one independently evaluated case and one registered arm.
This is an observational gate, NOT an NDU/FBSDE solver or a production owner.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import math

ARMS = ("static", "recurrent", "ndu", "split")
COHORTS = ("ordinary", "long", "deleted", "composition", "multimodal")
COST_KEYS = ("encoder", "training_amortized", "inference", "verification",
             "search", "migration_amortized", "memory", "recovery")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                      allow_nan=False).encode()).hexdigest()


def _finite(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field}: finite nonnegative number required")
    return float(value)


@dataclass(frozen=True)
class PairedRow:
    case_id: str
    group_id: str
    cohort: str
    arm: str
    source_sha256: str
    evaluator_sha256: str
    correct: bool
    evidence_supported: bool
    cost: dict

    @classmethod
    def parse(cls, d):
        expected = set(cls.__dataclass_fields__)
        if type(d) is not dict or set(d) != expected:
            raise ValueError("invalid or incomplete paired row schema")
        for key in ("case_id", "group_id"):
            if type(d[key]) is not str or not 1 <= len(d[key]) <= 128:
                raise ValueError(f"invalid {key}")
        for key in ("source_sha256", "evaluator_sha256"):
            v = d[key]
            if (type(v) is not str or len(v) != 64
                    or v == "0" * 64 or any(x not in "0123456789abcdef" for x in v)):
                raise ValueError(f"invalid {key}")
        if d["cohort"] not in COHORTS or d["arm"] not in ARMS:
            raise ValueError("unknown cohort or arm")
        if type(d["correct"]) is not bool or type(d["evidence_supported"]) is not bool:
            raise ValueError("verified booleans required")
        if type(d["cost"]) is not dict or set(d["cost"]) != set(COST_KEYS):
            raise ValueError("all lifecycle cost categories required")
        return cls(**{**d, "cost": {k: _finite(v, k) for k, v in d["cost"].items()}})


def review(rows, *, preregistered_arms=("recurrent", "ndu", "split"),
           cost_weight=1.0, min_groups=20, max_group_loss=0.05,
           min_improvement=0.0, alpha=0.05):
    """Source-group paired conservative gate; no adaptive candidate search.

    Costs are required in externally pre-registered normalized task-utility
    units, rather than mixing seconds and bytes. Group-level bounded paired
    rewards use [-1,1] only when weighted total cost <= 1 per case.
    The Hoeffding radius assumes independently sampled source groups and
    one predeclared comparison; this code does not establish independence.
    """
    if (type(preregistered_arms) not in (tuple, list) or not preregistered_arms
            or len(set(preregistered_arms)) != len(preregistered_arms)
            or any(a not in ARMS or a == "static" for a in preregistered_arms)):
        raise ValueError("invalid pre-registered candidate arms")
    _finite(cost_weight, "cost_weight")
    if cost_weight <= 0:
        raise ValueError("cost weight must be positive")
    _finite(max_group_loss, "max_group_loss")
    _finite(min_improvement, "min_improvement")
    if type(min_groups) is not int or min_groups < 2 or not (0 < alpha < 1):
        raise ValueError("invalid preregistered statistical controls")
    parsed = [PairedRow.parse(d) for d in rows]
    if not parsed:
        raise ValueError("empty observations")
    by_case = defaultdict(dict)
    group_cohort = {}
    for row in parsed:
        if row.arm in by_case[row.case_id]:
            raise ValueError("duplicate (case, arm) observation")
        previous = group_cohort.setdefault(row.group_id, row.cohort)
        if previous != row.cohort:
            raise ValueError("a source group may not cross cohorts")
        by_case[row.case_id][row.arm] = row
    required = {"static", *preregistered_arms}
    groups = defaultdict(list)
    for case, arm_rows in by_case.items():
        if set(arm_rows) != required:
            raise ValueError("unpaired case or undisclosed extra candidate")
        base = arm_rows["static"]
        for row in arm_rows.values():
            if (row.group_id, row.cohort, row.source_sha256, row.evaluator_sha256,
                    row.evidence_supported) != (
                    base.group_id, base.cohort, base.source_sha256,
                    base.evaluator_sha256, base.evidence_supported):
                raise ValueError("source/evaluator/evidence identity mismatch")
            if not row.evidence_supported and row.correct:
                raise ValueError("unsupported case cannot count as verified correct")
            if cost_weight * sum(row.cost.values()) > 1:
                raise ValueError("cost bound does not support Hoeffding range")
        groups[base.group_id].append(arm_rows)
    report = {"schema": "hepta.group.independent-utility-gate.v1",
              "authority": "DENY_ALL", "production_promotion_permitted": False,
              "source_group_independence_verified": False,
              "causal_efficiency_established": False, "number_of_cases": len(by_case),
              "number_of_source_groups": len(groups), "arms": {}}
    for arm in preregistered_arms:
        deltas, cohort_loss, rescued, harmed = [], defaultdict(list), 0, 0
        for group_cases in groups.values():
            changes = []
            for row in group_cases:
                baseline, candidate = row["static"], row[arm]
                base_u = float(baseline.correct) - cost_weight * sum(baseline.cost.values())
                cand_u = float(candidate.correct) - cost_weight * sum(candidate.cost.values())
                changes.append(cand_u - base_u)
                cohort_loss[baseline.cohort].append(cand_u - base_u)
                rescued += int(candidate.correct and not baseline.correct)
                harmed += int(baseline.correct and not candidate.correct)
            deltas.append(sum(changes) / len(changes))
        n = len(deltas)
        mean = sum(deltas) / n
        # Delta lies in [-2,2] for individually bounded [-1,1] utilities.
        radius = 4 * math.sqrt(math.log(2 * len(preregistered_arms) / alpha) / (2 * n))
        lower = mean - radius
        strata = {k: sum(v) / len(v) for k, v in sorted(cohort_loss.items())}
        accepted = (n >= min_groups and lower > min_improvement
                    and all(v >= -max_group_loss for v in strata.values())
                    and "deleted" in strata and "composition" in strata)
        report["arms"][arm] = {
            "decision": "candidate_admissible" if accepted else "reject_or_insufficient_evidence",
            "paired_mean_delta": mean, "conservative_lower": lower,
            "group_radius": radius, "source_groups": n, "cohort_mean_deltas": strata,
            "rescued": rescued, "harmed": harmed, "missing_critical_cohorts":
                [c for c in ("deleted", "composition") if c not in strata],
        }
    report["observation_sha256"] = _digest(rows)
    report["policy_sha256"] = _digest({
        "arms": list(preregistered_arms), "cost_weight": cost_weight,
        "min_groups": min_groups, "max_group_loss": max_group_loss,
        "min_improvement": min_improvement, "alpha": alpha})
    return report
