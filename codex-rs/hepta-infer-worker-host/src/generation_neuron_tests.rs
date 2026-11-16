use super::*;

use codex_hepta_infer_core::GenerationActionV1;
use codex_hepta_infer_core::generation_json_digest;

use crate::model_worker::ModelDriver;
use crate::model_worker::WorkerRequest;

fn registered() -> (
    tempfile::TempDir,
    GenerationDriver,
    GenerationNeuronBindingV1,
) {
    let (root, mut registration, mut raw) = super::super::tests::fixture();
    registration.pins.hidden = WIDTH;
    raw.model = registration.pins.clone();
    raw.actions = vec![GenerationActionV1::Couple];
    let raw_digest = generation_json_digest(&raw).expect("raw request");
    let driver = GenerationDriver::new(registration, vec![raw.clone()]).expect("driver");
    let manifest = driver.manifest().expect("manifest");
    let mut bytes = b"hepta.inference.generation-state.v1\0".to_vec();
    bytes.extend_from_slice(raw.model.snapshot_sha256.as_bytes());
    bytes.extend_from_slice("a".repeat(64).as_bytes());
    bytes.extend_from_slice(&(-2_i32).to_le_bytes());
    bytes.extend_from_slice(&[0; 4 * WIDTH * 4]);
    let previous_state = GenerationStateV1 {
        values_f32: vec![0; 4 * WIDTH],
        backend_state_sha256: "a".repeat(64),
        plan_index: None,
        state_sha256: Digest32::of_bytes(&bytes).to_string(),
    };
    let mut request = NeuronFeatureRequest {
        authorization: WorkerRequest {
            request_id: format!("ndu-neuron:{raw_digest}"),
            reservation_id: "registered-reservation".into(),
            model_digest: manifest.model_digest.clone(),
            payload_digest: String::new(),
            maximum_tokens: 8,
            deadline_ms: 90_000,
            lease_payload_digest: String::new(),
            reservation_model_digest: manifest.model_digest,
            reservation_maximum_tokens: 8,
            cancelled: false,
        },
        encoder_digest: raw.model.source_sha256,
        head_digest: generation_neuron_head_digest().to_string(),
        weights_digest: raw.model.parameters_sha256,
        input_digest: "5".repeat(64),
        feature_vector_q24: vec![0; WIDTH],
        expected_output_width: WIDTH,
    };
    let payload = canonical_neuron_feature_payload_digest(&request);
    request.authorization.payload_digest = payload.clone();
    request.authorization.lease_payload_digest = payload;
    (
        root,
        driver,
        GenerationNeuronBindingV1 {
            request,
            generation_request_sha256: raw_digest,
            previous_state,
        },
    )
}

#[test]
fn four_block_projection_preserves_each_component_without_clipping() {
    let mut state = GenerationStateV1 {
        values_f32: vec![0; 384],
        backend_state_sha256: "a".repeat(64),
        plan_index: None,
        state_sha256: "b".repeat(64),
    };
    let reference = (1.0_f64.tanh() * Q24).round() as i64;
    for block in 0..4 {
        state.values_f32.fill(0);
        state.values_f32[WIDTH * block] = 4.0_f32.to_bits();
        let mut expected = vec![0; WIDTH];
        expected[0] = reference;
        assert_eq!(
            project_generation_state(&state).expect("projection"),
            expected
        );
    }
    for value in [f32::NAN, f32::INFINITY, 8.1] {
        state.values_f32[0] = value.to_bits();
        assert!(project_generation_state(&state).is_err());
    }
}

#[test]
fn changed_full_state_rejects_even_when_projected_feature_is_unchanged() {
    let (_root, driver, mut binding) = registered();
    binding.previous_state.backend_state_sha256 = "c".repeat(64);
    assert!(driver.with_neuron_bindings(vec![binding]).is_err());
}

#[test]
fn changed_feature_or_insufficient_tokens_never_start_process() {
    let (_root, driver, binding) = registered();
    let raw_digest = binding.generation_request_sha256.clone();
    let mut driver = driver
        .with_neuron_bindings(vec![binding.clone()])
        .expect("feature registration");
    let manifest = driver.manifest().expect("manifest");
    let handle = driver.load(&manifest).expect("load");
    let mut bad = binding.request.clone();
    bad.input_digest = "9".repeat(64);
    assert_eq!(
        driver.run_neuron_features(&handle, &bad),
        Err(Error::PayloadMismatch)
    );
    for limit in 1..8 {
        let mut bad = binding.request.clone();
        bad.authorization.maximum_tokens = limit;
        assert_eq!(
            driver.run_neuron_features(&handle, &bad),
            Err(Error::TokenLimit)
        );
    }
    assert_eq!(driver.evidence().get(&raw_digest), None);
}
