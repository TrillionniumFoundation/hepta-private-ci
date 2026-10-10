use super::*;
use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct Driver;

impl ModelDriver for Driver {
    fn load(&mut self, _manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        Ok(DriverModelHandle {
            opaque_id: "loaded".into(),
            observed_memory_bytes: 1024,
        })
    }
    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure("generic path not admitted".into()))
    }
    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        Ok(())
    }
}

impl NeuronFeatureDriver for Driver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        req: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: req.encoder_digest.clone(),
            head_digest: req.head_digest.clone(),
            drive_q24: vec![1 << 24; req.expected_output_width],
            prediction_q24: vec![0; req.expected_output_width],
            observed_memory_bytes: 1024,
            transient_allocation_bytes: 2048,
            queue_age_micros: 8,
            latency_micros: 13,
        })
    }
}

fn digest(label: &[u8]) -> Digest32 {
    Digest32::of_bytes(label)
}

fn fixture_request() -> (ModelManifest, NeuronFeatureRequest, MicrobatchKeyV1) {
    let model = ModelManifest {
        model_id: "model".into(),
        model_digest: digest(b"model").to_string(),
        weights_digest: digest(b"weights").to_string(),
        tokenizer_digest: digest(b"tokenizer").to_string(),
        preprocessor_digest: digest(b"preprocessor").to_string(),
        quantization_digest: digest(b"quantization").to_string(),
        runtime_digest: digest(b"runtime").to_string(),
        device_digest: digest(b"device").to_string(),
        maximum_tokens: 128,
    };
    let mut request = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: "req-one".into(),
            reservation_id: "reservation-one".into(),
            model_digest: model.model_digest.clone(),
            payload_digest: String::new(),
            maximum_tokens: 8,
            deadline_ms: 9000,
            lease_payload_digest: String::new(),
            reservation_model_digest: model.model_digest.clone(),
            reservation_maximum_tokens: 8,
            cancelled: false,
        },
        encoder_digest: digest(b"encoder").to_string(),
        head_digest: digest(b"head").to_string(),
        weights_digest: model.weights_digest.clone(),
        input_digest: digest(b"input").to_string(),
        feature_vector_q24: vec![0, 1 << 24],
        expected_output_width: 3,
    };
    let payload = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = payload.clone();
    request.authorization.lease_payload_digest = payload;
    let key = MicrobatchKeyV1 {
        scope_id: StableId::new("scope").unwrap(),
        model_digest: Digest32::from_str(&model.model_digest).unwrap(),
        generation: Generation::new(3).unwrap(),
        route_fence: 2,
        authority_epoch: 9,
    };
    (model, request, key)
}

fn runner_with_driver<D: ModelDriver + NeuronFeatureDriver>(
    signing_key: &SigningKey,
    directory: &std::path::Path,
    model: ModelManifest,
    driver: D,
    max_batch_size: usize,
) -> AuthenticatedNeuronMicrobatchWorkerV1<D> {
    // FinalUseAuthority requires a private owner-controlled state directory.
    // Temp directory permissions vary with the runner and its inherited umask;
    // normalize the fixture rather than weakening the production owner gate.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700))
            .expect("private final-use fixture directory");
    }
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority = FinalUseAuthority::open_state_dir(
        directory,
        "security-owner".into(),
        signing_key.verifying_key().to_bytes(),
        head,
    )
    .unwrap();
    let grant = ResourceGrant {
        grant_id: "resource".into(),
        authority_epoch: 9,
        generation: 3,
        expires_at_ms: 10_000,
        revoked: false,
        maximum_models: 2,
        maximum_active_requests: 4,
        maximum_memory_bytes: 4096,
        semantic_digest: digest(b"resource-grant").to_string(),
    };
    let mut worker = InferenceWorker::new(100, "worker-one".into(), 3, grant, driver).unwrap();
    worker.load_model(100, model).unwrap();
    AuthenticatedNeuronMicrobatchWorkerV1::new(
        worker,
        authority,
        MicrobatchLimitsV1 {
            max_pending: 10,
            max_batch_size,
            max_lanes_per_poll: 4,
            max_wait_ms: 5,
        },
    )
    .unwrap()
}

fn runner(
    signing_key: &SigningKey,
    directory: &std::path::Path,
    model: ModelManifest,
) -> AuthenticatedNeuronMicrobatchWorkerV1<Driver> {
    runner_with_driver(signing_key, directory, model, Driver, 1)
}

fn signed(signing_key: &SigningKey, binding: FinalUseBinding) -> SignedFinalUseGrant {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "feature-one".into(),
        nonce: [9; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing_key
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

#[test]
fn signed_batch_executes_driver_once_then_rejects_duplicate() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[17; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut execution = runner(&signer, dir.path(), model);
    execution
        .enqueue(
            100,
            "model".into(),
            request.clone(),
            key.clone(),
            signed(&signer, binding),
        )
        .unwrap();
    let completed = execution.poll_and_execute(101).unwrap();
    assert_eq!(completed.outcomes.len(), 1);
    let receipt = completed.outcomes[0].result.as_ref().unwrap();
    assert_eq!(receipt.status, NeuronFeatureTerminalStatusV1::Succeeded);
    assert_eq!(execution.pending(), 0);
    assert_eq!(
        execution.enqueue(
            102,
            "model".into(),
            request,
            key,
            completed_signed_dummy(&signer)
        ),
        Err(BatchWorkerErrorV1::Duplicate)
    );
}

fn completed_signed_dummy(signer: &SigningKey) -> SignedFinalUseGrant {
    let (_, request, key) = fixture_request();
    signed(
        signer,
        neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap(),
    )
}

#[test]
fn corrupt_signed_grant_cannot_invoke_driver() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[19; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut grant = signed(&signer, binding);
    grant.signature[0] ^= 0x80;
    let mut execution = runner(&signer, dir.path(), model);
    execution
        .enqueue(100, "model".into(), request, key, grant)
        .unwrap();
    let completed = execution.poll_and_execute(101).unwrap();
    assert_eq!(completed.outcomes.len(), 1);
    assert!(matches!(
        &completed.outcomes[0].result,
        Err(BatchWorkerErrorV1::Authority)
    ));
}

#[test]
fn revoked_scope_drops_queued_intent_without_driver_effect() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[21; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut execution = runner(&signer, dir.path(), model);
    execution
        .enqueue(
            100,
            "model".into(),
            request,
            key.clone(),
            signed(&signer, binding),
        )
        .unwrap();
    let removed = execution.fence_scope(&key.scope_id, key.generation, 3, key.authority_epoch);
    assert_eq!(removed, vec![StableId::new("req-one").unwrap()]);
    let outcome = execution.poll_and_execute(101).unwrap();
    assert!(outcome.outcomes.is_empty());
    assert_eq!(execution.pending(), 0);
}

#[derive(Debug, Default)]
struct CapturedMetrics(std::sync::Mutex<Vec<PhaseMetricEventV1>>);

impl PhaseMetricSinkV1 for CapturedMetrics {
    fn record(
        &self,
        event: PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        self.0.lock().unwrap().push(event);
        Ok(())
    }

    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Ok(())
    }
}

#[test]
fn signed_worker_emits_admission_batch_and_terminal_metrics() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[23; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let captured = Arc::new(CapturedMetrics::default());
    let mut worker = runner(&signer, dir.path(), model).with_metric_sink(captured.clone());
    worker
        .enqueue(100, "model".into(), request, key, signed(&signer, binding))
        .unwrap();
    assert!(
        worker.poll_and_execute(101).unwrap().outcomes[0]
            .result
            .is_ok()
    );
    let events = captured.0.lock().unwrap();
    assert_eq!(events.len(), 3);
    assert_eq!(events[0].phase, PhaseMetricKindV1::Admission);
    assert_eq!(events[1].phase, PhaseMetricKindV1::Microbatch);
    assert_eq!(events[2].phase, PhaseMetricKindV1::NeuronFeature);
    assert!(events.iter().all(|event| event.succeeded));
    assert!(events.iter().all(|event| !event.scope_digest.is_zero()));
    assert!(events.iter().all(|event| !event.operation_digest.is_zero()));
}

#[test]
fn rejected_signature_records_failed_terminal_without_invoking_driver() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[25; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut grant = signed(&signer, binding);
    grant.signature[0] ^= 0x80;
    let captured = Arc::new(CapturedMetrics::default());
    let mut worker = runner(&signer, dir.path(), model).with_metric_sink(captured.clone());
    worker
        .enqueue(100, "model".into(), request, key, grant)
        .unwrap();
    let poll = worker.poll_and_execute(101).unwrap();
    assert!(matches!(
        &poll.outcomes[0].result,
        Err(BatchWorkerErrorV1::Authority)
    ));
    let events = captured.0.lock().unwrap();
    assert_eq!(events.len(), 3);
    assert!(events[0].succeeded);
    assert!(events[1].succeeded);
    assert!(!events[2].succeeded);
}

#[test]
fn signed_batch_rejects_authorization_quota_and_reservation_mutations() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[27; 32]);
    let (model, original, key) = fixture_request();
    let original_grant = || {
        signed(
            &signer,
            neuron_batch_final_use_binding_v1("worker-one", &key, &original).unwrap(),
        )
    };
    let mut worker = runner(&signer, dir.path(), model);

    let mut changed_quota = original.clone();
    changed_quota.authorization.maximum_tokens += 1;
    let mut changed_reservation_quota = original.clone();
    changed_reservation_quota
        .authorization
        .reservation_maximum_tokens += 1;
    let mut changed_reservation_model = original.clone();
    changed_reservation_model
        .authorization
        .reservation_model_digest = digest(b"other-model").to_string();

    for mutated in [
        changed_quota,
        changed_reservation_quota,
        changed_reservation_model,
    ] {
        assert_eq!(
            worker.enqueue(100, "model".into(), mutated, key.clone(), original_grant()),
            Err(BatchWorkerErrorV1::InvalidBinding)
        );
        assert_eq!(worker.pending(), 0);
    }

    // Failed comparisons cannot claim the signed one-shot nonce or poison
    // the original exact request. It is still admitted and executes once.
    worker
        .enqueue(
            100,
            "model".into(),
            original.clone(),
            key.clone(),
            original_grant(),
        )
        .unwrap();
    let poll = worker.poll_and_execute(101).unwrap();
    assert_eq!(poll.outcomes.len(), 1);
    assert_eq!(
        poll.outcomes[0].result.as_ref().unwrap().status,
        NeuronFeatureTerminalStatusV1::Succeeded
    );
}


#[derive(Clone)]
struct NativeTestDriver {
    invocations: Arc<std::sync::atomic::AtomicUsize>,
    truncate_outputs: bool,
}

impl ModelDriver for NativeTestDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        Driver.load(manifest)
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Driver.run(handle, request)
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        Driver.unload(handle)
    }
}

impl NeuronFeatureDriver for NativeTestDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        Driver.run_neuron_features(handle, request)
    }

    fn run_neuron_features_batch(
        &mut self,
        _handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureObservation>, Error> {
        self.invocations.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let mut observed: Vec<_> = requests
            .iter()
            .map(|request| DriverNeuronFeatureObservation {
                terminal_observed: true,
                succeeded: true,
                encoder_digest: request.encoder_digest.clone(),
                head_digest: request.head_digest.clone(),
                drive_q24: vec![1 << 24; request.expected_output_width],
                prediction_q24: vec![0; request.expected_output_width],
                observed_memory_bytes: 1024,
                transient_allocation_bytes: 2048,
                queue_age_micros: 8,
                latency_micros: 13,
            })
            .collect();
        if self.truncate_outputs {
            observed.pop();
        }
        Ok(observed)
    }
}

fn signed_member(
    signer: &SigningKey,
    binding: FinalUseBinding,
    grant_id: &str,
    nonce: u8,
) -> SignedFinalUseGrant {
    let mut signed = signed(signer, binding);
    signed.grant.grant_id = grant_id.to_owned();
    signed.grant.nonce = [nonce; 32];
    signed.signature = signer.sign(&signed.grant.signing_bytes().unwrap()).to_bytes().to_vec();
    signed
}

fn second_request(first: &NeuronFeatureRequest) -> NeuronFeatureRequest {
    let mut next = first.clone();
    next.authorization.request_id = "req-two".into();
    next.authorization.reservation_id = "reservation-two".into();
    next
}

#[test]
fn native_batch_dispatches_one_backend_call_with_two_signed_receipts_and_six_metrics() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[35; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let metrics = Arc::new(CapturedMetrics::default());
    let driver = NativeTestDriver { invocations: calls.clone(), truncate_outputs: false };
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2)
        .with_metric_sink(metrics.clone());
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    worker.enqueue(100, "model".into(), first, key.clone(), signed_member(&signer, one, "grant-1", 41)).unwrap();
    worker.enqueue(100, "model".into(), second, key, signed_member(&signer, two, "grant-2", 42)).unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(worker.pending(), 0);
    assert!(observed.outcomes.iter().all(|item| matches!(&item.result, Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded)));
    let events = metrics.0.lock().unwrap();
    assert_eq!(events.len(), 6);
    for phase in [PhaseMetricKindV1::Admission, PhaseMetricKindV1::Microbatch, PhaseMetricKindV1::NeuronFeature] {
        assert_eq!(events.iter().filter(|sample| sample.phase == phase).count(), 2);
    }
}

#[test]
fn native_batch_denies_all_effects_when_one_signature_is_invalid() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[37; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver { invocations: calls.clone(), truncate_outputs: false };
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    let mut malicious = signed_member(&signer, two, "grant-2", 44);
    malicious.signature[0] ^= 0x80;
    worker.enqueue(100, "model".into(), first, key.clone(), signed_member(&signer, one, "grant-1", 43)).unwrap();
    worker.enqueue(100, "model".into(), second, key, malicious).unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert!(observed.outcomes.iter().all(|item| matches!(item.result, Err(BatchWorkerErrorV1::Authority))));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert_eq!(worker.pending(), 0);
}

#[test]
fn native_batch_backend_absence_fails_closed_instead_of_sequential_fallback() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[39; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let mut worker = runner_with_driver(&signer, dir.path(), model, Driver, 2);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    worker.enqueue(100, "model".into(), first, key.clone(), signed_member(&signer, one, "grant-1", 45)).unwrap();
    worker.enqueue(100, "model".into(), second, key, signed_member(&signer, two, "grant-2", 46)).unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert!(observed.outcomes.iter().all(|item| matches!(item.result, Err(BatchWorkerErrorV1::Worker))));
}

#[test]
fn native_batch_malformed_result_count_cannot_be_partially_committed() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[40; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver { invocations: calls.clone(), truncate_outputs: true };
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    worker.enqueue(100, "model".into(), first, key.clone(), signed_member(&signer, one, "grant-1", 47)).unwrap();
    worker.enqueue(100, "model".into(), second, key, signed_member(&signer, two, "grant-2", 48)).unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert!(observed.outcomes.iter().all(|item| matches!(item.result, Err(BatchWorkerErrorV1::Worker))));
}


#[test]
fn native_batch_failed_backend_cannot_replay_consumed_grants_after_owner_reopen() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[51; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    let first_grant = signed_member(&signer, one, "grant-1", 52);
    let second_grant = signed_member(&signer, two, "grant-2", 53);
    {
        let driver = NativeTestDriver {
            invocations: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
            truncate_outputs: true,
        };
        let mut initial = runner_with_driver(&signer, dir.path(), model.clone(), driver, 2);
        initial.enqueue(100, "model".into(), first.clone(), key.clone(), first_grant.clone()).unwrap();
        initial.enqueue(100, "model".into(), second.clone(), key.clone(), second_grant.clone()).unwrap();
        let failed = initial.poll_and_execute(101).unwrap();
        assert_eq!(failed.outcomes.len(), 2);
        assert!(failed.outcomes.iter().all(|x| matches!(x.result, Err(BatchWorkerErrorV1::Worker))));
    }
    // The authoritative nonce journal is reopened, not reset. Previously
    // signed grants cannot trigger a duplicate external effect.
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver { invocations: calls.clone(), truncate_outputs: false };
    let mut recovered = runner_with_driver(&signer, dir.path(), model, driver, 2);
    recovered.enqueue(200, "model".into(), first, key.clone(), first_grant).unwrap();
    recovered.enqueue(200, "model".into(), second, key, second_grant).unwrap();
    let denied = recovered.poll_and_execute(201).unwrap();
    assert_eq!(denied.outcomes.len(), 2);
    assert!(denied.outcomes.iter().all(|x| matches!(x.result, Err(BatchWorkerErrorV1::Authority))));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
}
