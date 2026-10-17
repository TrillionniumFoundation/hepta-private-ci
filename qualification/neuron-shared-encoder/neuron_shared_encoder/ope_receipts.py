"""Research-only causal/OPE receipts for the shared Stem transfer loop.

The existing Rust learning ledger already records decisions, terminal outcomes,
watermarks and credit lineage.  This module is the adapter boundary for the
next experiment: it keeps ``X`` (context), ``P`` (policy/action), ``Y``
(independent outcome) and ``Z`` (resource/censoring/accounting) as separate
immutable receipts, then binds them into an off-policy episode.  It does not
load a model, train a Cell, select a candidate, or grant authority.

The estimators are deliberately small deterministic research implementations.
They require logged support and a matched budget, reject model-visible gold,
and emit ``DENY_ALL`` estimates.  Their intervals are accounting intervals,
not a claim of efficacy or causal validity beyond the supplied evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Callable, Iterable, Mapping


SCHEMA_X = "hepta.ope.context-receipt.v1"
SCHEMA_P = "hepta.ope.policy-receipt.v1"
SCHEMA_Y = "hepta.ope.outcome-receipt.v1"
SCHEMA_Z = "hepta.ope.accounting-receipt.v1"
SCHEMA_EPISODE = "hepta.ope.xyz-episode.v1"
SCHEMA_ESTIMATE = "hepta.ope.estimate.v1"

REAL_SHADOW = "REAL_SHADOW"
SYNTHETIC_SMOKE = "SYNTHETIC_SMOKE"
INCOMPLETE = "INCOMPLETE"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_IDENT = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class OPEReceiptError(ValueError):
    """Raised when a causal/OPE receipt cannot be audited safely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OPEReceiptError(message)


def _digest(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX64.fullmatch(value) is not None, f"{name} must be a lowercase sha256")


def _blob(name: str, value: str) -> None:
    _require(isinstance(value, str) and _HEX40.fullmatch(value) is not None, f"{name} must be a lowercase Git SHA-1")


def _identifier(name: str, value: str) -> None:
    _require(isinstance(value, str) and _IDENT.fullmatch(value) is not None, f"{name} is not a stable identifier")


def _finite(name: str, value: Any) -> None:
    _require(type(value) in (int, float) and math.isfinite(float(value)), f"{name} must be finite")


def _nonnegative(name: str, value: Any) -> None:
    _finite(name, value)
    _require(float(value) >= 0.0, f"{name} must be non-negative")


def _probability(name: str, value: Any, *, allow_zero: bool = True) -> None:
    _finite(name, value)
    lower = 0.0 if allow_zero else math.nextafter(0.0, 1.0)
    _require(lower <= float(value) <= 1.0, f"{name} must be in (0,1]" if not allow_zero else f"{name} must be in [0,1]")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def canonical_candidate_set_digest(candidate_ids: tuple[str, ...] | list[str]) -> str:
    """Digest the complete sorted action support, including cardinality."""
    return _sha({"candidate_ids": sorted(candidate_ids)})


@dataclass(frozen=True)
class ContextReceiptV1:
    """X: model-visible context and independent source identity."""

    episode_id: str
    context_digest: str
    source_digest: str
    source_blob_digest: str
    request_digest: str
    reader_manifest_digest: str
    source_split: str
    independent_source: bool = True
    model_input_gold_visible: bool = False

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        for name, value in (
            ("context_digest", self.context_digest),
            ("source_digest", self.source_digest),
            ("request_digest", self.request_digest),
            ("reader_manifest_digest", self.reader_manifest_digest),
        ):
            _digest(name, value)
        _blob("source_blob_digest", self.source_blob_digest)
        _require(self.source_split in {"train", "future", "ood"}, "source_split must be train/future/ood")
        _require(type(self.independent_source) is bool, "independent_source must be boolean")
        _require(type(self.model_input_gold_visible) is bool, "model_input_gold_visible must be boolean")
        _require(self.independent_source, "OPE requires an independently identified source")
        _require(not self.model_input_gold_visible, "gold cannot enter X/model-visible context")

    @property
    def receipt_digest(self) -> str:
        return _sha({"schema": SCHEMA_X, **asdict(self)})

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA_X, **asdict(self), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True)
class PolicyDecisionReceiptV1:
    """P: the logged action, propensity and target policy support."""

    episode_id: str
    candidate_set_digest: str
    candidate_ids: tuple[str, ...]
    selected_candidate_id: str
    target_policy_id: str
    logging_propensity: float
    target_propensity: float
    support_digest: str
    budget_digest: str
    policy_digest: str
    policy_principal_id: str
    model_input_gold_visible: bool = False

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        _identifier("target_policy_id", self.target_policy_id)
        _identifier("selected_candidate_id", self.selected_candidate_id)
        _identifier("policy_principal_id", self.policy_principal_id)
        for name, value in (
            ("candidate_set_digest", self.candidate_set_digest),
            ("support_digest", self.support_digest),
            ("budget_digest", self.budget_digest),
            ("policy_digest", self.policy_digest),
        ):
            _digest(name, value)
        _require(self.candidate_ids and len(set(self.candidate_ids)) == len(self.candidate_ids), "candidate_ids must be non-empty and unique")
        for candidate_id in self.candidate_ids:
            _identifier("candidate_id", candidate_id)
        _require(
            self.candidate_set_digest == canonical_candidate_set_digest(self.candidate_ids),
            "candidate_set_digest does not bind the complete candidate support",
        )
        _require(self.selected_candidate_id in self.candidate_ids, "selected candidate is outside the logged candidate set")
        _require(self.target_policy_id in self.candidate_ids, "target policy is outside the logged candidate set")
        _probability("logging_propensity", self.logging_propensity, allow_zero=False)
        _probability("target_propensity", self.target_propensity)
        _require(type(self.model_input_gold_visible) is bool, "model_input_gold_visible must be boolean")
        _require(not self.model_input_gold_visible, "gold cannot enter P/model-visible policy input")

    @property
    def receipt_digest(self) -> str:
        return _sha({"schema": SCHEMA_P, **asdict(self)})

    def to_dict(self) -> dict[str, Any]:
        result = {"schema": SCHEMA_P, **asdict(self), "receipt_digest": self.receipt_digest}
        result["candidate_ids"] = list(self.candidate_ids)
        return result


@dataclass(frozen=True)
class DelayedOutcomeReceiptV1:
    """Y: independently observed delayed outcome and terminality."""

    episode_id: str
    outcome_id: str
    observer_principal_id: str
    observer_signing_key_digest: str
    observed_at_unix_ms: int
    latest_observable_at_unix_ms: int
    expected_delay_profile_digest: str
    terminality: str
    utility: float | None
    support_digest: str
    independent_source: bool = True
    finalized_at_unix_ms: int | None = None
    censoring_reason: str | None = None
    correction_predecessor: str | None = None
    model_input_gold_visible: bool = False

    def __post_init__(self) -> None:
        for name, value in (("episode_id", self.episode_id), ("outcome_id", self.outcome_id), ("observer_principal_id", self.observer_principal_id)):
            _identifier(name, value)
        for name, value in (("observer_signing_key_digest", self.observer_signing_key_digest), ("expected_delay_profile_digest", self.expected_delay_profile_digest), ("support_digest", self.support_digest)):
            _digest(name, value)
        _require(type(self.observed_at_unix_ms) is int and self.observed_at_unix_ms >= 0, "observed_at_unix_ms must be a non-negative integer")
        _require(type(self.latest_observable_at_unix_ms) is int and self.latest_observable_at_unix_ms >= self.observed_at_unix_ms, "latest_observable_at_unix_ms must be ordered")
        _require(self.terminality in {"PENDING", "CENSORED", "TERMINAL"}, "unknown outcome terminality")
        _require(type(self.independent_source) is bool and self.independent_source, "outcome must have an independent source")
        _require(type(self.model_input_gold_visible) is bool and not self.model_input_gold_visible, "gold cannot enter Y/model-visible input")
        if self.utility is not None:
            _finite("utility", self.utility)
        if self.finalized_at_unix_ms is not None:
            _require(type(self.finalized_at_unix_ms) is int and self.finalized_at_unix_ms >= self.latest_observable_at_unix_ms, "finalized_at_unix_ms must be ordered")
        if self.terminality == "TERMINAL":
            _require(self.utility is not None and self.finalized_at_unix_ms is not None, "terminal outcomes require utility and finalization")
            _require(self.censoring_reason is None, "terminal outcomes cannot carry a censoring reason")
        else:
            _require(self.utility is None, "pending/censored outcomes cannot carry utility")
            if self.terminality == "CENSORED":
                _require(bool(self.censoring_reason), "censored outcomes require a reason")
            _require(self.finalized_at_unix_ms is None or self.terminality == "CENSORED", "pending outcomes cannot be finalized")
        if self.correction_predecessor is not None:
            _identifier("correction_predecessor", self.correction_predecessor)

    @property
    def receipt_digest(self) -> str:
        return _sha({"schema": SCHEMA_Y, **asdict(self)})

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA_Y, **asdict(self), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True)
class OPEBudgetV1:
    """Fixed budget against which all policy episodes are charged."""

    budget_digest: str
    cost_weights_digest: str
    max_forward_calls: int
    max_input_tokens: int
    max_flops: float
    max_peak_memory_bytes: float
    max_p95_latency_ms: float
    max_energy_mj: float

    def __post_init__(self) -> None:
        _digest("budget_digest", self.budget_digest)
        _digest("cost_weights_digest", self.cost_weights_digest)
        _require(type(self.max_forward_calls) is int and self.max_forward_calls >= 1, "max_forward_calls must be positive")
        _require(type(self.max_input_tokens) is int and self.max_input_tokens >= 1, "max_input_tokens must be positive")
        for name in ("max_flops", "max_peak_memory_bytes", "max_p95_latency_ms", "max_energy_mj"):
            _nonnegative(name, getattr(self, name))


@dataclass(frozen=True)
class OPEResourceReceiptV1:
    """Z resource charge; aggregate values are not physical equivalence."""

    episode_id: str
    budget_digest: str
    evidence_class: str
    forward_calls: int
    input_tokens: int
    flops: float
    peak_memory_bytes: float
    p95_latency_ms: float
    energy_mj: float
    resident_params: int
    active_params: int
    feasible: bool = True
    model_input_gold_visible: bool = False

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        _digest("budget_digest", self.budget_digest)
        # An incomplete resource cannot be projected into OPE.  Preserve such
        # records in the upstream ledger, but reject them at this adapter
        # boundary instead of silently mapping them to synthetic smoke.
        _require(self.evidence_class in {REAL_SHADOW, SYNTHETIC_SMOKE}, "OPE resource evidence must be REAL_SHADOW or SYNTHETIC_SMOKE")
        for name in ("forward_calls", "input_tokens", "resident_params", "active_params"):
            _require(type(getattr(self, name)) is int and getattr(self, name) >= 0, f"{name} must be a non-negative integer")
        _require(self.active_params <= self.resident_params, "active_params cannot exceed resident_params")
        for name in ("flops", "peak_memory_bytes", "p95_latency_ms", "energy_mj"):
            _nonnegative(name, getattr(self, name))
        _require(type(self.feasible) is bool, "feasible must be boolean")
        _require(type(self.model_input_gold_visible) is bool and not self.model_input_gold_visible, "gold cannot enter Z/model-visible input")

    @property
    def receipt_digest(self) -> str:
        return _sha({"schema": SCHEMA_Z, **asdict(self)})

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA_Z, **asdict(self), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True)
class XYZEpisodeV1:
    """Immutable binding of distinct X/P/Y/Z receipts."""

    episode_id: str
    context: ContextReceiptV1
    decision: PolicyDecisionReceiptV1
    outcome: DelayedOutcomeReceiptV1
    resources: OPEResourceReceiptV1
    evidence_class: str

    def __post_init__(self) -> None:
        _identifier("episode_id", self.episode_id)
        _require(self.context.episode_id == self.episode_id, "X episode mismatch")
        _require(self.decision.episode_id == self.episode_id, "P episode mismatch")
        _require(self.outcome.episode_id == self.episode_id, "Y episode mismatch")
        _require(self.resources.episode_id == self.episode_id, "Z episode mismatch")
        _require(self.decision.budget_digest == self.resources.budget_digest, "P/Z budget mismatch")
        _require(self.evidence_class in {REAL_SHADOW, SYNTHETIC_SMOKE}, "OPE episode evidence must be REAL_SHADOW or SYNTHETIC_SMOKE")
        _require(self.resources.evidence_class == self.evidence_class, "episode/resource evidence mismatch")
        _require(self.context.source_split in {"future", "ood", "train"}, "invalid X source split")
        _require(self.decision.policy_principal_id != self.outcome.observer_principal_id, "policy and outcome principals must be independent")
        _require(self.decision.policy_digest != self.outcome.support_digest, "policy and outcome support must not be aliased")

    @property
    def episode_digest(self) -> str:
        return _sha({
            "schema": SCHEMA_EPISODE,
            "episode_id": self.episode_id,
            "x": self.context.receipt_digest,
            "p": self.decision.receipt_digest,
            "y": self.outcome.receipt_digest,
            "z": self.resources.receipt_digest,
            "evidence_class": self.evidence_class,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_EPISODE,
            "episode_id": self.episode_id,
            "x": self.context.to_dict(),
            "p": self.decision.to_dict(),
            "y": self.outcome.to_dict(),
            "z": self.resources.to_dict(),
            "evidence_class": self.evidence_class,
            "episode_digest": self.episode_digest,
        }


@dataclass(frozen=True)
class OPEEstimateV1:
    target_policy_id: str
    estimator: str
    budget_digest: str
    episodes_digest: str
    evidence_class: str
    sample_count: int
    terminal_count: int
    censored_count: int
    estimate: float
    lcb: float
    ucb: float
    effective_sample_size: float
    max_weight: float
    support_violation_count: int
    interval_method: str = "normal_approx_research_only.v1"
    authority: str = "DENY_ALL"
    model_efficacy_measured: bool = False

    def __post_init__(self) -> None:
        _identifier("target_policy_id", self.target_policy_id)
        _require(self.estimator in {"IPS", "SNIPS", "DR"}, "unknown OPE estimator")
        _digest("budget_digest", self.budget_digest)
        _digest("episodes_digest", self.episodes_digest)
        _require(self.evidence_class in {REAL_SHADOW, SYNTHETIC_SMOKE}, "OPE estimate cannot be marked incomplete")
        for name in ("sample_count", "terminal_count", "censored_count", "support_violation_count"):
            _require(type(getattr(self, name)) is int and getattr(self, name) >= 0, f"{name} must be non-negative integer")
        _require(self.terminal_count <= self.sample_count, "terminal_count exceeds sample_count")
        _require(self.authority == "DENY_ALL", "OPE estimate authority is always DENY_ALL")
        _require(self.model_efficacy_measured is False, "OPE adapter cannot assert efficacy")
        for name in ("estimate", "lcb", "ucb", "effective_sample_size", "max_weight"):
            _finite(name, getattr(self, name))
        _require(self.lcb <= self.estimate <= self.ucb, "invalid OPE interval")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA_ESTIMATE, **asdict(self)}


def validate_xyz_episode(episode: XYZEpisodeV1, budget: OPEBudgetV1, *, require_real_shadow: bool = True) -> None:
    """Fail closed on budget, support, identity and evidence mismatches."""
    _require(episode.decision.budget_digest == budget.budget_digest, "episode budget does not match evaluation budget")
    _require(episode.resources.budget_digest == budget.budget_digest, "resource budget does not match evaluation budget")
    if require_real_shadow:
        _require(episode.evidence_class == REAL_SHADOW, "real OPE requires REAL_SHADOW evidence")
    _require(episode.resources.forward_calls <= budget.max_forward_calls, "forward-call budget exceeded")
    _require(episode.resources.input_tokens <= budget.max_input_tokens, "input-token budget exceeded")
    _require(episode.resources.flops <= budget.max_flops, "FLOP budget exceeded")
    _require(episode.resources.peak_memory_bytes <= budget.max_peak_memory_bytes, "memory budget exceeded")
    _require(episode.resources.p95_latency_ms <= budget.max_p95_latency_ms, "latency budget exceeded")
    _require(episode.resources.energy_mj <= budget.max_energy_mj, "energy budget exceeded")
    _require(episode.decision.logging_propensity > 0.0, "logged propensity has no support")
    _require(episode.decision.target_propensity >= 0.0, "target propensity is negative")
    if episode.outcome.terminality == "TERMINAL":
        _require(episode.outcome.finalized_at_unix_ms is not None, "terminal outcome has no finalization")


def _normal_interval(values: list[float], estimate: float) -> tuple[float, float]:
    if len(values) < 2:
        return estimate, estimate
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    standard_error = math.sqrt(max(variance, 0.0) / len(values))
    radius = 1.96 * standard_error
    return estimate - radius, estimate + radius


def estimate_ope(
    episodes: Iterable[XYZEpisodeV1],
    *,
    target_policy_id: str,
    budget: OPEBudgetV1,
    estimator: str = "SNIPS",
    reward_model: Mapping[str, tuple[float, float]] | Callable[[XYZEpisodeV1], tuple[float, float]] | None = None,
    require_real_shadow: bool = True,
) -> OPEEstimateV1:
    """Compute IPS/SNIPS/DR over terminal, supported episodes only.

    ``reward_model`` supplies ``(mu_logged, mu_target)`` for DR and is treated
    as an externally evaluated nuisance model.  It is never trained or
    accepted by this adapter.  Pending/censored outcomes remain in the receipt
    audit count but are excluded from the terminal estimator.
    """
    _identifier("target_policy_id", target_policy_id)
    _require(estimator in {"IPS", "SNIPS", "DR"}, "unknown OPE estimator")
    if estimator == "DR":
        _require(reward_model is not None, "DR requires an independently supplied reward model")
    items = tuple(episodes)
    _require(items, "OPE requires at least one episode")
    seen: set[str] = set()
    terminal: list[XYZEpisodeV1] = []
    censored = 0
    for episode in items:
        _require(episode.episode_id not in seen, "duplicate episode_id")
        seen.add(episode.episode_id)
        validate_xyz_episode(episode, budget, require_real_shadow=require_real_shadow)
        _require(episode.decision.target_policy_id == target_policy_id, "target policy mismatch")
        if episode.outcome.terminality == "TERMINAL":
            terminal.append(episode)
        else:
            censored += 1
    _require(terminal, "no terminal outcomes available for OPE")

    weights: list[float] = []
    rewards: list[float] = []
    dr_values: list[float] = []
    support_violations = 0
    for episode in terminal:
        decision = episode.decision
        if decision.target_propensity > 0.0 and decision.logging_propensity <= 0.0:
            support_violations += 1
            continue
        _require(decision.logging_propensity > 0.0, "logging propensity outside support")
        weight = decision.target_propensity / decision.logging_propensity
        _finite("importance_weight", weight)
        _require(weight >= 0.0, "importance weight is negative")
        weights.append(weight)
        reward = float(episode.outcome.utility)  # terminality guarantees non-None
        rewards.append(reward)
        if estimator == "DR":
            if callable(reward_model):
                mu_logged, mu_target = reward_model(episode)
            else:
                mu_logged, mu_target = reward_model[episode.episode_id]  # type: ignore[index]
            _finite("mu_logged", mu_logged)
            _finite("mu_target", mu_target)
            dr_values.append(float(mu_target) + weight * (reward - float(mu_logged)))
    _require(not support_violations, "target policy lacks logged support")
    _require(weights, "no supported terminal episodes")

    if estimator == "IPS":
        contributions = [weight * reward for weight, reward in zip(weights, rewards)]
        estimate = sum(contributions) / len(contributions)
    elif estimator == "SNIPS":
        denominator = sum(weights)
        _require(denominator > 0.0, "SNIPS has zero target support")
        contributions = [weight * reward for weight, reward in zip(weights, rewards)]
        estimate = sum(contributions) / denominator
    else:
        contributions = dr_values
        estimate = sum(contributions) / len(contributions)
    lcb, ucb = _normal_interval(contributions, estimate)
    sum_weights = sum(weights)
    sum_squared_weights = sum(weight * weight for weight in weights)
    ess = (sum_weights * sum_weights / sum_squared_weights) if sum_squared_weights > 0 else 0.0
    episodes_digest = _sha(sorted(episode.episode_digest for episode in items))
    evidence_class = REAL_SHADOW if all(episode.evidence_class == REAL_SHADOW for episode in items) else SYNTHETIC_SMOKE
    return OPEEstimateV1(
        target_policy_id=target_policy_id,
        estimator=estimator,
        budget_digest=budget.budget_digest,
        episodes_digest=episodes_digest,
        evidence_class=evidence_class,
        sample_count=len(items),
        terminal_count=len(terminal),
        censored_count=censored,
        estimate=estimate,
        lcb=lcb,
        ucb=ucb,
        effective_sample_size=ess,
        max_weight=max(weights),
        support_violation_count=support_violations,
    )


# Explicit adapter names for callers that use the repository's registered
# ``DecisionReceipt``/``OutcomeReceipt`` vocabulary.  The aliases do not alter
# the existing Rust wire schemas; they remain Python-side X/P/Y/Z views.
DecisionReceiptV1 = PolicyDecisionReceiptV1
OutcomeReceiptV1 = DelayedOutcomeReceiptV1


__all__ = [
    "ContextReceiptV1",
    "DecisionReceiptV1",
    "DelayedOutcomeReceiptV1",
    "INCOMPLETE",
    "OPEBudgetV1",
    "OPEEstimateV1",
    "OPEReceiptError",
    "OPEResourceReceiptV1",
    "OutcomeReceiptV1",
    "PolicyDecisionReceiptV1",
    "REAL_SHADOW",
    "SCHEMA_ESTIMATE",
    "SCHEMA_EPISODE",
    "SCHEMA_P",
    "SCHEMA_X",
    "SCHEMA_Y",
    "SCHEMA_Z",
    "SYNTHETIC_SMOKE",
    "XYZEpisodeV1",
    "canonical_candidate_set_digest",
    "estimate_ope",
    "validate_xyz_episode",
]
