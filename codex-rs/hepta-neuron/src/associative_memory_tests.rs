use super::*;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use serde_json::json;

use crate::AssociativeMemoryModelPortV1;
use crate::NeuronCalibrationProfileV1;
use crate::NeuronModelError;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::NeuronResourceEnvelopeV1;
use crate::NeuronRuntimeConfigV1;
use crate::canonical_feature_vector_digest_v1;

const SEMANTIC: &[u8] = include_bytes!("../tests/fixtures/associative-memory/semantic.native.json");
const PROCEDURE: &[u8] = include_bytes!("../tests/fixtures/associative-memory/procedure.native.json");
const EXPECTED: &[u8] = include_bytes!("../tests/fixtures/associative-memory/expected.json");

fn load(bytes: &[u8]) -> Result<AssociativeMemoryCellV1, AssociativeMemoryError> {
    AssociativeMemoryCellV1::from_bytes(bytes, Digest32::of_bytes(bytes))
}

#[test]
fn frozen_python_models_retain_all_parameter_predictions_and_sources()
-> Result<(), Box<dyn StdError>> {
    let fixture: Value = serde_json::from_slice(EXPECTED)?;
    let cases = fixture["models"].as_array().ok_or("models")?;
    for (bytes, case) in [SEMANTIC, PROCEDURE].into_iter().zip(cases) {
        let cell = load(bytes)?;
        assert_eq!(cell.digest().to_string(), case["native"]["sha256"].as_str().ok_or("digest")?);
        assert_eq!(serde_json::to_value(cell.lineage_sources())?, case["lineage_sources"]);
        let key = case["feature_key"].as_str().ok_or("feature key")?;
        let expected_features: Vec<f64> = serde_json::from_value(case["features"].clone())?;
        for (native, python) in cell.encode_key(key)?.into_iter().zip(expected_features) {
            assert!((native - python).abs() <= 1e-15, "address feature mismatch");
        }
        for row in case["rows"].as_array().ok_or("rows")? {
            let predicted = cell.predict(row["key"].as_str().ok_or("key")?)?;
            assert_eq!(predicted.value, Some(row["value"].clone()));
            assert_eq!(serde_json::to_value(predicted.source_ids)?, row["source_ids"]);
            assert_eq!(predicted.parameter_digest, row["parameter_sha256"].as_str().ok_or("parameter")?);
            assert_eq!(predicted.abstain, None);
            assert!((predicted.confidence - row["confidence"].as_f64().ok_or("confidence")?).abs() <= 1e-10);
        }
    }
    Ok(())
}

#[test]
fn modified_bytes_weights_lineage_and_catalogs_are_rejected()
-> Result<(), Box<dyn StdError>> {
    let original: Value = serde_json::from_slice(SEMANTIC)?;
    let mut changed = SEMANTIC.to_vec();
    changed.push(b' ');
    assert!(matches!(AssociativeMemoryCellV1::from_bytes(&changed, Digest32::of_bytes(SEMANTIC)),
        Err(AssociativeMemoryError::BindingMismatch)));
    let mut mutations = Vec::new();
    for (field, value) in [
        ("kind", json!("event")), ("dimension", json!(1025)), ("hidden", json!(0)),
        ("threshold", json!(1.1)), ("address_profile", json!("unknown")),
        ("numeric_profile", json!("different")), ("schema", json!("unversioned")),
    ] {
        let mut mutation = original.clone(); mutation[field] = value; mutations.push(mutation);
    }
    let mut changed_weight = original.clone();
    changed_weight["arrays"]["input_weights"][0] = json!(0.12345);
    mutations.push(changed_weight);
    let mut overflow = original.clone();
    overflow["arrays"]["input_weights"][0] = json!(1e300);
    mutations.push(overflow);
    let mut wrong_shape = original.clone();
    wrong_shape["arrays"]["hidden_bias"] = json!([0]);
    mutations.push(wrong_shape);
    let mut wrong_lineage = original.clone();
    wrong_lineage["lineage_sources"] = json!(["11".repeat(32)]);
    mutations.push(wrong_lineage);
    let mut duplicate_catalog = original.clone();
    duplicate_catalog["catalog"][1] = duplicate_catalog["catalog"][0].clone();
    mutations.push(duplicate_catalog);
    let mut wrong_value = original;
    wrong_value["catalog"][0] = json!({"factor": true, "label": "x"});
    mutations.push(wrong_value);
    for mutation in mutations { assert!(load(&serde_json::to_vec(&mutation)?).is_err()); }
    Ok(())
}

#[test]
fn unsupported_and_threshold_rejections_clear_value_and_dependencies()
-> Result<(), Box<dyn StdError>> {
    let cell = load(SEMANTIC)?;
    let outside = cell.predict("unwritten-实体")?;
    assert_eq!((outside.value, outside.source_ids, outside.abstain),
        (None, vec![], Some(AssociativeMemoryAbstentionV1::OutsideWrittenSupport)));
    assert!(matches!(cell.predict(""), Err(AssociativeMemoryError::InvalidInput)));
    assert!(matches!(cell.predict(&"x".repeat(4097)), Err(AssociativeMemoryError::InvalidInput)));
    let fixture: Value = serde_json::from_slice(EXPECTED)?;
    let key = fixture["models"][0]["feature_key"].as_str().ok_or("key")?;
    let mut model: Value = serde_json::from_slice(SEMANTIC)?;
    for (field, value) in [("threshold", json!(1.0)), ("acceptance_enabled", json!(false))] {
        model[field] = value;
        let readout = load(&serde_json::to_vec(&model)?)?.predict(key)?;
        assert_eq!((readout.value, readout.source_ids, readout.abstain),
            (None, vec![], Some(AssociativeMemoryAbstentionV1::BelowSelectionThreshold)));
    }
    Ok(())
}

#[test]
fn existing_neuron_port_executes_quantized_feature_reference_and_checks_binding()
-> Result<(), Box<dyn StdError>> {
    let cell = load(SEMANTIC)?;
    let fixture: Value = serde_json::from_slice(EXPECTED)?;
    let features: Vec<i64> = serde_json::from_value(fixture["models"][0]["port_features_q24"].clone())?;
    let address = Digest32::of_bytes(ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1.as_bytes());
    let marker = Digest32::of_bytes(b"native-port-test-owner-marker");
    let generation = Generation::new(1)?;
    let config = NeuronRuntimeConfigV1 {
        config_id: StableId::new("memory.config")?, generation,
        model_id: StableId::new("memory.semantic")?,
        model_manifest_digest: cell.digest(), encoder_digest: address,
        head_digest: cell.head_digest(), weights_digest: cell.parameters_digest(),
        tokenizer_digest: marker, preprocessor_digest: address,
        quantization_digest: Digest32::of_bytes(ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1.as_bytes()),
        runtime_digest: marker, device_digest: marker, normalization_digest: marker,
        native_config_digest: marker, input_feature_dimension: cell.input_dimension(),
        state_width: cell.output_width(), modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: marker, ood_artifact_digest: marker, generation,
            valid_from_sequence: 1, expires_after_sequence: 2,
            zero_confidence_error_q24: 1, maximum_in_domain_error_q24: 1,
            minimum_confidence_ppm: 0, maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0, maximum_active_ppm: 1_000_000, maximum_projection_count: 4096,
            measured_ece_ppm: 0, maximum_ece_ppm: 0,
            measured_false_acceptance_ppm: 0, maximum_false_acceptance_ppm: 0,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 1, p99_latency_micros: 2, transient_allocation_bytes: 1_000_000,
            checkpoint_bytes: 1_000_000, write_amplification_ppm: 1_000_000,
        },
    };
    let mut wrong = config.clone(); wrong.weights_digest = marker;
    assert!(matches!(AssociativeMemoryModelPortV1::new(cell.clone(), &wrong), Err(AssociativeMemoryError::InvalidConfiguration)));
    let mut port = AssociativeMemoryModelPortV1::new(cell, &config)?;
    let mut request = NeuronModelRequestV1 {
        request_id: StableId::new("memory.query")?, config_id: config.config_id.clone(), generation,
        model_id: config.model_id.clone(), encoder_digest: address, head_digest: config.head_digest,
        weights_digest: config.weights_digest, input_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features, expected_output_width: config.state_width,
    };
    let output = port.execute(&request)?;
    assert_eq!(serde_json::to_value(output.drive_q24)?, fixture["models"][0]["port_drive_q24"]);
    assert_eq!(output.runtime_receipt.weights_digest, config.weights_digest);
    assert_eq!(output.runtime_receipt.model_manifest_digest, config.model_manifest_digest);
    assert_eq!(output.prediction_q24, vec![0; config.state_width]);
    request.input_digest = marker;
    assert_eq!(port.execute(&request), Err(NeuronModelError::Rejected));
    Ok(())
}
