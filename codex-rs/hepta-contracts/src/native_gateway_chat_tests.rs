#![allow(clippy::unwrap_used)]
use super::*;

#[test]
fn chat_proof_binds_finite_operation_exact_post_body_and_incarnation() {
    let key = [7; 32];
    let incarnation = [9; 32];
    let body = b"{\"request_id\":71}";
    let proof = NativeGatewayChatRequestV2::sign(
        &key,
        "POST",
        NATIVE_GATEWAY_CHAT_PATH,
        NativeGatewayChatOperationV2::Send,
        body,
        [3; 32],
        100_000,
        incarnation,
    )
    .unwrap();
    let proof = NativeGatewayChatRequestV2::parse_header(&proof.header_value()).unwrap();
    proof
        .verify(
            &key,
            "POST",
            NATIVE_GATEWAY_CHAT_PATH,
            NativeGatewayChatOperationV2::Send,
            body,
            100_001,
            &incarnation,
        )
        .unwrap();
    for (method, path, operation, changed, epoch) in [
        (
            "GET",
            NATIVE_GATEWAY_CHAT_PATH,
            NativeGatewayChatOperationV2::Send,
            body.as_slice(),
            incarnation,
        ),
        (
            "POST",
            "/api/hepta/runtime",
            NativeGatewayChatOperationV2::Send,
            body.as_slice(),
            incarnation,
        ),
        (
            "POST",
            NATIVE_GATEWAY_CHAT_PATH,
            NativeGatewayChatOperationV2::Cancel,
            body.as_slice(),
            incarnation,
        ),
        (
            "POST",
            NATIVE_GATEWAY_CHAT_PATH,
            NativeGatewayChatOperationV2::Send,
            b"{}".as_slice(),
            incarnation,
        ),
        (
            "POST",
            NATIVE_GATEWAY_CHAT_PATH,
            NativeGatewayChatOperationV2::Send,
            body.as_slice(),
            [8; 32],
        ),
    ] {
        assert!(
            proof
                .verify(&key, method, path, operation, changed, 100_001, &epoch)
                .is_err()
        );
    }
    assert!(
        proof
            .verify(
                &[6; 32],
                "POST",
                NATIVE_GATEWAY_CHAT_PATH,
                NativeGatewayChatOperationV2::Send,
                body,
                100_001,
                &incarnation
            )
            .is_err()
    );
    assert!(
        proof
            .verify(
                &key,
                "POST",
                NATIVE_GATEWAY_CHAT_PATH,
                NativeGatewayChatOperationV2::Send,
                body,
                131_000,
                &incarnation
            )
            .is_err()
    );
}

#[test]
fn chat_and_read_proofs_are_not_interchangeable_and_response_is_bound() {
    let key = [7; 32];
    let epoch = [9; 32];
    let read =
        NativeGatewayRequestV2::sign(&key, "/api/hepta/runtime", [3; 32], 100_000, epoch).unwrap();
    assert!(NativeGatewayChatRequestV2::parse_header(&read.header_value()).is_err());
    let proof = NativeGatewayChatRequestV2::sign(
        &key,
        "POST",
        NATIVE_GATEWAY_CHAT_PATH,
        NativeGatewayChatOperationV2::Reconcile,
        b"{}",
        [4; 32],
        100_000,
        epoch,
    )
    .unwrap();
    assert!(NativeGatewayRequestV2::parse_header(&proof.header_value()).is_err());
    // Changing the public scheme cannot change the authenticated purpose.
    let substituted = proof
        .header_value()
        .replace("Hepta-Chat-MAC-V2", "Hepta-MAC-V2");
    assert!(
        NativeGatewayRequestV2::parse_header(&substituted)
            .unwrap()
            .verify(&key, "/api/hepta/runtime", 100_001, &epoch)
            .is_err()
    );
    let tag = proof.response_tag(&key, 200, b"receipt").unwrap();
    proof.verify_response(&key, 200, b"receipt", &tag).unwrap();
    assert!(proof.verify_response(&key, 200, b"foreign", &tag).is_err());
    assert!(read.verify_response(&key, 200, b"receipt", &tag).is_err());
    assert!(
        NativeGatewayChatRequestV2::sign(
            &key,
            "POST",
            NATIVE_GATEWAY_CHAT_PATH,
            NativeGatewayChatOperationV2::Attach,
            b"{}",
            [4; 32],
            100_000,
            [0; 32]
        )
        .is_err()
    );
}

#[test]
fn chat_and_lifecycle_purposes_reject_a_substituted_public_scheme() {
    use super::super::lifecycle::NativeGatewayLifecycleOperationV2;
    use super::super::lifecycle::NativeGatewayLifecycleRequestV2;
    let key = [7; 32];
    let epoch = [9; 32];
    let lifecycle = NativeGatewayLifecycleRequestV2::sign(
        &key,
        "POST",
        super::super::lifecycle::NATIVE_GATEWAY_LIFECYCLE_PATH,
        NativeGatewayLifecycleOperationV2::Receipt,
        b"{}",
        [3; 32],
        100_000,
        epoch,
    )
    .unwrap();
    let header = lifecycle
        .header_value()
        .replace("Hepta-Lifecycle-MAC-V2", "Hepta-Chat-MAC-V2");
    let substituted = NativeGatewayChatRequestV2::parse_header(&header).unwrap();
    assert!(
        substituted
            .verify(
                &key,
                "POST",
                NATIVE_GATEWAY_CHAT_PATH,
                NativeGatewayChatOperationV2::Reconcile,
                b"{}",
                100_001,
                &epoch
            )
            .is_err()
    );
}
