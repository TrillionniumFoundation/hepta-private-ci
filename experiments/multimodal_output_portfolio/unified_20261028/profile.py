"""One finite-horizon NDU objective for training, planning and delivered outputs.

The fixed-gamma, undiscounted exponential profile uses actual net returns. A
profile hash binds semantics; it does not authenticate an observer or an owner.
Source clusters used for inference are distinct from conditional task contexts.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from numbers import Real


SCHEMA = "hepta.ndu.unified-profile.v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    return float(value)


def _identity(value, name):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError(f"{name} must be a lowercase SHA-256 identity")


@dataclass(frozen=True)
class NduProfile:
    objective_sha256: str
    observer_sha256: str
    continuation_sha256: str
    gamma: float = 2.0
    aggregation: str = "population"
    cost_unit: str = "normalized_utility"
    utility_bounds: tuple[float, float] = (-1.0, 1.0)
    required_modalities: tuple[str, ...] = ("text", "image")

    def __post_init__(self):
        for name in ("objective_sha256", "observer_sha256", "continuation_sha256"):
            _identity(getattr(self, name), name)
        gamma = _finite(self.gamma, "gamma")
        if gamma < 0 or self.aggregation not in {"conditional", "population"}:
            raise ValueError("Nonnegative risk and an explicit aggregation scope are required")
        if not isinstance(self.cost_unit, str) or not self.cost_unit:
            raise ValueError("A declared cost unit is required")
        if not isinstance(self.utility_bounds, tuple) or len(self.utility_bounds) != 2:
            raise ValueError("Utility bounds must be an immutable pair")
        lower, upper = (_finite(v, "utility bound") for v in self.utility_bounds)
        if lower >= upper:
            raise ValueError("Utility bounds must be ordered")
        if (not isinstance(self.required_modalities, tuple) or not self.required_modalities
                or len(set(self.required_modalities)) != len(self.required_modalities)
                or any(m not in {"text", "image", "audio", "video"}
                       for m in self.required_modalities)):
            raise ValueError("Declare a unique immutable set of required output modalities")
        object.__setattr__(self, "gamma", gamma)
        object.__setattr__(self, "utility_bounds", (lower, upper))

    def to_dict(self):
        return {"schema": SCHEMA, "time_discount": 1.0,
                "cost_treatment": "actual_joint_increment_once",
                "stopping": "explicit_delivered_terminal_outcome",
                "reward_source": "bound_external_post_codec_observer", **asdict(self)}

    @property
    def digest(self):
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Profile must be an object")
        fixed = {"schema": SCHEMA, "time_discount": 1.0,
                 "cost_treatment": "actual_joint_increment_once",
                 "stopping": "explicit_delivered_terminal_outcome",
                 "reward_source": "bound_external_post_codec_observer"}
        if any(value.get(k) != v for k, v in fixed.items()):
            raise ValueError("Unsupported objective, cost, stopping or discount semantics")
        if isinstance(value["time_discount"], bool):
            raise ValueError("Time discount cannot be a Boolean")
        fields = set(cls.__dataclass_fields__)
        if set(value) != fields | set(fixed):
            raise ValueError("Profile fields must be complete and exact")
        args = {k: value[k] for k in fields}
        args["utility_bounds"] = tuple(args["utility_bounds"])
        args["required_modalities"] = tuple(args["required_modalities"])
        return cls(**args)


def _law(values, probabilities=None):
    values = tuple(_finite(v, "return") for v in values)
    if not values:
        raise ValueError("An empty outcome law has no value")
    if probabilities is None:
        probabilities = (1.0 / len(values),) * len(values)
    else:
        probabilities = tuple(_finite(p, "probability") for p in probabilities)
        if len(probabilities) != len(values):
            raise ValueError("Outcome/probability dimensions differ")
        if any(p < 0 for p in probabilities):
            raise ValueError("Probabilities cannot be negative")
        total = math.fsum(probabilities)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("A complete probability law summing to one is required")
        probabilities = tuple(p / total for p in probabilities)
    return values, probabilities


def _risk_statistics(values, gamma, probabilities=None):
    values, probabilities = _law(values, probabilities)
    gamma = _finite(gamma, "gamma")
    if gamma < 0:
        raise ValueError("This profile requires nonnegative risk aversion")
    mean = math.fsum(p * v for p, v in zip(probabilities, values))
    if gamma == 0.0:
        return mean, mean, 0.0
    shifted = tuple(-gamma * (v - mean) for v in values)
    if not all(math.isfinite(x) for x in shifted):
        raise ValueError("Return/risk scale exceeds the supported floating point domain")
    if max(abs(x) for x in shifted) <= 0.5:
        correction = math.log1p(math.fsum(
            p * math.expm1(x) for p, x in zip(probabilities, shifted)))
    else:
        maximum = max(x for p, x in zip(probabilities, shifted) if p > 0)
        correction = maximum + math.log(math.fsum(
            p * math.exp(x - maximum) for p, x in zip(probabilities, shifted) if p > 0))
    ce = mean - correction / gamma
    log_m = -gamma * mean + correction
    if not math.isfinite(ce) or not math.isfinite(log_m):
        raise ValueError("Computed risk statistic is outside the numeric domain")
    return ce, mean, log_m


def certainty_equivalent(values, gamma, probabilities=None):
    """CE of a complete declared law; gamma=0 is the expectation limit."""
    return _risk_statistics(values, gamma, probabilities)[0]


def log_moment(values, gamma, probabilities=None):
    """Log E exp(-gamma R), including its zero-risk value of zero."""
    return _risk_statistics(values, gamma, probabilities)[2]


def moment_cost(net_return, gamma):
    """(exp(-gamma R)-1)/gamma, with its continuous -R limit.

Minimizing its expectation has the population CE optimum under the same hard
constraints. Adding a fixed external regularizer changes that equivalence.
An average of conditional CEs requires conditional normalization instead.
"""
    value, gamma = _finite(net_return, "return"), _finite(gamma, "gamma")
    if gamma < 0:
        raise ValueError("Risk aversion must be nonnegative")
    if gamma == 0:
        return -value
    try:
        result = math.expm1(-gamma * value) / gamma
    except OverflowError as exc:
        raise ValueError("Moment overflow: use log moments for this scale") from exc
    if not math.isfinite(result):
        raise ValueError("Moment is outside the numeric domain")
    return result


def aggregate(profile, values_by_context, context_weights=None, probabilities_by_context=None):
    """Report both scopes, select only the one named in the immutable profile.

Contexts identify a fixed public task input. They are not source clusters or
training seeds. Training seed replications should be summarized separately.
"""
    if not isinstance(profile, NduProfile) or not values_by_context:
        raise ValueError("A profile and nonempty context laws are required")
    names = tuple(sorted(values_by_context))
    if any(not isinstance(k, str) or not k for k in names):
        raise ValueError("Contexts require explicit nonempty identities")
    if context_weights is None:
        weights = (1.0 / len(names),) * len(names)
    else:
        if set(context_weights) != set(names):
            raise ValueError("Context weights must cover exactly the declared contexts")
        _, weights = _law((0.0,) * len(names), [context_weights[k] for k in names])
    if probabilities_by_context is not None and set(probabilities_by_context) != set(names):
        raise ValueError("Conditional probabilities must cover exactly the contexts")
    all_values, all_probabilities, details = [], [], []
    for name, weight in zip(names, weights):
        supplied = None if probabilities_by_context is None else probabilities_by_context[name]
        values, probabilities = _law(values_by_context[name], supplied)
        ce, mean, log_m = _risk_statistics(values, profile.gamma, probabilities)
        details.append({"context_id": name, "weight": weight, "samples": len(values),
                        "ce": ce, "mean_net": mean, "log_moment": log_m})
        all_values.extend(values)
        all_probabilities.extend(weight * p for p in probabilities)
    population, mean, log_m = _risk_statistics(all_values, profile.gamma, all_probabilities)
    conditional = math.fsum(d["weight"] * d["ce"] for d in details)
    # These are normalized tilted probability masses, not a statistical CI.
    logs = [math.log(p) - profile.gamma * v
            for p, v in zip(all_probabilities, all_values) if p > 0]
    peak = max(logs)
    scaled = [math.exp(x - peak) for x in logs]
    ess = math.fsum(scaled) ** 2 / math.fsum(w * w for w in scaled)
    return {"profile_sha256": profile.digest, "aggregation": profile.aggregation,
            "value": population if profile.aggregation == "population" else conditional,
            "population_ce": population, "conditional_ce": conditional,
            "mean_net": mean, "population_log_moment": log_m,
            "tilted_mass_ess": ess, "contexts": details}


@dataclass(frozen=True)
class CostEvent:
    event_id: str
    amount: float
    unit: str = "normalized_utility"
    kind: str = "execution"


def total_cost(profile, events):
    """Same event is idempotent; real repeated work needs distinct event IDs."""
    seen = {}
    for event in events:
        if (not isinstance(event, CostEvent) or not isinstance(event.event_id, str)
                or not event.event_id or event.unit != profile.cost_unit
                or not isinstance(event.kind, str) or not event.kind):
            raise ValueError("Every cost needs an event identity, kind and matching units")
        amount = _finite(event.amount, "actual cost")
        if amount < 0:
            raise ValueError("Actual resource cost cannot be negative")
        if (event.event_id in seen
                and canonical(asdict(seen[event.event_id])) != canonical(asdict(event))):
            raise ValueError("Conflicting repeated cost event")
        seen[event.event_id] = event
    return math.fsum(event.amount for event in seen.values())


@dataclass(frozen=True)
class DeliveredOutcome:
    context_id: str
    sample_id: str
    source_cluster_id: str
    delivered_utility: float
    costs: tuple[CostEvent, ...]
    artifact_sha256: tuple[tuple[str, str], ...]
    observer_sha256: str
    objective_sha256: str
    continuation_sha256: str
    terminal_kind: str = "delivered"


def net_return(profile, outcome):
    """Validate recorded post-codec scoring bindings and charge actual costs.

Artifact hashes must originate from the caller's real readback. Hash syntax is
not proof of observation, authenticity, file completeness or semantic truth.
"""
    if not isinstance(outcome, DeliveredOutcome):
        raise ValueError("A delivered-outcome receipt is required")
    if any(not isinstance(s, str) or not s
           for s in (outcome.context_id, outcome.sample_id, outcome.source_cluster_id)):
        raise ValueError("Task, draw and independent-source identities are required")
    for field in ("observer_sha256", "objective_sha256", "continuation_sha256"):
        if getattr(outcome, field) != getattr(profile, field):
            raise ValueError(f"Changed {field} requires a new profile")
    utility = _finite(outcome.delivered_utility, "observed terminal utility")
    if not profile.utility_bounds[0] <= utility <= profile.utility_bounds[1]:
        raise ValueError("Observer output is outside the declared utility range")
    if outcome.terminal_kind not in {"delivered", "failed", "refused"}:
        raise ValueError("A complete delivered, failed or refused terminal outcome is required")
    if not isinstance(outcome.costs, tuple) or not isinstance(outcome.artifact_sha256, tuple):
        raise ValueError("Receipt collections must be immutable")
    if any(not isinstance(pair, tuple) or len(pair) != 2 for pair in outcome.artifact_sha256):
        raise ValueError("Artifact receipts must be immutable modality/hash pairs")
    modalities = []
    for modality, sha256 in outcome.artifact_sha256:
        if modality not in {"text", "image", "audio", "video"}:
            raise ValueError("Unknown output modality")
        _identity(sha256, "readback artifact")
        modalities.append(modality)
    if len(set(modalities)) != len(modalities):
        raise ValueError("Duplicate output modality receipt")
    if (outcome.terminal_kind == "delivered"
            and not set(profile.required_modalities).issubset(modalities)):
        raise ValueError("A delivered bundle lacks required output artifacts")
    return utility - total_cost(profile, outcome.costs)


def summarize_outcomes(profile, outcomes, context_weights=None):
    grouped, draws = {}, set()
    for outcome in outcomes:
        value = net_return(profile, outcome)
        key = (outcome.context_id, outcome.sample_id)
        if key in draws:
            raise ValueError("Repeated rollout draw cannot inflate the empirical law")
        draws.add(key)
        grouped.setdefault(outcome.context_id, []).append(value)
    return aggregate(profile, grouped, context_weights)


@dataclass(frozen=True)
class JointBranch:
    probability: float
    incremental_reward: float
    incremental_cost: float
    continuation_value: float
    continuation_sha256: str


def backup(profile, branches):
    """One conditional CE of joint reward, cost and executable continuation."""
    values, probabilities = [], []
    for branch in branches:
        if (not isinstance(branch, JointBranch)
                or branch.continuation_sha256 != profile.continuation_sha256):
            raise ValueError("Backup must bind the deployed continuation")
        cost = _finite(branch.incremental_cost, "incremental cost")
        reward = _finite(branch.incremental_reward, "incremental reward")
        continuation = _finite(branch.continuation_value, "continuation value")
        if cost < 0:
            raise ValueError("Incremental cost cannot be negative")
        values.append(reward - cost + continuation)
        probabilities.append(branch.probability)
    return certainty_equivalent(values, profile.gamma, probabilities)
