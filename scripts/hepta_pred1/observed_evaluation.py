"""Observed-action scores and a conditional paired eligibility check.

These checks validate declarations, not owner provenance, randomization or
independence. A passed numerical gate never adopts a model. Missing effects,
counterfactuals and costs remain missing; continuous targets use their own units.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import itertools
import json
import math
from numbers import Real
import re
from types import MappingProxyType

import numpy as np

from .contracts import Evidence, EvidenceSource, EffectTimeKind, ObservationStatus

COST_FIELDS = (
    "action", "preparation", "inference", "training", "validation", "failures",
    "recovery", "transport",
)
QUANTILES = (0.1, 0.5, 0.9)
FORECAST_FIELDS = {
    "success_probability", "duration_values", "duration_probabilities",
    "cost_values", "cost_probabilities",
}


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError("nonempty bounded identity required")


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("SHA256 identity required")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("finite nonnegative number required")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative number required")
    return value


def _freeze_forecast(forecast):
    if not isinstance(forecast, Mapping) or set(forecast) != FORECAST_FIELDS:
        raise ValueError("forecast fields differ")
    result = {"success_probability": _number(forecast["success_probability"])}
    if result["success_probability"] > 1:
        raise ValueError("invalid success probability")
    for name in ("duration", "cost"):
        x, p = (forecast[name + suffix] for suffix in ("_values", "_probabilities"))
        if not 1 <= len(x) <= 4096 or len(p) != len(x):
            raise ValueError("need 1..4096 matching marginal atoms")
        pairs = sorted((_number(v), _number(w)) for v, w in zip(x, p))
        total = math.fsum(w for _, w in pairs)
        if not math.isclose(total, 1, rel_tol=1e-7, abs_tol=1e-10):
            raise ValueError("marginal probabilities must sum to one")
        result[name + "_values"] = tuple(v for v, _ in pairs)
        result[name + "_probabilities"] = tuple(w / total for _, w in pairs)
    return MappingProxyType(result)


def validate_forecast(prediction):
    """Validate before execution without inventing evidence; return a JSON copy."""
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in _freeze_forecast(prediction).items()
    }


@dataclass(frozen=True)
class UtilityContract:
    """Utility and identical resource caps; unknown caps cannot qualify adoption."""

    cost_unit: str
    time_weight: float
    cost_weight: float
    max_wall_seconds: float | None = None
    max_total_cost: float | None = None

    def __post_init__(self):
        _text(self.cost_unit)
        for key in ("time_weight", "cost_weight"):
            object.__setattr__(self, key, _number(getattr(self, key)))
        for key in ("max_wall_seconds", "max_total_cost"):
            if getattr(self, key) is not None:
                object.__setattr__(self, key, _number(getattr(self, key)))

    @property
    def digest(self):
        return sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    @property
    def budget_limits(self):
        return {"max_wall_seconds": self.max_wall_seconds, "max_total_cost": self.max_total_cost}


@dataclass(frozen=True, kw_only=True)
class ObservedDecision:
    """A forecast joined to one later receipt; references are host declarations.

    The supplied forecast and ledger are copied into immutable mappings. Clocks
    must share the declared domain. Without an arrival cursor, equal decision
    and receipt timestamps cannot establish causal ordering and are rejected.
    Full wall time spans task start through receipt arrival, including queueing
    and scheduling; the observed decision-to-receipt span is a known lower bound.
    """

    sample_id: str
    task_group: str
    split: str
    policy_id: str
    chosen_action: str
    executed_action: str | None
    execution_ref: str | None
    decision_at: float
    prediction_at: float
    clock_id: str
    information_set_digest: str
    budget_contract_digest: str
    prediction: dict
    evidence: Evidence
    full_wall_seconds: float | None
    costs: dict
    source: str = "fixture"

    def __post_init__(self):
        for key in ("sample_id", "task_group", "policy_id", "chosen_action", "clock_id"):
            _text(getattr(self, key))
        for key in ("information_set_digest", "budget_contract_digest"):
            _digest(getattr(self, key))
        if self.split not in ("train", "dev", "confirm"):
            raise ValueError("invalid split")
        if self.source not in ("fixture", "declared_owner"):
            raise ValueError("invalid observation source")
        if not isinstance(self.evidence, Evidence) or self.evidence.source == EvidenceSource.IMAGINED:
            raise ValueError("factual Evidence required")
        if self.source == "declared_owner" and self.evidence.source != EvidenceSource.REAL:
            raise ValueError("owner declaration cannot use simulator evidence")
        for key in ("prediction_at", "decision_at"):
            object.__setattr__(self, key, _number(getattr(self, key)))
        if not self.prediction_at <= self.decision_at < self.evidence.observed_at:
            raise ValueError("forecast must precede the later receipt")
        if self.executed_action is None:
            if self.execution_ref is not None:
                raise ValueError("execution reference without executed action")
        else:
            _text(self.executed_action)
            _text(self.execution_ref)
        object.__setattr__(self, "prediction", _freeze_forecast(self.prediction))
        if not isinstance(self.costs, Mapping) or set(self.costs) != set(COST_FIELDS):
            raise ValueError("complete ledger field set required; use None for unknown")
        costs = {key: None if value is None else _number(value) for key, value in self.costs.items()}
        action = costs["action"]
        if action is not None and action < self.evidence.confirmed_cost_lower_bound:
            raise ValueError("action ledger is below confirmed cost")
        if self.evidence.final_cost is not None and action is not None and action != self.evidence.final_cost:
            raise ValueError("action ledger differs from final cost evidence")
        object.__setattr__(self, "costs", MappingProxyType(costs))
        if self.full_wall_seconds is not None:
            wall = _number(self.full_wall_seconds)
            if wall < self.evidence.observed_at - self.decision_at:
                raise ValueError("full wall time omits decision-to-receipt waiting")
            if self.evidence.time_kind == EffectTimeKind.EXACT and wall < self.evidence.time_lower:
                raise ValueError("full wall time is shorter than exact effect duration")
            object.__setattr__(self, "full_wall_seconds", wall)


def observed_to_dict(decision):
    """Copy a frozen decision to plain JSON; never deepcopy a mapping proxy."""
    if not isinstance(decision, ObservedDecision):
        raise ValueError("observed decision required")
    result = {field.name: getattr(decision, field.name) for field in fields(decision)}
    result["prediction"] = validate_forecast(decision.prediction)
    result["costs"] = dict(decision.costs)
    result["evidence"] = asdict(decision.evidence)
    for name in ("source", "observation_status", "time_kind"):
        result["evidence"][name] = result["evidence"][name].value
    return result


def _marginal(forecast, name, truth):
    x = np.asarray(forecast[name + "_values"])
    p = np.asarray(forecast[name + "_probabilities"])
    cumulative = np.cumsum(p)
    quantiles = [float(x[min(np.searchsorted(cumulative, q), len(x) - 1)]) for q in QUANTILES]
    if truth is None:
        score = None
    else:
        # Sorted-atom exact CRPS in O(n), avoiding an n-by-n distance matrix.
        score = float(p @ np.abs(x - truth) - (p * x * (2 * cumulative - p - 1)).sum())
        if not math.isfinite(score):
            raise ValueError("nonfinite marginal score")
        score = max(0.0, score)
    return score, [
        {"level": q, "prediction": value, "covered": None if truth is None else truth <= value}
        for q, value in zip(QUANTILES, quantiles)
    ]


def score_forecast(prediction, evidence):
    """Pure retrospective scores; no execution, timing or causal gain is proved."""
    if not isinstance(evidence, Evidence) or evidence.source == EvidenceSource.IMAGINED:
        raise ValueError("factual Evidence required")
    forecast = _freeze_forecast(prediction)
    duration = evidence.time_lower if evidence.time_kind == EffectTimeKind.EXACT else None
    duration_score, duration_coverage = _marginal(forecast, "duration", duration)
    cost_score, cost_coverage = _marginal(forecast, "cost", evidence.final_cost)
    return {
        "quality_brier": None if evidence.outcome is None else (forecast["success_probability"] - evidence.outcome) ** 2,
        "duration_crps": duration_score, "cost_crps": cost_score,
        "duration_quantiles": duration_coverage, "cost_quantiles": cost_coverage,
        "score_scope": "forecast scores alone do not establish execution, predecision prediction or causal policy gain",
    }


def score_observed(decision, contract):
    """Score only the chosen and executed action; no other action is imputed."""
    if not isinstance(decision, ObservedDecision) or not isinstance(contract, UtilityContract):
        raise ValueError("observed decision and utility contract required")
    if decision.budget_contract_digest != contract.digest:
        raise ValueError("budget utility contract digest differs")
    e, f = decision.evidence, decision.prediction
    executed = decision.executed_action == decision.chosen_action
    outcome = e.outcome if executed else None
    missing = [key for key in COST_FIELDS if decision.costs[key] is None]
    total = None if missing else math.fsum(decision.costs.values())
    if total is not None and not math.isfinite(total):
        raise ValueError("nonfinite complete cost")
    within_cost = None if total is None or contract.max_total_cost is None else total <= contract.max_total_cost
    within_time = None if decision.full_wall_seconds is None or contract.max_wall_seconds is None else decision.full_wall_seconds <= contract.max_wall_seconds
    within_budget = False if False in (within_cost, within_time) else None if None in (within_cost, within_time) else True
    utility = None
    if outcome is not None and total is not None and decision.full_wall_seconds is not None:
        utility = outcome - contract.cost_weight * total - contract.time_weight * decision.full_wall_seconds
        if not math.isfinite(utility):
            raise ValueError("nonfinite actual utility")
    if executed:
        metrics = score_forecast(f, e)
    else:
        metrics = {key: None for key in ("quality_brier", "duration_crps", "cost_crps")}
        for name in ("duration", "cost"):
            _, metrics[name + "_quantiles"] = _marginal(f, name, None)
        metrics["score_scope"] = "chosen action was not observed executed; factual scores unavailable"
    return {
        "sample_id": decision.sample_id, "task_group": decision.task_group,
        "split": decision.split, "policy_id": decision.policy_id, "source": decision.source,
        "executed_choice_observed": executed,
        "observation_status": e.observation_status.value, "time_kind": e.time_kind.value,
        "outcome": outcome, "success_probability": f["success_probability"],
        **metrics,
        "missing_cost_items": missing, "cost_ledger_complete": not missing,
        "full_cost": total, "full_wall_seconds": decision.full_wall_seconds,
        "budget_limits": contract.budget_limits, "within_budget": within_budget,
        "actual_net_utility": utility,
        "counterfactual_policy_value": None,
    }


def _records(decisions):
    rows = list(itertools.islice(iter(decisions), 4097))
    if not rows or len(rows) > 4096 or not all(isinstance(d, ObservedDecision) for d in rows):
        raise ValueError("need 1..4096 observed decisions")
    seen, units, refs, splits = set(), set(), set(), {}
    for d in rows:
        unit = (d.task_group, d.policy_id)
        if d.sample_id in seen or unit in units:
            raise ValueError("duplicate sample or group-policy evaluation unit")
        seen.add(d.sample_id)
        units.add(unit)
        if d.task_group in splits and splits[d.task_group] != d.split:
            raise ValueError("task group crosses data splits")
        splits[d.task_group] = d.split
        for kind, ref in (("execution", d.execution_ref), ("receipt", d.evidence.receipt_ref)):
            if ref is not None:
                if (kind, ref) in refs:
                    raise ValueError("reused execution or effect receipt")
                refs.add((kind, ref))
    return rows


def evaluate_observed(decisions, contract):
    """Report observed-only scores by source/split/policy, without adopting."""
    scored = [score_observed(d, contract) for d in _records(decisions)]
    summaries = []
    keys = sorted({(r["source"], r["split"], r["policy_id"]) for r in scored})
    for source, split, policy in keys:
        rows = [r for r in scored if (r["source"], r["split"], r["policy_id"]) == (source, split, policy)]
        metrics = {}
        for field in ("quality_brier", "duration_crps", "cost_crps", "actual_net_utility"):
            values = [r[field] for r in rows if r[field] is not None]
            metrics[field] = {"observed_count": len(values), "mean": float(np.mean(values)) if values else None}
        reliability = []
        for b in range(10):
            observed = [r for r in rows if r["outcome"] is not None and min(int(r["success_probability"] * 10), 9) == b]
            reliability.append({
                "lower": b / 10, "upper": (b + 1) / 10, "count": len(observed),
                "mean_prediction": float(np.mean([r["success_probability"] for r in observed])) if observed else None,
                "outcome_rate": float(np.mean([r["outcome"] for r in observed])) if observed else None,
            })
        coverage = {}
        for name in ("duration", "cost"):
            coverage[name] = []
            for i, level in enumerate(QUANTILES):
                values = [r[name + "_quantiles"][i]["covered"] for r in rows if r[name + "_quantiles"][i]["covered"] is not None]
                coverage[name].append({"level": level, "observed_count": len(values), "coverage": float(np.mean(values)) if values else None})
        summaries.append({
            "source": source, "split": split, "policy_id": policy, "count": len(rows),
            "observation_status_counts": dict(Counter(r["observation_status"] for r in rows)),
            "time_kind_counts": dict(Counter(r["time_kind"] for r in rows)),
            "unobserved_chosen_actions": sum(not r["executed_choice_observed"] for r in rows),
            "metrics": metrics, "success_reliability_bins": reliability,
            "quantile_coverage": coverage,
        })
    return {
        "schema": "pred1-observed-evaluation-v1", "decision": "NoUpdate",
        "utility_contract_sha256": contract.digest, "summaries": summaries, "per_sample": scored,
        "budget_limits": contract.budget_limits,
        "counterfactual_policy_value": None,
        "scope": "actual chosen-action labels only; missingness may be informative; complete-case scores do not identify all-task calibration",
        "verification_scope": "structural checks of host declarations; owner provenance and receipt authenticity are not verified",
    }


@dataclass(frozen=True, kw_only=True)
class PairedRegistration:
    """Host-supplied preregistration for randomized, matched independent replicas."""

    registration_ref: str
    clock_id: str
    frozen_at: float
    candidate_policy_id: str
    parent_policy_id: str
    task_groups: tuple
    excluded_task_groups: tuple
    budget_contract_digest: str
    utility_contract_digest: str
    assignment_evidence_ref: str | None = None
    owner_evidence_ref: str | None = None
    design: str = "randomized_paired_replicas"
    independent_groups: bool = False
    new_confirmation: bool = False
    practical_gain: float = 0.02
    alpha: float = 0.05

    def __post_init__(self):
        for key in ("registration_ref", "clock_id", "candidate_policy_id", "parent_policy_id", "design"):
            _text(getattr(self, key))
        if self.candidate_policy_id == self.parent_policy_id:
            raise ValueError("different policy identities required")
        for key in ("budget_contract_digest", "utility_contract_digest"):
            _digest(getattr(self, key))
        for key in ("frozen_at", "practical_gain", "alpha"):
            object.__setattr__(self, key, _number(getattr(self, key)))
        if not 0 < self.alpha <= 0.05 or self.practical_gain < 0.02:
            raise ValueError("gate cannot relax p<=0.05 or gain>=0.02")
        for key in ("independent_groups", "new_confirmation"):
            if type(getattr(self, key)) is not bool:
                raise ValueError("explicit boolean declaration required")
        for key in ("task_groups", "excluded_task_groups"):
            values = tuple(getattr(self, key))
            if len(values) > 4096 or len(set(values)) != len(values):
                raise ValueError("invalid registered groups")
            for value in values:
                _text(value)
            object.__setattr__(self, key, values)
        for value in (self.assignment_evidence_ref, self.owner_evidence_ref):
            if value is not None:
                _text(value)


def paired_adoption_gate(decisions, contract, registration=None):
    """Conditional eligibility, never deployment; no model loss enters the gate.

    Exact sign-flip inference assumes exchangeability from actual randomized
    paired replicas. Refs and declarations do not establish that design. Require
    2..16 prespecified independent groups; no post-hoc subset of complete rows.
    """
    result = {
        "decision": "NoUpdate", "candidate_eligible": False, "production_activation": False,
        "reasons": [], "paired_groups": 0, "mean_net_gain": None, "one_sided_signflip_p": None,
        "budget_limits": contract.budget_limits if isinstance(contract, UtilityContract) else None,
        "within_budget": None, "over_budget_samples": None,
        "verification_scope": "conditional numerical eligibility under supplied owner, preregistration, pairing and independence declarations; not authentication or external adoption approval",
        "counterfactual_scope": "only actual paired task replicas; other unexecuted actions remain unidentified",
    }
    if not isinstance(registration, PairedRegistration):
        result["reasons"] = ["new_preregistration_missing"]
        return result
    try:
        rows = _records(decisions)
    except ValueError as exc:
        result["reasons"] = [str(exc)]
        return result
    r, reasons = registration, result["reasons"]
    if not isinstance(contract, UtilityContract) or r.utility_contract_digest != contract.digest:
        reasons.append("utility_contract_differs")
    elif r.budget_contract_digest != contract.digest:
        reasons.append("budget_utility_contract_differs")
    if isinstance(contract, UtilityContract) and any(value is None for value in contract.budget_limits.values()):
        reasons.append("explicit_shared_budget_limits_missing")
    if not r.new_confirmation or not r.independent_groups:
        reasons.append("new_independent_confirmation_not_declared")
    if r.design != "randomized_paired_replicas" or not r.assignment_evidence_ref or not r.owner_evidence_ref:
        reasons.append("actual_randomized_pair_or_owner_evidence_missing")
    groups = set(r.task_groups)
    if not 2 <= len(groups) <= 16 or groups & set(r.excluded_task_groups):
        reasons.append("invalid_or_previously_used_confirmation_groups")
    policies = {r.candidate_policy_id, r.parent_policy_id}
    if {(d.task_group, d.policy_id) for d in rows} != set(itertools.product(groups, policies)):
        reasons.append("actual_paired_group_coverage_incomplete")
    if any(d.split != "confirm" or d.source != "declared_owner" for d in rows):
        reasons.append("non_owner_or_non_confirmation_observation")
    # Monotonic timestamps from different clocks are never ordered numerically.
    if any(d.clock_id != r.clock_id for d in rows):
        reasons.append("registration_and_observation_clock_domains_differ")
    elif any(r.frozen_at >= d.prediction_at for d in rows):
        reasons.append("registration_not_frozen_before_predictions")
    if any(d.budget_contract_digest != r.budget_contract_digest for d in rows):
        reasons.append("budget_contract_differs")
    lookup = {(d.task_group, d.policy_id): d for d in rows}
    for group in groups:
        pair = [lookup.get((group, p)) for p in (r.candidate_policy_id, r.parent_policy_id)]
        if all(pair) and pair[0].information_set_digest != pair[1].information_set_digest:
            reasons.append("paired_information_sets_differ")
            break
    if reasons:
        return result
    scores = {key: score_observed(d, contract) for key, d in lookup.items()}
    result["paired_groups"] = len(groups)
    result["over_budget_samples"] = [score["sample_id"] for score in scores.values() if score["within_budget"] is False]
    within = [score["within_budget"] for score in scores.values()]
    result["within_budget"] = False if False in within else None if None in within else True
    if result["over_budget_samples"]:
        reasons.append("actual_shared_budget_limit_exceeded")
    values = {key: score["actual_net_utility"] for key, score in scores.items()}
    if any(value is None for value in values.values()):
        reasons.append("actual_effect_or_complete_cost_or_wall_time_missing")
    if reasons:
        return result
    differences = np.array([values[g, r.candidate_policy_id] - values[g, r.parent_policy_id] for g in r.task_groups])
    sums = np.array([0.0])
    for difference in differences:
        sums = np.concatenate((sums + difference, sums - difference))
    observed = float(differences.mean())
    p = float(np.mean(sums >= differences.sum() - 1e-12))
    result.update(paired_groups=len(groups), mean_net_gain=observed, one_sided_signflip_p=p)
    if observed < r.practical_gain:
        reasons.append("net_gain_below_practical_threshold")
    if p > r.alpha:
        reasons.append("paired_randomization_threshold_not_met")
    if not reasons:
        result.update(decision="CandidateEligible", candidate_eligible=True)
    return result
