use super::*;

#[test]
fn goal_projection_preserves_complete_training_material_and_all_context_limits() {
    let root = tempfile::tempdir().expect("fixture");
    let (_, baseline, _) =
        crate::neuron_runtime_v2::parameter_checkpoint_tests::fixture(root.path());
    let before = encode_neuron_generation_material_v2(&baseline).expect("original full baseline");
    let mut goal = baseline.clone();
    goal.scope.scope_digest = Digest32::of_bytes(b"actual distinct Goal scope");
    goal.scope.objective_digest = Digest32::of_bytes(b"actual distinct Goal objective");
    goal.store_context.scope = goal.scope;
    goal.index_context.scope = goal.scope;
    goal.witness_context.scope = goal.scope;
    goal.generation_store = root.path().join("goal-store");
    goal.runtime_index = root.path().join("goal-index");
    goal.witness = root.path().join("goal-witness");
    validate_parameter_goal_material_projection_v3(&baseline, &goal)
        .expect("only exact original Goal projection differs");
    for field in 0..5 {
        let mut changed = goal.clone();
        match field {
            0 => changed.store_context.max_records += 1,
            1 => changed.index_context.max_records += 1,
            2 => changed.witness_context.max_records += 1,
            3 => {
                changed.body.effective_parameter_digest = Digest32::of_bytes(b"foreign parameters")
            }
            _ => {
                changed.runtime.generation =
                    codex_hepta_agent_components::types::Generation::new(2).expect("generation")
            }
        }
        assert!(
            validate_parameter_goal_material_projection_v3(&baseline, &changed).is_err(),
            "field {field}"
        );
    }
    assert_eq!(
        encode_neuron_generation_material_v2(&baseline).expect("original unchanged baseline"),
        before
    );
}
