"""Selected-policy tail bounds from complete, independent-source event outcomes.

Feedback, all modality scores, refusal/failure and actual costs stay in the same
event. A candidate's marginal accuracy is never multiplied into a joint law.
The policy and selection stratum must be frozen before these records arrive.
"""

from dataclasses import asdict, dataclass
import math

from .profile import DeliveredOutcome, digest, moment_cost, net_return, total_cost


@dataclass(frozen=True)
class JointEvent:
    event_id: str
    source_ids: tuple[str, ...]
    selected_action: str
    executed_action: str
    feedback: float
    outcome: DeliveredOutcome
    policy_sha256: str
    profile_sha256: str
    execution_receipt_sha256: str
    selection_key: str = "all"


def success_lower_bound(successes, trials, alpha):
    """One-sided exact binomial bound, computed without a SciPy dependency."""
    if (isinstance(trials, bool) or not isinstance(trials, int) or trials < 0
            or isinstance(successes, bool) or not isinstance(successes, int)
            or not 0 <= successes <= trials or not 0 < alpha < 1):
        raise ValueError("Invalid binomial evidence or tail probability")
    if successes == 0:
        return 0.0
    if successes == trials:
        return math.exp(math.log(alpha) / trials)
    coefficients = [math.lgamma(trials + 1) - math.lgamma(k + 1)
                    - math.lgamma(trials - k + 1) for k in range(successes, trials + 1)]
    lower, upper = 0.0, 1.0
    for _ in range(64):
        p = (lower + upper) / 2
        logs = [coefficient + k * math.log(p) + (trials - k) * math.log1p(-p)
                for k, coefficient in zip(range(successes, trials + 1), coefficients)]
        peak = max(logs)
        log_tail = peak + math.log(math.fsum(math.exp(x - peak) for x in logs))
        if log_tail < math.log(alpha):
            lower = p
        else:
            upper = p
    return lower


def calibrate_selected(events, profile, *, policy_sha256, net_return_bounds,
                       excluded_source_ids, selection_key="all", alpha=0.05,
                       family_size=1, method="bounded"):
    """Upper-bound E exp(-gamma R) for one frozen selected-policy stratum.

Bounds are declared support of FUTURE net returns, including maximum admissible
costs; estimating the support from these observations is invalid. ``two_point``
requires a predeclared binary return law and uses Clopper-Pearson. ``bounded``
uses a distribution-free one-sided Hoeffding bound. Simultaneous policy/stratum
selection requires the declared family size; it cannot correct post-hoc policy
fitting on this calibration set. Exact repeated events are idempotent. Different
events sharing an original source are rejected instead of inflating sample size.
A conditional profile admits one public context per call; pooling distinct
contexts estimates a population moment, not the average conditional CE.
"""
    if (not 0 < alpha < 1 or isinstance(family_size, bool)
            or not isinstance(family_size, int) or family_size < 1
            or method not in {"bounded", "two_point"}):
        raise ValueError("Invalid confidence contract")
    if (not isinstance(policy_sha256, str) or len(policy_sha256) != 64
            or any(c not in "0123456789abcdef" for c in policy_sha256)):
        raise ValueError("A frozen policy SHA-256 is required")
    if (not isinstance(net_return_bounds, tuple) or len(net_return_bounds) != 2
            or any(isinstance(v, bool) or not math.isfinite(v) for v in net_return_bounds)):
        raise ValueError("A predeclared finite net-return support is required")
    lower, upper = net_return_bounds
    if lower >= upper or not selection_key:
        raise ValueError("Ordered support and a frozen selection stratum are required")
    excluded = frozenset(excluded_source_ids)
    seen, used, clusters, records, values = {}, set(), set(), [], []
    contexts = set()
    for event in events:
        if not isinstance(event, JointEvent) or not event.event_id:
            raise ValueError("A complete actual event record is required")
        fingerprint = digest(asdict(event))
        if event.event_id in seen:
            if seen[event.event_id] != fingerprint:
                raise ValueError("Conflicting repeated event")
            continue
        if (event.policy_sha256 != policy_sha256 or event.profile_sha256 != profile.digest
                or event.selection_key != selection_key):
            raise ValueError("Calibration policy/profile/selection differs from execution")
        if (not isinstance(event.source_ids, tuple) or not event.source_ids
                or len(set(event.source_ids)) != len(event.source_ids)
                or any(not isinstance(s, str) or not s for s in event.source_ids)):
            raise ValueError("Original source identities are required")
        if used.intersection(event.source_ids) or excluded.intersection(event.source_ids):
            raise ValueError("Calibration sources overlap another event or a reserved split")
        if (event.outcome.source_cluster_id in clusters
                or event.outcome.source_cluster_id in excluded):
            raise ValueError("Calibration source clusters overlap another event or a reserved split")
        if (not event.selected_action or not event.executed_action
                or not math.isfinite(event.feedback)
                or len(event.execution_receipt_sha256) != 64
                or any(c not in "0123456789abcdef" for c in event.execution_receipt_sha256)):
            raise ValueError("Actual action, feedback and execution receipt are required")
        value = net_return(profile, event.outcome)
        contexts.add(event.outcome.context_id)
        if profile.aggregation == "conditional" and len(contexts) > 1:
            raise ValueError("Conditional calibration cannot pool distinct public contexts")
        if not lower <= value <= upper:
            raise ValueError("Actual cost/failure branch exceeds declared net-return support")
        seen[event.event_id] = fingerprint
        used.update(event.source_ids)
        clusters.add(event.outcome.source_cluster_id)
        records.append(event)
        values.append(value)
    high_loss, low_loss = moment_cost(lower, profile.gamma), moment_cost(upper, profile.gamma)
    width = high_loss - low_loss
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Unsupported support/risk numeric scale")
    losses = [moment_cost(value, profile.gamma) for value in values]
    normalized = [(loss - low_loss) / width for loss in losses]
    mean = math.fsum(normalized) / len(normalized) if normalized else None
    confidence_alpha = alpha / family_size
    success_lower = None
    if method == "two_point":
        if any(not (math.isclose(value, lower, abs_tol=1e-12, rel_tol=0)
                    or math.isclose(value, upper, abs_tol=1e-12, rel_tol=0)) for value in values):
            raise ValueError("A two-point bound cannot ignore variable costs or intermediate outcomes")
        successes = sum(math.isclose(value, upper, abs_tol=1e-12, rel_tol=0) for value in values)
        success_lower = success_lower_bound(successes, len(values), confidence_alpha)
        normalized_upper = 1.0 - success_lower
    else:
        normalized_upper = min(1.0, mean + math.sqrt(math.log(1 / confidence_alpha)
                                                   / (2 * len(values)))) if values else 1.0
    upper_loss = low_loss + width * normalized_upper
    empirical_loss = low_loss + width * mean if mean is not None else None
    if profile.gamma:
        moment_upper = 1 + profile.gamma * upper_loss
        empirical_moment = 1 + profile.gamma * empirical_loss if values else None
        ce_lower = -math.log1p(profile.gamma * upper_loss) / profile.gamma
    else:
        moment_upper, empirical_moment, ce_lower = 1.0, 1.0 if values else None, -upper_loss
    contract = {"schema": "hepta.ndu.selected-policy-tail.v1", "profile_sha256": profile.digest,
                "policy_sha256": policy_sha256, "selection_key": selection_key,
                "net_return_bounds": list(net_return_bounds), "method": method,
                "alpha": alpha, "family_size": family_size,
                "excluded_source_ids_sha256": digest(sorted(excluded))}
    return {**contract, "contract_sha256": digest(contract), "independent_events": len(values),
            "source_count": len(used), "record_sha256": digest(sorted(seen.items())),
            "moment_upper": moment_upper, "empirical_moment": empirical_moment,
            "moment_cost_upper": upper_loss, "ce_lower": ce_lower,
            "success_probability_lower": success_lower,
            "mean_actual_cost": (math.fsum(total_cost(profile, r.outcome.costs) for r in records)
                                 / len(records)) if records else None,
            "terminal_counts": {kind: sum(r.outcome.terminal_kind == kind for r in records)
                                for kind in ("delivered", "refused", "failed")},
            "calibration_observations_used_to_fit_policy": False,
            "independence_assumption": "independent source-disjoint draws from the frozen selected-policy law",
            "scope": "one declared population or public-context stratum; not an ECE guarantee"}
