use super::*;

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::NeuronStorageCapacityV2;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn capacity() -> NeuronRuntimeCapacityV2 {
    let storage = NeuronStorageCapacityV2 {
        records: 0,
        record_limit: 16,
        file_bytes: 128,
        byte_limit: 16 * 1024,
        reserved_bytes: 0,
    };
    NeuronRuntimeCapacityV2 {
        generation: storage,
        index: storage,
        witness_records_remaining: Some(16),
    }
}

struct DurableStateStubOwner {
    generation: u64,
    reconciles: AtomicU64,
}

impl ProductNeuronOwnerV2 for DurableStateStubOwner {
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
        Ok(NeuronOperationStatusV2::NotRecorded)
    }

    fn capacity_snapshot(&self) -> Result<NeuronRuntimeCapacityV2, NeuronRuntimeV2Error> {
        Ok(capacity())
    }

    fn generation(&self) -> Option<u64> {
        Some(self.generation)
    }

    fn body_bundle_digest(&self) -> Option<Digest32> {
        Some(Digest32::of_bytes(
            format!("durable-state-body-{}", self.generation).as_bytes(),
        ))
    }
}

fn handle(generation: u64) -> (AgentdNeuronHandleV2, Arc<DurableStateStubOwner>) {
    let owner = Arc::new(DurableStateStubOwner {
        generation,
        reconciles: AtomicU64::new(0),
    });
    (
        AgentdNeuronHandleV2 {
            owner: owner.clone(),
            config_digest: Digest32::of_bytes(
                format!("durable-state-config-{generation}").as_bytes(),
            ),
            lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
        },
        owner,
    )
}

#[test]
fn generation_state_round_trips_and_rejects_digest_tampering() {
    let directory = checked(tempfile::tempdir());
    let path = directory.path().join("neuron-generation-state.json");
    let state = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Serving,
        2,
        vec![1],
        None,
    ));
    checked(write_agentd_neuron_generation_state_v2(&path, &state));
    assert_eq!(checked(read_agentd_neuron_generation_state_v2(&path)), state);

    let encoded = checked(std::fs::read_to_string(&path));
    let tampered = encoded.replacen("\"activeGeneration\": 2", "\"activeGeneration\": 3", 1);
    assert_ne!(encoded, tampered);
    checked(std::fs::write(&path, tampered));
    let error = read_agentd_neuron_generation_state_v2(&path)
        .expect_err("tampered generation state was accepted");
    assert_eq!(error.stable_code(), "control_state_corrupt");
}

#[test]
fn durable_controller_publishes_every_lifecycle_transition() {
    let directory = checked(tempfile::tempdir());
    let path = directory.path().join("neuron-generation-state.json");
    let (active, _) = handle(1);
    let controller = checked(AgentdNeuronGenerationControllerV2::new_with_state_path(
        active, &path,
    ));
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Starting
    );

    checked(controller.start());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Serving
    );
    checked(controller.begin_quiesce());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Quiescing
    );
    checked(controller.seal());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Sealed
    );
    checked(controller.shutdown());
    assert_eq!(
        checked(read_agentd_neuron_generation_state_v2(&path)).lifecycle,
        AgentdNeuronLifecycleStateV2::Stopped
    );
}

#[test]
fn interrupted_reload_accepts_only_the_old_or_completed_topology() {
    let directory = checked(tempfile::tempdir());
    let path = directory.path().join("neuron-generation-state.json");
    let interrupted = checked(AgentdNeuronGenerationStateV2::new(
        AgentdNeuronLifecycleStateV2::Reloading,
        1,
        Vec::new(),
        Some(2),
    ));
    checked(write_agentd_neuron_generation_state_v2(
        &path,
        &interrupted,
    ));

    let (old_active, _) = handle(1);
    let old_topology = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            old_active,
            std::iter::empty(),
            &path,
        ),
    );
    assert_eq!(
        checked(old_topology.state()),
        AgentdNeuronLifecycleStateV2::Sealed
    );
    let sealed = checked(read_agentd_neuron_generation_state_v2(&path));
    assert_eq!(sealed.lifecycle, AgentdNeuronLifecycleStateV2::Sealed);
    assert_eq!(sealed.active_generation, 1);
    assert_eq!(sealed.reload_target_generation, None);

    checked(write_agentd_neuron_generation_state_v2(
        &path,
        &interrupted,
    ));
    let (new_active, new_owner) = handle(2);
    let (old_retained, old_owner) = handle(1);
    let completed_topology = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            new_active,
            [old_retained],
            &path,
        ),
    );
    assert_eq!(
        checked(completed_topology.state()),
        AgentdNeuronLifecycleStateV2::Starting
    );
    checked(completed_topology.start());
    assert_eq!(new_owner.reconciles.load(Ordering::SeqCst), 1);
    assert_eq!(old_owner.reconciles.load(Ordering::SeqCst), 1);
    let serving = checked(read_agentd_neuron_generation_state_v2(&path));
    assert_eq!(serving.lifecycle, AgentdNeuronLifecycleStateV2::Serving);
    assert_eq!(serving.active_generation, 2);
    assert_eq!(serving.retained_generations, vec![1]);
    assert_eq!(serving.reload_target_generation, None);

    checked(write_agentd_neuron_generation_state_v2(
        &path,
        &interrupted,
    ));
    let (ambiguous_active, _) = handle(3);
    let error = match
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            ambiguous_active,
            std::iter::empty(),
            &path,
        )
    {
        Ok(_) => panic!("ambiguous interrupted reload topology was accepted"),
        Err(error) => error,
    };
    assert_eq!(error.stable_code(), "generation_conflict");
}

#[test]
fn corrupt_control_state_poison_fails_closed_before_service() {
    let directory = checked(tempfile::tempdir());
    let path = directory.path().join("neuron-generation-state.json");
    checked(std::fs::write(&path, b"not-json"));
    let (active, _) = handle(1);
    let error = match
        AgentdNeuronGenerationControllerV2::from_recovered_generations_with_state_path(
            active,
            std::iter::empty(),
            &path,
        )
    {
        Ok(_) => panic!("corrupt control state was accepted"),
        Err(error) => error,
    };
    assert_eq!(error.stable_code(), "controller_poisoned");
}
