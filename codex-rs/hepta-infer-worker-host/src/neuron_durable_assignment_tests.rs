use super::*;

use std::io::Write;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;

use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::InferenceRequest;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::durable_control::Reservation;
use codex_hepta_infer_core::durable_control::TerminalObservation;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::ModelManifest;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronPreopenedWeightModelDriver;
use crate::model_worker::ResourceGrant;

struct FixtureDriver {
    _calls: Arc<AtomicUsize>,
    observed_tokens: u32,
}

impl ModelDriver for FixtureDriver {
    fn load(&mut self, _: &ModelManifest) -> Result<DriverModelHandle, WorkerError> {
        Ok(DriverModelHandle {
            opaque_id: "frozen-model-handle".to_owned(),
            observed_memory_bytes: 4096,
        })
    }

    fn run(
        &mut self,
        _: &DriverModelHandle,
        _: &WorkerRequest,
    ) -> Result<DriverRunObservation, WorkerError> {
        Err(WorkerError::MissingTerminalOutput)
    }

    fn unload(&mut self, _: DriverModelHandle) -> Result<(), WorkerError> {
        Ok(())
    }
}

impl NeuronFeatureDriver for FixtureDriver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, WorkerError> {
        self._calls
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            consumed_tokens: self.observed_tokens,
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: vec![1 << 24; request.expected_output_width],
            prediction_q24: vec![0; request.expected_output_width],
            observed_memory_bytes: 4096,
            transient_allocation_bytes: 256,
            queue_age_micros: 3,
            latency_micros: 10,
        })
    }
}

impl NeuronPreopenedWeightModelDriver for FixtureDriver {
    fn load_from_preopened_weight_file(
        &mut self,
        manifest: &ModelManifest,
        mut weights: std::fs::File,
    ) -> Result<DriverModelHandle, WorkerError> {
        // The fixture driver really reads the SAME File moved by the Worker.
        // It is not a physical Laya decoder or a production-attested loader.
        let hash = Digest32::of_reader(&mut weights, 2 * 1024 * 1024 * 1024)
            .map_err(|error| WorkerError::DriverFailure(error.to_string()))?;
        if hash.to_string() != manifest.weights_digest {
            return Err(WorkerError::ModelMismatch);
        }
        self.load(manifest)
    }
}

fn typed_request() -> NeuronFeatureRequestV1 {
    NeuronFeatureRequestV1 {
        request_id: StableId::new("tick.1").unwrap(),
        generation: Generation::new(3).unwrap(),
        model_id: StableId::new("model.1").unwrap(),
        encoder_digest: "a".repeat(64).parse().unwrap(),
        head_digest: "b".repeat(64).parse().unwrap(),
        weights_digest: "3".repeat(64).parse().unwrap(),
        input_digest: "c".repeat(64).parse().unwrap(),
        feature_vector_q24: vec![1 << 22, -(1 << 21)],
        expected_output_width: 5,
    }
}

fn worker() -> InferenceWorker<FixtureDriver> {
    worker_with_calls(Arc::new(AtomicUsize::new(0)))
}

fn worker_with_calls(calls: Arc<AtomicUsize>) -> InferenceWorker<FixtureDriver> {
    worker_with_calls_and_tokens(calls, 4)
}

fn worker_with_calls_and_tokens(
    calls: Arc<AtomicUsize>,
    observed_tokens: u32,
) -> InferenceWorker<FixtureDriver> {
    let mut value = InferenceWorker::new(
        100,
        "worker.1".to_owned(),
        3,
        ResourceGrant {
            grant_id: "grant.1".to_owned(),
            authority_epoch: 2,
            generation: 3,
            expires_at_ms: 10_000,
            revoked: false,
            maximum_models: 2,
            maximum_active_requests: 4,
            maximum_memory_bytes: 8192,
            semantic_digest: "1".repeat(64),
        },
        FixtureDriver {
            _calls: calls,
            observed_tokens,
        },
    )
    .unwrap();
    value
        .load_model(
            100,
            ModelManifest {
                model_id: "model.1".to_owned(),
                model_digest: "2".repeat(64),
                weights_digest: "3".repeat(64),
                tokenizer_digest: "4".repeat(64),
                preprocessor_digest: "5".repeat(64),
                quantization_digest: "6".repeat(64),
                runtime_digest: "7".repeat(64),
                device_digest: "8".repeat(64),
                maximum_tokens: 128,
            },
        )
        .unwrap();
    value
}

fn control(
    directory: &tempfile::TempDir,
    request: &NeuronFeatureRequestV1,
) -> DurableInferenceControl {
    control_with_semantic(directory, request, None)
}

fn control_with_semantic(
    directory: &tempfile::TempDir,
    request: &NeuronFeatureRequestV1,
    override_semantic_digest: Option<String>,
) -> DurableInferenceControl {
    control_with_overrides(directory, request, override_semantic_digest, None)
}

fn control_with_overrides(
    directory: &tempfile::TempDir,
    request: &NeuronFeatureRequestV1,
    override_semantic_digest: Option<String>,
    override_payload_digest: Option<String>,
) -> DurableInferenceControl {
    // Only explicitly malformed contract fixtures can be admitted to this
    // legacy WAL with a fallback digest; valid Neuron requests are always
    // bound to the complete canonical NeuronFeatureRequestV1 identity.
    let semantic_digest = override_semantic_digest.unwrap_or_else(|| {
        neuron_feature_request_digest_v1(request)
            .map_or_else(|_| "d".repeat(64), |value| value.to_string())
    });
    let mut feature = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: request.request_id.to_string(),
            reservation_id: "reservation.1".to_owned(),
            model_digest: "2".repeat(64),
            payload_digest: "e".repeat(64),
            maximum_tokens: 64,
            deadline_ms: 9_000,
            lease_payload_digest: "e".repeat(64),
            reservation_model_digest: "2".repeat(64),
            reservation_maximum_tokens: 64,
            cancelled: false,
        },
        encoder_digest: request.encoder_digest.to_string(),
        head_digest: request.head_digest.to_string(),
        weights_digest: request.weights_digest.to_string(),
        input_digest: request.input_digest.to_string(),
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    };
    let payload = override_payload_digest
        .unwrap_or_else(|| canonical_neuron_feature_payload_digest(&feature));
    feature.authorization.payload_digest = payload.clone();
    feature.authorization.lease_payload_digest = payload.clone();

    let mut owner =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    owner
        .submit(
            100,
            InferenceRequest {
                request_id: request.request_id.to_string(),
                principal_id: "principal.1".to_owned(),
                model_digest: "2".repeat(64),
                payload_digest: payload,
                maximum_tokens: 64,
                deadline_ms: 9_000,
                semantic_digest,
            },
        )
        .unwrap();
    owner
        .reserve(
            100,
            request.request_id.as_str(),
            1,
            Reservation {
                reservation_id: "reservation.1".to_owned(),
                quota_units: 100,
                maximum_tokens: 64,
                authority_epoch: 4,
                valid_until_ms: 8_000,
            },
        )
        .unwrap();
    owner
        .assign(
            request.request_id.as_str(),
            2,
            Assignment {
                worker_id: "worker.1".to_owned(),
                worker_generation: 3,
                assignment_digest: "f".repeat(64),
            },
        )
        .unwrap();
    owner
}

#[test]
fn assigned_durable_owner_and_loaded_worker_match_exact_neuron_features() {
    let temporary = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let durable = control(&temporary, &typed);
    let worker = worker();
    let diag = read_neuron_durable_assignment_v1(&durable, &worker, &typed, 100).unwrap();
    assert!(diag.validate_integrity());
    assert_eq!(diag.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(diag.control_revision, 3);
    assert_eq!(diag.worker_generation, worker.worker_generation());
    assert_eq!(
        diag.payload_digest.to_string(),
        durable.get("tick.1").unwrap().request.payload_digest
    );
    let mut forged = diag.clone();
    forged.control_revision += 1;
    assert!(!forged.validate_integrity());
    drop(durable);
    let recovered =
        DurableInferenceControl::open(temporary.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&recovered, &worker, &typed, 100).unwrap(),
        diag
    );
}

#[test]
fn forged_semantic_digest_cannot_claim_dispatch_even_if_payload_and_worker_match() {
    let directory = tempfile::tempdir().unwrap();
    let typed = typed_request();
    // The WAL accepts a generic well-formed legacy semantic digest, but
    // the strict Neuron gateway must reject it as a different request.
    let mut owner = control_with_semantic(&directory, &typed, Some("d".repeat(64)));
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker_with_calls(calls.clone());
    assert_eq!(
        read_neuron_durable_assignment_v1(&owner, &worker, &typed, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &typed, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    ));
    let record = owner.get(typed.request_id.as_str()).unwrap();
    assert_eq!(record.revision, 3);
    assert_eq!(record.state, RequestState::Assigned);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    drop(owner);

    // An ordinary close/reopen cannot turn the forged semantic identity
    // into a usable Worker admission or a fresh Dispatching claim.
    let mut reopened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&reopened, &worker, &typed, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut reopened, &mut worker, &typed, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    ));
    assert_eq!(reopened.get(typed.request_id.as_str()).unwrap().revision, 3);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
}

#[test]
fn missing_reserved_cancelling_expired_and_drifted_requests_are_rejected() {
    let temporary = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let worker = worker();
    let mut durable = control(&temporary, &typed);
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &typed, 8_000),
        Err(NeuronDurableAssignmentErrorV1::Expired)
    );
    let mut forged = typed.clone();
    forged.feature_vector_q24[0] += 1;
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &forged, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    let mut wrong_model = typed.clone();
    wrong_model.weights_digest = "4".repeat(64).parse().unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &wrong_model, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &typed, 100)
            .unwrap()
            .control_revision,
        3
    );

    // Even a durable journal entry with a matching canonical payload digest
    // cannot admit Neuron features outside the typed Q24 contract.
    let another = tempfile::tempdir().unwrap();
    let mut outside = typed_request();
    outside.feature_vector_q24[0] = 9 * (1_i64 << 24);
    let invalid_owner = control(&another, &outside);
    assert_eq!(
        read_neuron_durable_assignment_v1(&invalid_owner, &worker, &outside, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    durable.cancel("tick.1", 3).unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&durable, &worker, &typed, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    );
}

#[test]
fn owner_freshness_rejects_self_rehashed_stale_assignment_and_cancellation() {
    let directory = tempfile::tempdir().unwrap();
    let request = typed_request();
    let worker = worker();
    let mut owner = control(&directory, &request);
    let initial = read_neuron_durable_assignment_v1(&owner, &worker, &request, 100).unwrap();
    assert_eq!(
        revalidate_neuron_durable_assignment_v1(&owner, &worker, &request, &initial, 100),
        Ok(())
    );
    // A caller can rehash a forged prior report, but cannot alter what the
    // current Ledger + Worker owners actually observed.
    let mut changed = initial.clone();
    changed.control_revision += 1;
    changed.diagnostic_digest = changed.computed_digest();
    assert!(changed.validate_integrity());
    assert_eq!(
        revalidate_neuron_durable_assignment_v1(&owner, &worker, &request, &changed, 100),
        Err(NeuronDurableAssignmentErrorV1::Stale)
    );
    let mut changed = initial.clone();
    changed.diagnostic_digest = Digest32::ZERO;
    assert_eq!(
        revalidate_neuron_durable_assignment_v1(&owner, &worker, &request, &changed, 100),
        Err(NeuronDurableAssignmentErrorV1::Stale)
    );
    assert_eq!(
        revalidate_neuron_durable_assignment_v1(&owner, &worker, &request, &initial, 8000),
        Err(NeuronDurableAssignmentErrorV1::Expired)
    );
    owner.cancel(request.request_id.as_str(), 3).unwrap();
    assert_eq!(
        revalidate_neuron_durable_assignment_v1(&owner, &worker, &request, &initial, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    );
}

#[test]
fn assigned_durable_owner_must_not_report_a_consumed_worker_attempt_as_unused() {
    let directory = tempfile::tempdir().unwrap();
    let request = typed_request();
    let owner = control(&directory, &request);
    let mut worker = worker();
    let initial = read_neuron_durable_assignment_v1(&owner, &worker, &request, 100).unwrap();
    let used = WorkerRequest {
        request_id: request.request_id.to_string(),
        reservation_id: initial.reservation_id.clone(),
        model_digest: "2".repeat(64),
        payload_digest: initial.payload_digest.to_string(),
        maximum_tokens: 64,
        deadline_ms: 9000,
        lease_payload_digest: initial.payload_digest.to_string(),
        reservation_model_digest: "2".repeat(64),
        reservation_maximum_tokens: 64,
        cancelled: false,
    };
    // This is the same Worker method that every Neuron ModelPort consumes
    // before any potential backend execution. The durable record remains
    // Assigned until its independent owner observes the terminal result.
    worker.consume_neuron_attempt(&used).unwrap();
    assert_eq!(
        read_neuron_durable_assignment_v1(&owner, &worker, &request, 100),
        Err(NeuronDurableAssignmentErrorV1::Worker(
            WorkerError::NeuronReservationReplay
        ))
    );
    assert_eq!(
        revalidate_neuron_durable_assignment_v1(&owner, &worker, &request, &initial, 100),
        Err(NeuronDurableAssignmentErrorV1::Worker(
            WorkerError::NeuronReservationReplay
        ))
    );
}

#[test]
fn fsynced_dispatch_precedes_real_worker_model_port_and_survives_crash_restart() {
    let directory = tempfile::tempdir().unwrap();
    let request = typed_request();
    let mut control = control(&directory, &request);
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker_with_calls(calls.clone());
    let (claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut control, &mut worker, &request, 100).unwrap();
    assert_eq!(claim.revision, 4);
    assert_eq!(claim.state, RequestState::Dispatching);
    assert!(!claim.idempotent);
    assert_eq!(
        control.get("tick.1").unwrap().state,
        RequestState::Dispatching
    );
    let result = port.execute_feature(&request).unwrap();
    assert_eq!(
        result.status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded
    );
    drop(port);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    drop(control);

    // The in-memory Worker tombstone set disappears on process death. The
    // pre-call fsynced Dispatching event must still block any replay.
    let mut recovered =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        recovered.get("tick.1").unwrap().state,
        RequestState::Dispatching
    );
    let mut restarted_worker = worker_with_calls(calls.clone());
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut recovered, &mut restarted_worker, &request, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    ));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    let observation = TerminalObservation {
        request_id: "tick.1".to_owned(),
        reservation_id: "reservation.1".to_owned(),
        worker_id: "worker.1".to_owned(),
        worker_generation: 3,
        model_digest: "2".repeat(64),
        payload_digest: recovered
            .get("tick.1")
            .unwrap()
            .request
            .payload_digest
            .clone(),
        terminal_observed: true,
        terminal_status: Some(RequestState::Completed),
        output_digest: Some(result.receipt_digest.to_string()),
        consumed_tokens: 0,
        usage_units: 0,
    };
    let terminal = recovered
        .settle("tick.1", 4, "9".repeat(64), observation)
        .unwrap();
    assert_eq!(terminal.state, RequestState::Completed);
    drop(recovered);
    let opened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(opened.get("tick.1").unwrap().state, RequestState::Completed);
}

#[test]
fn durable_claim_rejects_replayed_or_expired_worker_admission_without_dispatch() {
    let directory = tempfile::tempdir().unwrap();
    let request = typed_request();
    let mut control = control(&directory, &request);
    let mut worker = worker();

    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut control, &mut worker, &request, 8_000),
        Err(NeuronDurableAssignmentErrorV1::Expired)
    ));
    assert_eq!(control.get("tick.1").unwrap().state, RequestState::Assigned);
    let (claim, port) =
        claim_neuron_durable_dispatch_v1(&mut control, &mut worker, &request, 100).unwrap();
    assert_eq!(claim.state, RequestState::Dispatching);
    drop(port);
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut control, &mut worker, &request, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    ));
    assert_eq!(control.get("tick.1").unwrap().revision, 4);
}

#[test]
fn abandoned_fsynced_neuron_dispatch_is_not_replayable_after_crash() {
    let directory = tempfile::tempdir().unwrap();
    let request = typed_request();
    let mut owner = control(&directory, &request);
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker_with_calls(calls.clone());

    // Crash after durable ownership moved to Dispatching, but BEFORE the
    // driver is invoked: even a new Worker has no permission to guess.
    let (claim, port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &request, 100).unwrap();
    assert_eq!(claim.state, RequestState::Dispatching);
    assert!(port.reservation_unconsumed());
    drop(port);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    drop(worker);
    drop(owner);

    let mut recovered =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    let mut fresh_worker = worker_with_calls(calls.clone());
    assert_eq!(
        recovered.get(request.request_id.as_str()).unwrap().state,
        RequestState::Dispatching
    );
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut recovered, &mut fresh_worker, &request, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    ));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
}

#[test]
fn fsynced_neuron_token_overrun_is_indeterminate_and_not_replayable_after_crash() {
    let directory = tempfile::tempdir().unwrap();
    let request = typed_request();
    let mut owner = control(&directory, &request);
    let calls = Arc::new(AtomicUsize::new(0));
    // Pre-driver both the durable reservation and the loaded manifest allow
    // this request (64 tokens); the backend actually reports consuming 65.
    let mut worker = worker_with_calls_and_tokens(calls.clone(), 65);
    let (claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &request, 100).unwrap();
    assert_eq!(claim.state, RequestState::Dispatching);
    assert_eq!(claim.revision, 4);
    assert_eq!(
        port.execute_feature(&request),
        Err(NeuronModelError::Indeterminate),
        "physical overrun is an unknown outcome, never a successful model receipt"
    );
    assert!(!port.reservation_unconsumed());
    drop(port);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert!(
        worker.is_quarantined(),
        "post-dispatch token overrun must quarantine backend"
    );
    assert_eq!(
        owner.get(request.request_id.as_str()).unwrap().state,
        RequestState::Dispatching
    );
    drop(worker);
    drop(owner);

    // A restart loses in-memory Worker tombstones, but not the fsynced
    // Dispatching record. It cannot double-execute the same reservation.
    let mut reopened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        reopened.get(request.request_id.as_str()).unwrap().state,
        RequestState::Dispatching
    );
    let mut fresh_worker = worker_with_calls(calls.clone());
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut reopened, &mut fresh_worker, &request, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    ));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    // Only a separate authenticated terminal/recovery owner can settle this
    // uncertain execution. No local retry or arbitrary success is issued.
}

#[test]
fn model_generation_is_not_worker_process_generation_after_restart() {
    let directory = tempfile::tempdir().unwrap();
    let mut request = typed_request();
    // Neuron/Cell generation is retained when its serving Worker restarts.
    // The independently assigned Worker process remains generation 3 here.
    request.generation = Generation::new(7).unwrap();
    let mut owner = control(&directory, &request);
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker_with_calls(Arc::clone(&calls));
    assert_ne!(worker.worker_generation(), request.generation.get());
    let source = read_neuron_durable_assignment_v1(&owner, &worker, &request, 100).unwrap();
    assert_eq!(source.worker_generation, worker.worker_generation());
    let mut forged = request.clone();
    forged.generation = Generation::new(8).unwrap();
    // The typed semantic digest is fsynced by inference.control; changing the
    // Neuron generation under the same assigned reservation fails PRE-driver.
    assert_eq!(
        read_neuron_durable_assignment_v1(&owner, &worker, &forged, 100),
        Err(NeuronDurableAssignmentErrorV1::Mismatch)
    );
    let (claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &request, 100).unwrap();
    assert_eq!(claim.state, RequestState::Dispatching);
    assert_eq!(claim.revision, 4);
    let receipt = port.execute_feature(&request).unwrap();
    assert_eq!(
        receipt.status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded
    );
    assert_eq!(
        receipt.request_digest,
        neuron_feature_request_digest_v1(&request).unwrap()
    );
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    drop(port);
    drop(owner);
    let mut recovered =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    let mut restarted_worker = worker_with_calls(Arc::clone(&calls));
    // Reopening the WAL and recreating a Worker cannot reissue that claim,
    // irrespective of the independent model and process generation numbers.
    assert!(matches!(
        claim_neuron_durable_dispatch_v1(&mut recovered, &mut restarted_worker, &request, 100),
        Err(NeuronDurableAssignmentErrorV1::NotAssigned)
    ));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
}

fn load_test_file_bound_model(
    worker: &mut InferenceWorker<FixtureDriver>,
    bytes: &[u8],
) -> NeuronFileBoundModelLoadV1 {
    let mut file = tempfile::tempfile().unwrap();
    file.write_all(bytes).unwrap();
    worker
        .load_model_from_preopened_weight_file_v1(
            100,
            ModelManifest {
                model_id: "model.1".to_owned(),
                model_digest: "2".repeat(64),
                weights_digest: Digest32::of_bytes(bytes).to_string(),
                tokenizer_digest: "4".repeat(64),
                preprocessor_digest: "5".repeat(64),
                quantization_digest: "6".repeat(64),
                runtime_digest: "7".repeat(64),
                device_digest: "8".repeat(64),
                maximum_tokens: 128,
            },
            file,
        )
        .unwrap()
}

#[test]
fn file_bound_durable_claim_rejects_retired_load_and_executes_one_live_identity() {
    let directory = tempfile::tempdir().unwrap();
    let bytes = vec![0x5e_u8; 4_096];
    let mut request = typed_request();
    request.weights_digest = Digest32::of_bytes(&bytes);
    let mut owner = control(&directory, &request);
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker_with_calls(Arc::clone(&calls));
    // Retire the existing legacy fixture load before taking a REAL preopened
    // File through the strict digest/Driver path.
    worker.unload_model(100, "model.1").unwrap();
    let first = load_test_file_bound_model(&mut worker, &bytes);
    assert!(first.validate_integrity());
    assert!(first.load_revision() > 0);
    assert_eq!(first.loaded_weights_digest(), request.weights_digest);

    // Retiring and reloading the SAME weights with the SAME model and opaque
    // handle must invalidate the first load ticket before any WAL mutation.
    worker.unload_model(100, "model.1").unwrap();
    let second = load_test_file_bound_model(&mut worker, &bytes);
    assert_ne!(first.load_revision(), second.load_revision());
    assert!(matches!(
        claim_neuron_file_bound_durable_dispatch_v1(&mut owner, &mut worker, &request, &first, 100),
        Err(NeuronFileBoundDispatchErrorV1::Load(
            NeuronWeightFileDiagnosticErrorV1::StaleLoad
        ))
    ));
    assert_eq!(owner.get("tick.1").unwrap().state, RequestState::Assigned);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);

    let mut wrong_weights = request.clone();
    wrong_weights.weights_digest = Digest32::of_bytes(b"wrong-cell-weights");
    assert!(matches!(
        claim_neuron_file_bound_durable_dispatch_v1(
            &mut owner,
            &mut worker,
            &wrong_weights,
            &second,
            100
        ),
        Err(NeuronFileBoundDispatchErrorV1::LoadIdentityMismatch)
    ));
    assert_eq!(owner.get("tick.1").unwrap().state, RequestState::Assigned);

    let (claim, mut port) = claim_neuron_file_bound_durable_dispatch_v1(
        &mut owner,
        &mut worker,
        &request,
        &second,
        100,
    )
    .unwrap();
    assert_eq!(claim.state, RequestState::Dispatching);
    assert_eq!(claim.revision, 4);
    let result = port.execute_feature(&request).unwrap();
    assert_eq!(
        result.status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded
    );
    drop(port);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    // Even the CURRENT file-load ticket cannot authorize a second use of a
    // durable request whose physical dispatch was already claimed.
    assert!(matches!(
        claim_neuron_file_bound_durable_dispatch_v1(
            &mut owner,
            &mut worker,
            &request,
            &second,
            100
        ),
        Err(NeuronFileBoundDispatchErrorV1::Durable(
            NeuronDurableAssignmentErrorV1::NotAssigned
        ))
    ));
    drop(owner);
    let reopened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        reopened.get("tick.1").unwrap().state,
        RequestState::Dispatching
    );
}

#[test]
fn file_bound_claim_checks_worker_resource_expiry_before_fsync() {
    let directory = tempfile::tempdir().unwrap();
    let bytes = vec![0x36_u8; 1_024];
    let mut request = typed_request();
    request.weights_digest = Digest32::of_bytes(&bytes);
    let mut owner = control(&directory, &request);
    let mut worker = worker();
    worker.unload_model(100, "model.1").unwrap();
    let ticket = load_test_file_bound_model(&mut worker, &bytes);
    // At the worker's expiration the source is no longer current. The old
    // reservation is NOT spent; a new independent owner may decide its fate.
    assert!(matches!(
        claim_neuron_file_bound_durable_dispatch_v1(
            &mut owner,
            &mut worker,
            &request,
            &ticket,
            10_000,
        ),
        Err(NeuronFileBoundDispatchErrorV1::Load(
            NeuronWeightFileDiagnosticErrorV1::Worker(WorkerError::GrantExpired)
        ))
    ));
    assert_eq!(owner.get("tick.1").unwrap().state, RequestState::Assigned);
}

#[test]
fn file_bound_dispatch_refuses_old_worker_instance_before_durable_claim() {
    let directory = tempfile::tempdir().unwrap();
    let bytes = vec![0x59_u8; 2_048];
    let mut request = typed_request();
    request.weights_digest = Digest32::of_bytes(&bytes);
    let mut owner = control(&directory, &request);
    let calls = Arc::new(AtomicUsize::new(0));

    let mut original_worker = worker_with_calls(Arc::clone(&calls));
    original_worker.unload_model(100, "model.1").unwrap();
    let original = load_test_file_bound_model(&mut original_worker, &bytes);
    drop(original_worker);

    // A process restart may reuse the external Worker/model/handle identity
    // and the same load ordinal. Only the new instance's own ticket can
    // spend the existing fsynced Assigned reservation.
    let mut restarted = worker_with_calls(Arc::clone(&calls));
    restarted.unload_model(100, "model.1").unwrap();
    let fresh = load_test_file_bound_model(&mut restarted, &bytes);
    assert_eq!(original.load_revision(), fresh.load_revision());
    assert_eq!(original.model_load(), fresh.model_load());
    assert!(matches!(
        claim_neuron_file_bound_durable_dispatch_v1(
            &mut owner,
            &mut restarted,
            &request,
            &original,
            100,
        ),
        Err(NeuronFileBoundDispatchErrorV1::Load(
            NeuronWeightFileDiagnosticErrorV1::StaleLoad
        ))
    ));
    assert_eq!(owner.get("tick.1").unwrap().revision, 3);
    assert_eq!(owner.get("tick.1").unwrap().state, RequestState::Assigned);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);

    let (committed, mut port) = claim_neuron_file_bound_durable_dispatch_v1(
        &mut owner,
        &mut restarted,
        &request,
        &fresh,
        100,
    )
    .unwrap();
    assert_eq!(committed.state, RequestState::Dispatching);
    assert_eq!(
        port.execute_feature(&request).unwrap().status,
        codex_hepta_infer_core::NeuronFeatureTerminalStatusV1::Succeeded
    );
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
}

#[test]
fn observed_token_cost_binds_fsynced_dispatch_and_exact_worker_incarnation() {
    let directory = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let mut owner = control(&directory, &typed);
    let calls = Arc::new(AtomicUsize::new(0));
    let mut worker = worker_with_calls(Arc::clone(&calls));
    let (claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &typed, 100).unwrap();
    assert_eq!(claim.state, RequestState::Dispatching);
    let receipt = port.execute_feature(&typed).unwrap();
    let cost = port
        .take_cost_diagnostic()
        .expect("physically observed cost");
    assert!(port.take_cost_diagnostic().is_none());
    drop(port);
    let observed =
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &receipt, &cost, 100).unwrap();
    assert!(observed.validate_integrity());
    assert_eq!(observed.observed_tokens, 4);
    assert_eq!(observed.control_revision, claim.revision);
    assert_eq!(observed.feature_receipt_digest, receipt.receipt_digest);
    assert_eq!(observed.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    revalidate_neuron_observed_cost_source_v1(
        &owner, &worker, &typed, &receipt, &cost, &observed, 100,
    )
    .unwrap();

    // A new Worker may reuse every printable worker ID and generation.
    // Its distinct in-memory incarnation must NEVER validate old metering.
    let restarted_worker = worker();
    assert_eq!(worker.worker_id(), restarted_worker.worker_id());
    assert_eq!(
        worker.worker_generation(),
        restarted_worker.worker_generation()
    );
    assert_eq!(
        read_neuron_observed_cost_source_v1(
            &owner,
            &restarted_worker,
            &typed,
            &receipt,
            &cost,
            100,
        ),
        Err(NeuronObservedCostSourceErrorV1::Binding)
    );
    let mut altered_request = typed.clone();
    altered_request.weights_digest = Digest32::of_bytes(b"different-weight");
    assert_eq!(
        read_neuron_observed_cost_source_v1(
            &owner,
            &worker,
            &altered_request,
            &receipt,
            &cost,
            100,
        ),
        Err(NeuronObservedCostSourceErrorV1::Binding)
    );
    let mut altered_receipt = receipt.clone();
    altered_receipt.receipt_digest = Digest32::of_bytes(b"forged-receipt");
    assert_eq!(
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &altered_receipt, &cost, 100,),
        Err(NeuronObservedCostSourceErrorV1::Binding)
    );

    // Rehashing an arbitrary prior digest is not a license to claim a
    // different observed cost from the current control+Worker owners.
    let mut fabricated = observed.clone();
    fabricated.observed_tokens += 1;
    fabricated.source_digest = fabricated.computed_digest();
    assert!(fabricated.validate_integrity());
    assert_eq!(
        revalidate_neuron_observed_cost_source_v1(
            &owner,
            &worker,
            &typed,
            &receipt,
            &cost,
            &fabricated,
            100,
        ),
        Err(NeuronObservedCostSourceErrorV1::Stale)
    );

    // Cancellation after a dispatched physical call makes the previous
    // read-side cost diagnostic unavailable for further scoring.
    let cancelled = owner
        .cancel(typed.request_id.as_str(), claim.revision)
        .unwrap();
    assert_eq!(cancelled.state, RequestState::Cancelling);
    assert_eq!(
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &receipt, &cost, 100,),
        Err(NeuronObservedCostSourceErrorV1::Stale)
    );

    // Reopen the real durable control WAL. A terminal settlement (including
    // failed/unknown outcomes) is not a second fresh cost observation.
    drop(owner);
    let reopened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        reopened.get(typed.request_id.as_str()).unwrap().state,
        RequestState::Cancelling
    );
    assert_eq!(
        read_neuron_observed_cost_source_v1(&reopened, &worker, &typed, &receipt, &cost, 100,),
        Err(NeuronObservedCostSourceErrorV1::Stale)
    );
}

#[test]
fn observed_token_cost_rejects_identical_model_reload_inside_same_worker() {
    let directory = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let mut owner = control(&directory, &typed);
    let mut worker = worker();
    let (_, mut port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &typed, 100).unwrap();
    let receipt = port.execute_feature(&typed).unwrap();
    let cost = port.take_cost_diagnostic().unwrap();
    drop(port);

    let observed =
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &receipt, &cost, 100).unwrap();
    let original_revision = worker
        .current_neuron_model_load_revision("model.1")
        .unwrap();
    assert_eq!(observed.model_load_revision, original_revision);
    assert_eq!(cost.model_load_revision(), original_revision);

    // Identical model, Worker ID, process generation and driver handle are NOT
    // sufficient. Only the actual monotonically increasing load ordinal
    // distinguishes the reloaded physical model from the prior invocation.
    let manifest = worker
        .inspected_neuron_manifest(100, "model.1")
        .unwrap()
        .clone();
    worker.unload_model(100, "model.1").unwrap();
    worker.load_model(100, manifest).unwrap();
    assert!(
        worker
            .current_neuron_model_load_revision("model.1")
            .unwrap()
            > original_revision
    );
    assert!(
        observed.validate_integrity(),
        "a self-consistent old diagnostic is not proof of current loading"
    );
    assert_eq!(
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &receipt, &cost, 100),
        Err(NeuronObservedCostSourceErrorV1::Binding)
    );
    assert_eq!(
        revalidate_neuron_observed_cost_source_v1(
            &owner, &worker, &typed, &receipt, &cost, &observed, 100,
        ),
        Err(NeuronObservedCostSourceErrorV1::Binding)
    );
}

#[test]
fn observed_token_cost_is_not_a_settled_wal_or_authoritative_resource_debit() {
    let directory = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let mut owner = control(&directory, &typed);
    let mut worker = worker();
    let (claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &typed, 100).unwrap();
    let receipt = port.execute_feature(&typed).unwrap();
    let cost = port.take_cost_diagnostic().unwrap();
    drop(port);
    let report =
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &receipt, &cost, 100).unwrap();
    assert_eq!(report.observed_tokens, 4);
    let current = owner.get(typed.request_id.as_str()).unwrap();
    assert_eq!(current.state, RequestState::Dispatching);
    assert_eq!(
        current.usage_units, 0,
        "read-only observation cannot settle a debit"
    );
    assert_eq!(current.consumed_tokens, 0);
    let durable_payload = owner
        .get(typed.request_id.as_str())
        .unwrap()
        .request
        .payload_digest
        .clone();
    let settlement = owner
        .settle(
            typed.request_id.as_str(),
            claim.revision,
            "a".repeat(64),
            TerminalObservation {
                request_id: typed.request_id.to_string(),
                reservation_id: "reservation.1".to_owned(),
                worker_id: worker.worker_id().to_owned(),
                worker_generation: worker.worker_generation(),
                model_digest: "2".repeat(64),
                payload_digest: durable_payload,
                terminal_observed: true,
                terminal_status: Some(RequestState::Completed),
                output_digest: Some(receipt.output_digest.to_string()),
                consumed_tokens: cost.consumed_tokens(),
                // This comes from an independent charging scheme, not a
                // made-up conversion of tokens into quota units.
                usage_units: 0,
            },
        )
        .unwrap();
    assert_eq!(settlement.state, RequestState::Completed);
    assert_eq!(
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &receipt, &cost, 100,),
        Err(NeuronObservedCostSourceErrorV1::Stale)
    );

    // Historical settlement is a separate, current-WAL comparison. The
    // pre-settlement physical receipt is not itself a payment/debit.
    let historical =
        read_neuron_settled_cost_diagnostic_v1(&owner, &typed, &receipt, &report).unwrap();
    assert!(historical.validate_integrity());
    assert_eq!(
        historical.terminal_status,
        NeuronFeatureTerminalStatusV1::Succeeded
    );
    assert_eq!(historical.settled_tokens, 4);
    assert_eq!(historical.settled_usage_units, 0);
    assert_eq!(
        historical.dispatch_revision + 1,
        historical.settlement_revision
    );
    assert_eq!(historical.authority, AuthorityPosture::DENY_ALL);
    revalidate_neuron_settled_cost_diagnostic_v1(&owner, &typed, &receipt, &report, &historical)
        .unwrap();

    let mut claimed_more_tokens = report.clone();
    claimed_more_tokens.observed_tokens += 1;
    claimed_more_tokens.source_digest = claimed_more_tokens.computed_digest();
    assert!(claimed_more_tokens.validate_integrity());
    assert_eq!(
        read_neuron_settled_cost_diagnostic_v1(&owner, &typed, &receipt, &claimed_more_tokens,),
        Err(NeuronSettledCostErrorV1::Mismatch)
    );

    let mut forged_usage = historical.clone();
    forged_usage.settled_usage_units += 1;
    forged_usage.diagnostic_digest = forged_usage.computed_digest();
    assert!(forged_usage.validate_integrity());
    assert_eq!(
        revalidate_neuron_settled_cost_diagnostic_v1(
            &owner,
            &typed,
            &receipt,
            &report,
            &forged_usage,
        ),
        Err(NeuronSettledCostErrorV1::Stale)
    );
    let mut wrong_receipt = receipt.clone();
    wrong_receipt.receipt_digest = Digest32::of_bytes(b"forged-output");
    assert_eq!(
        read_neuron_settled_cost_diagnostic_v1(&owner, &typed, &wrong_receipt, &report,),
        Err(NeuronSettledCostErrorV1::Mismatch)
    );

    // Actual WAL reopening is mandatory: this does not silently fall back to
    // a cached in-process accounting claim or a live Worker instance token.
    drop(owner);
    let reopened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    let after_restart =
        read_neuron_settled_cost_diagnostic_v1(&reopened, &typed, &receipt, &report).unwrap();
    assert_eq!(after_restart, historical);
    revalidate_neuron_settled_cost_diagnostic_v1(&reopened, &typed, &receipt, &report, &historical)
        .unwrap();
}

#[test]
fn settled_neuron_cost_refuses_generic_wal_with_unrelated_feature_payload() {
    // First execute a real typed Worker invocation and bind its token source
    // to an actual Dispatching record. This is still a synthetic fixture
    // Driver, never evidence of production Laya execution.
    let source_directory = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let mut genuine_owner = control(&source_directory, &typed);
    let mut actual_worker = worker();
    let (_claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut genuine_owner, &mut actual_worker, &typed, 100)
            .unwrap();
    let receipt = port.execute_feature(&typed).unwrap();
    let cost = port.take_cost_diagnostic().unwrap();
    drop(port);
    let observed = read_neuron_observed_cost_source_v1(
        &genuine_owner,
        &actual_worker,
        &typed,
        &receipt,
        &cost,
        100,
    )
    .unwrap();

    // The legacy control writer accepts a generic well-formed SHA-256 as
    // payload_digest. Give this *other* durable owner the same typed semantic
    // digest, model, reservation and Worker labels, but an unrelated payload.
    // Its fsynced terminal can still be structurally valid for generic
    // inference; it is NOT the actual canonical Neuron feature invocation.
    let unrelated_directory = tempfile::tempdir().unwrap();
    let wrong_payload = "f".repeat(64);
    let mut unrelated = control_with_overrides(
        &unrelated_directory,
        &typed,
        None,
        Some(wrong_payload.clone()),
    );
    let assigned = unrelated.get(typed.request_id.as_str()).unwrap();
    let assignment = assigned.assignment.clone().unwrap();
    let reservation = assigned.reservation.clone().unwrap();
    let revision = assigned.revision;
    let dispatch = unrelated
        .claim_dispatch(
            100,
            typed.request_id.as_str(),
            revision,
            &reservation.reservation_id,
            &assignment,
        )
        .unwrap();
    let completed = unrelated
        .settle(
            typed.request_id.as_str(),
            dispatch.revision,
            "a".repeat(64),
            TerminalObservation {
                request_id: typed.request_id.to_string(),
                reservation_id: reservation.reservation_id,
                worker_id: assignment.worker_id,
                worker_generation: assignment.worker_generation,
                model_digest: "2".repeat(64),
                payload_digest: wrong_payload,
                terminal_observed: true,
                terminal_status: Some(RequestState::Completed),
                output_digest: Some(receipt.output_digest.to_string()),
                consumed_tokens: observed.observed_tokens,
                usage_units: 0,
            },
        )
        .unwrap();
    assert_eq!(completed.state, RequestState::Completed);
    assert_eq!(
        read_neuron_settled_cost_diagnostic_v1(&unrelated, &typed, &receipt, &observed,),
        Err(NeuronSettledCostErrorV1::Mismatch)
    );
    drop(unrelated);
    let recovered =
        DurableInferenceControl::open(unrelated_directory.path().join("inference.journal"), 32)
            .unwrap();
    assert_eq!(
        read_neuron_settled_cost_diagnostic_v1(&recovered, &typed, &receipt, &observed,),
        Err(NeuronSettledCostErrorV1::Mismatch)
    );
}

#[test]
fn historical_neuron_cost_refuses_different_fsynced_output_after_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let mut owner = control(&directory, &typed);
    let mut worker = worker();
    let (claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &typed, 100).unwrap();
    let receipt = port.execute_feature(&typed).unwrap();
    let cost = port.take_cost_diagnostic().unwrap();
    drop(port);
    let observed =
        read_neuron_observed_cost_source_v1(&owner, &worker, &typed, &receipt, &cost, 100).unwrap();
    let original_payload = owner
        .get(typed.request_id.as_str())
        .unwrap()
        .request
        .payload_digest
        .clone();
    let other_output = Digest32::of_bytes(b"a-different-physical-model-output").to_string();
    assert_ne!(other_output, receipt.output_digest.to_string());
    let unrelated = TerminalObservation {
        request_id: typed.request_id.to_string(),
        reservation_id: "reservation.1".to_owned(),
        worker_id: worker.worker_id().to_owned(),
        worker_generation: worker.worker_generation(),
        model_digest: "2".repeat(64),
        payload_digest: original_payload,
        terminal_observed: true,
        terminal_status: Some(RequestState::Completed),
        output_digest: Some(other_output.clone()),
        consumed_tokens: cost.consumed_tokens(),
        usage_units: 0,
    };
    let terminal = owner
        .settle(
            typed.request_id.as_str(),
            claim.revision,
            "d".repeat(64),
            unrelated.clone(),
        )
        .unwrap();
    assert_eq!(terminal.state, RequestState::Completed);
    assert_eq!(
        owner
            .get(typed.request_id.as_str())
            .unwrap()
            .terminal_output_digest
            .as_deref(),
        Some(other_output.as_str()),
    );
    assert_eq!(
        read_neuron_settled_cost_diagnostic_v1(&owner, &typed, &receipt, &observed),
        Err(NeuronSettledCostErrorV1::Mismatch),
    );
    // A changed terminal result under the SAME caller-supplied observation
    // identity is not an idempotent acknowledgement.
    let mut replay = unrelated.clone();
    replay.output_digest = Some(receipt.output_digest.to_string());
    assert!(
        owner
            .settle(
                typed.request_id.as_str(),
                terminal.revision,
                "d".repeat(64),
                replay,
            )
            .is_err()
    );
    assert!(
        owner
            .settle(
                typed.request_id.as_str(),
                terminal.revision,
                "d".repeat(64),
                unrelated,
            )
            .unwrap()
            .idempotent
    );

    drop(owner);
    let reopened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        read_neuron_settled_cost_diagnostic_v1(&reopened, &typed, &receipt, &observed),
        Err(NeuronSettledCostErrorV1::Mismatch),
    );
    let record = reopened.get(typed.request_id.as_str()).unwrap();
    assert_eq!(
        record.terminal_output_digest.as_deref(),
        Some(other_output.as_str())
    );
}

#[test]
fn known_worker_terminal_settles_once_with_separately_priced_units_and_reopens() {
    let directory = tempfile::tempdir().unwrap();
    let typed = typed_request();
    let mut owner = control(&directory, &typed);
    let mut worker = worker();
    let (claim, mut port) =
        claim_neuron_durable_dispatch_v1(&mut owner, &mut worker, &typed, 100).unwrap();
    let receipt = port.execute_feature(&typed).unwrap();
    let cost = port.take_cost_diagnostic().unwrap();
    drop(port);

    // Pricing is an externally supplied number; this function never
    // converts consumed_tokens into usage units by itself.
    assert!(matches!(
        settle_neuron_live_worker_terminal_v1(
            &mut owner, &worker, &typed, &receipt, &cost, 100, 101,
        ),
        Err(NeuronLiveTerminalSettlementErrorV1::PriceExceedsReservation)
    ));
    assert_eq!(
        owner.get(typed.request_id.as_str()).unwrap().state,
        RequestState::Dispatching
    );
    assert_eq!(
        owner.get(typed.request_id.as_str()).unwrap().revision,
        claim.revision
    );

    let (committed, historical) = settle_neuron_live_worker_terminal_v1(
        &mut owner, &worker, &typed, &receipt, &cost, 100, 7,
    )
    .unwrap();
    assert_eq!(committed.state, RequestState::Completed);
    assert!(!committed.idempotent);
    assert_eq!(historical.settled_tokens, cost.consumed_tokens());
    assert_eq!(historical.settled_usage_units, 7);
    assert_eq!(historical.authority, AuthorityPosture::DENY_ALL);
    assert!(historical.validate_integrity());
    assert_eq!(
        owner
            .get(typed.request_id.as_str())
            .unwrap()
            .terminal_output_digest
            .as_deref(),
        Some(receipt.output_digest.to_string().as_str())
    );
    // Even with identical source/price, no second fsynced settlement is
    // permitted through the already-completed live Worker request.
    assert!(matches!(
        settle_neuron_live_worker_terminal_v1(
            &mut owner, &worker, &typed, &receipt, &cost, 100, 7,
        ),
        Err(NeuronLiveTerminalSettlementErrorV1::Source(
            NeuronObservedCostSourceErrorV1::Stale
        ))
    ));
    drop(owner);

    // On physical restart the historical terminal and independently priced
    // cost come from the reopened durable control WAL, not the old Worker.
    let reopened =
        DurableInferenceControl::open(directory.path().join("inference.journal"), 32).unwrap();
    assert_eq!(
        reopened.get(typed.request_id.as_str()).unwrap().state,
        RequestState::Completed
    );
    assert_eq!(reopened.get(typed.request_id.as_str()).unwrap().usage_units, 7);
    assert_eq!(reopened.get(typed.request_id.as_str()).unwrap().consumed_tokens, 4);
    assert_eq!(historical.settlement_revision, committed.revision);
}
