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

#[path = "neuron_runtime_v2_archive_tests.rs"]
mod archive_tests;
