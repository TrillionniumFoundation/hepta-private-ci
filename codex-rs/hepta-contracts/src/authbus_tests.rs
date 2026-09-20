use super::*;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn owner() -> Principal {
    Principal::new("owner:qualification").expect("owner")
}

fn subject() -> SubjectRef {
    SubjectRef::new("tenant-a", "workspace-a", "agent-a", "inferd", 7).expect("subject")
}

fn request() -> AuthRequest {
    AuthRequest {
        schema_version: AUTHBUS_CONTRACT_SCHEMA_VERSION,
        request_id: "request:qualification-1".to_string(),
        subject: subject(),
        resource_sha256: digest("resource:qualification"),
        payload_sha256: digest("payload:qualification"),
        model_sha256: Some(digest("model:qualification")),
        audience: "hepta-authbus-qualification".to_string(),
        max_usage: 128,
        deadline_unix_seconds: 1_500,
        expected_revision: 4,
        owner_epoch: 3,
        generation: 7,
        policy_sha256: digest("policy:qualification"),
        nonce_sha256: digest("nonce:qualification"),
    }
}

fn pending_lease() -> ResourceLease {
    ResourceLease::new("lease:qualification-1", request(), owner(), 9, 1_000, 2_000).expect("lease")
}

fn active_lease() -> ResourceLease {
    let lease = pending_lease();
    lease
        .transition(1, 9, LeaseState::Active)
        .expect("active lease")
}

#[test]
fn source_manifest_fixture_is_pinned_and_fail_closed() {
    let manifest = embedded_source_manifest().expect("embedded manifest");
    assert_eq!(manifest.schema, AUTHBUS_SOURCE_MANIFEST_SCHEMA);
    assert_eq!(manifest.plan_id, AUTHBUS_PLAN_ID);
    assert_eq!(manifest.status, "LOCAL_QUALIFICATION_ONLY");
    assert_eq!(manifest.source_binding_status, "CAPTURED_LOCAL_SNAPSHOT");
    assert_eq!(manifest.captured_at, "2026-08-26T18:12:00+08:00");
    assert_eq!(manifest.upstream.repository, BASIL_UPSTREAM_REPOSITORY);
    assert_eq!(manifest.upstream.commit, BASIL_UPSTREAM_COMMIT);
    assert_eq!(manifest.upstream.workspace_version, BASIL_WORKSPACE_VERSION);
    assert_eq!(
        manifest.upstream.latest_published_release,
        BASIL_LATEST_RELEASE
    );
    assert_eq!(manifest.upstream.license, BASIL_LICENSE);
    assert_eq!(
        manifest.upstream.source_status,
        "PINNED_RESEARCH_BASELINE_NOT_IMPORTED"
    );
    assert_eq!(manifest.upstream.sbom_status, "NOT_CAPTURED");
    assert_eq!(manifest.upstream.native_build_status, "NOT_RUN");
    assert_eq!(
        manifest.candidate.commit,
        "983470042b76becd76ffcc5a23f5b711a04823e8"
    );
    assert_eq!(
        manifest.candidate.tree,
        "dd852801437c0631706e5c88045d00617fb5b587"
    );
    assert_eq!(manifest.attachments.len(), 6);
    assert_eq!(
        manifest.attachments[0].sha256.as_str(),
        "3e32cc14eec5827cd3778e09b4409d38221155fe826ce257aab9354cca9d36ed"
    );
    assert_eq!(manifest.gaps.len(), 3);
    assert!(manifest.authority.all_false());
    assert_eq!(
        manifest.digest().expect("manifest digest").as_str(),
        "bac4cda2391d82b1796ace0b0f95cb72eea3de4086bb68c2f26f5eca1610cd0b"
    );
}

#[test]
fn source_manifest_rejects_authority_and_unknown_fields() {
    let mut value: serde_json::Value =
        serde_json::from_str(AUTHBUS_SOURCE_MANIFEST_JSON).expect("manifest json");
    value["authority"]["execute_allowed"] = serde_json::Value::Bool(true);
    let tampered: AuthBusSourceManifest =
        serde_json::from_value(value.clone()).expect("wire shape remains valid");
    assert!(tampered.validate().is_err());

    value["authority"]["execute_allowed"] = serde_json::Value::Bool(false);
    value["unexpected"] = serde_json::Value::Bool(true);
    assert!(serde_json::from_value::<AuthBusSourceManifest>(value).is_err());
}

#[test]
fn source_manifest_requires_exact_observed_candidate_binding() {
    let manifest = embedded_source_manifest().expect("embedded manifest");

    // The checked-in fixture predates the current canonical qualification
    // checkout.  It must not be accepted as evidence for that checkout.
    let error = manifest
        .validate_for_candidate(
            "4d5b0b2d082ddbe0abb6d2fc880d9d9448434ab2",
            "a3988c2d4624437080a2cdb65185ce74e7cee488",
        )
        .expect_err("stale candidate binding must fail closed");
    assert!(error.to_string().contains("candidate commit"));
    assert!(
        embedded_source_manifest_for_candidate(
            "4d5b0b2d082ddbe0abb6d2fc880d9d9448434ab2",
            "a3988c2d4624437080a2cdb65185ce74e7cee488",
        )
        .is_err()
    );
}

#[test]
fn source_manifest_accepts_matching_observed_candidate_binding() {
    let manifest = embedded_source_manifest().expect("embedded manifest");
    let commit = manifest.candidate.commit.clone();
    let tree = manifest.candidate.tree.clone();

    assert!(manifest.validate_for_candidate(&commit, &tree).is_ok());
    assert!(embedded_source_manifest_for_candidate(&commit, &tree).is_ok());
}

#[test]
fn source_manifest_rejects_malformed_expected_candidate_binding() {
    let manifest = embedded_source_manifest().expect("embedded manifest");
    assert!(
        manifest
            .validate_for_candidate("not-a-commit", &manifest.candidate.tree)
            .is_err()
    );
    assert!(
        manifest
            .validate_for_candidate(&manifest.candidate.commit, "not-a-tree")
            .is_err()
    );
}

#[test]
fn auth_request_has_stable_versioned_golden_bytes() {
    let request = request();
    let bytes = request.canonical_bytes().expect("request bytes");
    assert_eq!(
        String::from_utf8(bytes).expect("utf8"),
        "{\"schema_version\":1,\"request_id\":\"request:qualification-1\",\"subject\":{\"tenant\":\"tenant-a\",\"workspace\":\"workspace-a\",\"agent\":\"agent-a\",\"service\":\"inferd\",\"generation\":7},\"resource_sha256\":\"9886f608649fb8e819958ba549a4617a7e30f7f853b9f9a72de7e42097d478f9\",\"payload_sha256\":\"3afc5eec039e5f50c139dc691869c3c756b53d7356cb9306c2b2c2888d307339\",\"model_sha256\":\"d6b058822746b870515a0a791db9b2bdbd800057835533439f47b16efff06395\",\"audience\":\"hepta-authbus-qualification\",\"max_usage\":128,\"deadline_unix_seconds\":1500,\"expected_revision\":4,\"owner_epoch\":3,\"generation\":7,\"policy_sha256\":\"2cab61a08e60d2fc478120b3a636c20bf5967642784e41c409753f8d6910b794\",\"nonce_sha256\":\"5da1113d840943a5723f958a8f37f7b516dff46751c3ea05089afa81c138a1e9\"}"
    );
    assert_eq!(
        request.digest().expect("request digest").as_str(),
        "e7739335deb497c99239a1c407f3f8642a1bc45fc299c667709b52c23296cb39"
    );
}

#[test]
fn auth_request_fences_subject_generation() {
    let mut request = request();
    request.generation += 1;
    assert!(request.validate().is_err());
    assert!(request.canonical_bytes().is_err());
    assert!(request.digest().is_err());
}

#[test]
fn lease_cas_epoch_and_permit_binding_are_strict() {
    let pending = pending_lease();
    assert!(pending.transition(0, 9, LeaseState::Active).is_err());
    assert!(pending.transition(1, 8, LeaseState::Active).is_err());

    let active = pending
        .transition(1, 9, LeaseState::Active)
        .expect("active");
    assert_eq!(active.revision, 2);
    assert_eq!(active.state, LeaseState::Active);
    let replay = active
        .transition(2, 9, LeaseState::Active)
        .expect("idempotent replay");
    assert_eq!(replay, active);
    assert!(active.transition(2, 9, LeaseState::Pending).is_err());

    let permit = UsagePermit::from_lease(&active, "permit:qualification-1", digest("fence"))
        .expect("permit");
    assert_eq!(
        permit.digest().expect("permit digest").as_str(),
        "42ff94d324746ee0d87da005b8abf85c67531bd98a58c45240462b1a0ca753ae"
    );
    assert_eq!(permit.lease_revision, active.revision);
    assert_eq!(permit.resource_sha256, active.request.resource_sha256);
    assert!(
        UsagePermit::from_lease(
            &pending,
            "permit:qualification-pending",
            digest("fence-pending")
        )
        .is_err()
    );
}

#[test]
fn usage_permit_rejects_subject_generation_mismatch() {
    let active = active_lease();
    let mut permit =
        UsagePermit::from_lease(&active, "permit:qualification-generation", digest("fence"))
            .expect("permit");
    permit.subject.generation += 1;

    assert!(permit.validate().is_err());
    assert!(permit.canonical_bytes().is_err());
    assert!(permit.digest().is_err());

    let mut encoded = serde_json::to_value(
        UsagePermit::from_lease(
            &active,
            "permit:qualification-generation-wire",
            digest("fence-wire"),
        )
        .expect("permit"),
    )
    .expect("permit json");
    encoded["subject"]["generation"] = serde_json::Value::Number(serde_json::Number::from(8));
    let forged: UsagePermit = serde_json::from_value(encoded).expect("wire shape");
    assert!(forged.validate().is_err());
}

#[test]
fn usage_receipt_binds_permit_and_preserves_indeterminate() {
    let active = active_lease();
    let permit = UsagePermit::from_lease(&active, "permit:qualification-1", digest("fence"))
        .expect("permit");
    let receipt = UsageReceipt::new(
        &permit,
        "receipt:qualification-1",
        1_200,
        UsageTerminal::Consumed { used: 3 },
    )
    .expect("receipt");
    assert_eq!(
        receipt.receipt_sha256.as_str(),
        "4ed882e8b88fa0a3f8765278e656b7eba13311583ef759f75340b48a3299f3bd"
    );
    assert_eq!(
        receipt.digest().expect("receipt digest").as_str(),
        "d10fa546273b594e2af02e914654fc239a2ed0fadca4336b67a840272a26f829"
    );
    receipt.validate_against(&permit).expect("receipt binding");

    let uncertain = UsageReceipt::new(
        &permit,
        "receipt:qualification-2",
        1_201,
        UsageTerminal::Indeterminate {
            reason_code: "provider_timeout".to_string(),
        },
    )
    .expect("indeterminate receipt");
    assert!(matches!(
        uncertain.terminal,
        UsageTerminal::Indeterminate { .. }
    ));

    let mut tampered = receipt.clone();
    tampered.permit_id = "permit:other".to_string();
    assert!(tampered.validate_against(&permit).is_err());
    let mut oversized = receipt;
    oversized.terminal = UsageTerminal::Consumed { used: 129 };
    assert!(oversized.validate_against(&permit).is_err());
}

#[test]
fn revoke_binds_owner_revision_and_epoch() {
    let active = active_lease();
    let revoke = Revoke::for_lease(
        &active,
        "revoke:qualification-1",
        "operator_requested",
        1_300,
    )
    .expect("revoke");
    revoke.validate_against(&active).expect("revoke binding");
    assert_eq!(revoke.expected_revision, active.revision);
    assert_eq!(revoke.revocation_revision, active.revision + 1);

    let mut stale = revoke;
    stale.expected_revision -= 1;
    assert!(stale.validate_against(&active).is_err());
    let revoked = active
        .transition(active.revision, active.authority_epoch, LeaseState::Revoked)
        .expect("revoked");
    assert!(
        UsagePermit::from_lease(
            &revoked,
            "permit:after-revoke",
            digest("fence-after-revoke")
        )
        .is_err()
    );
}

#[test]
fn wire_round_trip_is_strict_and_secret_free() {
    let active = active_lease();
    let permit = UsagePermit::from_lease(&active, "permit:qualification-1", digest("fence"))
        .expect("permit");
    let bytes = serde_json::to_vec(&permit).expect("permit json");
    assert_eq!(
        serde_json::from_slice::<UsagePermit>(&bytes).expect("permit round trip"),
        permit
    );
    let unknown = format!(
        "{}\n",
        String::from_utf8(bytes)
            .expect("utf8")
            .trim_end_matches('}')
            .to_owned()
            + ",\"unexpected\":true}"
    );
    assert!(serde_json::from_str::<UsagePermit>(&unknown).is_err());

    let secret_ref =
        SecretRef::new("openbao", "kv/data/hepta/authbus/qualification").expect("secret ref");
    let secret_json = serde_json::to_string(&secret_ref).expect("secret ref json");
    assert!(secret_json.contains("reference"));
    assert!(!secret_json.contains("access_token"));
    assert!(!secret_json.contains("private_key"));
    assert!(!secret_json.contains("raw_secret"));
}
