use std::collections::BTreeMap;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryInventoryPolicyV1;
use codex_hepta_cognitive_types::MemoryInventoryProgramV1;
use codex_hepta_cognitive_types::MemoryInventoryValueV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::*;

const POLICY_DIGEST: &str = "d5448c231d22f59a24ff76f2a33f0dc773efa90d1f66848654045aa7fcb0f879";
const ABLATED_DIGEST: &str = "e71ae4053bb3b0a3822fe5cf9e414c73833ad60e6c82d963c3e824196dcd2869";
const TIE_DIGEST: &str = "7bebe3032d805f87bb1683633c4f3b0b900542bdac2cff4dc424eb35371306aa";
const DIMENSION: usize = 384;

fn tensor(shape: &[usize], values: &[f32]) -> Value {
    let bytes: Vec<u8> = values.iter().flat_map(|v| v.to_le_bytes()).collect();
    let hex: String = bytes.iter().map(|v| format!("{v:02x}")).collect();
    json!({"shape": shape, "f32le_hex": hex})
}

fn envelope(kind: MemoryCellKindV1, width: usize, arrays: Value, parameter: &str) -> Value {
    let mut supports = BTreeMap::new();
    let mut features = BTreeMap::new();
    let mut lineage = Vec::new();
    for (key, sign) in [("positive", 1_f32), ("negative", -1_f32)] {
        let address = Digest32::of_bytes(key.as_bytes()).to_string();
        let source = Digest32::of_bytes(format!("source:{key}").as_bytes()).to_string();
        lineage.push(source.clone());
        supports.insert(address.clone(), vec![source]);
        let mut vector = vec![0.0; DIMENSION]; vector[0] = sign;
        let bytes: Vec<u8> = vector.iter().flat_map(|v| v.to_le_bytes()).collect();
        features.insert(address, json!({
            "canonical_text_sha256": Digest32::of_bytes(key.as_bytes()).to_string(),
            "feature_sha256": Digest32::of_bytes(&bytes).to_string(),
            "f32le_hex": tensor(&[DIMENSION], &vector)["f32le_hex"],
        }));
    }
    lineage.sort();
    let output_profile = match kind {
        MemoryCellKindV1::Semantic => MEMORY_RESIDUAL_POLICY_PROFILE_V1,
        MemoryCellKindV1::Procedure => MEMORY_RESIDUAL_PROGRAM_PROFILE_V1,
        MemoryCellKindV1::Event => panic!("not a parameter kind"),
    };
    assert_eq!(arrays["head.bias"]["shape"], json!([width]));
    json!({"schema": MEMORY_RESIDUAL_SCHEMA_V1, "kind": kind,
        "address_profile": MEMORY_RESIDUAL_ADDRESS_PROFILE_V1,
        "numeric_profile": MEMORY_RESIDUAL_NUMERIC_PROFILE_V1,
        "output_profile": output_profile, "dimension": DIMENSION, "rank": 1,
        "minimum_margin": 0.001, "encoder_sha256": Digest32::of_bytes(b"unit-fixture-encoder").to_string(),
        "owner_cut_sha256": Digest32::of_bytes(b"owner-cut").to_string(),
        "parameter_sha256": parameter,
        "checkpoint_sha256": Digest32::of_bytes(b"unit-fixture-checkpoint").to_string(),
        "training_receipt_sha256": Digest32::of_bytes(b"analytic-fixture-not-a-training-claim").to_string(),
        "supports": supports, "lineage_sources": lineage, "features": features, "arrays": arrays})
}

fn policy() -> Value {
    let mut a = vec![0_f32; DIMENSION]; a[0] = 1.0;
    let signs = [1_f32, -1., -1., -1., -1., 1., -1., -1., 1., 1., -1., -1.];
    let mut head = vec![0_f32; 12 * DIMENSION];
    for (row, sign) in signs.iter().enumerate() { head[row * DIMENSION] = *sign; }
    let bias: Vec<f32> = signs.iter().map(|v| -1.5 * v).collect();
    envelope(MemoryCellKindV1::Semantic, 12, json!({
        "A": tensor(&[1, DIMENSION], &a), "B": tensor(&[DIMENSION, 1], &a),
        "head.bias": tensor(&[12], &bias), "head.weight": tensor(&[12, DIMENSION], &head),
    }), POLICY_DIGEST)
}

fn load_value(value: &Value) -> MemoryResidualCellV1 {
    let raw = serde_json::to_vec(value).unwrap();
    MemoryResidualCellV1::from_bytes(&raw, Digest32::of_bytes(&raw)).unwrap()
}

#[test]
fn residual_factors_change_a_typed_value_with_identical_owner_and_features() {
    let wire = policy();
    let model = load_value(&wire);
    let prediction = model.predict("positive").unwrap();
    let signs = [1.0, -1., -1., -1., -1., 1., -1., -1., 1., 1., -1., -1.];
    assert_eq!(prediction, MemoryResidualPredictionV1 {
        kind: MemoryCellKindV1::Semantic,
        value: Some(MemoryInventoryValueV1::Semantic(MemoryInventoryPolicyV1 { reserve: 1, pack: 2, limit: 3 })),
        logits: signs.iter().map(|v| 0.5 * v).collect(), minimum_margin: 0.5,
        source_ids: vec![Digest32::of_bytes(b"source:positive").to_string()],
        artifact_digest: model.digest().to_string(), parameter_digest: POLICY_DIGEST.to_string(), abstain: None,
    });
    let mut ablated = wire.clone();
    ablated["arrays"]["B"] = tensor(&[DIMENSION, 1], &vec![0.0; DIMENSION]);
    ablated["parameter_sha256"] = json!(ABLATED_DIGEST);
    let ablated = load_value(&ablated);
    assert_eq!(ablated.predict("positive").unwrap().value,
        Some(MemoryInventoryValueV1::Semantic(MemoryInventoryPolicyV1 { reserve: 14, pack: 13, limit: 12 })));
    assert_eq!(model.predict("negative").unwrap().value, ablated.predict("negative").unwrap().value);
    assert_eq!(model.head_digest(), ablated.head_digest());
    assert_eq!(model.cost().parameter_bytes, 21_552);
    assert_eq!(model.cost().feature_bytes, 3072);
}

#[test]
fn residual_is_added_after_the_complete_b_reduction() {
    // Exact cancellation makes the declared order observable: adding x before
    // +2^54 and -2^54 would lose x and incorrectly abstain on zero logits.
    // Digest and logits were independently checked with reference.scalar_forward.
    let mut a = vec![0_f32; 2 * DIMENSION];
    a[0] = 1.0;
    a[DIMENSION] = 1.0;
    let mut b = vec![0_f32; 2 * DIMENSION];
    b[0] = 18_014_398_509_481_984.0;
    b[1] = -18_014_398_509_481_984.0;
    let mut head = vec![0_f32; 12 * DIMENSION];
    for row in 0..12 { head[row * DIMENSION] = 1.0; }
    let mut wire = envelope(MemoryCellKindV1::Semantic, 12, json!({
        "A": tensor(&[2, DIMENSION], &a), "B": tensor(&[DIMENSION, 2], &b),
        "head.bias": tensor(&[12], &[0_f32; 12]), "head.weight": tensor(&[12, DIMENSION], &head),
    }), "2cbf6b63ef19b4ae7271d39f82fa1fcd44218fc0e7772bbe623c87a74070f467");
    wire["rank"] = json!(2);
    let model = load_value(&wire);
    for (key, logit, decoded) in [("positive", 1.0, 15), ("negative", -1.0, 0)] {
        let prediction = model.predict(key).unwrap();
        assert_eq!((prediction.logits, prediction.value, prediction.abstain),
            (vec![logit; 12], Some(MemoryInventoryValueV1::Semantic(MemoryInventoryPolicyV1 {
                reserve: decoded, pack: decoded, limit: decoded,
            })), None));
    }
}

#[test]
fn unsupported_addresses_and_tied_or_low_margin_logits_do_not_expose_values() {
    let model = load_value(&policy());
    assert_eq!(model.predict("unwritten").unwrap(), MemoryResidualPredictionV1 {
        kind: MemoryCellKindV1::Semantic, value: None, logits: Vec::new(), minimum_margin: 0.0,
        source_ids: Vec::new(), artifact_digest: model.digest().to_string(),
        parameter_digest: POLICY_DIGEST.to_string(), abstain: Some(MemoryResidualAbstentionV1::OutsideWrittenSupport),
    });
    let mut wire = policy(); wire["minimum_margin"] = json!(1.0);
    let low = load_value(&wire).predict("positive").unwrap();
    assert_eq!((low.value, low.source_ids, low.abstain),
        (None, Vec::<String>::new(), Some(MemoryResidualAbstentionV1::BelowSelectionMargin)));
    wire["arrays"]["head.weight"] = tensor(&[12, DIMENSION], &vec![0.0; 12 * DIMENSION]);
    wire["arrays"]["head.bias"] = tensor(&[12], &[0.0; 12]);
    wire["parameter_sha256"] = json!(TIE_DIGEST);
    let tied = load_value(&wire).predict("positive").unwrap();
    assert_eq!((tied.value, tied.minimum_margin, tied.abstain),
        (None, 0.0, Some(MemoryResidualAbstentionV1::BelowSelectionMargin)));
}

#[test]
fn drift_shape_nonfinite_ambiguity_and_profile_mismatches_fail_before_prediction() {
    let original = policy();
    let address = Digest32::of_bytes(b"positive").to_string();
    let mut cases = Vec::new();
    let mut changed = original.clone(); changed["arrays"]["A"]["shape"] = json!([usize::MAX, DIMENSION]); cases.push(changed);
    let mut changed = original.clone(); changed["arrays"]["A"]["f32le_hex"] = json!("00".repeat(DIMENSION * 4)); cases.push(changed);
    let mut changed = original.clone(); changed["features"][&address]["feature_sha256"] = json!(Digest32::of_bytes(b"wrong").to_string()); cases.push(changed);
    let mut changed = original.clone(); changed["features"][&address]["f32le_hex"] = json!(format!("0000807f{}", "00".repeat((DIMENSION-1)*4))); cases.push(changed);
    let mut changed = original.clone(); changed["numeric_profile"] = json!("hepta.memory.f32-weights-f64-tanh-softmax.v1"); cases.push(changed);
    let mut changed = original.clone(); changed["arrays"]["answer"] = json!({"shape": [1], "f32le_hex": "00000000"}); cases.push(changed);
    let mut changed = original.clone(); changed["lineage_sources"] = json!([Digest32::of_bytes(b"different-owner").to_string()]); cases.push(changed);
    for value in cases {
        let bytes = serde_json::to_vec(&value).unwrap();
        assert!(MemoryResidualCellV1::from_bytes(&bytes, Digest32::of_bytes(&bytes)).is_err());
    }
    let raw = serde_json::to_string(&original).unwrap();
    let duplicated = raw.replacen("\"supports\":{", &format!("\"supports\":{{\"{address}\":[],"), 1);
    assert!(MemoryResidualCellV1::from_bytes(duplicated.as_bytes(), Digest32::of_bytes(duplicated.as_bytes())).is_err());
    assert!(MemoryResidualCellV1::from_bytes(raw.as_bytes(), Digest32::of_bytes(b"different-artifact")).is_err());
}

#[test]
fn independent_procedure_heads_decode_both_feature_addresses() {
    let mut a = vec![0_f32; DIMENSION]; a[0] = 1.0;
    let mut head = vec![0_f32; 28 * DIMENSION];
    for (group, (positive, negative)) in [(1, 4), (2, 5), (3, 0)].into_iter().enumerate() {
        head[(7 * group + positive) * DIMENSION] = 1.0;
        head[(7 * group + negative) * DIMENSION] = -1.0;
    }
    let mut bias = vec![0_f32; 28]; bias[27] = 3.0;
    let wire = envelope(MemoryCellKindV1::Procedure, 28, json!({
        "A": tensor(&[1, DIMENSION], &a), "B": tensor(&[DIMENSION, 1], &a),
        "head.bias": tensor(&[28], &bias), "head.weight": tensor(&[28, DIMENSION], &head),
    }), "5cd07a091c4e2eb526d1e64b8b9a26671371f0d7fccba2bf093e63acadfca11e");
    let model = load_value(&wire);
    assert_eq!(model.predict("positive").unwrap().value,
        Some(MemoryInventoryValueV1::Procedure(MemoryInventoryProgramV1 { opcodes: [1, 2, 3, 6] })));
    assert_eq!(model.predict("negative").unwrap().value,
        Some(MemoryInventoryValueV1::Procedure(MemoryInventoryProgramV1 { opcodes: [4, 5, 0, 6] })));
}
