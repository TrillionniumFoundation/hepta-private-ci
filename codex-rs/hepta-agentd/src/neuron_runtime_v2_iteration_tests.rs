//! Actual V2 generation/index files with a deterministic test model. These tests
//! assert physical lifecycle and receipt recovery, never production acceptance.
use super::*;

struct UnusedTickProvider;
impl AgentdNeuronTickProviderV2 for UnusedTickProvider {
    fn build_tick(
        &self,
        _: &crate::AgentdIdentity,
        _: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        _: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, crate::AgentdError> {
        Err(crate::AgentdError::Invalid("unused by owner probe".into()))
    }
}

fn generation_fixture(generation: u64) -> Harness {
    let mut fixture = Harness::new();
    let version = checked(Generation::new(generation));
    fixture.native.generation = version;
    fixture.config.generation = version;
    fixture.config.native_config_digest = checked(fixture.native.digest());
    fixture.config.calibration.generation = version;
    fixture.body.body_generation = version;
    fixture.tick.body_generation = Some(generation);
    fixture.cell.request.generation = version;
    fixture.cell.request.body_digest = checked(fixture.body.semantic_digest());
    fixture
}

#[test]
fn canary_and_forward_rollback_keep_real_durable_receipts_and_revoke_old_epochs() {
    let directory = super::super::super::durable_state_tests::private_state_directory();
    let first = generation_fixture(1);
    let second = generation_fixture(2);
    let rollback = generation_fixture(3);
    let path = directory.path().join("control.json");
    let controller = checked(AgentdNeuronGenerationControllerV2::new_with_state_path(
        first.owner(),
        &path,
    ));
    checked(controller.start());
    let stale_first = first.prepared(&controller);
    let host = AgentdNeuronRuntimeV2Host {
        controller,
        tick_provider: Arc::new(UnusedTickProvider),
        goal_scope_factory: None,
        lifecycle: Mutex::new(()),
        stopped: AtomicBool::new(false),
        iteration_quarantine: AtomicBool::new(false),
    };
    let second_handle = second.owner();
    let rollback_handle = rollback.owner();
    checked(host.quarantine_iteration());
    checked(host.install_iteration_generation(second_handle.clone(), 1));
    assert!(
        stale_first
            .execute(&first.input(), &mut first.allow())
            .is_err()
    );
    assert_eq!(first.calls.load(Ordering::SeqCst), 0);
    let canary = second.prepared(&host.controller);
    let commit = checked(canary.execute(&second.input(), &mut second.allow()));
    assert_eq!(second.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        checked(canary.execute(&second.input(), &mut second.allow())),
        commit
    );
    checked(host.quarantine_iteration());
    checked(host.install_iteration_generation(rollback_handle.clone(), 2));
    checked(host.release_iteration_quarantine());
    let actual = checked(host.generation_snapshot());
    assert_eq!(actual.active_generation, 3);
    assert_eq!(actual.retained_generations, vec![1, 2]);
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).active_generation,
        3
    );
    assert!(
        canary
            .execute(&second.input(), &mut second.allow())
            .is_err()
    );
    assert_eq!(second.calls.load(Ordering::SeqCst), 1);
    assert!(matches!(
        checked(second_handle.query_decision_cell_operation(&second.cell, &second.tick)),
        NeuronOperationStatusV2::Committed { .. }
    ));
    checked(host.quarantine_iteration());
    checked(host.install_iteration_generation(rollback_handle, 2));
    checked(host.release_iteration_quarantine());
    assert_eq!(checked(host.generation_snapshot()).active_generation, 3);
    assert_eq!(second.calls.load(Ordering::SeqCst), 1);
}

#[test]
fn goal_mode_canary_and_forward_rollback_use_the_original_scope_controller() {
    let directory = super::super::super::durable_state_tests::private_state_directory();
    let first = generation_fixture(1);
    let second = generation_fixture(2);
    let rollback = generation_fixture(3);
    let path = directory.path().join("goal-control.json");
    let first_handle = super::goal_scope_tests::scope_owner(&first, first.tick.objective_digest);
    let first_scope = checked(AgentdNeuronGoalScopeV3::capture(1, &first_handle));
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_goal_scopes_v3(
            first_scope.clone(),
            first_handle.clone(),
            Vec::new(),
            &path,
        ),
    );
    checked(controller.start());
    let stale_first = first.prepared(&controller);
    let host = AgentdNeuronRuntimeV2Host {
        controller,
        tick_provider: Arc::new(UnusedTickProvider),
        goal_scope_factory: None,
        lifecycle: Mutex::new(()),
        stopped: AtomicBool::new(false),
        iteration_quarantine: AtomicBool::new(false),
    };
    let (current, scope) = checked(host.current_installed_owner_v3());
    assert_eq!(
        current.configuration_digest(),
        first_handle.configuration_digest()
    );
    assert_eq!(scope, Some(first_scope.clone()));
    let second_handle = super::goal_scope_tests::scope_owner(&second, second.tick.objective_digest);
    checked(host.quarantine_iteration());
    assert!(host.current_installed_owner_v3().is_err());
    checked(host.install_iteration_generation(second_handle.clone(), 1));
    let second_scope = checked(AgentdNeuronGoalScopeV3::capture(2, &second_handle));
    assert_eq!(
        checked(read_agentd_neuron_goal_scope_state_v3(&path)).active_scope,
        second_scope
    );
    assert!(
        stale_first
            .execute(&first.input(), &mut first.allow())
            .is_err()
    );
    assert_eq!(first.calls.load(Ordering::SeqCst), 0);
    let canary = second.prepared(&host.controller);
    let receipt = checked(canary.execute(&second.input(), &mut second.allow()));
    assert_eq!(second.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        checked(canary.execute(&second.input(), &mut second.allow())),
        receipt
    );
    checked(host.quarantine_iteration());
    let rollback_handle =
        super::goal_scope_tests::scope_owner(&rollback, rollback.tick.objective_digest);
    checked(host.install_iteration_generation(rollback_handle.clone(), 2));
    checked(host.release_iteration_quarantine());
    let third_scope = checked(AgentdNeuronGoalScopeV3::capture(3, &rollback_handle));
    let (current, scope) = checked(host.current_installed_owner_v3());
    assert_eq!(
        current.configuration_digest(),
        rollback_handle.configuration_digest()
    );
    assert_eq!(scope, Some(third_scope.clone()));
    let durable = checked(read_agentd_neuron_goal_scope_state_v3(&path));
    assert_eq!(durable.active_scope, third_scope);
    assert_eq!(durable.retained_scopes, vec![first_scope, second_scope]);
    assert!(
        canary
            .execute(&second.input(), &mut second.allow())
            .is_err()
    );
    assert_eq!(second.calls.load(Ordering::SeqCst), 1);
    assert!(matches!(
        checked(second_handle.query_decision_cell_operation(&second.cell, &second.tick)),
        NeuronOperationStatusV2::Committed { .. }
    ));
    checked(host.quarantine_iteration());
    let quarantined = checked(read_agentd_neuron_goal_scope_state_v3(&path));
    let foreign = generation_fixture(3);
    let foreign_handle =
        super::goal_scope_tests::scope_owner(&foreign, digest("foreign-recovery-goal"));
    assert!(
        host.install_iteration_generation(foreign_handle, 2)
            .is_err()
    );
    assert_eq!(
        checked(read_agentd_neuron_goal_scope_state_v3(&path)),
        quarantined
    );
    assert_eq!(foreign.calls.load(Ordering::SeqCst), 0);
    checked(host.install_iteration_generation(rollback_handle, 2));
    checked(host.release_iteration_quarantine());
    assert_eq!(
        checked(read_agentd_neuron_goal_scope_state_v3(&path)),
        durable
    );
    assert_eq!(second.calls.load(Ordering::SeqCst), 1);
}

#[path = "neuron_runtime_v2_archive_tests.rs"]
mod archive_tests;
