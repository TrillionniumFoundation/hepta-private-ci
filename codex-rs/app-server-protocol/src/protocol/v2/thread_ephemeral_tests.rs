use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn ephemeral_retention_requires_positive_version_and_complete_binding_on_wire() {
    let mut request = json!({
        "protocolVersion":1,"threadId":"thread","expectedSessionId":"session","operationId":"operation"
    });
    let decoded: ThreadEphemeralRetainParams = serde_json::from_value(request.clone()).unwrap();
    assert_eq!(decoded.protocol_version, 1);
    for field in [
        "protocolVersion",
        "threadId",
        "expectedSessionId",
        "operationId",
    ] {
        let saved = request.as_object_mut().unwrap().remove(field).unwrap();
        assert!(serde_json::from_value::<ThreadEphemeralRetainParams>(request.clone()).is_err());
        request[field] = saved;
    }
    // A legacy success response is not a residency acknowledgement.
    assert!(
        serde_json::from_value::<ThreadEphemeralRetainResponse>(json!({"status":"unsubscribed"}))
            .is_err()
    );
    let mut response = json!({
        "protocolVersion":1,"threadId":"thread","sessionId":"session","operationId":"operation"
    });
    for field in ["protocolVersion", "threadId", "sessionId", "operationId"] {
        let saved = response.as_object_mut().unwrap().remove(field).unwrap();
        assert!(serde_json::from_value::<ThreadEphemeralRetainResponse>(response.clone()).is_err());
        response[field] = saved;
    }
}
