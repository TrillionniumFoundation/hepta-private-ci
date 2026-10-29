use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use crate::{InventoryCellSemanticHeadV1, INVENTORY_CELL_SEMANTIC_ENCODER_V1, INVENTORY_CELL_SEMANTIC_PROFILE_V1};

fn wire() -> Value {
    let mut intent = vec![vec![0.0_f32; 384]; 8];
    let mut shape = vec![vec![0.0_f32; 384]; 4];
    for i in 0..4 { intent[i][i] = 20.0; shape[i][i] = 20.0; }
    json!({"schema":"hepta.memory.inventory-semantic-router.v1", "feature_profile":INVENTORY_CELL_SEMANTIC_PROFILE_V1,
        "encoder_digest":INVENTORY_CELL_SEMANTIC_ENCODER_V1, "dimension":384,
        "training_digest":Digest32::of_bytes(b"synthetic-head-test-training").to_string(),
        "calibration_digest":Digest32::of_bytes(b"synthetic-head-test-development").to_string(),
        "intent_labels":["semantic","skill","compose","reject:mutation","reject:external","reject:prediction","reject:negation","reject:other"],
        "shape_labels":["policy_tuple","program","computed_integer","unsupported"],
        "intent_weights":intent, "intent_bias":vec![0.0; 8], "shape_weights":shape, "shape_bias":vec![0.0; 4],
        "threshold":0.5, "minimum_margin":0.2,
        "aliases":[{"kind":"entity","key":"inventory:entity:0","phrases":["Cedar Harbor"]},
                   {"kind":"entity","key":"inventory:entity:1","phrases":["Maple Quay"]},
                   {"kind":"workflow","key":"inventory:workflow:3","phrases":["Jade Method"]}]})
}
fn load(value: Value) -> Result<InventoryCellSemanticHeadV1, String> {
    let bytes = serde_json::to_vec(&value).unwrap(); InventoryCellSemanticHeadV1::from_bytes(&bytes, Digest32::of_bytes(&bytes))
}
fn feature(index: usize) -> Vec<f32> { let mut values = vec![0.0; 384]; values[index] = 1.0; values }

#[test]
fn inventory_semantic_head_keeps_roles_shapes_and_two_names_independent() {
    let head = load(wire()).unwrap();
    let policy = head.route_features("读取 Cedar Harbor 的策略", &feature(0)).unwrap().unwrap();
    assert_eq!(policy.operation, MemoryOperationV1::Semantic); assert!(policy.workflow.is_none());
    let program = head.route_features("Jade Method", &feature(1)).unwrap().unwrap();
    assert_eq!(program.operation, MemoryOperationV1::Procedure); assert!(program.entity.is_none());
    let apply = head.route_features("Jade Method at Cedar Harbor", &feature(2)).unwrap().unwrap();
    assert_eq!(apply.operation, MemoryOperationV1::Apply); assert_ne!(apply.entity, apply.workflow);
    assert!(head.route_features("Jade Method at Cedar Harbor", &feature(0)).unwrap().is_none());
    assert!(head.route_features("Cedar Harbor", &feature(3)).unwrap().is_none());
    assert!(head.route_features("Cedar Harborview", &feature(0)).unwrap().is_none());
    assert!(head.route_features("Cedar Harbor and Maple Quay", &feature(0)).unwrap().is_none());
}

#[test]
fn inventory_semantic_head_rejects_profile_alias_shape_and_numeric_changes() {
    let head = load(wire()).unwrap();
    assert!(head.route_features("Cedar Harbor", &[0.0; 384]).is_err());
    assert!(head.route_features("Cedar Harbor", &[1.0]).is_err());
    let mut value = wire(); value["encoder_digest"] = json!(Digest32::of_bytes(b"different-preprocessing").to_string());
    assert!(load(value).is_err());
    let mut value = wire(); value["intent_labels"][0] = json!("apply"); assert!(load(value).is_err());
    let mut value = wire(); value["aliases"][1]["phrases"] = json!(["Cedar Harbor"]); assert!(load(value).is_err());
    let mut value = wire(); value["shape_weights"][0] = json!([0.0]); assert!(load(value).is_err());
    let mut value = wire(); value["intent_weights"][0][0] = json!(f32::MAX); value["intent_bias"][0] = json!(f32::MAX);
    assert!(load(value).unwrap().route_features("Cedar Harbor", &feature(0)).is_err());
    let mut value = wire(); value["shape_bias"][3] = json!(100.0);
    assert!(load(value).unwrap().route_features("Cedar Harbor", &feature(0)).unwrap().is_none());
}
