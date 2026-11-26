use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_agent_components::neuron::NeuronAdmissionGuard;
use codex_hepta_agent_components::neuron::NeuronOperationStatusV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeCapacityV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeCommitV2;
use codex_hepta_agent_components::neuron::NeuronRuntimeV2Error;
use codex_hepta_agent_components::neuron::NeuronStorageCapacityV2;
use codex_hepta_agent_components::neuron::NeuronTickInputV1;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;

use super::AgentdNeuronExecutionGateV2;
use super::AgentdNeuronHandleV2;
use super::ProductNeuronOwnerV2;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture: {error:?}"),
    }
}

struct StubProductOwner {
    reconciles: AtomicUsize,
}

impl ProductNeuronOwnerV2 for StubProductOwner {
    fn execute(
        &self,
        _input: NeuronTickInputV1,
        _guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn reconcile(&self) -> Result<(), NeuronRuntimeV2Error> {
        self.reconciles.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }

    fn query_operation(
        &self,
        _tick_id: &StableId,
        _input_digest: Digest32,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        Ok(NeuronOperationStatusV2::NotExecuted)
    }

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        let storage = NeuronStorageCapacityV2 {
            records: 8,
            record_limit: 10,
            file_bytes: 50,
            byte_limit: 100,
            reserved_bytes: 0,
        };
        Ok(NeuronRuntimeCapacityV2 {
            generation: storage,
            index: storage,
            witness_records_remaining: Some(2),
        })
    }
}

#[test]
fn shared_handle_exposes_serialized_recovery_and_capacity_inspection() {
    let owner = Arc::new(StubProductOwner {
        reconciles: AtomicUsize::new(0),
    });
    let config_digest = Digest32::of_bytes(b"agentd-neuron-config");
    let handle = AgentdNeuronHandleV2 {
        owner: owner.clone(),
        config_digest,
        lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
    };

    assert_eq!(handle.configuration_digest(), config_digest);
    assert!(handle.reconcile().is_ok());
    assert_eq!(owner.reconciles.load(Ordering::SeqCst), 1);
    let tick_id = checked(StableId::new("agentd-neuron-operation"));
    let status = checked(handle.query_operation(&tick_id, Digest32::of_bytes(b"input")));
    assert_eq!(status.stable_code(), "reserved_not_executed");
    let capacity = checked(handle.capacity_snapshot());
    assert_eq!(capacity.action_code(), "schedule_generation_handoff");
}
