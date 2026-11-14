use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::decode_neuron_tick_input_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use rrsnn_hepta_type_adapter::FeatureRequest;
use rrsnn_hepta_type_adapter::prepare_shadow_input;
use rrsnn_hepta_type_adapter::quantize_features;

fn request() -> FeatureRequest {
    serde_json::from_str(include_str!("../fixtures/feature_request.json")).unwrap()
}

#[test]
fn official_type_codec_and_digest_roundtrip() {
    let shadow = prepare_shadow_input(&request()).unwrap();
    let raw = serde_json::to_vec(&shadow.official_input).unwrap();
    let tick = decode_neuron_tick_input_v1(&raw).unwrap();
    assert_eq!(tick.feature_vector_q24, shadow.feature_vector_q24);
    assert_eq!(
        tick.semantic_digest().unwrap().to_string(),
        shadow.official_input_semantic_digest
    );
    assert!(shadow.maximum_absolute_quantization_error <= 0.5 / 16_777_216.0);
    assert!(!shadow.official_owner_executed);
    assert_eq!(shadow.official_runtime_receipt, None);
}

#[test]
fn ties_even_and_closed_range_are_explicit() {
    let q = 16_777_216.0;
    assert_eq!(
        quantize_features(&[0.5 / q, 1.5 / q, -0.5 / q, -1.5 / q, -8.0, 8.0]).unwrap(),
        vec![0, 2, 0, -2, -134_217_728, 134_217_728]
    );
    assert!(quantize_features(&[f64::NAN]).is_err());
    assert!(quantize_features(&[8.0 + 1.0 / q]).is_err());
    assert!(quantize_features(&vec![0.0; 513]).is_err());
}

#[test]
fn existing_v1_refuses_an_unregistered_physical_checkpoint_field() {
    let shadow = prepare_shadow_input(&request()).unwrap();
    let mut json = shadow.official_input;
    json["rrCheckpoint"] = serde_json::json!({"time": 1.0, "rng": []});
    assert!(decode_neuron_tick_input_v1(&serde_json::to_vec(&json).unwrap()).is_err());
}

#[test]
fn official_validation_rejects_feature_tamper_and_invalid_predecessor() {
    let shadow = prepare_shadow_input(&request()).unwrap();
    let mut json = shadow.official_input;
    json["featureVectorQ24"][0] = serde_json::json!(1);
    assert!(decode_neuron_tick_input_v1(&serde_json::to_vec(&json).unwrap()).is_err());
    let mut next = request();
    next.logical_sequence = 2;
    assert!(prepare_shadow_input(&next).is_err());
}

struct UnavailableOwner;

impl NeuronInferenceControlPort for UnavailableOwner {
    fn execute_feature(
        &mut self,
        _: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        Err(NeuronModelError::Rejected)
    }
}

#[test]
fn real_inference_adapter_propagates_missing_owner_without_fabricating_a_receipt() {
    let digest = Digest32::of_bytes(b"explicit-offline-request-fixture");
    let request = NeuronModelRequestV1 {
        request_id: StableId::new("request:offline-owner-negative").unwrap(),
        config_id: StableId::new("config:offline-owner-negative").unwrap(),
        generation: Generation::new(1).unwrap(),
        model_id: StableId::new("model:offline-owner-negative").unwrap(),
        encoder_digest: digest,
        head_digest: digest,
        weights_digest: digest,
        input_digest: digest,
        feature_vector_q24: vec![0; 5],
        expected_output_width: 5,
    };
    let mut owner = UnavailableOwner;
    let mut official_adapter = InferenceControlModelPort::new(&mut owner);
    assert!(matches!(
        official_adapter.execute(&request),
        Err(NeuronModelError::Rejected)
    ));
}
