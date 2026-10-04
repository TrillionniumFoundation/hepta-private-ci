use super::*;
use codex_hepta_agent_components::neuron::NeuronGenerationMaterialV2;
use codex_hepta_agent_components::neuron::SparseCheckpoint;
struct NoTick;
impl AgentdNeuronTickProviderV2 for NoTick {
    fn build_tick(
        &self,
        _: &crate::AgentdIdentity,
        _: &codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        _: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, crate::AgentdError> {
        panic!("observation must not dispatch Goal");
    }
}
struct Allow;
impl NeuronAdmissionGuard for Allow {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        Ok(())
    }
}
pub(crate) fn fixture(
    root: &Path,
) -> (
    lock_metrics_tests::RuntimeFixture,
    NeuronGenerationMaterialV2,
    Arc<AgentdNeuronRuntimeV2Host>,
) {
    let (runtime, material) = lock_metrics_tests::parameter_checkpoint_fixture();
    let host = AgentdNeuronRuntimeV2Config::new(
        runtime.handle.clone(),
        root.join("checkpoint-control.json"),
        Arc::new(NoTick),
    )
    .expect("original host config")
    .start()
    .expect("actual Serving host");
    let invocation = host
        .controller
        .prepare(
            runtime.input.tick_id.clone(),
            runtime.handle.body_bundle_digest().expect("body"),
            runtime.input.clone(),
        )
        .expect("original invocation");
    invocation
        .execute(&runtime.canonical, &mut Allow)
        .expect("original model/tick/ACK");
    (runtime, material, host)
}
#[test]
fn whole_checkpoint_observes_actual_ack_without_provider_or_store_changes() {
    let root = tempfile::tempdir().expect("root");
    let (runtime, material, host) = fixture(root.path());
    let before = [
        std::fs::read(&material.generation_store).expect("store"),
        std::fs::read(&material.runtime_index).expect("index"),
        std::fs::read(&material.witness).expect("witness"),
    ];
    let (anchor, bytes, ordinal) = host
        .prepare_parameter_checkpoint_observation(&material)
        .expect("full observation");
    let actual = SparseCheckpoint::decode_observation_v1(
        &bytes,
        Digest32::of_bytes(&bytes),
        &material.native,
        material.scope,
        material.body.semantic_digest().expect("body"),
        anchor,
    )
    .expect("exact whole state");
    assert_eq!(ordinal, None);
    assert_eq!(actual.sequence(), anchor.sequence);
    assert_eq!(actual.digest(), anchor.checkpoint_digest);
    assert_eq!(runtime.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        [
            std::fs::read(&material.generation_store).expect("store"),
            std::fs::read(&material.runtime_index).expect("index"),
            std::fs::read(&material.witness).expect("witness")
        ],
        before
    );
    // Advance the actual same owner, then observe its current ACK rather than
    // borrow the already acknowledged prior tick receipt.
    let committed = advance_fixture(&runtime, &host, &material, anchor);
    let (current, next_bytes, next_ordinal) = host
        .prepare_parameter_checkpoint_observation(&material)
        .expect("actual latest complete state");
    assert_eq!(next_ordinal, ordinal);
    assert_eq!(current, committed);
    assert_eq!(current.sequence, 2);
    assert_ne!(current, anchor);
    assert_ne!(next_bytes, bytes);
    for field in 0..3 {
        let mut changed = material.clone();
        match field {
            0 => changed.scope.scope_digest = Digest32::of_bytes(b"foreign"),
            1 => changed.body.effective_parameter_digest = Digest32::of_bytes(b"foreign"),
            _ => changed.runtime.generation = Generation::new(2).expect("generation"),
        }
        assert!(
            host.prepare_parameter_checkpoint_observation(&changed)
                .is_err()
        );
    }
    host.begin_quiesce().expect("original quiesce");
    assert!(
        host.prepare_parameter_checkpoint_observation(&material)
            .is_err()
    );
    assert_eq!(runtime.calls.load(Ordering::SeqCst), 2);
}

// Execute a real second tick through the original held controller for both the
// plain observation fixture and the protected socket/frozen-input regression.
pub(crate) fn advance_fixture(
    runtime: &lock_metrics_tests::RuntimeFixture,
    host: &Arc<AgentdNeuronRuntimeV2Host>,
    material: &NeuronGenerationMaterialV2,
    anchor: codex_hepta_agent_components::neuron::JournalAnchor,
) -> codex_hepta_agent_components::neuron::JournalAnchor {
    let mut next_input = runtime.input.clone();
    next_input.tick_id = StableId::new("checkpoint.actual.second").expect("id");
    next_input.logical_sequence = 2;
    next_input.monotonic_time_micros = 2000;
    next_input.checkpoint_digest = anchor.checkpoint_digest;
    let mut canonical = runtime.canonical.clone();
    canonical.run_id = next_input.tick_id.clone();
    let invocation = host
        .controller
        .prepare(
            next_input.tick_id.clone(),
            material.body.semantic_digest().expect("body"),
            next_input,
        )
        .expect("same owner next tick");
    let committed = invocation
        .execute(&canonical, &mut Allow)
        .expect("actual next model/tick/ACK");
    committed.next_anchor
}
