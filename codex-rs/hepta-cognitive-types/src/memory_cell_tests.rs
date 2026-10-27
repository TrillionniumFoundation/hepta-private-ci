use super::*;
use serde_json::json;

#[test]
fn a_prediction_survives_roundtrip_without_becoming_source_evidence() -> Result<(), Box<dyn std::error::Error>> {
    let value = json!({
        "schema": "hepta.memory.readout.v1", "query_id": "q1", "operation": "semantic",
        "status": "ok", "value": {"factor": 7, "label": "new"},
        "source_ids": ["11".repeat(32)], "generation": 1,
        "snapshot_digest": "22".repeat(32), "prediction_kind": "model_prediction",
        "cell_digests": ["33".repeat(32)], "hops": 1, "elapsed_seconds": 0.001,
        "reason": null
    });
    let readout = decode_memory_readout_v1(&serde_json::to_vec(&value)?)?;
    assert_eq!(readout.prediction_kind, MemoryPredictionKindV1::ModelPrediction);
    assert_eq!(serde_json::to_value(&readout)?, value);
    let mut stale = value;
    stale["status"] = json!("stale");
    stale["reason"] = json!("revoked");
    assert!(decode_memory_readout_v1(&serde_json::to_vec(&stale)?).is_err());
    Ok(())
}

#[test]
fn requests_reject_unknown_fields_and_invalid_temporal_ranges() -> Result<(), Box<dyn std::error::Error>> {
    let mut value = json!({"schema":"hepta.memory.request.v1","query_id":"q1","scope":"workspace",
        "entity":"entity1","text":"What was recorded then?","at":20,"since":10,"max_hops":4,"max_cells":3});
    let request = decode_memory_request_v1(&serde_json::to_vec(&value)?)?;
    assert_eq!(serde_json::to_value(request)?, value);
    value["gold_operation"] = json!("history");
    assert!(decode_memory_request_v1(&serde_json::to_vec(&value)?).is_err());
    value.as_object_mut().ok_or("object")?.remove("gold_operation");
    value["since"] = json!(21);
    assert!(decode_memory_request_v1(&serde_json::to_vec(&value)?).is_err());
    Ok(())
}

#[test]
fn duplicate_support_and_missing_model_binding_are_rejected() -> Result<(), Box<dyn std::error::Error>> {
    let mut value = json!({"schema":"hepta.memory.readout.v1","query_id":"q1","operation":"semantic",
        "status":"ok","value":8,"source_ids":["11".repeat(32),"11".repeat(32)],"generation":1,
        "snapshot_digest":"22".repeat(32),"prediction_kind":"model_prediction","cell_digests":[],
        "hops":1,"elapsed_seconds":0.0,"reason":null});
    assert!(decode_memory_readout_v1(&serde_json::to_vec(&value)?).is_err());
    value["source_ids"] = json!(["11".repeat(32)]);
    assert!(decode_memory_readout_v1(&serde_json::to_vec(&value)?).is_err());
    value["cell_digests"] = json!(["33".repeat(32)]);
    assert!(decode_memory_readout_v1(&serde_json::to_vec(&value)?).is_ok());
    value["hops"] = json!(0);
    assert!(decode_memory_readout_v1(&serde_json::to_vec(&value)?).is_err());
    Ok(())
}
