use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn parsed_reference() -> ParsedSecretReferenceV1 {
    let secret_digest = digest(b"secret-digest").to_string();
    let Ok(reference) =
        ParsedSecretReferenceV1::parse_parts("heptabao", "secret:1", "3", &secret_digest)
    else {
        panic!("reference fixture must parse");
    };
    reference
}

fn boundary_fixture(
    status: SecretPermissionStatusV1,
) -> (SecretBoundaryRequestV1, SecretPermissionObservationV1) {
    let request = SecretBoundaryRequestV1 {
        schema_version: SECRET_BOUNDARY_SCHEMA_VERSION_V1,
        request_id: id("request:boundary:1"),
        operation_id: id("operation:1"),
        principal_id: id("principal:1"),
        destination_id: id(HEPTABAO_DESTINATION_ID),
        reference: parsed_reference(),
        scope_digest: digest(b"scope"),
        payload_digest: digest(b"final-payload"),
        deadline_ms: 2_000,
    };
    let Ok(request_digest) = secret_boundary_request_digest_v1(&request) else {
        panic!("request fixture must validate");
    };
    let permission = SecretPermissionObservationV1 {
        schema_version: SECRET_BOUNDARY_SCHEMA_VERSION_V1,
        authority_producer_id: id(KERNEL_AUTHORITY_PRODUCER_ID),
        policy_producer_id: id(AUTHBUS_POLICY_PRODUCER_ID),
        principal_id: request.principal_id.clone(),
        operation_id: request.operation_id.clone(),
        destination_id: request.destination_id.clone(),
        request_digest,
        reference_digest: request.reference.digest(),
        scope_digest: request.scope_digest,
        payload_digest: request.payload_digest,
        grant_id: Some(id("grant:1")),
        quota_reservation_id: Some(id("quota:1")),
        authority_epoch: 7,
        revocation_revision: 9,
        policy_revision: 11,
        quota_revision: 13,
        not_before_ms: 500,
        expires_at_ms: 2_500,
        revoked: false,
        status,
    };
    (request, permission)
}

fn fixture() -> (SecretRequest, SecretLease) {
    let reference = SecretReference {
        secret_id: id("secret:1"),
        version: 3,
        secret_digest: digest(b"secret-digest"),
    };
    let request = SecretRequest {
        request_id: id("request:1"),
        reference: reference.clone(),
        scope_digest: digest(b"scope"),
        deadline_ms: 2_000,
    };
    let lease = SecretLease {
        lease_id: id("lease:1"),
        secret_id: reference.secret_id,
        version: reference.version,
        secret_digest: reference.secret_digest,
        scope_digest: request.scope_digest,
        expires_at_ms: 1_500,
        revoked: false,
    };
    (request, lease)
}

#[test]
fn exact_reference_returns_only_opaque_digest() {
    let (request, lease) = fixture();
    let Ok(receipt) = resolve(1_000, request, lease) else {
        panic!("exact secret reference must resolve");
    };
    assert!(!receipt.contains_raw_secret);
    assert!(!receipt.authority.grants_any());
    assert_eq!(
        receipt.opaque_handle_digest.to_string(),
        "d119d2033c20d37672af96289859582a931b39204299cfdd99cdc36064988181"
    );
}

#[test]
fn revoked_lease_is_rejected() {
    let (request, mut lease) = fixture();
    lease.revoked = true;
    assert_eq!(resolve(1_000, request, lease), Err(Error::LeaseRevoked));
}

#[test]
fn scope_drift_is_rejected() {
    let (request, mut lease) = fixture();
    lease.scope_digest = digest(b"other");
    assert_eq!(resolve(1_000, request, lease), Err(Error::ScopeMismatch));
}

#[test]
fn version_drift_is_rejected() {
    let (request, mut lease) = fixture();
    lease.version = 4;
    assert_eq!(resolve(1_000, request, lease), Err(Error::VersionMismatch));
}

#[test]
fn bounded_reference_parser_rejects_hostile_components() {
    let digest_hex = digest(b"secret-digest").to_string();
    let maximum = "x".repeat(MAX_SECRET_REFERENCE_COMPONENT_BYTES);
    assert!(ParsedSecretReferenceV1::parse_parts("heptabao", &maximum, "3", &digest_hex).is_ok());
    let oversized = "x".repeat(MAX_SECRET_REFERENCE_COMPONENT_BYTES + 1);
    assert_eq!(
        ParsedSecretReferenceV1::parse_parts("heptabao", &oversized, "3", &digest_hex),
        Err(SecretBoundaryErrorV1::InputTooLarge {
            field: "reference id",
            maximum: MAX_SECRET_REFERENCE_COMPONENT_BYTES,
        })
    );
    assert_eq!(
        ParsedSecretReferenceV1::parse_parts("heptabao", "../secret", "3", &digest_hex),
        Err(SecretBoundaryErrorV1::InvalidField("reference id"))
    );
    assert_eq!(
        ParsedSecretReferenceV1::parse_parts("other", "secret:1", "3", &digest_hex),
        Err(SecretBoundaryErrorV1::UnsupportedBackend)
    );
    assert_eq!(
        ParsedSecretReferenceV1::parse_parts("heptabao", "secret:1", "03", &digest_hex),
        Err(SecretBoundaryErrorV1::InvalidField("version"))
    );
    assert_eq!(
        ParsedSecretReferenceV1::parse_parts(
            "heptabao",
            "secret:1",
            "3",
            &digest_hex.to_uppercase(),
        ),
        Err(SecretBoundaryErrorV1::InvalidField("secret digest"))
    );
}

#[test]
fn unknown_schema_and_expired_request_are_rejected() {
    let (mut request, permission) = boundary_fixture(SecretPermissionStatusV1::Denied);
    request.schema_version = 2;
    assert_eq!(
        assess_secret_boundary_v1(1_000, &request, &permission),
        Err(SecretBoundaryErrorV1::UnsupportedSchemaVersion("request"))
    );

    let (request, permission) = boundary_fixture(SecretPermissionStatusV1::Denied);
    assert_eq!(
        assess_secret_boundary_v1(request.deadline_ms, &request, &permission),
        Err(SecretBoundaryErrorV1::DeadlineExpired)
    );
}

#[test]
fn current_permission_still_cannot_self_mint_provider_authority() {
    let (request, permission) = boundary_fixture(SecretPermissionStatusV1::Granted);
    let Ok(decision) = assess_secret_boundary_v1(1_000, &request, &permission) else {
        panic!("bounded assessment must be representable");
    };
    assert_eq!(
        decision.disposition(),
        SecretBoundaryDispositionV1::VerifiedUseTokenUnavailable
    );
    assert_eq!(decision.request_digest(), permission.request_digest);
    assert_eq!(decision.reference_digest(), permission.reference_digest);
    assert!(!decision.permission_observation_digest().is_zero());
    assert!(!decision.contains_raw_secret());
    assert!(!decision.provider_dispatch_attempted());
    assert!(!decision.authority().grants_any());
}

#[test]
fn denied_unavailable_and_indeterminate_remain_distinct() {
    for (status, expected) in [
        (
            SecretPermissionStatusV1::Denied,
            SecretBoundaryDispositionV1::PermissionDenied,
        ),
        (
            SecretPermissionStatusV1::Unavailable,
            SecretBoundaryDispositionV1::AuthorityUnavailable,
        ),
        (
            SecretPermissionStatusV1::Indeterminate,
            SecretBoundaryDispositionV1::AuthorityIndeterminate,
        ),
    ] {
        let (request, permission) = boundary_fixture(status);
        let Ok(decision) = assess_secret_boundary_v1(1_000, &request, &permission) else {
            panic!("negative authority state must be represented");
        };
        assert_eq!(decision.disposition(), expected);
        assert!(!decision.authority().grants_any());
    }
}

#[test]
fn revoked_and_stale_grants_fail_before_any_effect() {
    let (request, mut permission) = boundary_fixture(SecretPermissionStatusV1::Granted);
    permission.revoked = true;
    let Ok(revoked) = assess_secret_boundary_v1(1_000, &request, &permission) else {
        panic!("revocation must produce a decision");
    };
    assert_eq!(
        revoked.disposition(),
        SecretBoundaryDispositionV1::GrantRevoked
    );
    assert!(!revoked.provider_dispatch_attempted());

    permission.revoked = false;
    permission.expires_at_ms = 1_500;
    let Ok(expired) = assess_secret_boundary_v1(1_600, &request, &permission) else {
        panic!("expired grant must produce a decision");
    };
    assert_eq!(
        expired.disposition(),
        SecretBoundaryDispositionV1::GrantExpired
    );
    assert!(!expired.provider_dispatch_attempted());
}

#[test]
fn producer_principal_and_payload_bindings_are_exact() {
    let (request, mut permission) = boundary_fixture(SecretPermissionStatusV1::Granted);
    permission.authority_producer_id = id("attacker.authority");
    assert_eq!(
        assess_secret_boundary_v1(1_000, &request, &permission),
        Err(SecretBoundaryErrorV1::ProducerIdentityMismatch("authority"))
    );

    let (request, mut permission) = boundary_fixture(SecretPermissionStatusV1::Granted);
    permission.principal_id = id("principal:other");
    assert_eq!(
        assess_secret_boundary_v1(1_000, &request, &permission),
        Err(SecretBoundaryErrorV1::BindingMismatch("principal"))
    );

    let (mut request, mut permission) = boundary_fixture(SecretPermissionStatusV1::Granted);
    request.payload_digest = digest(b"drifted-payload");
    permission.request_digest = secret_boundary_request_digest_v1(&request)
        .unwrap_or_else(|error| panic!("changed request must remain valid: {error}"));
    assert_eq!(
        assess_secret_boundary_v1(1_000, &request, &permission),
        Err(SecretBoundaryErrorV1::BindingMismatch("payload"))
    );
}

#[test]
fn incomplete_or_overlong_grant_metadata_never_degrades_to_success() {
    let (request, mut permission) = boundary_fixture(SecretPermissionStatusV1::Granted);
    permission.quota_reservation_id = None;
    assert_eq!(
        assess_secret_boundary_v1(1_000, &request, &permission),
        Err(SecretBoundaryErrorV1::IncompleteGrant)
    );

    let result = ParsedSecretReferenceV1::parse_parts(
        "heptabao",
        &"s".repeat(MAX_SECRET_REFERENCE_COMPONENT_BYTES + 1),
        "3",
        &digest(b"secret-digest").to_string(),
    );
    let Err(error) = result else {
        panic!("oversized reference must fail");
    };
    assert!(!error.to_string().contains(&"s".repeat(32)));
}
