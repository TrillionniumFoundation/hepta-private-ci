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
use codex_hepta_types::PhaseMetricSinkErrorV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Debug, Default)]
struct RecordedSink(std::sync::Mutex<Vec<PhaseMetricEventV1>>);

impl PhaseMetricSinkV1 for RecordedSink {
    fn record(&self, event: PhaseMetricEventV1) -> Result<(), PhaseMetricSinkErrorV1> {
        self.0
            .lock()
            .map_err(|_| PhaseMetricSinkErrorV1::Unavailable)?
            .push(event);
        Ok(())
    }

    fn healthy(&self) -> bool {
        self.0.lock().is_ok()
    }

    fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        if self.healthy() {
            Ok(())
        } else {
            Err(PhaseMetricSinkErrorV1::Unavailable)
        }
    }
}

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

fn runner(
    signing_key: &SigningKey,
    directory: &std::path::Path,
    model: ModelManifest,
) -> AuthenticatedNeuronMicrobatchWorkerV1<Driver> {
    runner_with_batch_size(signing_key, directory, model, 1)
}

fn runner_with_batch_size(
    signing_key: &SigningKey,
    directory: &std::path::Path,
    model: ModelManifest,
    batch_size: usize,
) -> AuthenticatedNeuronMicrobatchWorkerV1<Driver> {
    runner_with_batch_size_and_driver(signing_key, directory, model, batch_size, Driver)
}

#[derive(Debug)]
struct TestScopeFrontier(std::sync::Mutex<MicrobatchKeyV1>);

impl MicrobatchScopeFrontierV1 for TestScopeFrontier {
    fn current(&self, scope: &StableId) -> Result<MicrobatchKeyV1, BatchWorkerErrorV1> {
        let current = self
            .0
            .lock()
            .map_err(|_| BatchWorkerErrorV1::InvalidBinding)?;
        if &current.scope_id != scope {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        Ok(current.clone())
    }
}

fn runner_with_batch_size_and_driver<D: ModelDriver + NeuronFeatureDriver>(
    signing_key: &SigningKey,
    directory: &std::path::Path,
    model: ModelManifest,
    batch_size: usize,
    driver: D,
) -> AuthenticatedNeuronMicrobatchWorkerV1<D> {
    let key = MicrobatchKeyV1 {
        scope_id: StableId::new("scope").unwrap(),
        model_digest: Digest32::from_str(&model.model_digest).unwrap(),
        generation: Generation::new(3).unwrap(),
        route_fence: 2,
        authority_epoch: 9,
    };
    runner_with_scope_frontier(
        signing_key,
        directory,
        model,
        batch_size,
        driver,
        std::sync::Arc::new(TestScopeFrontier(std::sync::Mutex::new(key))),
    )
}

fn runner_with_scope_frontier<D: ModelDriver + NeuronFeatureDriver>(
    signing_key: &SigningKey,
    directory: &std::path::Path,
    model: ModelManifest,
    batch_size: usize,
    driver: D,
    scope_frontier: std::sync::Arc<dyn MicrobatchScopeFrontierV1>,
) -> AuthenticatedNeuronMicrobatchWorkerV1<D> {
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
        scope_frontier,
        MicrobatchLimitsV1 {
            max_pending: 10,
            max_batch_size: batch_size,
            max_lanes_per_poll: 4,
            max_wait_ms: 5,
        },
    )
    .unwrap()
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
    let metrics = std::sync::Arc::new(RecordedSink::default());
    let mut execution = runner(&signer, dir.path(), model).with_metric_sink(metrics.clone());
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
    let samples = metrics.0.lock().unwrap();
    assert_eq!(
        samples
            .iter()
            .map(|sample| (sample.phase, sample.succeeded))
            .collect::<Vec<_>>(),
        vec![
            (PhaseMetricKindV1::Admission, true),
            (PhaseMetricKindV1::Microbatch, true),
            (PhaseMetricKindV1::NeuronFeature, true),
            (PhaseMetricKindV1::Admission, false),
        ]
    );
}

#[test]
fn multi_request_batch_records_each_member_in_all_three_metric_phases() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[81; 32]);
    let (model, original, key) = fixture_request();
    let metrics = std::sync::Arc::new(RecordedSink::default());
    let mut worker =
        runner_with_batch_size(&signer, dir.path(), model, 2).with_metric_sink(metrics.clone());
    let mut request_digests = Vec::new();
    for index in 0_u8..2 {
        let mut request = original.clone();
        request.authorization.request_id = format!("metric-member-{index}");
        request.authorization.reservation_id = format!("metric-reservation-{index}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("metric-grant-{index}");
        grant.grant.nonce = [index + 1; 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        request_digests.push(Digest32::of_bytes(
            request.authorization.request_id.as_bytes(),
        ));
        worker
            .enqueue(100, "model".into(), request, key.clone(), grant)
            .unwrap();
    }
    let polled = worker.poll_and_execute(101).unwrap();
    assert_eq!(polled.outcomes.len(), 2);
    assert!(polled.outcomes.iter().all(|outcome| matches!(
        &outcome.result,
        Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
    )));
    assert!(worker.production_metrics_ready());

    let events = metrics.0.lock().unwrap();
    assert_eq!(events.len(), 6);
    for phase in [
        PhaseMetricKindV1::Admission,
        PhaseMetricKindV1::Microbatch,
        PhaseMetricKindV1::NeuronFeature,
    ] {
        assert_eq!(events.iter().filter(|event| event.phase == phase).count(), 2);
    }
    for request in request_digests {
        assert_eq!(
            events
                .iter()
                .filter(|event| event.operation_digest == request)
                .count(),
            3,
        );
    }
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

#[test]
fn same_lane_three_item_group_preserves_independent_final_use_nonces() {
    // Scheduling a three-item group must not accidentally reuse one signed
    // grant or bypass the native one-request-at-a-time model driver.
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[23; 32]);
    let (model, fixture, key) = fixture_request();
    let mut execution = runner_with_batch_size(&signer, dir.path(), model, 3);
    for i in 0_u8..3 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("req-{i}");
        request.authorization.reservation_id = format!("reservation-{i}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("neuron-feature-{i}");
        grant.grant.nonce = [i + 1; 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        execution
            .enqueue(100, "model".to_owned(), request, key.clone(), grant)
            .unwrap();
    }
    assert_eq!(execution.pending(), 3);
    let completed = execution.poll_and_execute(101).unwrap();
    assert_eq!(completed.outcomes.len(), 3);
    assert_eq!(completed.pending, 0);
    assert_eq!(
        completed
            .outcomes
            .iter()
            .map(|o| o.request_id.clone())
            .collect::<BTreeSet<_>>()
            .len(),
        3
    );
    assert!(completed.outcomes.iter().all(|outcome| {
        matches!(
            outcome.result,
            Ok(ref receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
        )
    }));
    // This verifies admission grouping, not physical backend batching.
}

#[derive(Debug)]
struct UnavailableMetricSink;

impl PhaseMetricSinkV1 for UnavailableMetricSink {
    fn record(&self, _event: PhaseMetricEventV1) -> Result<(), PhaseMetricSinkErrorV1> {
        Err(PhaseMetricSinkErrorV1::Unavailable)
    }

    fn healthy(&self) -> bool {
        true
    }

    fn flush(&self) -> Result<(), PhaseMetricSinkErrorV1> {
        Err(PhaseMetricSinkErrorV1::Unavailable)
    }
}

#[test]
fn worker_metrics_failures_latch_not_ready_without_retrying_authorized_effect() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[27; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut execution = runner(&signer, dir.path(), model);
    assert!(!execution.production_metrics_ready());
    assert!(!execution.flush_production_metrics());
    execution = execution.with_metric_sink(Arc::new(UnavailableMetricSink));
    assert!(execution.production_metrics_ready());
    // Admission succeeds even though non-authorizing telemetry fails.
    execution
        .enqueue(
            100,
            "model".to_string(),
            request,
            key,
            signed(&signer, binding),
        )
        .unwrap();
    assert!(!execution.production_metrics_ready());
    assert!(!execution.flush_production_metrics());
    let completed = execution.poll_and_execute(101).unwrap();
    assert_eq!(completed.outcomes.len(), 1);
    assert!(matches!(
        &completed.outcomes[0].result,
        Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
    ));
    assert_eq!(execution.pending(), 0);
    assert!(!execution.production_metrics_ready());
}

#[test]
fn terminal_replay_capacity_is_independent_of_active_microbatch_capacity() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[29; 32]);
    let (model, fixture, key) = fixture_request();
    // The test worker allows only ten simultaneous pending requests. Twelve
    // successive terminal requests must not exhaust the pending budget.
    let mut execution = runner(&signer, dir.path(), model);
    for i in 0_u8..12 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("req-{i}");
        request.authorization.reservation_id = format!("reservation-{i}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("one-shot-{i}");
        grant.grant.nonce = [i + 1; 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        execution
            .enqueue(
                100 + u64::from(i),
                "model".to_string(),
                request,
                key.clone(),
                grant,
            )
            .unwrap();
        let completed = execution.poll_and_execute(101 + u64::from(i)).unwrap();
        assert_eq!(completed.outcomes.len(), 1);
        assert!(matches!(
            &completed.outcomes[0].result,
            Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
        ));
        assert_eq!(execution.pending(), 0);
    }
    assert_eq!(execution.retired.len(), 12);
    let mut replay = fixture;
    replay.authorization.request_id = "req-0".to_string();
    replay.authorization.reservation_id = "reservation-0".to_string();
    let payload = canonical_neuron_feature_payload_digest(&replay);
    replay.authorization.payload_digest = payload.clone();
    replay.authorization.lease_payload_digest = payload;
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &replay).unwrap();
    assert_eq!(
        execution.enqueue(
            120,
            "model".to_string(),
            replay,
            key,
            signed(&signer, binding)
        ),
        Err(BatchWorkerErrorV1::Duplicate)
    );
}

#[derive(Clone)]
struct PhysicalBatchDriver {
    backend_calls: std::sync::Arc<std::sync::atomic::AtomicUsize>,
    scalar_calls: std::sync::Arc<std::sync::atomic::AtomicUsize>,
}

impl ModelDriver for PhysicalBatchDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        let mut driver = Driver;
        driver.load(manifest)
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::FeatureContract)
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        Ok(())
    }
}

impl NeuronFeatureDriver for PhysicalBatchDriver {
    fn run_neuron_features(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.scalar_calls
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Err(Error::FeatureContract)
    }

    fn supports_physical_neuron_batch(&self) -> bool {
        true
    }

    fn run_neuron_features_batch(
        &mut self,
        _handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureObservation>, Error> {
        self.backend_calls
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Ok(requests
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
            .collect())
    }
}

#[test]
fn three_authorized_neuron_items_enter_one_physical_batch_driver_invocation() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[44; 32]);
    let (model, fixture, key) = fixture_request();
    let backend_calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let scalar_calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = PhysicalBatchDriver {
        backend_calls: backend_calls.clone(),
        scalar_calls: scalar_calls.clone(),
    };
    let metrics = std::sync::Arc::new(RecordedSink::default());
    let mut execution = runner_with_batch_size_and_driver(&signer, dir.path(), model, 3, driver)
        .with_metric_sink(metrics.clone());
    for i in 0_u8..3 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("batch-request-{i}");
        request.authorization.reservation_id = format!("batch-reservation-{i}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("physical-batch-{i}");
        grant.grant.nonce = [i + 1; 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        execution
            .enqueue(100, "model".into(), request, key.clone(), grant)
            .unwrap();
    }
    let poll = execution.poll_and_execute(101).unwrap();
    assert_eq!(poll.outcomes.len(), 3);
    assert!(poll.outcomes.iter().all(|item| {
        matches!(
            &item.result,
            Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
        )
    }));
    assert_eq!(backend_calls.load(std::sync::atomic::Ordering::Relaxed), 1);
    assert_eq!(scalar_calls.load(std::sync::atomic::Ordering::Relaxed), 0);
    assert_eq!(execution.pending(), 0);
    let samples = metrics.0.lock().unwrap();
    assert_eq!(samples.len(), 9);
    for phase in [
        PhaseMetricKindV1::Admission,
        PhaseMetricKindV1::Microbatch,
        PhaseMetricKindV1::NeuronFeature,
    ] {
        assert_eq!(
            samples.iter().filter(|sample| sample.phase == phase).count(),
            3,
        );
    }
}

#[test]
fn invalid_signed_grant_is_excluded_before_native_backend_batch_entry() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[45; 32]);
    let (model, fixture, key) = fixture_request();
    let backend_calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let scalar_calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = PhysicalBatchDriver {
        backend_calls: backend_calls.clone(),
        scalar_calls: scalar_calls.clone(),
    };
    let mut execution = runner_with_batch_size_and_driver(&signer, dir.path(), model, 3, driver);
    for i in 0_u8..3 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("invalid-grant-{i}");
        request.authorization.reservation_id = format!("invalid-reservation-{i}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("verified-grant-{i}");
        grant.grant.nonce = [i + 1; 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        if i == 1 {
            grant.signature[0] ^= 1;
        }
        execution
            .enqueue(100, "model".into(), request, key.clone(), grant)
            .unwrap();
    }
    let poll = execution.poll_and_execute(101).unwrap();
    assert_eq!(poll.outcomes.len(), 3);
    assert!(poll.outcomes[0].result.is_ok());
    assert!(matches!(
        &poll.outcomes[1].result,
        Err(BatchWorkerErrorV1::Authority)
    ));
    assert!(poll.outcomes[2].result.is_ok());
    assert_eq!(backend_calls.load(std::sync::atomic::Ordering::Relaxed), 1);
    assert_eq!(scalar_calls.load(std::sync::atomic::Ordering::Relaxed), 0);
}

#[test]
fn external_control_fence_cutover_denies_queued_grant_without_driver_effect() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[46; 32]);
    let (model, request, key) = fixture_request();
    let scope_frontier = std::sync::Arc::new(TestScopeFrontier(std::sync::Mutex::new(key.clone())));
    let backend_calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let scalar_calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = PhysicalBatchDriver {
        backend_calls: backend_calls.clone(),
        scalar_calls: scalar_calls.clone(),
    };
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut execution = runner_with_scope_frontier(
        &signer,
        dir.path(),
        model,
        1,
        driver,
        scope_frontier.clone(),
    );
    execution
        .enqueue(
            100,
            "model".into(),
            request,
            key.clone(),
            signed(&signer, binding),
        )
        .unwrap();
    scope_frontier.0.lock().unwrap().route_fence += 1;
    let result = execution.poll_and_execute(101).unwrap();
    assert_eq!(result.outcomes.len(), 1);
    assert!(matches!(
        &result.outcomes[0].result,
        Err(BatchWorkerErrorV1::InvalidBinding)
    ));
    assert_eq!(backend_calls.load(std::sync::atomic::Ordering::Relaxed), 0);
    assert_eq!(scalar_calls.load(std::sync::atomic::Ordering::Relaxed), 0);
    assert_eq!(execution.pending(), 0);
}

#[cfg(unix)]
#[derive(Clone)]
struct CutoverDuringBackendDriver {
    frontier: std::sync::Arc<TestScopeFrontier>,
    calls: std::sync::Arc<std::sync::atomic::AtomicUsize>,
    physical: bool,
}

#[cfg(unix)]
impl ModelDriver for CutoverDuringBackendDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        let mut driver = Driver;
        driver.load(manifest)
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::FeatureContract)
    }

    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> {
        Ok(())
    }
}

#[cfg(unix)]
impl NeuronFeatureDriver for CutoverDuringBackendDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        self.calls
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let mut driver = Driver;
        let receipt = driver.run_neuron_features(handle, request)?;
        self.frontier.0.lock().unwrap().route_fence += 1;
        Ok(receipt)
    }

    fn supports_physical_neuron_batch(&self) -> bool {
        self.physical
    }

    fn run_neuron_features_batch(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureObservation>, Error> {
        self.calls
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let mut driver = Driver;
        let receipts = requests
            .iter()
            .map(|request| driver.run_neuron_features(handle, request))
            .collect::<Result<Vec<_>, _>>()?;
        self.frontier.0.lock().unwrap().route_fence += 1;
        Ok(receipts)
    }
}

/// The test driver advances the Control frontier *inside* a model invocation.
/// The underlying computation may have run; its stale success cannot escape
/// as a live receipt. Both paths consume terminal request identities.
#[cfg(unix)]
fn in_flight_scope_cutover_is_not_a_successful_result(batch_size: usize, physical: bool) {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[47; 32]);
    let (model, fixture, key) = fixture_request();
    let frontier = std::sync::Arc::new(TestScopeFrontier(std::sync::Mutex::new(key.clone())));
    let calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let driver = CutoverDuringBackendDriver {
        frontier: frontier.clone(),
        calls: calls.clone(),
        physical,
    };
    let mut execution =
        runner_with_scope_frontier(&signer, dir.path(), model, batch_size, driver, frontier);
    for i in 0..batch_size {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("inflight-cutover-{i}");
        request.authorization.reservation_id = format!("inflight-reservation-{i}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("cutover-grant-{i}");
        grant.grant.nonce = [u8::try_from(i + 1).unwrap(); 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        execution
            .enqueue(100, "model".into(), request, key.clone(), grant)
            .unwrap();
    }
    let finished = execution.poll_and_execute(101).unwrap();
    assert_eq!(calls.load(std::sync::atomic::Ordering::Relaxed), 1);
    assert_eq!(finished.outcomes.len(), batch_size);
    assert!(
        finished.outcomes.iter().all(|outcome| {
            matches!(&outcome.result, Err(BatchWorkerErrorV1::StaleAfterEffect))
        })
    );
    assert_eq!(execution.pending(), 0);
}

#[test]
#[cfg(unix)]
fn scalar_completion_after_scope_cutover_is_never_published() {
    in_flight_scope_cutover_is_not_a_successful_result(
        /*batch_size*/ 1, /*physical*/ false,
    );
}

#[test]
#[cfg(unix)]
fn physical_batch_completion_after_scope_cutover_denies_all_old_route_results() {
    in_flight_scope_cutover_is_not_a_successful_result(
        /*batch_size*/ 2, /*physical*/ true,
    );
}
