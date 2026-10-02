use super::*;

fn scope_owner(h: &Harness, objective_digest: Digest32) -> AgentdNeuronHandleV2 {
    let mut journal_scope = scope();
    journal_scope.objective_digest = objective_digest;
    let (mut store_context, mut index_context) = contexts(&h.native, &h.config, &h.body);
    store_context.scope = journal_scope;
    index_context.scope = journal_scope;
    let runtime = checked(NeuronRuntimeV2::bootstrap(
        &h.root.path().join("generation.hptngs02"),
        &h.root.path().join("index.hptngi02"),
        h.native.clone(),
        journal_scope,
        h.config.clone(),
        h.body.clone(),
        store_context,
        index_context,
        h.witness.clone(),
    ));
    let model = FakeDecisionCellModel {
        calls: h.calls.clone(),
        runtime: h.cell.selected_runtime.clone(),
        encoder_digest: h.config.encoder_digest,
        head_digest: h.config.head_digest,
        output_width: h.config.state_width,
    };
    checked(
        AgentdNeuronOwnerV2::new(
            runtime,
            Control {
                model,
                state: h.state.clone(),
            },
        )
        .into_shared(Admission(h.admitted.clone())),
    )
}

#[test]
fn goal_scope_v3_reads_two_real_scopes_with_the_same_actual_model_generation() {
    let first = Harness::new();
    let second = Harness::new();
    let first_owner = scope_owner(&first, digest("first-goal"));
    let second_owner = scope_owner(&second, digest("second-goal"));
    let first_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &first_owner));
    let second_scope = checked(AgentdNeuronGoalScopeV3::capture(2, &second_owner));
    assert_eq!(first_scope.identity.model_generation, 1);
    assert_eq!(second_scope.identity.model_generation, 1);
    assert_eq!(
        first_scope.identity.runtime_configuration_digest,
        second_scope.identity.runtime_configuration_digest
    );
    assert_eq!(
        first_scope.identity.body_bundle_digest,
        second_scope.identity.body_bundle_digest
    );
    assert_ne!(
        first_scope.identity.objective_digest,
        second_scope.identity.objective_digest
    );
    let path = first.root.path().join("goal-scope-control.json");
    let state = checked(AgentdNeuronGoalScopeStateV3::new(
        AgentdNeuronLifecycleStateV2::Serving,
        second_scope,
        vec![first_scope],
        None,
    ));
    checked(write_agentd_neuron_goal_scope_state_v3(&path, &state));
    assert_eq!(
        checked(read_agentd_neuron_goal_scope_state_v3(&path)),
        state
    );
    assert!(read_agentd_neuron_generation_state_v2(&path).is_err());
    assert_eq!(first.calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn goal_scope_v3_rejects_foreign_subject_skipped_slot_and_mutated_model_history() {
    let first = Harness::new();
    let second = Harness::new();
    let first_owner = scope_owner(&first, digest("first-goal"));
    let second_owner = scope_owner(&second, digest("second-goal"));
    let active = checked(AgentdNeuronGoalScopeV3::capture(1, &first_owner));
    let next = checked(AgentdNeuronGoalScopeV3::capture(2, &second_owner));
    for invalid in [
        AgentdNeuronGoalScopeV3 {
            ordinal: 3,
            ..next.clone()
        },
        AgentdNeuronGoalScopeV3 {
            identity: AgentdNeuronScopeIdentityV3 {
                subject_scope_digest: digest("foreign-subject"),
                ..next.identity.clone()
            },
            ..next
        },
        AgentdNeuronGoalScopeV3 {
            ordinal: 2,
            identity: active.identity.clone(),
        },
    ] {
        assert!(
            AgentdNeuronGoalScopeStateV3::new(
                AgentdNeuronLifecycleStateV2::Reloading,
                active.clone(),
                Vec::new(),
                Some(invalid),
            )
            .is_err()
        );
    }
    let mut state = checked(AgentdNeuronGoalScopeStateV3::new(
        AgentdNeuronLifecycleStateV2::Reloading,
        active,
        Vec::new(),
        Some(next),
    ));
    state.active_scope.identity.model_generation = 2;
    assert!(state.validate().is_err());
}

#[test]
fn goal_scope_v3_cannot_reinterpret_a_legacy_control_file() {
    let root = super::super::super::durable_state_tests::private_state_directory();
    let path = root.path().join("control.json");
    let legacy = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Serving,
        2,
        vec![1],
        None,
    ));
    checked(write_agentd_neuron_generation_state_v2(&path, &legacy));
    let before = checked(std::fs::read(&path));
    assert!(read_agentd_neuron_goal_scope_state_v3(&path).is_err());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)),
        legacy
    );
    assert_eq!(checked(std::fs::read(&path)), before);
}
