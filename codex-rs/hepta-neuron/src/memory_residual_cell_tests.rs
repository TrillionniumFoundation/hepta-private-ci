use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde::Deserialize;

use super::MemoryResidualCellV1;
use super::MemoryResidualValueV1;
use crate::AssociativeMemoryError;

const FIXTURES: [&str; 6] = [
    include_str!("../tests/fixtures/residual-memory/seed-731-semantic.json"),
    include_str!("../tests/fixtures/residual-memory/seed-731-skill.json"),
    include_str!("../tests/fixtures/residual-memory/seed-732-semantic.json"),
    include_str!("../tests/fixtures/residual-memory/seed-732-skill.json"),
    include_str!("../tests/fixtures/residual-memory/seed-733-semantic.json"),
    include_str!("../tests/fixtures/residual-memory/seed-733-skill.json"),
];

#[derive(Deserialize)]
struct ReferenceCase {
    features: Vec<f32>,
    logits: Vec<f32>,
    value: MemoryResidualValueV1,
}

#[derive(Deserialize)]
struct Fixture {
    artifact_json: String,
    artifact_sha256: String,
    parameter_sha256: String,
    encoder_sha256: String,
    cases: Vec<ReferenceCase>,
}

#[test]
fn original_trained_models_retain_parameters_and_typed_float32_outputs() {
    for source in FIXTURES {
        let fixture: Fixture = serde_json::from_str(source).unwrap();
        let model = MemoryResidualCellV1::from_bytes(
            fixture.artifact_json.as_bytes(),
            fixture.artifact_sha256.parse().unwrap(),
        )
        .unwrap();
        assert_eq!(model.parameters_digest().to_string(), fixture.parameter_sha256);
        assert_eq!(model.encoder_digest().to_string(), fixture.encoder_sha256);
        for case in fixture.cases {
            let prediction = model.predict(&case.features, model.encoder_digest()).unwrap();
            assert_eq!(prediction.value, case.value);
            assert_eq!(prediction.logits.len(), case.logits.len());
            for (actual, expected) in prediction.logits.iter().zip(&case.logits) {
                assert!((actual - expected).abs() <= 1e-4 + 1e-5 * expected.abs(),
                    "float32 reduction mismatch: {actual} versus {expected}");
            }
        }
    }
}

#[test]
fn corrupted_parameters_fail_even_when_outer_artifact_hash_is_updated() {
    let fixture: Fixture = serde_json::from_str(FIXTURES[0]).unwrap();
    let mut wire: serde_json::Value = serde_json::from_str(&fixture.artifact_json).unwrap();
    let encoded = wire["tensors"]["A"]["f32le_hex"].as_str().unwrap();
    let changed = format!("{}{}", if encoded.starts_with('0') { "1" } else { "0" }, &encoded[1..]);
    wire["tensors"]["A"]["f32le_hex"] = changed.into();
    let bytes = serde_json::to_vec(&wire).unwrap();
    assert!(matches!(MemoryResidualCellV1::from_bytes(&bytes, Digest32::of_bytes(&bytes)),
        Err(AssociativeMemoryError::BindingMismatch)));
}

#[test]
fn malformed_shapes_and_unknown_wire_fields_are_rejected() {
    let fixture: Fixture = serde_json::from_str(FIXTURES[0]).unwrap();
    for (field, value) in [("rank", serde_json::json!(u64::MAX)), ("new_field", serde_json::json!(1))] {
        let mut wire: serde_json::Value = serde_json::from_str(&fixture.artifact_json).unwrap();
        wire[field] = value;
        let bytes = serde_json::to_vec(&wire).unwrap();
        assert!(matches!(MemoryResidualCellV1::from_bytes(&bytes, Digest32::of_bytes(&bytes)),
            Err(AssociativeMemoryError::InvalidArtifact)));
    }
}

#[test]
fn encoder_mismatch_and_nonfinite_or_wrong_width_features_are_rejected() {
    let fixture: Fixture = serde_json::from_str(FIXTURES[0]).unwrap();
    let model = MemoryResidualCellV1::from_bytes(
        fixture.artifact_json.as_bytes(), fixture.artifact_sha256.parse().unwrap(),
    ).unwrap();
    assert!(matches!(model.predict(&fixture.cases[0].features, Digest32::ZERO),
        Err(AssociativeMemoryError::BindingMismatch)));
    assert!(matches!(model.predict(&[], model.encoder_digest()),
        Err(AssociativeMemoryError::InvalidInput)));
    let mut features = fixture.cases[0].features.clone();
    features[0] = f32::NAN;
    assert!(matches!(model.predict(&features, model.encoder_digest()),
        Err(AssociativeMemoryError::InvalidInput)));
}

#[test]
fn skill_decoder_preserves_float32_softmax_ties_before_argmax() {
    let fixture: Fixture = serde_json::from_str(FIXTURES[1]).unwrap();
    let mut model = MemoryResidualCellV1::from_bytes(fixture.artifact_json.as_bytes(), fixture.artifact_sha256.parse().unwrap()).unwrap();
    // Internal decoder-only perturbation; this is not a published artifact.
    model.head_weight.fill(0.0);
    for scores in model.head_bias.chunks_exact_mut(7) {
        scores.fill(-1.0);
        scores[0] = 0.0;
        scores[1] = f32::EPSILON / 16.0;
    }
    let prediction = model.predict(&vec![0.0; 384], model.encoder_digest()).unwrap();
    assert_eq!(prediction.value, MemoryResidualValueV1::Skill { program: [0; 4] });
}
