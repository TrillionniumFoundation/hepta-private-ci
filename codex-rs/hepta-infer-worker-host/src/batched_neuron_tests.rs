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

#[derive(Debug)]
struct FixtureRouteGuardV1;

#[derive(Debug)]
struct FixtureCurrentScopeRoutesV1;

impl CurrentScopeRoutePortV1 for FixtureCurrentScopeRoutesV1 {
    fn enter_exact_route(
        &self,
        _key: &MicrobatchKeyV1,
    ) -> Result<Box<dyn ScopedRouteEffectGuardV1>, BatchWorkerErrorV1> {
        // Qualification mock only: production must use the actual CNS owner
        // and atomically hold its route cutover fence until this drops.
        Ok(Box::new(FixtureRouteGuardV1))
    }
}

#[derive(Debug)]
struct SingleStaleScopeRoutesV1 {
    stale_scope: StableId,
}

impl CurrentScopeRoutePortV1 for SingleStaleScopeRoutesV1 {
    fn enter_exact_route(
        &self,
        key: &MicrobatchKeyV1,
    ) -> Result<Box<dyn ScopedRouteEffectGuardV1>, BatchWorkerErrorV1> {
        if key.scope_id == self.stale_scope {
            return Err(BatchWorkerErrorV1::StaleRoute);
        }
        Ok(Box::new(FixtureRouteGuardV1))
    }
}

#[derive(Debug)]
struct FixtureMetricSink {
    reject_records: bool,
}

impl codex_hepta_types::PhaseMetricSinkV1 for FixtureMetricSink {
    fn record(
        &self,
        _sample: codex_hepta_types::PhaseMetricEventV1,
    ) -> Result<(), codex_hepta_types::PhaseMetricSinkErrorV1> {
        if self.reject_records {
            Err(codex_hepta_types::PhaseMetricSinkErrorV1::Backpressure)
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

struct Driver {
    batch_calls: std::sync::Arc<std::sync::atomic::AtomicUsize>,
}

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
    runner_with_counter(
        signing_key,
        directory,
        model,
        batch_size,
        std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0)),
    )
}

fn runner_with_counter(
    signing_key: &SigningKey,
    directory: &std::path::Path,
    model: ModelManifest,
    batch_size: usize,
    batch_calls: std::sync::Arc<std::sync::atomic::AtomicUsize>,
) -> AuthenticatedNeuronMicrobatchWorkerV1<Driver> {
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
    let mut worker =
        InferenceWorker::new(100, "worker-one".into(), 3, grant, Driver { batch_calls }).unwrap();
    worker.load_model(100, model).unwrap();
    AuthenticatedNeuronMicrobatchWorkerV1::new(
        worker,
        authority,
        MicrobatchLimitsV1 {
            max_pending: 10,
            max_batch_size: batch_size,
            max_lanes_per_poll: 4,
            max_wait_ms: 5,
        },
    )
    .unwrap()
    .with_metric_sink(std::sync::Arc::new(FixtureMetricSink {
        reject_records: false,
    }))
    .with_current_scope_routes(std::sync::Arc::new(FixtureCurrentScopeRoutesV1))
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

impl crate::model_worker::NeuronPhysicalBatchDriver for Driver {
    fn run_neuron_feature_batch(
        &mut self,
        _handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<crate::model_worker::PhysicalBatchRunObservationV1, Error> {
        // Conformance fixture only; physical forward evidence requires hardware.
        self.batch_calls
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        let items = requests
            .iter()
            .map(
                |request| crate::model_worker::PhysicalBatchItemObservationV1 {
                    request_id: request.authorization.request_id.clone(),
                    payload_digest: request.authorization.payload_digest.clone(),
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
        Ok(crate::model_worker::PhysicalBatchRunObservationV1 {
            submission_digest: crate::model_worker::canonical_physical_batch_submission_digest_v1(
                "worker-one",
                "model",
                3,
                requests,
            )
            .to_string(),
            batch_execution_digest: digest(b"mock-batch-call").to_string(),
            claimed_encoder_forward_count: 1,
            observed_peak_memory_bytes: 3072,
            items,
        })
    }
}

#[test]
fn one_backend_batch_call_requires_three_independent_signed_claims() {
    let temp = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[27; 32]);
    let (model, fixture, key) = fixture_request();
    let calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut owner = runner_with_counter(&signer, temp.path(), model, 3, calls.clone());
    let before = calls.load(std::sync::atomic::Ordering::SeqCst);
    for index in 0_u8..3 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("physical-req-{index}");
        request.authorization.reservation_id = format!("physical-reservation-{index}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut signed_grant = signed(&signer, binding);
        signed_grant.grant.grant_id = format!("physical-grant-{index}");
        signed_grant.grant.nonce = [index + 31; 32];
        signed_grant.signature = signer
            .sign(&signed_grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        owner
            .enqueue(100, "model".into(), request, key.clone(), signed_grant)
            .unwrap();
    }
    let result = owner.poll_and_execute_physical(101).unwrap();
    assert_eq!(result.outcomes.len(), 3);
    assert_eq!(result.pending, 0);
    assert!(result.outcomes.iter().all(|item| {
        matches!(
            &item.result,
            Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
        )
    }));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), before + 1);
}

#[test]
fn one_invalid_signature_fences_entire_physical_group_before_backend() {
    let temp = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[29; 32]);
    let (model, fixture, key) = fixture_request();
    let calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut owner = runner_with_counter(&signer, temp.path(), model, 3, calls.clone());
    let before = calls.load(std::sync::atomic::Ordering::SeqCst);
    for index in 0_u8..3 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("denied-req-{index}");
        request.authorization.reservation_id = format!("denied-reservation-{index}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut signed_grant = signed(&signer, binding);
        signed_grant.grant.grant_id = format!("denied-grant-{index}");
        signed_grant.grant.nonce = [index + 51; 32];
        signed_grant.signature = signer
            .sign(&signed_grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        if index == 2 {
            signed_grant.signature[0] ^= 1;
        }
        owner
            .enqueue(100, "model".into(), request, key.clone(), signed_grant)
            .unwrap();
    }
    let result = owner.poll_and_execute_physical(101).unwrap();
    assert_eq!(result.outcomes.len(), 3);
    assert!(
        result
            .outcomes
            .iter()
            .all(|item| { item.result.as_ref().err() == Some(&BatchWorkerErrorV1::Authority) })
    );
    assert_eq!(result.pending, 0);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), before);
}

#[test]
fn physical_backend_coalesces_three_scopes_without_merging_final_use_authority() {
    let temp = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[41; 32]);
    let (model, fixture, base) = fixture_request();
    let calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut owner = runner_with_counter(&signer, temp.path(), model, 3, calls.clone());
    for index in 0_u8..3 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("cross-scope-{index}");
        request.authorization.reservation_id = format!("cross-reservation-{index}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let mut key = base.clone();
        key.scope_id = StableId::new(format!("scope-{index}")).unwrap();
        key.route_fence = 10 + u64::from(index);
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut signed_grant = signed(&signer, binding);
        signed_grant.grant.grant_id = format!("cross-grant-{index}");
        signed_grant.grant.nonce = [index + 71; 32];
        signed_grant.signature = signer
            .sign(&signed_grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        owner
            .enqueue(100, "model".into(), request, key, signed_grant)
            .unwrap();
    }

    // All three independent scope lanes become ready after max_wait_ms.
    let result = owner.poll_and_execute_physical(106).unwrap();
    assert_eq!(result.outcomes.len(), 3);
    assert_eq!(result.pending, 0);
    assert!(result.outcomes.iter().all(|item| {
        matches!(
            &item.result,
            Ok(receipt) if receipt.status == NeuronFeatureTerminalStatusV1::Succeeded
        )
    }));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
}

#[test]
fn telemetry_commit_error_preserves_result_and_fences_future_physical_batches() {
    let temp = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[43; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut owner = runner(&signer, temp.path(), model).with_metric_sink(std::sync::Arc::new(
        FixtureMetricSink {
            reject_records: true,
        },
    ));
    owner
        .enqueue(100, "model".into(), request, key, signed(&signer, binding))
        .unwrap();
    let first = owner.poll_and_execute_physical(101).unwrap();
    assert_eq!(first.outcomes.len(), 1);
    assert!(first.outcomes[0].result.is_ok());
    // The completed external effect must not be retried just because the
    // metric writer failed. Instead, the next physical attempt is denied.
    assert!(matches!(
        owner.poll_and_execute_physical(102),
        Err(BatchWorkerErrorV1::TelemetryUnavailable)
    ));
}

#[test]
fn legacy_group_commit_failure_denies_remaining_intents_without_claiming_them() {
    let temp = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[45; 32]);
    let (model, fixture, key) = fixture_request();
    let mut owner = runner_with_batch_size(&signer, temp.path(), model, 2).with_metric_sink(
        std::sync::Arc::new(FixtureMetricSink {
            reject_records: true,
        }),
    );

    for index in 0_u8..2 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("metric-failure-{index}");
        request.authorization.reservation_id = format!("metric-reservation-{index}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("metric-grant-{index}");
        grant.grant.nonce = [index + 91; 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        owner
            .enqueue(100, "model".into(), request, key.clone(), grant)
            .unwrap();
    }

    let completed = owner.poll_and_execute(101).unwrap();
    assert_eq!(completed.outcomes.len(), 2);
    assert!(completed.outcomes[0].result.is_ok());
    assert!(matches!(
        &completed.outcomes[1].result,
        Err(BatchWorkerErrorV1::TelemetryUnavailable)
    ));
    assert_eq!(completed.pending, 0);
    // The second grant did not enter the signed final-use effect.
    assert_eq!(owner.authority.capacity().unwrap().used_nonces, 1);

    // Replacing the observer cannot erase the generation's lost metric.
    let mut owner = owner.with_metric_sink(std::sync::Arc::new(FixtureMetricSink {
        reject_records: false,
    }));
    let mut new_request = fixture;
    new_request.authorization.request_id = "post-metric-fault".to_owned();
    new_request.authorization.reservation_id = "post-metric-reservation".to_owned();
    let payload = canonical_neuron_feature_payload_digest(&new_request);
    new_request.authorization.payload_digest = payload.clone();
    new_request.authorization.lease_payload_digest = payload;
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &new_request).unwrap();
    assert_eq!(
        owner.enqueue(
            102,
            "model".to_owned(),
            new_request,
            key,
            signed(&signer, binding),
        ),
        Err(BatchWorkerErrorV1::TelemetryUnavailable)
    );
    assert!(matches!(
        owner.poll_and_execute(102),
        Err(BatchWorkerErrorV1::TelemetryUnavailable)
    ));
}


#[test]
fn physical_batch_without_current_cns_route_owner_denies_before_nonce_claim() {
    let directory = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[57; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut owner = runner(&signer, directory.path(), model);
    owner.scope_routes = None;
    owner
        .enqueue(100, "model".to_owned(), request, key, signed(&signer, binding))
        .unwrap();
    assert!(matches!(
        owner.poll_and_execute_physical(101),
        Err(BatchWorkerErrorV1::RouteUnavailable)
    ));
    assert_eq!(owner.pending(), 1);
    assert_eq!(owner.authority.capacity().unwrap().used_nonces, 0);
}

#[test]
fn stale_scope_cutover_denies_entire_cross_scope_batch_without_any_nonce_claim() {
    let directory = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[59; 32]);
    let (model, fixture, key) = fixture_request();
    let stale_scope = StableId::new("scope-cutover").unwrap();
    let calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut owner = runner_with_counter(&signer, directory.path(), model, 2, calls.clone())
        .with_current_scope_routes(std::sync::Arc::new(SingleStaleScopeRoutesV1 {
            stale_scope: stale_scope.clone(),
        }));
    for index in 0_u8..2 {
        let mut request = fixture.clone();
        request.authorization.request_id = format!("cutover-request-{index}");
        request.authorization.reservation_id = format!("cutover-reservation-{index}");
        let payload = canonical_neuron_feature_payload_digest(&request);
        request.authorization.payload_digest = payload.clone();
        request.authorization.lease_payload_digest = payload;
        let mut scoped = key.clone();
        scoped.scope_id = if index == 0 {
            StableId::new("scope-live").unwrap()
        } else {
            stale_scope.clone()
        };
        scoped.route_fence = u64::from(index) + 10;
        let binding = neuron_batch_final_use_binding_v1("worker-one", &scoped, &request).unwrap();
        let mut grant = signed(&signer, binding);
        grant.grant.grant_id = format!("cutover-grant-{index}");
        grant.grant.nonce = [index + 101; 32];
        grant.signature = signer
            .sign(&grant.grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        owner
            .enqueue(100, "model".to_owned(), request, scoped, grant)
            .unwrap();
    }
    let result = owner.poll_and_execute_physical(106).unwrap();
    assert_eq!(result.outcomes.len(), 2);
    assert_eq!(result.pending, 0);
    assert!(result.outcomes.iter().all(|item| {
        item.result.as_ref().err() == Some(&BatchWorkerErrorV1::StaleRoute)
    }));
    assert_eq!(owner.authority.capacity().unwrap().used_nonces, 0);
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
}
