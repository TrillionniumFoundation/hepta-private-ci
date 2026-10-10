use super::*;
use crate::model_worker::{
    DriverModelHandle, DriverNeuronFeatureObservation, DriverRunObservation,
    Error, ModelManifest, ResourceGrant, WorkerRequest,
};
use codex_hepta_contracts::{FinalUseGrant, FinalUseRevocations};
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_types::Generation;
use ed25519_dalek::{Signer, SigningKey};
use std::collections::BTreeSet;
use std::time::{SystemTime, UNIX_EPOCH};

struct Driver;

impl ModelDriver for Driver {
    fn load(&mut self, _manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        Ok(DriverModelHandle { opaque_id: "loaded".into(), observed_memory_bytes: 1024 })
    }
    fn run(
        &mut self, _handle: &DriverModelHandle, _request: &WorkerRequest
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure("generic path not admitted".into()))
    }
    fn unload(&mut self, _handle: DriverModelHandle) -> Result<(), Error> { Ok(()) }
}

impl NeuronFeatureDriver for Driver {
    fn run_neuron_features(
        &mut self, _handle: &DriverModelHandle, req: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true, succeeded: true,
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

fn digest(label: &[u8]) -> Digest32 { Digest32::of_bytes(label) }

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
    signing_key: &SigningKey, directory: &std::path::Path,
    model: ModelManifest,
) -> AuthenticatedNeuronMicrobatchWorkerV1<Driver> {
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority = FinalUseAuthority::open_state_dir(
        directory, "security-owner".into(),
        signing_key.verifying_key().to_bytes(), head,
    ).unwrap();
    let grant = ResourceGrant {
        grant_id: "resource".into(), authority_epoch: 9, generation: 3,
        expires_at_ms: 10_000, revoked: false, maximum_models: 2,
        maximum_active_requests: 4, maximum_memory_bytes: 4096,
        semantic_digest: digest(b"resource-grant").to_string(),
    };
    let mut worker = InferenceWorker::new(
        100, "worker-one".into(), 3, grant, Driver,
    ).unwrap();
    worker.load_model(100, model).unwrap();
    AuthenticatedNeuronMicrobatchWorkerV1::new(
        worker, authority,
        MicrobatchLimitsV1 {
            max_pending: 10, max_batch_size: 1,
            max_lanes_per_poll: 4, max_wait_ms: 5,
        }
    ).unwrap()
}

fn signed(
    signing_key: &SigningKey,
    binding: FinalUseBinding,
) -> SignedFinalUseGrant {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64;
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
    let signature = signing_key.sign(&grant.signing_bytes().unwrap()).to_bytes().to_vec();
    SignedFinalUseGrant { grant, signature }
}

#[test]
fn signed_batch_executes_driver_once_then_rejects_duplicate() {
    let dir = tempfile::tempdir().unwrap();
    let signer = SigningKey::from_bytes(&[17; 32]);
    let (model, request, key) = fixture_request();
    let binding = neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap();
    let mut execution = runner(&signer, dir.path(), model);
    execution.enqueue(
        100, "model".into(), request.clone(), key.clone(), signed(&signer, binding)
    ).unwrap();
    let completed = execution.poll_and_execute(101).unwrap();
    assert_eq!(completed.outcomes.len(), 1);
    let receipt = completed.outcomes[0].result.as_ref().unwrap();
    assert_eq!(receipt.status, NeuronFeatureTerminalStatusV1::Succeeded);
    assert_eq!(execution.pending(), 0);
    assert_eq!(
        execution.enqueue(
            102, "model".into(), request, key,
            completed_signed_dummy(&signer)
        ),
        Err(BatchWorkerErrorV1::Duplicate)
    );
}

fn completed_signed_dummy(signer: &SigningKey) -> SignedFinalUseGrant {
    let (_, request, key) = fixture_request();
    signed(signer, neuron_batch_final_use_binding_v1("worker-one", &key, &request).unwrap())
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
    execution.enqueue(100, "model".into(), request, key, grant).unwrap();
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
    execution.enqueue(100, "model".into(), request, key.clone(), signed(&signer, binding)).unwrap();
    let removed = execution.fence_scope(
        &key.scope_id, key.generation, 3, key.authority_epoch
    );
    assert_eq!(removed, vec![StableId::new("req-one").unwrap()]);
    let outcome = execution.poll_and_execute(101).unwrap();
    assert!(outcome.outcomes.is_empty());
    assert_eq!(execution.pending(), 0);
}
