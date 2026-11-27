"""Independent-source risk calibration of the policy actually executed.

With unbounded physical CPU cost, a finite distribution-free upper confidence
bound on the exponential moment does not exist. A net-return threshold event
still admits an exact binomial bound. These conclusions must not be confused.
"""

from dataclasses import asdict, dataclass
import math

from ..unified_20261028.profile import (CostEvent, DeliveredOutcome, certainty_equivalent,
                                      digest, log_moment, net_return)
from ..unified_20261028.tail import success_lower_bound


@dataclass(frozen=True)
class CalibrationPlan:
    profile_sha256: str
    policy_sha256: str
    source_freeze_sha256: str
    source_ids: tuple[str, ...]
    excluded_source_ids: tuple[str, ...]
    return_threshold: float = 0.0
    alpha: float = .05
    family_size: int = 1

    def __post_init__(self):
        for name in ("profile_sha256", "policy_sha256", "source_freeze_sha256"):
            value = getattr(self, name)
            if (not isinstance(value, str) or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("Pre-execution profile, selected policy and source-freeze hashes are required")
        if (not isinstance(self.source_ids, tuple) or not self.source_ids
                or len(set(self.source_ids)) != len(self.source_ids)
                or not isinstance(self.excluded_source_ids, tuple)
                or set(self.source_ids).intersection(self.excluded_source_ids)):
            raise ValueError("Calibration must freeze unique sources disjoint from all fitting/selection")
        if (isinstance(self.return_threshold, bool) or not math.isfinite(self.return_threshold)
                or not 0 < self.alpha < 1 or isinstance(self.family_size, bool)
                or not isinstance(self.family_size, int) or self.family_size < 1):
            raise ValueError("A predeclared threshold and confidence family are required")

    @property
    def digest(self):
        return digest({"schema": "hepta.ndu.physical-risk-calibration-plan.v1", **asdict(self)})


def _outcome(record):
    value = dict(record["outcome"])
    value["costs"] = tuple(CostEvent(**entry) for entry in value["costs"])
    value["artifact_sha256"] = tuple(tuple(entry) for entry in value["artifact_sha256"])
    return DeliveredOutcome(**value)


def calibrate_actual(records, profile, plan):
    """All planned sources are required; a failed trajectory cannot be omitted.

The plan hash must be bound to each receipt before prediction. The caller must
provide its archived chronological source freeze; the hash alone does not
prove provenance, event independence or absence of earlier source exposure.
"""
    if plan.profile_sha256 != profile.digest:
        raise ValueError("Calibration profile differs from the actual objective")
    unique, sources, contexts = {}, set(), set()
    values, costs, selected_predictions, overruns = [], [], [], []
    for record in records:
        event_id = record["event_id"]
        fingerprint = digest(record)
        if event_id in unique:
            if unique[event_id] != fingerprint:
                raise ValueError("Conflicting replay of an actual calibration event")
            continue
        if (record["profile_sha256"] != profile.digest
                or record["policy_sha256"] != plan.policy_sha256
                or record["calibration_plan_sha256"] != plan.digest
                or record["split"] != "calibration"):
            raise ValueError("Actual selected policy/source phase differs from its frozen calibration plan")
        source = record["source_id"]
        if source not in plan.source_ids or source in sources or source in plan.excluded_source_ids:
            raise ValueError("Repeated, reserved or unplanned source cannot inflate calibration")
        outcome = _outcome(record)
        if outcome.source_cluster_id != source or outcome.sample_id != event_id:
            raise ValueError("Actual outcome identity differs from the execution receipt")
        value = net_return(profile, outcome)
        if not math.isclose(value, record["net_return"], rel_tol=0, abs_tol=1e-12):
            raise ValueError("Calibration return is not the fully charged executed outcome")
        contexts.add(outcome.context_id)
        if profile.aggregation == "conditional" and len(contexts) > 1:
            raise ValueError("Conditional risk cannot be calibrated by pooling different public contexts")
        if record["selected_action"] not in {"keep", "swap"} or record["executed_action"] not in {"keep", "swap"}:
            raise ValueError("The complete law must retain actual selected and executed actions")
        predicted = record["decision"]["predicted_complete_moments"]
        if predicted is None or record["decision"]["policy_sha256"] != plan.policy_sha256:
            raise ValueError("Calibrate the frozen deployed actor, not forced-action fitting records")
        selected_predictions.append(predicted[record["selected_action"]])
        unique[event_id] = fingerprint
        sources.add(source)
        values.append(value)
        costs.append(math.fsum(entry.amount for entry in outcome.costs))
        overruns.append(bool(record["cpu_admission_threshold_exceeded"]))
    if sources != set(plan.source_ids):
        raise ValueError("Every frozen calibration source needs a complete success/failure/cost outcome")
    # Two planned probability statements per policy family: net-return event
    # and CPU threshold overrun. Bonferroni retains their simultaneous meaning.
    per_test_alpha = plan.alpha / (2 * plan.family_size)
    success = sum(value >= plan.return_threshold for value in values)
    safe_cpu = len(overruns) - sum(overruns)
    violation_upper = 1 - success_lower_bound(success, len(values), per_test_alpha)
    overrun_upper = 1 - success_lower_bound(safe_cpu, len(values), per_test_alpha)
    return {"schema": "hepta.ndu.actual-selected-policy-risk.v1", "plan_sha256": plan.digest,
            "profile_sha256": profile.digest, "policy_sha256": plan.policy_sha256,
            "independent_sources": len(sources), "execution_records_sha256": digest(sorted(unique.items())),
            "source_freeze_sha256": plan.source_freeze_sha256,
            "empirical_complete_return_ce": certainty_equivalent(values, profile.gamma),
            "empirical_complete_log_moment": log_moment(values, profile.gamma),
            "mean_actual_total_cost": math.fsum(costs) / len(costs),
            "mean_selected_action_predicted_moment": math.fsum(selected_predictions) / len(values),
            "return_threshold": plan.return_threshold, "observed_return_violations": len(values) - success,
            "return_violation_probability_upper": violation_upper,
            "observed_cpu_threshold_overruns": sum(overruns), "cpu_overrun_probability_upper": overrun_upper,
            "alpha": plan.alpha, "family_size": plan.family_size,
            "ndu_moment_upper": None, "ndu_ce_lower": None, "ndu_tail_blocker_closed": False,
            "ndu_bound_status": "unavailable: complete physical CPU cost has no proved finite support or tail-moment envelope",
            "clipped_costs_or_returns": False, "policy_fit_on_these_records": False,
            "scope": "binomial threshold-risk guarantee under independent source sampling; not an NDU moment guarantee",
            "remaining_assumptions": ["source clusters are independent draws from the declared future population",
                                      "all policy/model/observer/source selection is fixed before these sources are consumed"]}


def unobserved_cost_witness(*, n, miss_probability, proposed_moment_upper, gamma):
    """Construct a rare-cost law that defeats a data-only finite moment bound.

This is an identifiability check, not observed tail evidence. The proposed law
gives n apparently harmless zero-return observations with the stated chance.
"""
    if (not isinstance(n, int) or isinstance(n, bool) or n < 1
            or not 0 < miss_probability < 1 or gamma <= 0 or proposed_moment_upper <= 1):
        raise ValueError("A positive-risk finite-bound challenge is required")
    rare_probability = -math.expm1(math.log(miss_probability) / n)
    catastrophic_cost = math.log(2 * proposed_moment_upper / rare_probability) / gamma
    actual_moment = 1 - rare_probability + rare_probability * math.exp(gamma * catastrophic_cost)
    return {"rare_cost_probability": rare_probability, "rare_actual_cost": catastrophic_cost,
            "all_n_costs_appear_zero_probability": (1 - rare_probability) ** n,
            "true_exponential_moment": actual_moment, "proposed_upper_is_violated": actual_moment > proposed_moment_upper}
