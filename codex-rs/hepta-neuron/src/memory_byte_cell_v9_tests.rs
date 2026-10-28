use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

fn wire(payload: &[u8]) -> Value {
    assert!(payload.len() <= VALUE_BYTES);
    let mut bytes = [0_u8; VALUE_BYTES + 2];
    bytes[..2].copy_from_slice(&(payload.len() as u16).to_be_bytes());
    bytes[2..2 + payload.len()].copy_from_slice(payload);
    let bias: Vec<f32> = (0..OUTPUT_BITS).map(|bit| {
        if bytes[bit / 8] & (1 << (7 - bit % 8)) == 0 { -20.0 } else { 20.0 }
    }).collect();
    let source = Digest32::of_bytes(b"source").to_string();
    let mut value = json!({"schema":SCHEMA,"kind":"semantic",
        "address_profile":ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1,
        "numeric_profile":MEMORY_BYTE_NUMERIC_PROFILE_V9,
        "dimension":8,"hidden":1,"max_value_bytes":128,"threshold":0.9,
        "supports":BTreeMap::from([(Digest32::of_bytes(b"entity:byte").to_string(),vec![source.clone()])]),
        "lineage_sources":[source],"training_receipt_sha256":Digest32::of_bytes(b"fixture-parameters-not-training").to_string(),
        "parameter_sha256":"", "arrays":{"input_weights":vec![0.0_f32;8],"hidden_bias":[0.0],
            "output_weights":vec![0.0_f32;OUTPUT_BITS],"output_bias":bias}});
    repin(&mut value);
    value
}

fn repin(value: &mut Value) {
    let mut bytes = Vec::new();
    for name in ["input_weights", "hidden_bias", "output_weights", "output_bias"] {
        for parameter in value["arrays"][name].as_array().unwrap() {
            bytes.extend_from_slice(&(parameter.as_f64().unwrap() as f32).to_le_bytes());
        }
    }
    value["parameter_sha256"] = json!(Digest32::of_bytes(&bytes).to_string());
}

fn load(value: &Value) -> Result<MemoryByteCellV9, AssociativeMemoryError> {
    let raw = serde_json::to_vec(value).unwrap();
    MemoryByteCellV9::from_bytes(&raw, Digest32::of_bytes(&raw))
}

#[test]
fn native_byte_parameters_decode_typed_utf8_and_refuse_unwritten_support() {
    let expected = json!({"factor":7,"label":"界"});
    let model = load(&wire(&serde_json::to_vec(&expected).unwrap())).unwrap();
    let result = model.predict("entity:byte").unwrap();
    assert_eq!((result.value, result.abstain, result.source_ids),
        (Some(expected), None, vec![Digest32::of_bytes(b"source").to_string()]));
    let absent = model.predict("entity:absent").unwrap();
    assert_eq!((absent.value, absent.abstain, absent.source_ids),
        (None, Some(AssociativeMemoryAbstentionV1::OutsideWrittenSupport), Vec::new()));
    assert_eq!(model.cost().unwrap().catalog, 0);
}

#[test]
fn native_byte_output_rejects_noncanonical_duplicate_and_invalid_typed_json() {
    for payload in [
        br#"{"label":"x","factor":2}"#.as_slice(),
        br#"{"factor":2,"factor":3,"label":"x"}"#.as_slice(),
        br#"{"factor":2.0,"label":"x"}"#.as_slice(),
        br#"{"factor":2,"label":"x","extra":0}"#.as_slice(),
        br#"{"factor":2,"label":"\u754c"}"#.as_slice(),
    ] {
        let result = load(&wire(payload)).unwrap().predict("entity:byte").unwrap();
        assert_eq!((result.value, result.source_ids), (None, Vec::new()));
    }
}

#[test]
fn native_byte_output_checks_every_padding_bit_and_numeric_binding() {
    let mut changed = wire(br#"{"factor":2,"label":"x"}"#);
    changed["arrays"]["output_bias"][OUTPUT_BITS - 1] = json!(20.0);
    assert!(matches!(load(&changed), Err(AssociativeMemoryError::BindingMismatch)));
    repin(&mut changed);
    assert!(load(&changed).unwrap().predict("entity:byte").unwrap().value.is_none());
    changed["arrays"]["output_bias"][OUTPUT_BITS - 1] = json!(0.1);
    repin(&mut changed);
    let result = load(&changed).unwrap().predict("entity:byte").unwrap();
    assert!(result.confidence < 0.9 && result.value.is_none());
    changed["catalog"] = json!([{"factor":2,"label":"x"}]);
    assert!(matches!(load(&changed), Err(AssociativeMemoryError::InvalidArtifact)));
}

#[test]
fn native_byte_model_runs_through_existing_population_budget_and_sleep() {
    let raw = serde_json::to_vec(&wire(br#"{"factor":2,"label":"x"}"#)).unwrap();
    let model = crate::MemoryCellPopulationV2::from_bytes(&raw, Digest32::of_bytes(&raw)).unwrap();
    assert_eq!(model.numeric_profile(), MEMORY_BYTE_NUMERIC_PROFILE_V9);
    model.set_resident_budget(0).unwrap();
    assert!(matches!(model.predict("entity:byte"), Err(AssociativeMemoryError::InvalidConfiguration)));
    model.set_resident_budget(16_384).unwrap();
    assert_eq!(model.predict("entity:byte").unwrap().value, Some(json!({"factor":2,"label":"x"})));
    model.sleep().unwrap();
    assert_eq!(model.cost().unwrap().resident_shards, 0);
    assert_eq!(model.predict("entity:byte").unwrap().value, Some(json!({"factor":2,"label":"x"})));
    assert_eq!(model.cost().unwrap().wake_count, 2);
}
