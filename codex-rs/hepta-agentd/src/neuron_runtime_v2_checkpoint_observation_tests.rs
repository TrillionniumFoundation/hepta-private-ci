use super::*;

#[test]
fn current_goal_checkpoint_rejects_other_tuple_and_quiescing_owner_without_model_work() {
    let h = Harness::new();
    let owner = scope_owner(&h, h.tick.objective_digest);
    let actual_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &owner));
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            actual_scope,
            owner.clone(),
            std::iter::empty(),
            h.root.path().join("current-eligibility-goal-scope.json"),
        ),
    );
    checked(controller.start());
    checked(h.prepared(&controller).execute(&h.input(), &mut h.allow()));
    let (_, anchor) = checked(controller.current_tick_anchor());
    let anchor = anchor.expect("real acknowledged checkpoint");
    let generation = checked(AgentdNeuronGenerationIdV2::new(1));
    let configuration = owner.configuration_digest();
    let body = owner.body_bundle_digest().expect("original durable body");
    let actual = checked(controller.current_sparse_checkpoint_v2(
        generation,
        configuration,
        body,
        scope(),
        anchor,
    ))
    .expect("whole current checkpoint");
    assert_eq!(actual.digest(), anchor.checkpoint_digest);
    assert!(!actual.eligibility_q24().is_empty());
    for change in 0..5 {
        let mut expected_generation = generation;
        let mut config = configuration;
        let mut expected_body = body;
        let mut expected_scope = scope();
        match change {
            0 => expected_generation = checked(AgentdNeuronGenerationIdV2::new(2)),
            1 => config = digest("other configuration"),
            2 => expected_body = digest("other body"),
            3 => expected_scope.objective_digest = digest("other objective"),
            4 => expected_scope.scope_digest = digest("other subject"),
            _ => unreachable!(),
        }
        assert!(
            controller
                .current_sparse_checkpoint_v2(
                    expected_generation,
                    config,
                    expected_body,
                    expected_scope,
                    anchor
                )
                .is_err()
        );
    }
    checked(controller.begin_quiesce());
    assert!(
        controller
            .current_sparse_checkpoint_v2(generation, configuration, body, scope(), anchor)
            .is_err()
    );
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
}
