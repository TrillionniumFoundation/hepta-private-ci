use super::*;

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::NeuronOperationFailureV2;
use codex_hepta_neuron::NeuronStorageCapacityV2;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    checked(StableId::new(value))
}

fn capacity() -> NeuronRuntimeCapacityV2 {
    let storage = NeuronStorageCapacityV2 {
        records: 1,
        record_limit: 16,
        file_bytes: 256,
        byte_limit: 16 * 1024,
        reserved_bytes: 0,
    };
    NeuronRuntimeCapacityV2 {
        generation: storage,
        index: storage,
        witness_records_remaining: Some(15),
    }
}

struct LifecycleStubOwner {
    generation: u64,
    reconciles: AtomicU64,
    recoveries: AtomicU64,
}

impl ProductNeuronOwnerV2 for LifecycleStubOwner {
    fn execute(
        &self,
        _input: NeuronTickInputV1,
        _guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn recover_operation_control(
        &self,
        _input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.recoveries.fetch_add(1, Ordering::SeqCst);
        Ok(NeuronOperationStatusV2::Failed(
            NeuronOperationFailureV2::AdmissionDenied,
        ))
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
            format!("body-generation-{}", self.generation).as_bytes(),
        ))
    }
}

fn handle(generation: u64) -> (AgentdNeuronHandleV2, Arc<LifecycleStubOwner>) {
    let owner = Arc::new(LifecycleStubOwner {
        generation,
        reconciles: AtomicU64::new(0),
        recoveries: AtomicU64::new(0),
    });
    (
        AgentdNeuronHandleV2 {
            owner: owner.clone(),
            config_digest: Digest32::of_bytes(
                format!("config-generation-{generation}").as_bytes(),
            ),
        },
        owner,
    )
}

#[test]
fn controller_quiesces_recovers_seals_and_retains_old_generation_queries() {
    let (first, first_owner) = handle(1);
    let controller = checked(AgentdNeuronGenerationControllerV2::new(first));
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Starting
    );
    checked(controller.start());
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Serving
    );
    checked(controller.begin_quiesce());
    let input = test_input();
    let report = checked(controller.recover_operation(&input));
    assert!(report.terminal);
    assert_eq!(report.failure_code.as_deref(), Some("admission_denied"));
    assert_eq!(first_owner.recoveries.load(Ordering::SeqCst), 1);
    checked(controller.seal());
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Sealed
    );

    let (second, second_owner) = handle(2);
    checked(controller.reload(second));
    assert_eq!(checked(controller.active_generation()), 2);
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Serving
    );
    assert!(first_owner.reconciles.load(Ordering::SeqCst) >= 2);
    assert!(second_owner.reconciles.load(Ordering::SeqCst) >= 1);
    assert_eq!(
        checked(controller.query_operation(
            1,
            &id("historical.tick"),
            Digest32::of_bytes(b"historical.input")
        )),
        NeuronOperationStatusV2::NotRecorded
    );

    checked(controller.shutdown());
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Stopped
    );
}

#[test]
fn controller_rejects_generation_regression_and_exposes_stable_control_codes() {
    let (first, _) = handle(2);
    let controller = checked(AgentdNeuronGenerationControllerV2::new(first));
    checked(controller.start());
    checked(controller.begin_quiesce());
    checked(controller.seal());
    let (regressed, _) = handle(1);
    let error = controller.reload(regressed).expect_err("generation regression");
    assert_eq!(error.stable_code(), "generation_conflict");
    assert_eq!(
        AgentdNeuronControlErrorV2::OwnerBusy.stable_code(),
        "owner_busy"
    );
    assert_eq!(
        AgentdNeuronControlErrorV2::OwnerPoisoned.stable_code(),
        "owner_poisoned"
    );
}

fn test_input() -> NeuronTickInputV1 {
    let features = vec![1, 2, 3];
    NeuronTickInputV1 {
        tick_id: id("control.recovery.tick"),
        subject_id: id("control.recovery.subject"),
        logical_sequence: 1,
        monotonic_time_micros: 1,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: codex_hepta_neuron::canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: Digest32::of_bytes(b"control.recovery.objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"control.recovery.ndu"),
        body_generation: Some(1),
        modulator_digest: None,
    }
}
