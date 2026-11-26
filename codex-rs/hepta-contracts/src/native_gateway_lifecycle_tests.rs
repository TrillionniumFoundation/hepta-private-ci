use super::*;

#[test]
fn lifecycle_proof_binds_finite_operation_exact_post_body_and_incarnation() {
    let key = [7; 32];
    let incarnation = [9; 32];
    let body = b"{\"request_id\":71}";
    let proof = NativeGatewayLifecycleRequestV2::sign(
        &key,
        "POST",
        NATIVE_GATEWAY_LIFECYCLE_PATH,
        NativeGatewayLifecycleOperationV2::Stop,
        body,
        [3; 32],
        100_000,
        incarnation,
    )
    .unwrap();
    let proof = NativeGatewayLifecycleRequestV2::parse_header(&proof.header_value()).unwrap();
    proof
        .verify(
            &key,
            "POST",
            NATIVE_GATEWAY_LIFECYCLE_PATH,
            NativeGatewayLifecycleOperationV2::Stop,
            body,
            100_001,
            &incarnation,
        )
        .unwrap();
    for (method, path, operation, changed, epoch) in [
        (
            "GET",
            NATIVE_GATEWAY_LIFECYCLE_PATH,
            NativeGatewayLifecycleOperationV2::Stop,
            body.as_slice(),
            incarnation,
        ),
        (
            "POST",
            "/api/hepta/runtime",
            NativeGatewayLifecycleOperationV2::Stop,
            body.as_slice(),
            incarnation,
        ),
        (
            "POST",
            NATIVE_GATEWAY_LIFECYCLE_PATH,
            NativeGatewayLifecycleOperationV2::Restart,
            body.as_slice(),
            incarnation,
        ),
        (
            "POST",
            NATIVE_GATEWAY_LIFECYCLE_PATH,
            NativeGatewayLifecycleOperationV2::Stop,
            b"{}".as_slice(),
            incarnation,
        ),
        (
            "POST",
            NATIVE_GATEWAY_LIFECYCLE_PATH,
            NativeGatewayLifecycleOperationV2::Stop,
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
                NATIVE_GATEWAY_LIFECYCLE_PATH,
                NativeGatewayLifecycleOperationV2::Stop,
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
                NATIVE_GATEWAY_LIFECYCLE_PATH,
                NativeGatewayLifecycleOperationV2::Stop,
                body,
                131_000,
                &incarnation
            )
            .is_err()
    );
}

#[test]
fn lifecycle_and_read_proofs_are_not_interchangeable_and_response_is_bound() {
    let key = [7; 32];
    let epoch = [9; 32];
    let read =
        NativeGatewayRequestV2::sign(&key, "/api/hepta/runtime", [3; 32], 100_000, epoch).unwrap();
    assert!(NativeGatewayLifecycleRequestV2::parse_header(&read.header_value()).is_err());
    let proof = NativeGatewayLifecycleRequestV2::sign(
        &key,
        "POST",
        NATIVE_GATEWAY_LIFECYCLE_PATH,
        NativeGatewayLifecycleOperationV2::Receipt,
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
        .replace("Hepta-Lifecycle-MAC-V2", "Hepta-MAC-V2");
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
        NativeGatewayLifecycleRequestV2::sign(
            &key,
            "POST",
            NATIVE_GATEWAY_LIFECYCLE_PATH,
            NativeGatewayLifecycleOperationV2::Start,
            b"{}",
            [4; 32],
            100_000,
            [0; 32]
        )
        .is_err()
    );
}
