use super::*;

#[path = "neuron_runtime_v2_operation_observation_tests.rs"]
mod operation_observation_tests;

struct ScopeAdmission(Arc<AtomicBool>);
impl NeuronAdmissionGuard for ScopeAdmission {
    fn check_scope(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: JournalScope,
    ) -> Result<(), NeuronAdmissionError> {
        if self.0.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(NeuronAdmissionError::Unavailable)
        }
    }
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Admission(self.0.clone()).check(config, input)
    }
}

pub(super) fn scope_owner(h: &Harness, objective_digest: Digest32) -> AgentdNeuronHandleV2 {
    let mut journal_scope = scope();
    journal_scope.objective_digest = objective_digest;
    let (mut store_context, mut index_context) = contexts(&h.native, &h.config, &h.body);
    store_context.scope = journal_scope;
    index_context.scope = journal_scope;
    let store_path = h.root.path().join("generation.hptngs02");
    let index_path = h.root.path().join("index.hptngi02");
    let runtime = checked(if store_path.exists() {
        NeuronRuntimeV2::recover(
            &store_path,
            &index_path,
            h.native.clone(),
            journal_scope,
            h.config.clone(),
            h.body.clone(),
            store_context,
            index_context,
            h.witness.clone(),
        )
    } else {
        NeuronRuntimeV2::bootstrap(
            &h.root.path().join("generation.hptngs02"),
            &h.root.path().join("index.hptngi02"),
            h.native.clone(),
            journal_scope,
            h.config.clone(),
            h.body.clone(),
            store_context,
            index_context,
            h.witness.clone(),
        )
    });
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
        .into_shared(ScopeAdmission(h.admitted.clone())),
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

#[test]
fn goal_scope_controller_v3_hands_off_two_goals_on_model_one_and_reopens_exact_topology() {
    let first = Harness::new();
    let second = Harness::new();
    let first_owner = scope_owner(&first, digest("first-goal"));
    let second_owner = scope_owner(&second, digest("second-goal"));
    let first_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &first_owner));
    let second_scope = checked(AgentdNeuronGoalScopeV3::capture(2, &second_owner));
    let path = first.root.path().join("scope-controller.json");
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            first_scope.clone(),
            first_owner.clone(),
            std::iter::empty(),
            &path,
        ),
    );
    checked(controller.start());
    checked(controller.begin_quiesce());
    checked(controller.seal());
    checked(controller.reload_goal_scope_v3(&first_scope, second_owner.clone()));
    let expected = checked(AgentdNeuronGoalScopeStateV3::new(
        AgentdNeuronLifecycleStateV2::Serving,
        second_scope.clone(),
        vec![first_scope.clone()],
        None,
    ));
    assert_eq!(checked(controller.goal_scope_state_v3()), expected);
    assert_eq!(checked(controller.active_generation()), 1);
    assert!(!first_owner.lifecycle_gate_snapshot().0);
    assert!(second_owner.lifecycle_gate_snapshot().0);
    assert!(controller.generation_state().is_err());
    assert!(controller.retained_generations().is_err());
    assert!(
        controller
            .query_operation(1, &id("absent"), digest("absent"))
            .is_err()
    );
    for scope in [&first_scope, &second_scope] {
        assert_eq!(
            checked(controller.query_goal_scope_operation_v3(
                scope,
                &id("absent"),
                digest("absent")
            )),
            NeuronOperationStatusV2::NotRecorded
        );
    }
    drop(controller);
    let reopened = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            second_scope,
            second_owner.clone(),
            [(first_scope, first_owner)],
            &path,
        ),
    );
    assert_eq!(
        checked(reopened.state()),
        AgentdNeuronLifecycleStateV2::Starting
    );
    assert!(!second_owner.lifecycle_gate_snapshot().0);
    checked(reopened.start());
    assert_eq!(checked(reopened.goal_scope_state_v3()), expected);
    assert_eq!(first.calls.load(Ordering::SeqCst), 0);
    assert_eq!(second.calls.load(Ordering::SeqCst), 0);
}

#[test]
fn goal_scope_controller_v3_rejects_stale_cas_expired_admission_and_legacy_reload() {
    let first = Harness::new();
    let second = Harness::new();
    let first_owner = scope_owner(&first, digest("first-goal"));
    let next = scope_owner(&second, digest("second-goal"));
    let original = checked(AgentdNeuronGoalScopeV3::capture(1, &first_owner));
    let path = first.root.path().join("scope-controller.json");
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            original.clone(),
            first_owner,
            std::iter::empty(),
            &path,
        ),
    );
    checked(controller.start());
    checked(controller.begin_quiesce());
    checked(controller.seal());
    let before = checked(std::fs::read(&path));
    let mut stale = original.clone();
    stale.identity.objective_digest = digest("old-or-foreign-goal");
    assert!(
        controller
            .reload_goal_scope_v3(&stale, next.clone())
            .is_err()
    );
    second.admitted.store(false, Ordering::SeqCst);
    assert!(
        controller
            .reload_goal_scope_v3(&original, next.clone())
            .is_err()
    );
    assert!(controller.reload(next.clone()).is_err());
    assert_eq!(checked(std::fs::read(&path)), before);
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Sealed
    );
    assert_eq!(checked(controller.active_generation()), 1);
    second.admitted.store(true, Ordering::SeqCst);
    checked(controller.reload_goal_scope_v3(&original, next));
    assert_eq!(checked(controller.active_generation()), 1);
}

#[path = "neuron_goal_scope_archive_v3_tests.rs"]
mod cold_tests;

#[path = "neuron_goal_scope_reload_v3_tests.rs"]
mod reload_tests;
