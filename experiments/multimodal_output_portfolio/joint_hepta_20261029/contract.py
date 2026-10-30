"""Joint generation records extending, without changing, the registered NDU.

Digests bind declared semantics and provenance; they do not authenticate an
observer, prove feature sufficiency, or establish that a resource was measured.
The owner still has to read emitted files and independently observe their result.
"""

from dataclasses import asdict, dataclass
import math

from experiments.multimodal_output_portfolio.unified_20261028.profile import (
    SCHEMA as PARENT_SCHEMA,
    CostEvent,
    DeliveredOutcome,
    NduProfile,
    canonical,
    digest,
    net_return,
    total_cost,
)


SCHEMA = "hepta.joint-generation.contract.v1"
PARENT_COMMIT = "a50c8974ac23c20c5174f7c3ad542a96e5652854"
PARENT_CODE = "experiments/multimodal_output_portfolio/unified_20261028/profile.py"
PARENT_BLOB = "98c62c6cef43489dadc8d010ce9b59735a88fc66"
MODALITIES = ("text", "image", "audio", "video")
MEDIA_UNITS = {"text": "token", "image": "none", "audio": "sample", "video": "frame"}


def _sha(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("A lowercase SHA-256 identity is required")


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _pairs(values, *, identities=False):
    if not isinstance(values, tuple) or any(not isinstance(p, tuple) or len(p) != 2 for p in values):
        raise ValueError("An immutable sequence of modality/value pairs is required")
    if len(dict(values)) != len(values) or any(m not in MODALITIES for m, _ in values):
        raise ValueError("Unknown or repeated modality")
    for _, value in values:
        if identities:
            _sha(value)
        elif type(value) is not int or value < 0:
            raise ValueError("Progress must be a nonnegative integer")
    return dict(values)


@dataclass(frozen=True)
class JointGenerationProfile:
    """One task contract shared by training, planning, rollout and evaluation.

The inherited NduProfile remains the objective. Parameter snapshots belong to
states, so changing candidate weights does not silently change the objective.
"""

    ndu: NduProfile
    input_contract_sha256: str
    randomness_contract_sha256: str
    resource_accounting_sha256: str
    model_port_sha256: str
    max_events: int = 64
    runtime_feature_keys: tuple[str, ...] = (
        "encoded_input", "latent_state", "committed_prefix", "remaining_budget",
        "remaining_steps", "clocks", "uncertainty",
    )

    def __post_init__(self):
        if not isinstance(self.ndu, NduProfile) or self.ndu.gamma != 2.0:
            raise ValueError("This joint profile requires the inherited fixed-gamma=2 NDU")
        if self.ndu.aggregation != "population":
            raise ValueError("Training/evaluation must retain population log-after-expectation")
        for name in ("input_contract_sha256", "randomness_contract_sha256",
                     "resource_accounting_sha256", "model_port_sha256"):
            _sha(getattr(self, name))
        if type(self.max_events) is not int or not 1 <= self.max_events <= 512:
            raise ValueError("The finite event horizon must be in [1, 512]")
        if (not isinstance(self.runtime_feature_keys, tuple) or not self.runtime_feature_keys
                or len(set(self.runtime_feature_keys)) != len(self.runtime_feature_keys)
                or any(not isinstance(k, str) or not k for k in self.runtime_feature_keys)):
            raise ValueError("Runtime features need an immutable explicit whitelist")
        forbidden = {"target", "targets", "terminal_score", "observer_output", "ground_truth"}
        if forbidden.intersection(self.runtime_feature_keys):
            raise ValueError("Future observer labels cannot be runtime features")

    def to_dict(self):
        value = asdict(self)
        value["ndu"] = self.ndu.to_dict()
        return {
            "schema": SCHEMA, "parent_schema": PARENT_SCHEMA,
            "parent_commit": PARENT_COMMIT, "parent_code": PARENT_CODE,
            "parent_blob": PARENT_BLOB, "time_discount": 1.0,
            "population_scope": "log_after_expectation_over_tasks_and_actual_rollouts",
            "conditional_scope": "same_gamma_joint_selected_action_complete_return",
            "stopping": "execute_delivery_then_observe; no_oracle_terminal_label",
            "event_clock": "monotone_decision_index",
            "compute_clock": "measured_monotonic_microseconds",
            "generation_clock": "per_modality_transition_count",
            "media_units": MEDIA_UNITS,
            "commitment": "buffered_bundle; one_immutable_final_file_per_modality",
            "filtration": "bound_input_and_past_executed_events",
            "parameter_updates": "candidate_only; immutable_selected_snapshot_per_episode",
            **value,
        }

    @property
    def digest(self):
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        """Load a complete exact profile without dropping semantic fields."""
        if not isinstance(value, dict):
            raise ValueError("Joint profile must be an object")
        fields = cls.__dataclass_fields__
        if not set(fields).issubset(value):
            raise ValueError("Joint profile is missing required fields")
        args = {key: value[key] for key in fields}
        args["ndu"] = NduProfile.from_dict(args["ndu"])
        args["runtime_feature_keys"] = tuple(args["runtime_feature_keys"])
        result = cls(**args)
        if canonical(result.to_dict()) != canonical(value):
            raise ValueError("Unknown or changed joint profile semantics")
        return result


def validate_runtime_features(profile, features):
    """Reject unregistered top-level inputs before assembling the actor input.

This structural check cannot inspect the semantics of an opaque tensor. Dataset
and feature-construction code require their own label-leakage checks.
"""
    if not isinstance(features, dict) or set(features) - set(profile.runtime_feature_keys):
        raise ValueError("Runtime features include an unregistered or future field")


@dataclass(frozen=True)
class GenerationState:
    profile_sha256: str
    context_id: str
    input_sha256: str
    parameter_snapshot_sha256: str
    policy_snapshot_sha256: str
    shared_state_sha256: str
    modality_state_sha256: tuple[tuple[str, str], ...]
    committed_artifact_sha256: tuple[tuple[str, str], ...]
    generation_steps: tuple[tuple[str, int], ...]
    media_positions: tuple[tuple[str, int], ...]
    event_index: int
    elapsed_us: int
    remaining_budget: float

    @property
    def digest(self):
        return digest(asdict(self))


def validate_state(profile, state):
    if not isinstance(state, GenerationState) or state.profile_sha256 != profile.digest:
        raise ValueError("State/profile binding mismatch")
    for name in ("input_sha256", "parameter_snapshot_sha256", "policy_snapshot_sha256",
                 "shared_state_sha256"):
        _sha(getattr(state, name))
    if not isinstance(state.context_id, str) or not state.context_id:
        raise ValueError("A public task context identity is required")
    if (type(state.event_index) is not int or not 0 <= state.event_index <= profile.max_events
            or type(state.elapsed_us) is not int or state.elapsed_us < 0
            or _number(state.remaining_budget, "remaining budget") < 0):
        raise ValueError("Invalid event clock, compute clock or remaining budget")
    latent = _pairs(state.modality_state_sha256, identities=True)
    committed = _pairs(state.committed_artifact_sha256, identities=True)
    generation = _pairs(state.generation_steps)
    media = _pairs(state.media_positions)
    if (set(latent) != set(generation) or set(latent) != set(media)
            or not set(profile.ndu.required_modalities).issubset(latent)
            or not set(committed).issubset(latent)):
        raise ValueError("Modality state, progress and required outputs disagree")
    if media.get("image", 0) != 0:
        raise ValueError("An image has no temporal media clock")


@dataclass(frozen=True)
class DecisionEvent:
    event_id: str
    profile_sha256: str
    predecessor_sha256: str
    successor_sha256: str
    selected_action: str
    joint_action_probabilities: tuple[tuple[str, float], ...]
    randomness_key_sha256: str
    costs: tuple[CostEvent, ...]
    terminal_kind: str = "ongoing"


def validate_episode(profile, states, events, outcome=None):
    """Verify executed chain, joint propensities, clocks, costs and final readback.

Action IDs identify whole composite controls. Multiplying marginal modality
probabilities is not an admitted replacement for their joint propensity.
Repeated work has a distinct cost identity; replaying a receipt is not new work.
"""
    if not isinstance(states, tuple) or not isinstance(events, tuple) or len(states) != len(events) + 1:
        raise ValueError("An immutable state/event chain is required")
    if not events or len(events) > profile.max_events:
        raise ValueError("An executed finite nonempty trajectory is required")
    for state in states:
        validate_state(profile, state)
    if states[0].event_index != 0:
        raise ValueError("A complete episode must start at event zero")
    seen_events, seen_costs, all_costs = set(), set(), []
    for index, event in enumerate(events):
        before, after = states[index:index + 2]
        if (not isinstance(event, DecisionEvent) or not isinstance(event.event_id, str)
                or not event.event_id or event.event_id in seen_events
                or event.profile_sha256 != profile.digest
                or event.predecessor_sha256 != before.digest or event.successor_sha256 != after.digest):
            raise ValueError("Event identity, replay or state chain mismatch")
        seen_events.add(event.event_id)
        _sha(event.randomness_key_sha256)
        fixed = ("context_id", "input_sha256", "parameter_snapshot_sha256", "policy_snapshot_sha256")
        if any(getattr(before, k) != getattr(after, k) for k in fixed):
            raise ValueError("Input or selected parameter/policy snapshot changed during execution")
        if after.event_index != before.event_index + 1 or after.elapsed_us < before.elapsed_us:
            raise ValueError("Nonmonotone event or measured compute clock")
        for field in ("generation_steps", "media_positions"):
            left, right = dict(getattr(before, field)), dict(getattr(after, field))
            if set(left) != set(right) or any(right[m] < left[m] for m in left):
                raise ValueError("Progress or modality set changed incompatibly")
        old, new = dict(before.committed_artifact_sha256), dict(after.committed_artifact_sha256)
        if any(new.get(m) != value for m, value in old.items()):
            raise ValueError("A committed artifact cannot be silently rewritten")
        law = event.joint_action_probabilities
        if (not isinstance(law, tuple) or any(not isinstance(p, tuple) or len(p) != 2 for p in law)
                or len(dict(law)) != len(law) or not law
                or any(not isinstance(a, str) or not a for a, _ in law)):
            raise ValueError("Declare the complete joint legal-action probability law")
        probabilities = {a: _number(p, "joint propensity") for a, p in law}
        if (any(p < 0 for p in probabilities.values())
                or not math.isclose(math.fsum(probabilities.values()), 1.0, abs_tol=1e-12, rel_tol=0)
                or probabilities.get(event.selected_action, 0) <= 0):
            raise ValueError("Invalid selected joint-action propensity")
        if not isinstance(event.costs, tuple):
            raise ValueError("Executed cost records must be immutable")
        charge = total_cost(profile.ndu, event.costs)
        for cost in event.costs:
            if cost.event_id in seen_costs:
                raise ValueError("Physical cost counted more than once")
            seen_costs.add(cost.event_id)
        all_costs.extend(event.costs)
        if not math.isclose(after.remaining_budget, before.remaining_budget - charge,
                            abs_tol=1e-12, rel_tol=1e-12):
            raise ValueError("Consumed/remaining budget does not conserve actual cost")
        if (event.terminal_kind not in {"ongoing", "delivered", "failed", "refused"}
                or event.terminal_kind != "ongoing" and index != len(events) - 1):
            raise ValueError("Invalid terminal kind or action after termination")
    if outcome is None:
        if events[-1].terminal_kind != "ongoing":
            raise ValueError("Termination requires a bound independent outcome")
        return None
    if (not isinstance(outcome, DeliveredOutcome)
            or outcome.context_id != states[-1].context_id
            or events[-1].terminal_kind != outcome.terminal_kind
            or dict(outcome.artifact_sha256) != dict(states[-1].committed_artifact_sha256)
            or sorted(canonical(asdict(c)) for c in outcome.costs)
            != sorted(canonical(asdict(c)) for c in all_costs)):
        raise ValueError("Delivered outcome does not match the executed terminal chain")
    return net_return(profile.ndu, outcome)
