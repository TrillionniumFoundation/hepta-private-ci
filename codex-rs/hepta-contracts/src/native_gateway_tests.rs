use super::*;
const KEY: &[u8] = b"independent-test-key-32-bytes-long-not-production";

#[test]
fn proof_binds_nonce_path_server_incarnation_and_window() {
    let proof =
        NativeGatewayRequestV2::sign(KEY, "/api/hepta/runtime", [1; 32], 100_000, [2; 32]).unwrap();
    let roundtrip = NativeGatewayRequestV2::parse_header(&proof.header_value()).unwrap();
    roundtrip
        .verify(KEY, "/api/hepta/runtime", 100_001, &[2; 32])
        .unwrap();
    assert!(
        roundtrip
            .verify(KEY, "/healthz", 100_001, &[2; 32])
            .is_err()
    );
    assert!(
        roundtrip
            .verify(KEY, "/api/hepta/runtime", 100_001, &[3; 32])
            .is_err()
    );
    assert!(
        roundtrip
            .verify(KEY, "/api/hepta/runtime", 130_001, &[2; 32])
            .is_err()
    );
    assert!(
        roundtrip
            .verify(KEY, "/api/hepta/runtime", 94_999, &[2; 32])
            .is_err()
    );
}
#[test]
fn response_cannot_be_substituted_or_reused_for_another_request() {
    let first = NativeGatewayRequestV2::sign(KEY, "/healthz", [1; 32], 100_000, [0; 32]).unwrap();
    first.verify(KEY, "/healthz", 100_001, &[2; 32]).unwrap();
    let tag = first.response_tag(KEY, 200, b"healthy").unwrap();
    first.verify_response(KEY, 200, b"healthy", &tag).unwrap();
    assert!(first.verify_response(KEY, 500, b"healthy", &tag).is_err());
    assert!(first.verify_response(KEY, 200, b"changed", &tag).is_err());
    let other = NativeGatewayRequestV2::sign(KEY, "/healthz", [3; 32], 100_000, [0; 32]).unwrap();
    assert!(other.verify_response(KEY, 200, b"healthy", &tag).is_err());
    assert!(
        first
            .verify_response(&[4; 32], 200, b"healthy", &tag)
            .is_err()
    );
    assert!(
        !first
            .header_value()
            .contains(std::str::from_utf8(KEY).unwrap())
    );
}
#[test]
fn invalid_headers_and_unknown_routes_are_rejected() {
    for value in [
        "",
        "Bearer abc",
        "Hepta-MAC-V2 1:a:b:c",
        "Hepta-MAC-V2 1:🦀",
    ] {
        assert!(NativeGatewayRequestV2::parse_header(value).is_err());
    }
    assert!(NativeGatewayRequestV2::sign(KEY, "/mutate", [1; 32], 1, [2; 32]).is_err());
    assert!(NativeGatewayRequestV2::sign(KEY, "/healthz", [0; 32], 1, [0; 32]).is_err());
    assert!(parse_native_gateway_incarnation(&"0".repeat(64)).is_err());
}
