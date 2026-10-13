use super::*;
use codex_hepta_bellman_operator::TransitionBranchV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(seed: u8) -> Digest32 {
    Digest32::from_array([seed; 32])
}

fn predictor_context() -> CellAdapterContextV1 {
    CellAdapterContextV1 {
        cell_id: id("cell.predictor.runtime"),
        generation: Generation::new(3).expect("generation"),
        scope_digest: digest(1),
        role: CellRoleV1::Predictor,
        capability_digest: digest(2),
        input_frontier_digest: digest(3),
        state_predecessor_digest: digest(4),
        resource_receipt_digest: digest(5),
        evidence_digest: digest(6),
    }
}

#[test]
fn predictor_runtime_binds_exact_state_bytes_to_projected_step() {
    let context = predictor_context();
    let input = LearnedRoleRuntimeInputV1::Predictor(WorldModelPredictionV1 {
        model_id: id("world.model"),
        dataset_digest: digest(10),
        state_id: id("state.before"),
        action_id: id("action.inspect"),
        mean_outcome: FixedQ32::from_raw(1 << 32),
        branches: vec![TransitionBranchV1 {
            next_state_id: id("state.after"),
            count: 1,
            probability: ProbabilityQ32::ONE,
        }],
        estimate_digest: digest(11),
        synthetic: true,
        authority: AuthorityPosture::DENY_ALL,
    });
    let state = b"predictor-checkpoint-v3";
    let execution = input.adapt(&context, state).expect("adapter execution");
    assert_eq!(
        execution.receipt.state_successor_digest,
        Digest32::of_bytes(state)
    );
    assert_eq!(execution.output.receipt(), &execution.receipt);
    assert_eq!(
        execution.receipt.state_predecessor_digest,
        context.state_predecessor_digest
    );
}

#[test]
fn runtime_bridge_rejects_empty_state_before_invoking_adapter() {
    let input = LearnedRoleRuntimeInputV1::Predictor(WorldModelPredictionV1 {
        model_id: id("world.model"),
        dataset_digest: digest(10),
        state_id: id("state.before"),
        action_id: id("action.inspect"),
        mean_outcome: FixedQ32::from_raw(1),
        branches: vec![TransitionBranchV1 {
            next_state_id: id("state.after"),
            count: 1,
            probability: ProbabilityQ32::ONE,
        }],
        estimate_digest: digest(11),
        synthetic: true,
        authority: AuthorityPosture::DENY_ALL,
    });
    assert_eq!(
        input.adapt(&predictor_context(), &[]),
        Err(LearnedRoleRuntimeErrorV1::EmptyState)
    );
}
