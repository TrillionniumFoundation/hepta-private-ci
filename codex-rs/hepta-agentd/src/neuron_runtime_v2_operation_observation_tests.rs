//! Original physical owner and Goal controller; no fabricated canary receipt.
use super::*;

#[test]
fn whole_current_goal_operation_rejects_substitution_and_retired_owners() {
    let h = Harness::new();
    let owner = scope_owner(&h, h.tick.objective_digest);
    let actual_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &owner));
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            actual_scope,
            owner.clone(),
            std::iter::empty(),
            h.root.path().join("export-goal-scope.json"),
        ),
    );
    checked(controller.start());
    checked(h.prepared(&controller).execute(&h.input(), &mut h.allow()));
    let status = checked(owner.query_decision_cell_operation(&h.cell, &h.tick));
    let NeuronOperationStatusV2::Committed {
        commit,
        witness_acknowledged: true,
    } = status
    else {
        panic!("actual original operation must be acknowledged");
    };
    let operation = checked(AgentdNeuronOperationIdentityV2::new(
        commit.key.tick_id.clone(),
        commit.key.input_semantic_digest,
    ));
    let generation = checked(AgentdNeuronGenerationIdV2::new(1));
    let configuration = owner.configuration_digest();
    let body = owner.body_bundle_digest().expect("actual durable body");
    let actual_journal_scope = scope();
    let exported = checked(controller.export_current_operation_v2(
        generation,
        configuration,
        body,
        actual_journal_scope,
        &operation,
    ));
    assert_eq!(exported.commit(), commit.as_ref());
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
    assert!(
        controller
            .query_operation(1, operation.tick_id(), operation.input_semantic_digest())
            .is_err()
    );
    for change in 0..5 {
        let mut expected_generation = generation;
        let mut expected_configuration = configuration;
        let mut expected_body = body;
        let mut expected_scope = actual_journal_scope;
        match change {
            0 => expected_generation = checked(AgentdNeuronGenerationIdV2::new(2)),
            1 => expected_configuration = digest("foreign config"),
            2 => expected_body = digest("foreign body"),
            3 => expected_scope.objective_digest = digest("foreign objective"),
            4 => expected_scope.scope_digest = digest("foreign subject"),
            _ => unreachable!(),
        }
        assert!(
            controller
                .export_current_operation_v2(
                    expected_generation,
                    expected_configuration,
                    expected_body,
                    expected_scope,
                    &operation
                )
                .is_err()
        );
    }
    checked(controller.begin_quiesce());
    assert!(
        controller
            .export_current_operation_v2(
                generation,
                configuration,
                body,
                actual_journal_scope,
                &operation
            )
            .is_err()
    );
    assert_eq!(h.calls.load(Ordering::SeqCst), 1);
}
