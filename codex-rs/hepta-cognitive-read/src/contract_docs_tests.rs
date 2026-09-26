use super::*;

const CONTRACT_LIMITS: &str =
    include_str!("../../../docs/modules/cognitive.read/CONTRACT_LIMITS.md");

#[test]
fn documented_limits_match_compiled_contracts() {
    assert!(CONTRACT_LIMITS.contains("MAX_READ_IDS_V1 = 512"));
    assert!(CONTRACT_LIMITS.contains("MAX_ENCODED_READ_RESULT_BYTES_V2 = 1048576"));
    assert_eq!(MAX_READ_IDS_V1, 512);
    assert_eq!(MAX_ENCODED_READ_RESULT_BYTES_V2, 1_048_576);
}

#[test]
fn byte_and_authority_semantics_are_documented() {
    for required in [
        "payload_encoded_bytes",
        "total_encoded_bytes",
        "AuthorityPosture::DENY_ALL",
        "activation=false",
        "TransientSnapshotProjectionV1",
        "cognitive.context.revalidate@1",
    ] {
        assert!(
            CONTRACT_LIMITS.contains(required),
            "missing cognitive.read contract marker: {required}"
        );
    }
}
