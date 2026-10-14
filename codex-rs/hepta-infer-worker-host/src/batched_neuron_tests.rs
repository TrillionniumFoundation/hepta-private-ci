use super::*;
use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelManifest;
use crate::model_worker::ResourceGrant;
use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Mutex;
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

#[derive(Debug)]
struct FixtureScopeFrontier {
    current: Mutex<BTreeMap<StableId, MicrobatchKeyV1>>,
}

impl FixtureScopeFrontier {
    fn new(model_digest: Digest32) -> Self {
        let scope = StableId::new("scope").unwrap();
        let current = MicrobatchKeyV1 {
            scope_id: scope.clone(),
            model_digest,
            generation: Generation::new(3).unwrap(),
            route_fence: 2,
            authority_epoch: 9,
        };
        let mut other = current.clone();
        other.scope_id = StableId::new("different-scope").unwrap();
        other.route_fence = 18;
        Self {
            current: Mutex::new(BTreeMap::from([
                (scope, current),
                (other.scope_id.clone(), other),
            ])),
        }
    }

    fn install(&self, key: MicrobatchKeyV1) {
        self.current
            .lock()
            .unwrap()
            .insert(key.scope_id.clone(), key);
    }
}

impl MicrobatchScopeFrontierV1 for FixtureScopeFrontier {
    fn current(&self, scope: &StableId) -> Result<MicrobatchKeyV1, BatchWorkerErrorV1> {
        self.current
            .lock()
            .unwrap()
            .get(scope)
            .cloned()
            .ok_or(BatchWorkerErrorV1::InvalidBinding)
    }
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
    let model_digest = Digest32::from_str(&model.model_digest).unwrap();
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
    .with_live_scope_frontier(Arc::new(FixtureScopeFrontier::new(model_digest)))
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
fn wrong_loaded_model_id_fails_before_consuming_valid_signed_nonce() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[69; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let grant = signed(&signer, binding);
    let mut worker = runner(&signer, dir.path(), model);
    assert_eq!(
        worker.enqueue(
            100,
            "wrong-model-id".into(),
            request.clone(),
            key.clone(),
            grant.clone(),
        ),
        Err(BatchWorkerErrorV1::InvalidBinding)
    );
    assert_eq!(worker.pending(), 0);
    worker
        .enqueue(100, "model".into(), request, key, grant)
        .unwrap();
    assert!(
        worker.poll_and_execute(101).unwrap().outcomes[0]
            .result
            .is_ok()
    );
}

#[test]
fn detached_batch_features_preserve_final_use_and_reject_mutation() {
    let (_, mut request, key) = fixture_request();
    let frozen_features = request.feature_vector_q24.clone();
    let expected = neuron_batch_final_use_binding_v1("worker-one", &key, &request)
        .expect("original full feature binding");
    // Queued requests store only metadata; the signed Q24 vector lives in an
    // immutable shared buffer until final-use and must not be cloned to hash.
    request.feature_vector_q24.clear();
    let detached = neuron_batch_final_use_binding_with_slice_v1(
        "worker-one",
        &key,
        &request,
        &frozen_features,
    )
    .expect("borrowed feature binding");
    assert_eq!(detached, expected);

    let mut changed = frozen_features;
    changed[0] += 1;
    assert_eq!(
        neuron_batch_final_use_binding_with_slice_v1("worker-one", &key, &request, &changed,),
        Err(BatchWorkerErrorV1::InvalidBinding),
        "changed shared Q24 bytes must never reuse the original signed grant",
    );
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

#[derive(Debug)]
struct UnavailableMetricSink;

impl PhaseMetricSinkV1 for UnavailableMetricSink {
    fn record(
        &self,
        _event: PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
    }

    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
    }
}

#[derive(Debug)]
struct FailAtPhaseMetricSink(PhaseMetricKindV1);

impl PhaseMetricSinkV1 for FailAtPhaseMetricSink {
    fn record(
        &self,
        event: PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        if event.phase == self.0 {
            Err(codex_hepta_types::PhaseMetricSinkErrorV1::Unavailable)
        } else {
            Ok(())
        }
    }

    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        Ok(())
    }
}

#[derive(Debug)]
struct DelayedMicrobatchMetricSink;

impl PhaseMetricSinkV1 for DelayedMicrobatchMetricSink {
    fn record(
        &self,
        event: PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        if event.phase == PhaseMetricKindV1::Microbatch {
            std::thread::sleep(std::time::Duration::from_millis(25));
        }
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
fn failed_metrics_latch_readiness_without_replaying_an_authorized_request() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[27; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut execution = runner(&signer, dir.path(), model);
    assert!(!execution.production_metrics_ready());
    assert!(!execution.flush_production_metrics());
    execution = execution.with_metric_sink(Arc::new(UnavailableMetricSink));
    assert!(execution.production_metrics_ready());
    assert_eq!(
        execution.enqueue(100, "model".into(), request, key, signed(&signer, binding)),
        Err(BatchWorkerErrorV1::AdmissionTelemetryIndeterminate)
    );
    // An error is not proof of non-admission: retain the identity for exact
    // original-owner reconciliation without consuming the signed grant.
    assert_eq!(execution.pending(), 1);
    assert!(!execution.production_metrics_ready());
    assert!(!execution.flush_production_metrics());
    assert!(matches!(
        execution.poll_and_execute(101),
        Err(BatchWorkerErrorV1::MetricsUnavailable)
    ));
    // Queue remains available only for original-owner reconciliation. No
    // signed nonce was claimed and no external backend effect was entered.
    assert_eq!(execution.pending(), 1);
    assert_eq!(
        execution.fence_scope(
            &StableId::new("scope").unwrap(),
            Generation::new(4).unwrap(),
            4,
            9,
        ),
        vec![StableId::new("req-one").unwrap()]
    );
    assert_eq!(execution.pending(), 0);
    assert!(!execution.production_metrics_ready());
}

#[test]
fn failed_native_batch_metrics_never_mark_production_ready_or_retry_driver() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[28; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let backend_calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let backend = NativeTestDriver {
        invocations: backend_calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut worker = runner_with_driver(&signer, dir.path(), model, backend, 2)
        .with_metric_sink(Arc::new(FailAtPhaseMetricSink(
            PhaseMetricKindV1::Microbatch,
        )));
    for (index, request) in [first, second].into_iter().enumerate() {
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        worker
            .enqueue(
                100,
                "model".into(),
                request,
                key.clone(),
                signed_member(
                    &signer,
                    binding,
                    &format!("telemetry-lost-{index}"),
                    u8::try_from(index).unwrap() + 81,
                ),
            )
            .unwrap();
    }
    let results = worker.poll_and_execute(101).unwrap();
    assert_eq!(results.outcomes.len(), 2);
    assert!(results.outcomes.iter().all(|item| matches!(
        &item.result,
        Err(BatchWorkerErrorV1::MetricsUnavailable)
    )));
    // The two legitimate grants reached Admission, but failed Phase telemetry
    // before one physical invocation or either durable nonce claim.
    assert_eq!(backend_calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert_eq!(worker.pending(), 0);
    assert!(!worker.production_metrics_ready());
    assert!(!worker.flush_production_metrics());
    assert!(matches!(
        worker.poll_and_execute(102),
        Err(BatchWorkerErrorV1::MetricsUnavailable)
    ));
}

#[derive(Clone)]
struct CountingScalarDriver(Arc<std::sync::atomic::AtomicUsize>);

impl ModelDriver for CountingScalarDriver {
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

impl NeuronFeatureDriver for CountingScalarDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.0.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Driver.run_neuron_features(handle, request)
    }
}

#[test]
fn terminal_metric_failure_preserves_completed_effect_but_blocks_next_admission() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[84; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let scalar_calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let backend = CountingScalarDriver(scalar_calls.clone());
    let mut worker = runner_with_driver(&signer, dir.path(), model, backend, 2)
        .with_metric_sink(Arc::new(FailAtPhaseMetricSink(
            PhaseMetricKindV1::NeuronFeature,
        )));
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            first,
            key.clone(),
            signed_member(&signer, binding, "completed-before-telemetry", 85),
        )
        .unwrap();
    let observed = worker.poll_and_execute(106).unwrap();
    assert_eq!(observed.outcomes.len(), 1);
    assert!(matches!(
        &observed.outcomes[0].result,
        Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
    ));
    // A terminal metric failure cannot rewrite the actual one-shot effect.
    assert_eq!(scalar_calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert!(!worker.production_metrics_ready());
    let next_binding = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    assert_eq!(
        worker.enqueue(
            107,
            "model".into(),
            second,
            key,
            signed_member(&signer, next_binding, "denied-after-telemetry", 86),
        ),
        Err(BatchWorkerErrorV1::MetricsUnavailable)
    );
    assert_eq!(worker.pending(), 0);
    assert_eq!(scalar_calls.load(std::sync::atomic::Ordering::SeqCst), 1);
}

#[test]
fn slow_metric_records_cannot_admit_expired_signed_physical_batch() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[87; 32]);
    let (model, mut first, key) = fixture_request();
    first.authorization.deadline_ms = 115;
    let second = second_request(&first);
    let backend_calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let backend = NativeTestDriver {
        invocations: backend_calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut worker = runner_with_driver(&signer, dir.path(), model, backend, 2)
        .with_metric_sink(Arc::new(DelayedMicrobatchMetricSink));
    for (index, request) in [first, second].into_iter().enumerate() {
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        worker
            .enqueue(
                100,
                "model".into(),
                request,
                key.clone(),
                signed_member(
                    &signer,
                    binding,
                    &format!("delayed-metric-{index}"),
                    u8::try_from(index).unwrap() + 88,
                ),
            )
            .unwrap();
    }
    let outcomes = worker.poll_and_execute(106).unwrap();
    assert_eq!(outcomes.outcomes.len(), 2);
    assert!(outcomes.outcomes.iter().all(|item| matches!(
        item.result,
        Err(BatchWorkerErrorV1::DeadlineExpired)
    )));
    assert_eq!(backend_calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert_eq!(worker.pending(), 0);
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
    reorder_outputs: bool,
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

    fn supports_neuron_feature_batch(&self, _handle: &DriverModelHandle) -> bool {
        true
    }

    fn run_neuron_features_batch(
        &mut self,
        _handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<crate::model_worker::DriverNeuronFeatureBatchObservationV1>, Error> {
        self.invocations
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let mut observed: Vec<_> = requests
            .iter()
            .map(
                |request| crate::model_worker::DriverNeuronFeatureBatchObservationV1 {
                    request_id: request.authorization.request_id.clone(),
                    input_digest: request.input_digest.clone(),
                    observation: DriverNeuronFeatureObservation {
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
                    },
                },
            )
            .collect();
        if self.reorder_outputs {
            observed.reverse();
        }
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
    signed.signature = signer
        .sign(&signed.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
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
    let driver = NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut worker =
        runner_with_driver(&signer, dir.path(), model, driver, 2).with_metric_sink(metrics.clone());
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            first,
            key.clone(),
            signed_member(&signer, one, "grant-1", 41),
        )
        .unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            second,
            key,
            signed_member(&signer, two, "grant-2", 42),
        )
        .unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(worker.pending(), 0);
    assert!(observed.outcomes.iter().all(|item| matches!(&item.result, Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded)));
    let events = metrics.0.lock().unwrap();
    assert_eq!(events.len(), 6);
    for phase in [
        PhaseMetricKindV1::Admission,
        PhaseMetricKindV1::Microbatch,
        PhaseMetricKindV1::NeuronFeature,
    ] {
        assert_eq!(
            events.iter().filter(|sample| sample.phase == phase).count(),
            2
        );
    }
}

#[test]
fn native_three_member_batch_preserves_distinct_signed_nonces_and_metrics() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[35; 32]);
    let (model, first, key) = fixture_request();
    let invocations = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let metrics = Arc::new(CapturedMetrics::default());
    let driver = NativeTestDriver {
        invocations: invocations.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut worker =
        runner_with_driver(&signer, dir.path(), model, driver, 3).with_metric_sink(metrics.clone());
    for index in 0_u8..3 {
        let mut request = first.clone();
        request.authorization.request_id = format!("batch-three-request-{index}");
        request.authorization.reservation_id = format!("batch-three-reservation-{index}");
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let grant = signed_member(
            &signer,
            binding,
            &format!("batch-three-grant-{index}"),
            index + 71,
        );
        assert_eq!(grant.grant.nonce, [index + 71; 32]);
        worker
            .enqueue(100, "model".into(), request, key.clone(), grant)
            .unwrap();
    }
    let completed = worker.poll_and_execute(101).unwrap();
    assert_eq!(completed.outcomes.len(), 3);
    assert_eq!(completed.pending, 0);
    assert_eq!(invocations.load(std::sync::atomic::Ordering::SeqCst), 1);
    let unique = completed
        .outcomes
        .iter()
        .map(|item| item.request_id.clone())
        .collect::<BTreeSet<_>>();
    assert_eq!(unique.len(), 3);
    assert!(completed.outcomes.iter().all(|item| matches!(
        &item.result,
        Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
    )));
    let events = metrics.0.lock().unwrap();
    assert_eq!(events.len(), 9);
    for phase in [
        PhaseMetricKindV1::Admission,
        PhaseMetricKindV1::Microbatch,
        PhaseMetricKindV1::NeuronFeature,
    ] {
        assert_eq!(
            events
                .iter()
                .filter(|event| event.phase == phase && event.succeeded)
                .count(),
            3
        );
    }
}

#[test]
fn completed_request_history_does_not_consume_concurrent_queue_capacity() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[72; 32]);
    let (model, first, key) = fixture_request();
    let mut worker = runner(&signer, dir.path(), model);
    for index in 0..12 {
        let mut request = first.clone();
        request.authorization.request_id = format!("lifetime-{index}");
        request.authorization.reservation_id = format!("reservation-{index}");
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let grant = signed_member(
            &signer,
            binding,
            &format!("grant-{index}"),
            (index + 80) as u8,
        );
        worker
            .enqueue(100 + index, "model".into(), request, key.clone(), grant)
            .unwrap();
        assert_eq!(
            worker.poll_and_execute(101 + index).unwrap().outcomes.len(),
            1
        );
        assert_eq!(worker.pending(), 0);
    }
    let mut old_request = first.clone();
    old_request.authorization.request_id = "lifetime-0".into();
    old_request.authorization.reservation_id = "reservation-0".into();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &old_request).unwrap();
    assert_eq!(
        worker.enqueue(
            120,
            "model".into(),
            old_request,
            key,
            signed_member(&signer, binding, "replay-new-grant", 99),
        ),
        Err(BatchWorkerErrorV1::Duplicate)
    );
}

#[test]
fn native_batch_coalesces_distinct_scopes_without_crossing_authority() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[61; 32]);
    let (model, first, first_key) = fixture_request();
    let second = second_request(&first);
    let mut other_key = first_key.clone();
    other_key.scope_id = StableId::new("different-scope").unwrap();
    other_key.route_fence = 18;
    let invocations = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let backend = NativeTestDriver {
        invocations: invocations.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut worker = runner_with_driver(&signer, dir.path(), model, backend, 2);
    let binding_a = neuron_batch_final_use_binding_v1("worker-one", &first_key, &first).unwrap();
    let binding_b = neuron_batch_final_use_binding_v1("worker-one", &other_key, &second).unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            first,
            first_key,
            signed_member(&signer, binding_a, "grant-a", 62),
        )
        .unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            second,
            other_key,
            signed_member(&signer, binding_b, "grant-b", 63),
        )
        .unwrap();
    let result = worker.poll_and_execute(106).unwrap();
    assert_eq!(result.outcomes.len(), 2);
    assert_eq!(invocations.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert!(result.outcomes.iter().all(|item| matches!(
        &item.result,
        Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
    )));
}

#[test]
fn missing_or_stale_live_scope_frontier_fails_closed() {
    let (_, request, key) = fixture_request();
    assert!(!scope_binding_current(None, &key));

    let frontier = Arc::new(FixtureScopeFrontier::new(key.model_digest));
    assert!(scope_binding_current(
        Some(&(frontier.clone() as Arc<dyn MicrobatchScopeFrontierV1>)),
        &key
    ));
    let mut old_key = key.clone();
    old_key.route_fence = 1;
    assert!(!scope_binding_current(
        Some(&(frontier as Arc<dyn MicrobatchScopeFrontierV1>)),
        &old_key
    ));

    // The request itself is correctly bound, so this is only a live
    // currentness rejection, not an invalid feature or signature fixture.
    assert!(!request.authorization.payload_digest.is_empty());
}

#[test]
fn coalesced_batch_denies_stale_other_scope_without_claiming_either_nonce() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[72; 32]);
    let (model, first, first_key) = fixture_request();
    let second = second_request(&first);
    let mut other_key = first_key.clone();
    other_key.scope_id = StableId::new("different-scope").unwrap();
    other_key.route_fence = 18;
    let frontier = Arc::new(FixtureScopeFrontier::new(first_key.model_digest));
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2)
        .with_live_scope_frontier(frontier.clone());
    let signed_a = signed_member(
        &signer,
        neuron_batch_final_use_binding_v1("worker-one", &first_key, &first).unwrap(),
        "live-a",
        73,
    );
    let signed_b = signed_member(
        &signer,
        neuron_batch_final_use_binding_v1("worker-one", &other_key, &second).unwrap(),
        "stale-b",
        74,
    );
    worker
        .enqueue(100, "model".into(), first, first_key, signed_a)
        .unwrap();
    worker
        .enqueue(100, "model".into(), second, other_key.clone(), signed_b)
        .unwrap();
    other_key.route_fence = 19;
    frontier.install(other_key);

    let result = worker.poll_and_execute(106).unwrap();
    assert_eq!(result.outcomes.len(), 2);
    assert!(
        result
            .outcomes
            .iter()
            .all(|item| matches!(item.result, Err(BatchWorkerErrorV1::InvalidBinding)))
    );
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert_eq!(worker.pending(), 0);
}

#[derive(Clone)]
struct DelayedNativeBatchDriver(NativeTestDriver);

impl ModelDriver for DelayedNativeBatchDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        self.0.load(manifest)
    }

    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        self.0.run(handle, request)
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        self.0.unload(handle)
    }
}

impl NeuronFeatureDriver for DelayedNativeBatchDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.0.run_neuron_features(handle, request)
    }

    fn supports_neuron_feature_batch(&self, handle: &DriverModelHandle) -> bool {
        self.0.supports_neuron_feature_batch(handle)
    }

    fn run_neuron_features_batch(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<crate::model_worker::DriverNeuronFeatureBatchObservationV1>, Error> {
        std::thread::sleep(std::time::Duration::from_millis(25));
        self.0.run_neuron_features_batch(handle, requests)
    }
}

#[test]
fn late_native_batch_receipt_is_stale_without_replay() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[89; 32]);
    let (model, mut first, key) = fixture_request();
    first.authorization.deadline_ms = 115;
    let second = second_request(&first);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = DelayedNativeBatchDriver(NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    });
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2);
    for (index, request) in [first, second].into_iter().enumerate() {
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        worker
            .enqueue(
                100,
                "model".into(),
                request,
                key.clone(),
                signed_member(
                    &signer,
                    binding,
                    &format!("late-driver-{index}"),
                    u8::try_from(index).unwrap() + 90,
                ),
            )
            .unwrap();
    }
    let result = worker.poll_and_execute(106).unwrap();
    assert_eq!(result.outcomes.len(), 2);
    assert!(result.outcomes.iter().all(|item| matches!(
        item.result,
        Err(BatchWorkerErrorV1::StaleAfterEffect)
    )));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(worker.pending(), 0);
    assert!(worker.poll_and_execute(132).unwrap().outcomes.is_empty());
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
}

#[test]
fn native_batch_denies_all_effects_when_one_signature_is_invalid() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[37; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    let mut malicious = signed_member(&signer, two, "grant-2", 44);
    malicious.signature[0] ^= 0x80;
    worker
        .enqueue(
            100,
            "model".into(),
            first,
            key.clone(),
            signed_member(&signer, one, "grant-1", 43),
        )
        .unwrap();
    worker
        .enqueue(100, "model".into(), second, key, malicious)
        .unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert!(
        observed
            .outcomes
            .iter()
            .all(|item| matches!(item.result, Err(BatchWorkerErrorV1::Authority)))
    );
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    assert_eq!(worker.pending(), 0);
}

#[test]
fn native_batch_backend_absence_fails_closed_instead_of_sequential_fallback() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[39; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    let first_grant = signed_member(&signer, one, "grant-1", 45);
    let second_grant = signed_member(&signer, two, "grant-2", 46);
    {
        let mut worker = runner_with_driver(&signer, dir.path(), model.clone(), Driver, 2);
        worker
            .enqueue(
                100,
                "model".into(),
                first.clone(),
                key.clone(),
                first_grant.clone(),
            )
            .unwrap();
        worker
            .enqueue(
                100,
                "model".into(),
                second.clone(),
                key.clone(),
                second_grant.clone(),
            )
            .unwrap();
        let observed = worker.poll_and_execute(101).unwrap();
        assert_eq!(observed.outcomes.len(), 2);
        assert!(
            observed
                .outcomes
                .iter()
                .all(|item| matches!(item.result, Err(BatchWorkerErrorV1::BatchUnsupported)))
        );
        assert_eq!(worker.pending(), 0);
    }

    // The unsupported driver never entered a model call, so its grants
    // were not consumed. Reopen the actual durable authority journal with
    // a newly selected batch-capable backend; the exact grants remain valid.
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut recovered = runner_with_driver(&signer, dir.path(), model, driver, 2);
    recovered
        .enqueue(200, "model".into(), first, key.clone(), first_grant)
        .unwrap();
    recovered
        .enqueue(200, "model".into(), second, key, second_grant)
        .unwrap();
    let completed = recovered.poll_and_execute(201).unwrap();
    assert_eq!(completed.outcomes.len(), 2);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    for item in &completed.outcomes {
        let receipt = item.result.as_ref().expect("authorized native batch");
        assert_eq!(receipt.status, NeuronFeatureTerminalStatusV1::Succeeded);
    }
}

#[test]
fn native_batch_malformed_result_count_cannot_be_partially_committed() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[40; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: true,
        reorder_outputs: false,
    };
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            first,
            key.clone(),
            signed_member(&signer, one, "grant-1", 47),
        )
        .unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            second,
            key,
            signed_member(&signer, two, "grant-2", 48),
        )
        .unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert!(
        observed
            .outcomes
            .iter()
            .all(|item| matches!(item.result, Err(BatchWorkerErrorV1::Worker)))
    );
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
            reorder_outputs: false,
        };
        let mut initial = runner_with_driver(&signer, dir.path(), model.clone(), driver, 2);
        initial
            .enqueue(
                100,
                "model".into(),
                first.clone(),
                key.clone(),
                first_grant.clone(),
            )
            .unwrap();
        initial
            .enqueue(
                100,
                "model".into(),
                second.clone(),
                key.clone(),
                second_grant.clone(),
            )
            .unwrap();
        let failed = initial.poll_and_execute(101).unwrap();
        assert_eq!(failed.outcomes.len(), 2);
        assert!(
            failed
                .outcomes
                .iter()
                .all(|x| matches!(x.result, Err(BatchWorkerErrorV1::Worker)))
        );
    }
    // The authoritative nonce journal is reopened, not reset. Previously
    // signed grants cannot trigger a duplicate external effect.
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: false,
        reorder_outputs: false,
    };
    let mut recovered = runner_with_driver(&signer, dir.path(), model, driver, 2);
    recovered
        .enqueue(200, "model".into(), first, key.clone(), first_grant)
        .unwrap();
    recovered
        .enqueue(200, "model".into(), second, key, second_grant)
        .unwrap();
    let denied = recovered.poll_and_execute(201).unwrap();
    assert_eq!(denied.outcomes.len(), 2);
    assert!(
        denied
            .outcomes
            .iter()
            .all(|x| matches!(x.result, Err(BatchWorkerErrorV1::Authority)))
    );
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
}

#[test]
fn native_batch_reordered_backend_results_are_denied_without_partial_receipts() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[57; 32]);
    let (model, first, key) = fixture_request();
    let second = second_request(&first);
    let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = NativeTestDriver {
        invocations: calls.clone(),
        truncate_outputs: false,
        reorder_outputs: true,
    };
    let mut worker = runner_with_driver(&signer, dir.path(), model, driver, 2);
    let one = neuron_batch_final_use_binding_v1("worker-one", &key, &first).unwrap();
    let two = neuron_batch_final_use_binding_v1("worker-one", &key, &second).unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            first,
            key.clone(),
            signed_member(&signer, one, "grant-1", 58),
        )
        .unwrap();
    worker
        .enqueue(
            100,
            "model".into(),
            second,
            key,
            signed_member(&signer, two, "grant-2", 59),
        )
        .unwrap();
    let observed = worker.poll_and_execute(101).unwrap();
    assert_eq!(observed.outcomes.len(), 2);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert!(
        observed
            .outcomes
            .iter()
            .all(|x| matches!(x.result, Err(BatchWorkerErrorV1::Worker)))
    );
}
