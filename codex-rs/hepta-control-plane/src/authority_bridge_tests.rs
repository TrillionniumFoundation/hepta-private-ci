#![cfg(unix)]

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::AuthorityBridgeError;
use super::claim_final_use_for_grant_request_v1;
use super::final_use_binding_for_grant_request_v1;
use super::with_authorized_grant_request_v1;
use crate::GrantRequestV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn request() -> GrantRequestV1 {
    GrantRequestV1 {
        operation_id: id("operation:publish"),
        candidate_id: id("candidate:publish"),
        plan_digest: digest("plan"),
        final_payload_digest: digest("payload"),
        objective_digest: digest("objective"),
        snapshot_digest: digest("snapshot"),
        revocation_frontier_digest: digest("revocation-frontier"),
        expires_at_micros: 9_000,
    }
}

fn signed_grant(
    signing: &SigningKey,
    binding: codex_hepta_contracts::FinalUseBinding,
) -> SignedFinalUseGrant {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("wall clock")
            .as_millis(),
    )
    .expect("milliseconds fit");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "planner-grant-issuer".to_string(),
        authority_epoch: 3,
        grant_id: "grant:planner:1".to_string(),
        nonce: [17; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(100),
        expires_at_unix_ms: now + 5_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("canonical grant"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn authority(
    directory: &std::path::Path,
    signing: &SigningKey,
) -> FinalUseAuthority {
    FinalUseAuthority::open_state_dir(
        directory,
        "planner-grant-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 3,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority")
}

#[test]
fn independent_authority_claims_exact_planner_binding() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[31; 32]);
    let authority = authority(&temporary.path().join("authority"), &signing);
    let request = request();
    let subject = id("agent:alpha");
    let destination = id("provider:effect");
    let scope = digest("effect-scope");
    let binding =
        final_use_binding_for_grant_request_v1(&request, &subject, &destination, scope)
            .expect("binding");
    let signed = signed_grant(&signing, binding.clone());

    let token = claim_final_use_for_grant_request_v1(
        &authority,
        &signed,
        &request,
        &subject,
        &destination,
        scope,
    )
    .expect("independent authority claim");

    let released = authority
        .with_verified_use(token, &binding, || "released")
        .expect("final revalidation");
    assert_eq!(released, "released");
}


#[test]
fn final_boundary_helper_revalidates_and_consumes_authority_once() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[33; 32]);
    let authority = authority(&temporary.path().join("authority"), &signing);
    let request = request();
    let subject = id("agent:alpha");
    let destination = id("provider:effect");
    let scope = digest("effect-scope");
    let binding =
        final_use_binding_for_grant_request_v1(&request, &subject, &destination, scope)
            .expect("binding");
    let signed = signed_grant(&signing, binding);

    let released = with_authorized_grant_request_v1(
        &authority,
        &signed,
        &request,
        &subject,
        &destination,
        scope,
        || "released",
    )
    .expect("final boundary");
    assert_eq!(released, "released");

    assert_eq!(
        with_authorized_grant_request_v1(
            &authority,
            &signed,
            &request,
            &subject,
            &destination,
            scope,
            || "must-not-run",
        )
        .expect_err("nonce reuse must fail before dispatch"),
        AuthorityBridgeError::Authority(FinalUseError::AlreadyClaimed)
    );
}

#[test]
fn payload_drift_is_rejected_by_independent_authority_binding() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let signing = SigningKey::from_bytes(&[32; 32]);
    let authority = authority(&temporary.path().join("authority"), &signing);
    let original = request();
    let subject = id("agent:alpha");
    let destination = id("provider:effect");
    let scope = digest("effect-scope");
    let binding =
        final_use_binding_for_grant_request_v1(&original, &subject, &destination, scope)
            .expect("binding");
    let signed = signed_grant(&signing, binding);

    let mut changed = original;
    changed.final_payload_digest = digest("changed-payload");
    assert_eq!(
        claim_final_use_for_grant_request_v1(
            &authority,
            &signed,
            &changed,
            &subject,
            &destination,
            scope,
        )
        .expect_err("changed final payload must not reuse signed authority"),
        AuthorityBridgeError::Authority(FinalUseError::BindingMismatch)
    );
}
