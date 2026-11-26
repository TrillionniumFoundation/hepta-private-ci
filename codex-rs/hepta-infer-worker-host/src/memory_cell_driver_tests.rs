use super::*;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ResourceGrant;
use crate::model_worker::canonical_neuron_feature_payload_digest;

fn fixture() -> (Vec<u8>, ModelManifest, MemoryCellBindingV1) {
    let binding = MemoryCellBindingV1 {
        encoder_digest: Digest32::of_bytes(b"test encoder"),
        dataset_digest: Digest32::of_bytes(b"test dataset"),
        scope_digest: Digest32::of_bytes(b"test scope"),
    };
    let circuit = Circuit {
        schema: "hepta.memory-circuit.v1".into(),
        encoder_digest: binding.encoder_digest.to_string(),
        dataset_digest: binding.dataset_digest.to_string(),
        scope_digest: binding.scope_digest.to_string(),
        output_profile: "relevance-state-five-v1".into(),
        dimension: 2,
        hidden: 1,
        semantic_weight: vec![1.0, -1.0],
        semantic_bias: vec![0.0],
        gate_weight: vec![0.0, 0.0],
        gate_bias: vec![0.0],
        procedural_weight: vec![0.0, 0.0, 1.0],
        procedural_bias: 0.0,
    };
    let bytes = serde_json::to_vec(&circuit).expect("fixture encoding");
    let manifest = ModelManifest {
        model_id: "cell.1".into(),
        model_digest: Digest32::of_bytes(b"manifest").to_string(),
        weights_digest: Digest32::of_bytes(&bytes).to_string(),
        tokenizer_digest: Digest32::of_bytes(b"pretrained tokenizer").to_string(),
        preprocessor_digest: Digest32::of_bytes(b"feature product").to_string(),
        quantization_digest: MemoryCellDriver::quantization_digest().to_string(),
        runtime_digest: MemoryCellDriver::runtime_digest().to_string(),
        device_digest: Digest32::of_bytes(b"test cpu").to_string(),
        maximum_tokens: 16,
    };
    (bytes, manifest, binding)
}
fn request(manifest: &ModelManifest, binding: &MemoryCellBindingV1) -> NeuronFeatureRequest {
    let mut req = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: "request.1".into(),
            reservation_id: "reservation.1".into(),
            model_digest: manifest.model_digest.clone(),
            payload_digest: "1".repeat(64),
            maximum_tokens: 1,
            deadline_ms: 100,
            lease_payload_digest: "1".repeat(64),
            reservation_model_digest: manifest.model_digest.clone(),
            reservation_maximum_tokens: 16,
            cancelled: false,
        },
        encoder_digest: binding.encoder_digest.to_string(),
        head_digest: MemoryCellDriver::head_digest().to_string(),
        weights_digest: manifest.weights_digest.clone(),
        input_digest: Digest32::of_bytes(b"input").to_string(),
        feature_vector_q24: vec![1 << 24, 0],
        expected_output_width: 5,
    };
    let payload = canonical_neuron_feature_payload_digest(&req);
    req.authorization.payload_digest = payload.clone();
    req.authorization.lease_payload_digest = payload;
    req
}
#[test]
fn learned_message_is_executed_through_worker_receipt_and_lease() {
    let (bytes, manifest, binding) = fixture();
    let driver =
        MemoryCellDriver::from_pinned_bytes(&bytes, manifest.clone(), &binding).expect("driver");
    let grant = ResourceGrant {
        grant_id: "grant.1".into(),
        authority_epoch: 1,
        generation: 1,
        expires_at_ms: 100,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 1,
        maximum_memory_bytes: 1 << 20,
        semantic_digest: Digest32::of_bytes(b"grant fixture").to_string(),
    };
    let mut worker = InferenceWorker::new(1, "worker.1".into(), 1, grant, driver).expect("worker");
    worker.load_model(1, manifest.clone()).expect("load");
    let receipt = worker
        .run_neuron_features_receipt(1, "cell.1", request(&manifest, &binding))
        .expect("receipt");
    let expected = ((1.0 / (1.0 + (-1_f64.tanh() / 2.0).exp())) * Q24).round() as i64;
    assert_eq!(
        &receipt.prediction_q24[..2],
        &[(1 << 24) - expected, expected]
    );
    let mut bad = request(&manifest, &binding);
    bad.authorization.lease_payload_digest = "f".repeat(64);
    assert_eq!(
        worker.run_neuron_features_receipt(1, "cell.1", bad),
        Err(Error::PayloadMismatch)
    );
    assert_eq!(
        worker.run_neuron_features_receipt(101, "cell.1", request(&manifest, &binding)),
        Err(Error::GrantExpired)
    );
}
#[test]
fn wrong_source_encoder_payload_and_partial_tensors_are_rejected() {
    let (bytes, manifest, mut binding) = fixture();
    binding.scope_digest = Digest32::of_bytes(b"another scope");
    assert!(MemoryCellDriver::from_pinned_bytes(&bytes, manifest.clone(), &binding).is_err());
    let (_, _, binding) = fixture();
    assert!(
        MemoryCellDriver::from_pinned_bytes(&bytes[..bytes.len() - 1], manifest.clone(), &binding)
            .is_err()
    );
    let mut c: Circuit = serde_json::from_slice(&bytes).expect("fixture");
    c.semantic_weight.pop();
    let bytes = serde_json::to_vec(&c).expect("encode");
    let mut manifest = manifest;
    manifest.weights_digest = Digest32::of_bytes(&bytes).to_string();
    assert!(MemoryCellDriver::from_pinned_bytes(&bytes, manifest, &binding).is_err());
}
