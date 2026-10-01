use super::*;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;

#[test]
fn preparation_response_preserves_snapshot_bytes_and_separates_receipt() {
    let snapshot: CognitiveContextSnapshot = serde_json::from_value(serde_json::json!({
        "snapshot_digest": "a".repeat(64),
        "read_digest": "b".repeat(64),
        "omitted_records": 0,
        "items": [],
        "plan": null
    }))
    .unwrap();
    let bytes = serde_json::to_vec(&snapshot).unwrap();
    let preparation = CognitivePreparationReceipt {
        read_request_id: 17,
        sequence: 3,
        event_digest: "c".repeat(64),
        chain_digest: "d".repeat(64),
    };
    preparation.validate().unwrap();
    let payload = AgentdPayload::CognitiveContextPrepared(CognitiveContextPreparation {
        snapshot,
        preparation: Some(preparation),
    });
    let decoded: AgentdPayload =
        serde_json::from_slice(&serde_json::to_vec(&payload).unwrap()).unwrap();
    assert_eq!(decoded, payload);
    let AgentdPayload::CognitiveContextPrepared(decoded) = decoded else {
        panic!("wrong payload");
    };
    assert_eq!(serde_json::to_vec(&decoded.snapshot).unwrap(), bytes);
    let request = AgentdRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 17,
        spawn_generation: 4,
        method: AgentdMethod::CognitiveContextPrepare {
            query: "lemon".to_string(),
            limit: 4,
        },
    };
    assert_eq!(
        serde_json::from_slice::<AgentdRequest>(&serde_json::to_vec(&request).unwrap()).unwrap(),
        request
    );
    let mut forged = decoded.preparation.unwrap();
    forged.sequence = 0;
    assert!(forged.validate().is_err());
    forged.sequence = 3;
    forged.event_digest = "0".repeat(64);
    assert!(forged.validate().is_err());
    forged.event_digest = "F".repeat(64);
    assert!(forged.validate().is_err());
    let mut unexpected = serde_json::to_value(&forged).unwrap();
    unexpected["training_grant"] = serde_json::json!(true);
    assert!(serde_json::from_value::<CognitivePreparationReceipt>(unexpected).is_err());
}
