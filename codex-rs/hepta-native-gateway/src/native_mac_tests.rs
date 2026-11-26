use super::*;
use crate::test_bearer_token;

fn request(
    auth: &GatewayAuth,
    path: &str,
    nonce: [u8; 32],
    server: [u8; 32],
) -> (String, NativeGatewayRequestV2) {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let proof =
        NativeGatewayRequestV2::sign(auth.bearer_token.as_bytes(), path, nonce, now, server)
            .unwrap();
    (
        format!(
            "GET {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: {}\r\n\r\n",
            proof.header_value()
        ),
        proof,
    )
}
#[test]
fn native_proofs_are_single_use_and_do_not_expose_the_secret() {
    let auth = GatewayAuth::new(test_bearer_token().to_owned()).unwrap();
    let (wire, _) = request(&auth, "/healthz", [1; 32], [0; 32]);
    assert!(!wire.contains(test_bearer_token()));
    assert!(authenticate(&wire, &auth).unwrap().is_some());
    assert!(authenticate(&wire, &auth).is_err());
}
#[test]
fn restarted_server_and_substituted_target_reject_old_read_proofs() {
    let auth = GatewayAuth::new(test_bearer_token().to_owned()).unwrap();
    let other = GatewayAuth::new(test_bearer_token().to_owned()).unwrap();
    let (wire, _) = request(
        &auth,
        "/api/hepta/runtime",
        [2; 32],
        auth.server_incarnation,
    );
    assert!(authenticate(&wire, &other).is_err());
    assert!(authenticate(&wire.replace("/api/hepta/runtime", "/healthz"), &auth).is_err());
    assert!(authenticate(&wire, &auth).unwrap().is_some());
}
#[test]
fn response_proof_covers_status_body_and_originating_request() {
    let auth = GatewayAuth::new(test_bearer_token().to_owned()).unwrap();
    let (_, proof) = request(&auth, "/healthz", [3; 32], [0; 32]);
    let wire = sign_response(
        crate::response("200 OK", "application/json", b"{}"),
        &proof,
        &auth,
    )
    .unwrap();
    let split = wire.windows(4).position(|v| v == b"\r\n\r\n").unwrap();
    let header = std::str::from_utf8(&wire[..split]).unwrap();
    let tag = header
        .lines()
        .find_map(|l| l.strip_prefix("X-Hepta-Response-MAC: "))
        .unwrap();
    proof
        .verify_response(auth.bearer_token.as_bytes(), 200, &wire[split + 4..], tag)
        .unwrap();
    assert!(
        proof
            .verify_response(auth.bearer_token.as_bytes(), 200, b"forged", tag)
            .is_err()
    );
}
