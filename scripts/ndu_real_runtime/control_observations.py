"""Research-only public-state heads; receipts are declarations, not authentication.

Identity labels concern unchanged canonical payload bytes, not semantic quality.
Value targets require actual matched STOP/one-continuation branches and complete
measured costs already converted to the common utility profile. Missing evidence
or any unknown price stays unknown. No native policy or production gate is changed.
Residual summaries are descriptive, without conditional coverage guarantees.

Minimal row contract: {split: "train", source_id, observation_id, context: CriticContext,
state: PublicState(...), implementation: observer_receipt_or_None,
branch_snapshot_sha256, branches: {stop: receipt, continue: receipt}}.
The test row() builder is a complete manufactured schema example, not evidence.
Independent IDs/flags are checked declarations; authenticating the observer,
provenance, common snapshot and full cost scope remains an external obligation.
Context names must be predeclared public bins, never source IDs or hidden labels.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math

from .critic_context import context_digest, require_context


ACTIONS = ("PLAN", "READ", "VERIFY", "REPAIR")
COSTS = (
    "observation",
    "residency",
    "recompute",
    "reuse",
    "coordination",
    "generate",
    "control",
    "delivery",
)


@dataclass(frozen=True)
class PublicState:
    context: str
    action: str
    belief: float
    pending_evidence: bool
    freshness: float
    legal_actions: tuple
    budget: float

    def __post_init__(self):
        if (
            type(self.context) is not str
            or not 0 < len(self.context) <= 128
            or self.action not in ACTIONS
            or type(self.legal_actions) is not tuple
            or any(type(a) is not str for a in self.legal_actions)
            or len(set(self.legal_actions)) != len(self.legal_actions)
            or set(self.legal_actions) - {"STOP", *ACTIONS}
            or "STOP" not in self.legal_actions
            or self.action not in self.legal_actions
            or type(self.pending_evidence) is not bool
            or any(
                type(v) not in (int, float) or not math.isfinite(v)
                for v in (self.belief, self.freshness, self.budget)
            )
            or not 0 <= self.belief <= 1
            or not all(0 <= v <= 1e6 for v in (self.freshness, self.budget))
        ):
            raise ValueError("Invalid public pre-action state")


def state_digest(state):
    """Common branch-start identity excludes the subsequently chosen action."""
    value = asdict(state)
    value.pop("action")
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _digest(value):
    return (
        type(value) is str
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _observed(record):
    return (
        isinstance(record, dict)
        and record.get("completed") is True
        and record.get("independent_observation") is True
        and record.get("provenance") == "measured"
        and type(record.get("actor_id")) is str
        and bool(record["actor_id"])
        and type(record.get("observer_id")) is str
        and bool(record["observer_id"])
        and record["actor_id"] != record["observer_id"]
        and _digest(record.get("evidence_sha256"))
    )


def implementation_label(observation):
    """Missing/uncorroborated stages are unknown; observed mismatch is failure."""
    fields = (
        "selected_payload_sha256",
        "serialized_payload_sha256",
        "delivered_payload_sha256",
        "evaluator_payload_sha256",
    )
    if (
        not _observed(observation)
        or not all(_digest(observation.get(k)) for k in fields)
        or not all(
            type(observation.get(k)) is str and observation[k]
            for k in ("expected_candidate_id", "observed_candidate_id")
        )
    ):
        return None
    return float(
        observation["expected_candidate_id"] == observation["observed_candidate_id"]
        and len({observation[k] for k in fields}) == 1
    )


def _implementation_row_label(row):
    context = require_context(row.get("context"))
    observation = row.get("implementation")
    label = implementation_label(observation)
    if label is None:
        return None
    if (
        not _digest(row.get("branch_snapshot_sha256"))
        or observation.get("branch_snapshot_sha256") != row["branch_snapshot_sha256"]
        or observation.get("source_id") != row["source_id"]
        or observation.get("pre_state_sha256") != state_digest(row["state"])
        or observation.get("action") != row["state"].action
        or observation.get("observation_id") != row["observation_id"]
        or observation.get("critic_context_sha256") != context_digest(context)
    ):
        raise ValueError(
            "Implementation observation differs from row source, state, snapshot or critic context"
        )
    return label


def continuation_label(row):
    """Paired actual gross returns minus the full marginal cost, charged once."""
    context = require_context(row.get("context"))
    pair = row.get("branches")
    if not isinstance(pair, dict) or set(pair) != {"stop", "continue"}:
        return None
    stop, follow = pair["stop"], pair["continue"]
    if not all(_observed(branch) for branch in (stop, follow)):
        return None
    if (
        not _digest(row.get("branch_snapshot_sha256"))
        or any(
            branch.get("branch_snapshot_sha256") != row["branch_snapshot_sha256"]
            for branch in (stop, follow)
        )
        or any(
            type(branch.get("operation_id")) is not str or not branch["operation_id"]
            for branch in (stop, follow)
        )
        or stop["operation_id"] == follow["operation_id"]
    ):
        raise ValueError("Independent branches require the same pinned start snapshot")
    for branch, action, count in ((stop, "STOP", 0), (follow, row["state"].action, 1)):
        if (
            branch.get("source_id") != row["source_id"]
            or branch.get("pre_state_sha256") != state_digest(row["state"])
            or branch.get("action") != action
            or branch.get("continuation_count") != count
            or branch.get("critic_context_sha256") != context_digest(context)
        ):
            raise ValueError(
                "Branch source, pre-state, one-continuation or critic identity differs"
            )
    for key, expected in (
        ("evaluator_sha256", context.evaluator_sha256),
        ("utility_profile_sha256", context.utility_sha256),
        ("tariff_sha256", context.tariff_sha256),
    ):
        if stop.get(key) != expected or follow.get(key) != expected:
            raise ValueError("Paired evaluator/utility/cost profile differs")
    net = []
    for branch in (stop, follow):
        costs, gross = branch.get("costs_in_utility"), branch.get("gross_utility")
        if (
            branch.get("all_costs_measured") is not True
            or not isinstance(costs, dict)
            or set(costs) != set(COSTS)
            or type(gross) not in (int, float)
            or not math.isfinite(gross)
            or abs(gross) > 1e6
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1e6
                for v in costs.values()
            )
        ):
            return None
        net.append(gross - math.fsum(costs.values()))
    return net[1] - net[0]
