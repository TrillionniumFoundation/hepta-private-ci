"""Manufactured schema examples for protocol tests, never scientific evidence."""

from .control_observations import COSTS, PublicState, state_digest
from .critic_context import CriticContext, context_digest


CRITIC_CONTEXT = CriticContext(
    encoder_sha256="2" * 64,
    answer_sha256="3" * 64,
    generator_sha256="4" * 64,
    public_state_sha256="5" * 64,
    action_sha256="6" * 64,
    settlement_sha256="7" * 64,
    utility_sha256="f" * 64,
    tariff_sha256="1" * 64,
    evaluator_sha256="e" * 64,
)


def observed():
    return dict(
        completed=True,
        independent_observation=True,
        provenance="measured",
        actor_id="actor",
        observer_id="independent-reader",
        evidence_sha256="a" * 64,
    )


def row(
    source,
    *,
    split="train",
    context="stable",
    belief=0.2,
    success=True,
    gain=0.3,
    critic_context=CRITIC_CONTEXT,
):
    state = PublicState(
        context, "READ", belief, True, 0.0, ("STOP", "READ", "REPAIR"), 9.0
    )
    identity = dict(
        observed(),
        source_id=source,
        pre_state_sha256=state_digest(state),
        branch_snapshot_sha256="d" * 64,
        critic_context_sha256=context_digest(critic_context),
        action="READ",
        observation_id=source + "/observation",
        expected_candidate_id="c1",
        observed_candidate_id="c1",
        selected_payload_sha256="b" * 64,
        serialized_payload_sha256="b" * 64,
        delivered_payload_sha256="b" * 64,
        evaluator_payload_sha256=("b" if success else "c") * 64,
    )
    common = dict(
        observed(),
        source_id=source,
        pre_state_sha256=state_digest(state),
        branch_snapshot_sha256="d" * 64,
        critic_context_sha256=context_digest(critic_context),
        evaluator_sha256=critic_context.evaluator_sha256,
        utility_profile_sha256=critic_context.utility_sha256,
        tariff_sha256=critic_context.tariff_sha256,
        all_costs_measured=True,
    )
    stop_cost, continue_cost = {k: 0.0 for k in COSTS}, {k: 0.0 for k in COSTS}
    stop_cost["control"], continue_cost["control"] = 2.0, 3.0
    stop = dict(
        common,
        operation_id=source + "/stop",
        action="STOP",
        continuation_count=0,
        gross_utility=10.0,
        costs_in_utility=stop_cost,
    )
    follow = dict(
        common,
        operation_id=source + "/read",
        action="READ",
        continuation_count=1,
        gross_utility=11.0 + gain,
        costs_in_utility=continue_cost,
    )
    return dict(
        split=split,
        context=critic_context,
        source_id=source,
        observation_id=source + "/observation",
        state=state,
        implementation=identity,
        branch_snapshot_sha256="d" * 64,
        branches={"stop": stop, "continue": follow},
    )
