use super::*;
use pretty_assertions::assert_eq;

#[test]
fn shared_frontier_wire_has_no_owner_or_initializer_and_rejects_duplicates() {
    let request = HostConsumerFrontierRequestV1::CompareAndSet {
        schema_version: 1,
        request_id: 9,
        expected: FinalUseFrontier {
            authority_epoch: 1,
            revocation_revision: 1,
            state_sha256: [2; 32],
        },
        next: FinalUseFrontier {
            authority_epoch: 1,
            revocation_revision: 1,
            state_sha256: [3; 32],
        },
    };
    let bytes = serde_json::to_vec(&request).unwrap();
    assert_eq!(
        serde_json::from_slice::<HostConsumerFrontierRequestV1>(&bytes).unwrap(),
        request
    );
    let mut value = serde_json::to_value(&request).unwrap();
    value["owner_id"] = serde_json::json!("peer-selected");
    assert!(serde_json::from_value::<HostConsumerFrontierRequestV1>(value).is_err());
    let duplicate = std::str::from_utf8(&bytes)
        .unwrap()
        .replace("\"request_id\":9", "\"request_id\":9,\"request_id\":10");
    assert!(serde_json::from_str::<HostConsumerFrontierRequestV1>(&duplicate).is_err());
    assert!(
        serde_json::from_str::<HostConsumerFrontierRequestV1>(
            r#"{"operation":"initialize","schema_version":1,"request_id":1}"#
        )
        .is_err()
    );
}
