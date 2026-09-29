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
    preserve_recoveries: AtomicU64,
    close_recoveries: AtomicU64,
    stale_rejections: AtomicU64,
}

impl ProductNeuronOwnerV2 for LifecycleStubOwner {
    fn execute(
        &self,
        _input: NeuronTickInputV1,
        _guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        Err(NeuronRuntimeV2Error::PendingOperation)
    }

    fn recover_operation_control_with_policy(
        &self,
        _input: &NeuronTickInputV1,
        policy: AgentdNeuronRecoveryPolicyV2,
    ) -> Result<NeuronOperationStatusV2, AgentdNeuronControlErrorV2> {
        self.recoveries.fetch_add(1, Ordering::SeqCst);
        if policy == AgentdNeuronRecoveryPolicyV2::CloseUnexecuted {
            self.close_recoveries.fetch_add(1, Ordering::SeqCst);
            Ok(NeuronOperationStatusV2::Failed(
                NeuronOperationFailureV2::AdmissionDenied,
            ))
        } else {
            self.preserve_recoveries.fetch_add(1, Ordering::SeqCst);
            Ok(NeuronOperationStatusV2::NotExecuted)
        }
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

    fn record_stale_invocation_rejection(&self) {
        self.stale_rejections.fetch_add(1, Ordering::SeqCst);
    }
}

fn handle(generation: u64) -> (AgentdNeuronHandleV2, Arc<LifecycleStubOwner>) {
    let owner = Arc::new(LifecycleStubOwner {
        generation,
        reconciles: AtomicU64::new(0),
        recoveries: AtomicU64::new(0),
        preserve_recoveries: AtomicU64::new(0),
        close_recoveries: AtomicU64::new(0),
        stale_rejections: AtomicU64::new(0),
    });
    (
        AgentdNeuronHandleV2 {
            owner: owner.clone(),
            config_digest: Digest32::of_bytes(
                format!("config-generation-{generation}").as_bytes(),
            ),
            lifecycle_gate: Arc::new(AgentdNeuronExecutionGateV2::standalone()),
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
    let input = test_input(1);
    let report = checked(controller.recover_operation(&input));
    assert!(report.terminal);
    assert_eq!(report.failure_code.as_deref(), Some("admission_denied"));
    assert_eq!(first_owner.recoveries.load(Ordering::SeqCst), 1);
    assert_eq!(first_owner.close_recoveries.load(Ordering::SeqCst), 1);
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
fn serving_recovery_preserves_unexecuted_work_and_quiesce_closes_it() {
    let (active, owner) = handle(1);
    let controller = checked(AgentdNeuronGenerationControllerV2::new(active));
    checked(controller.start());
    let input = test_input(1);

    let serving = checked(controller.recover_operation(&input));
    assert_eq!(serving.status_code, "reserved_not_executed");
    assert!(!serving.terminal);
    assert!(serving.requires_reconciliation);
    assert_eq!(owner.preserve_recoveries.load(Ordering::SeqCst), 1);
    assert_eq!(owner.close_recoveries.load(Ordering::SeqCst), 0);

    checked(controller.begin_quiesce());
    let quiescing = checked(controller.recover_operation(&input));
    assert_eq!(quiescing.failure_code.as_deref(), Some("admission_denied"));
    assert!(quiescing.terminal);
    assert_eq!(owner.close_recoveries.load(Ordering::SeqCst), 1);
}

#[test]
fn prepared_invocation_is_invalidated_when_quiesce_begins() {
    let (active, owner) = handle(1);
    let active_clone = active.clone();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(active));
    checked(controller.start());
    let input = test_input(1);
    let body_digest = active_clone.body_bundle_digest().expect("body digest");
    let invocation = checked(controller.prepare(
        input.tick_id.clone(),
        body_digest,
        input.clone(),
    ));

    checked(controller.begin_quiesce());
    assert!(matches!(
        invocation.enter_lifecycle_gate(),
        Err(NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Revoked))
    ));
    assert!(matches!(
        active_clone.prepare(input.tick_id.clone(), body_digest, input),
        Err(NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Revoked))
    ));
    assert_eq!(owner.stale_rejections.load(Ordering::SeqCst), 2);
}

#[test]
fn seal_waits_for_every_invocation_admitted_by_the_previous_epoch() {
    let (active, _) = handle(1);
    let active_clone = active.clone();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(active));
    checked(controller.start());
    let input = test_input(1);
    let invocation = checked(controller.prepare(
        input.tick_id.clone(),
        active_clone.body_bundle_digest().expect("body digest"),
        input,
    ));
    let in_flight = checked(invocation.enter_lifecycle_gate());

    checked(controller.begin_quiesce());
    let error = controller.seal().expect_err("in-flight invocation must block seal");
    assert_eq!(error.stable_code(), "controller_busy");
    drop(in_flight);
    checked(controller.seal());
    assert_eq!(
        checked(controller.state()),
        AgentdNeuronLifecycleStateV2::Sealed
    );
}

#[test]
fn reload_keeps_retained_clones_closed_and_opens_only_the_successor() {
    let (first, first_owner) = handle(1);
    let first_clone = first.clone();
    let controller = checked(AgentdNeuronGenerationControllerV2::new(first));
    checked(controller.start());
    checked(controller.begin_quiesce());
    checked(controller.seal());

    let (second, _) = handle(2);
    let second_clone = second.clone();
    checked(controller.reload(second));
    let first_input = test_input(1);
    assert!(matches!(
        first_clone.prepare(
            first_input.tick_id.clone(),
            first_clone.body_bundle_digest().expect("old body digest"),
            first_input,
        ),
        Err(NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Revoked))
    ));
    assert_eq!(first_owner.stale_rejections.load(Ordering::SeqCst), 1);

    let second_input = test_input(2);
    checked(second_clone.prepare(
        second_input.tick_id.clone(),
        second_clone.body_bundle_digest().expect("new body digest"),
        second_input,
    ));
    let snapshot = checked(controller.controller_snapshot());
    assert!(snapshot.accepting_new_work);
    assert_eq!(snapshot.active_generation, 2);
    assert_eq!(snapshot.retained_generations, vec![1]);
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

#[test]
fn controller_rehydrates_retained_generations_and_reports_topology() {
    let (active, active_owner) = handle(3);
    let (retained_one, retained_one_owner) = handle(1);
    let retained_one_clone = retained_one.clone();
    let (retained_two, retained_two_owner) = handle(2);
    let controller = checked(
        AgentdNeuronGenerationControllerV2::from_recovered_generations(
            active,
            [retained_two, retained_one],
        ),
    );

    assert_eq!(checked(controller.retained_generations()), vec![1, 2]);
    checked(controller.start());
    assert_eq!(active_owner.reconciles.load(Ordering::SeqCst), 1);
    assert_eq!(retained_one_owner.reconciles.load(Ordering::SeqCst), 1);
    assert_eq!(retained_two_owner.reconciles.load(Ordering::SeqCst), 1);

    assert_eq!(
        checked(controller.query_operation(
            1,
            &id("recovered.historical.tick"),
            Digest32::of_bytes(b"recovered.historical.input")
        )),
        NeuronOperationStatusV2::NotRecorded
    );
    let retained_input = test_input(1);
    assert!(matches!(
        retained_one_clone.prepare(
            retained_input.tick_id.clone(),
            retained_one_clone
                .body_bundle_digest()
                .expect("retained body digest"),
            retained_input,
        ),
        Err(NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Revoked))
    ));

    let snapshot = checked(controller.controller_snapshot());
    assert_eq!(snapshot.lifecycle, AgentdNeuronLifecycleStateV2::Serving);
    assert_eq!(snapshot.active_generation, 3);
    assert_eq!(snapshot.retained_generations, vec![1, 2]);
    assert!(snapshot.accepting_new_work);
    assert!(snapshot.execution_epoch > 0);
    assert_eq!(snapshot.active.generation, Some(3));
}

#[test]
fn controller_rejects_invalid_recovered_generation_sets_without_fencing_inputs() {
    let (active, _) = handle(3);
    let active_clone = active.clone();
    let (duplicate_one, _) = handle(1);
    let (duplicate_two, _) = handle(1);
    let error = match AgentdNeuronGenerationControllerV2::from_recovered_generations(
        active,
        [duplicate_one, duplicate_two],
    ) {
        Ok(_) => panic!("duplicate retained generation was accepted"),
        Err(error) => error,
    };
    assert_eq!(error.stable_code(), "generation_conflict");
    let input = test_input(3);
    checked(active_clone.prepare(
        input.tick_id.clone(),
        active_clone.body_bundle_digest().expect("active body digest"),
        input,
    ));

    let (active, _) = handle(2);
    let (not_historical, _) = handle(2);
    let error = match AgentdNeuronGenerationControllerV2::from_recovered_generations(
        active,
        [not_historical],
    ) {
        Ok(_) => panic!("non-historical retained generation was accepted"),
        Err(error) => error,
    };
    assert_eq!(error.stable_code(), "generation_conflict");
}

fn test_input(generation: u64) -> NeuronTickInputV1 {
    let features = vec![1, 2, 3];
    NeuronTickInputV1 {
        tick_id: id(&format!("control.recovery.tick.{generation}")),
        subject_id: id("control.recovery.subject"),
        logical_sequence: 1,
        monotonic_time_micros: 1,
        checkpoint_digest: Digest32::ZERO,
        input_feature_digest: codex_hepta_neuron::canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: Digest32::of_bytes(b"control.recovery.objective"),
        ndu_snapshot_digest: Digest32::of_bytes(b"control.recovery.ndu"),
        body_generation: Some(generation),
        modulator_digest: None,
    }
}
