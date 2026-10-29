use super::*;
use crate::FinalUseApproval;
use crate::FinalUseApprovalVerifier;
use crate::FinalUseRevocationAck;
use crate::FinalUseRevocationConvergenceVerifier;
use crate::FinalUseRevocationFeedVerifier;
use crate::FinalUseRevocationUpdate;
use crate::PqAuthorityTrustKey;
use crate::PqFinalUseRevocationNodeTrust;
use crate::SignedFinalUseApproval;
use crate::SignedFinalUseRevocationAck;
use crate::SignedFinalUseRevocationUpdate;
use crate::pq_auth::PqNativeSigningKey;
use crate::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;
use zeroize::Zeroizing;

#[path = "final_use_pq_capacity_tests.rs"]
mod capacity_tests;

fn key(seed: u8, id: &str) -> (PqNativeSigningKey, PqAuthorityTrustKey) {
    let seed = Zeroizing::new([seed; 32]);
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    let public_key_id = ml_dsa_65_key_id_from_spki(&spki).unwrap();
    let key = PqNativeSigningKey::from_owned_seed(seed, public_key_id).unwrap();
    let trust = PqAuthorityTrustKey {
        key_id: id.into(),
        public_key_id,
        public_key_spki: spki.to_vec(),
        not_before_authority_epoch: 9,
        not_after_authority_epoch: 9,
    };
    (key, trust)
}

struct PqFixture {
    directory: tempfile::TempDir,
    key: PqNativeSigningKey,
    trust: PqAuthorityTrustKey,
    frontier: Arc<MemoryFinalUseFrontier>,
    authority: FinalUseAuthority,
    signed: SignedFinalUseGrant,
}

fn pq_fixture() -> PqFixture {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let (key, trust) = key(17, "issuer-key");
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let frontier = Arc::new(MemoryFinalUseFrontier(Mutex::new(
        FinalUseFrontier::for_initial_head_with_profile(
            &head,
            FinalUseAuthenticationProfile::MlDsa65V2,
        )
        .unwrap(),
    )));
    let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        directory.path(),
        "security-owner".into(),
        vec![trust.clone()],
        head,
        Arc::new(FixedClock(2_000)),
        frontier.clone(),
    )
    .unwrap();
    let grant = FinalUseGrant {
        schema_version: 2,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "pq-grant".into(),
        nonce: [3; 32],
        binding: FinalUseBinding {
            subject_id: "subject".into(),
            destination_id: "destination".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 3_000,
    };
    let signed = SignedFinalUseGrant {
        signature: key
            .sign_exact_message(&grant.signing_bytes().unwrap())
            .unwrap()
            .to_vec(),
        grant,
    };
    PqFixture {
        directory,
        key,
        trust,
        frontier,
        authority,
        signed,
    }
}

#[test]
fn pq_final_use_consumes_original_durable_nonce_and_reopen_cannot_replay() {
    let fixture = pq_fixture();
    let token = fixture
        .authority
        .claim(&fixture.signed, &fixture.signed.grant.binding)
        .unwrap();
    let entered = token.enter(&fixture.signed.grant.binding).unwrap();
    assert!(entered.matches(&fixture.signed.grant.binding));
    drop(entered);
    assert_eq!(fixture.authority.capacity().unwrap().used_nonces, 1);
    let head = fixture.authority.revocation_head().unwrap();
    drop(fixture.authority);
    let reopened = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        fixture.directory.path(),
        "security-owner".into(),
        vec![fixture.trust],
        head,
        Arc::new(FixedClock(2_000)),
        fixture.frontier,
    )
    .unwrap();
    assert_eq!(
        reopened
            .claim(&fixture.signed, &fixture.signed.grant.binding)
            .unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    let snapshot: serde_json::Value = serde_json::from_slice(
        &std::fs::read(fixture.directory.path().join("authority.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(snapshot["schema"], 4);
}

#[test]
fn pq_final_use_rejects_classic_wire_signatures_and_cross_profile_stores() {
    let fixture = pq_fixture();
    let before = fixture.authority.frontier().unwrap();
    let classic = SigningKey::from_bytes(&[47; 32]);
    let mut classic_wire = fixture.signed.clone();
    classic_wire.grant.schema_version = 1;
    classic_wire.signature = classic
        .sign(&classic_wire.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    assert_eq!(
        fixture
            .authority
            .claim(&classic_wire, &classic_wire.grant.binding)
            .unwrap_err(),
        FinalUseError::InvalidGrant
    );
    let mut bad_signature = fixture.signed.clone();
    bad_signature.signature = classic
        .sign(&bad_signature.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    assert_eq!(
        fixture
            .authority
            .claim(&bad_signature, &bad_signature.grant.binding)
            .unwrap_err(),
        FinalUseError::InvalidSignature
    );
    assert_eq!(fixture.authority.frontier().unwrap(), before);
    let head = fixture.authority.revocation_head().unwrap();
    drop(fixture.authority);
    assert!(
        FinalUseAuthority::open_state_dir_with_clock(
            fixture.directory.path(),
            "security-owner".into(),
            classic.verifying_key().to_bytes(),
            head,
            Arc::new(FixedClock(2_000)),
        )
        .is_err()
    );
    let (old, _, old_directory) = super::fixture().unwrap();
    let old_head = old.revocation_head().unwrap();
    drop(old);
    let old_bytes = std::fs::read(old_directory.path().join("authority.json")).unwrap();
    assert!(
        FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            old_directory.path(),
            "security-owner".into(),
            vec![fixture.trust],
            old_head,
            Arc::new(FixedClock(2_000)),
            fixture.frontier,
        )
        .is_err()
    );
    assert_eq!(
        std::fs::read(old_directory.path().join("authority.json")).unwrap(),
        old_bytes
    );
}

#[test]
fn pq_final_use_independent_approval_revocation_and_ack_use_original_owners() {
    let fixture = pq_fixture();
    let (approver_key, approver_trust) = key(18, "approver-key");
    let (feed_key, feed_trust) = key(19, "feed-key");
    let (ack_key, ack_trust) = key(20, "node-key");
    let approval = FinalUseApproval::for_grant("operator".into(), &fixture.signed.grant).unwrap();
    let signed_approval = SignedFinalUseApproval {
        signature: approver_key
            .sign_exact_message(&approval.signing_bytes().unwrap())
            .unwrap()
            .to_vec(),
        approval,
    };
    let approver =
        FinalUseApprovalVerifier::new_pq_with_keys("operator".into(), vec![approver_trust])
            .unwrap();
    approver.verify(&fixture.signed, &signed_approval).unwrap();
    let mut substitution = fixture.signed.clone();
    substitution.grant.binding.payload_sha256[0] ^= 1;
    assert!(approver.verify(&substitution, &signed_approval).is_err());
    let token = fixture
        .authority
        .claim(&fixture.signed, &fixture.signed.grant.binding)
        .unwrap();
    let update = FinalUseRevocationUpdate::new_pq(
        "distributor".into(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from(["pq-grant".into()]),
        },
        /*issued_at_unix_ms*/ 1_900,
        /*expires_at_unix_ms*/ 2_500,
    );
    let signed_update = SignedFinalUseRevocationUpdate {
        signature: feed_key
            .sign_exact_message(&update.signing_bytes().unwrap())
            .unwrap()
            .to_vec(),
        update,
    };
    let feed =
        FinalUseRevocationFeedVerifier::new_pq_with_keys("distributor".into(), vec![feed_trust])
            .unwrap();
    let receipt = feed
        .apply(
            &fixture.authority,
            &signed_update,
            /*now_unix_ms*/ 2_000,
        )
        .unwrap();
    assert_eq!(
        token.enter(&fixture.signed.grant.binding).unwrap_err(),
        FinalUseError::Revoked
    );
    let ack = FinalUseRevocationAck::for_applied_update(
        "node".into(),
        &signed_update,
        &receipt,
        /*applied_at_unix_ms*/ 2_000,
    )
    .unwrap();
    let signed_ack = SignedFinalUseRevocationAck {
        signature: ack_key
            .sign_exact_message(&ack.signing_bytes().unwrap())
            .unwrap()
            .to_vec(),
        ack,
    };
    let convergence =
        FinalUseRevocationConvergenceVerifier::new_pq([PqFinalUseRevocationNodeTrust {
            node_id: "node".into(),
            keys: vec![ack_trust],
        }])
        .unwrap();
    assert!(
        convergence
            .verify(
                &feed,
                &signed_update,
                std::slice::from_ref(&signed_ack),
                /*now_unix_ms*/ 2_000
            )
            .unwrap()
            .converged()
    );
    let mut forged = signed_ack;
    forged.signature[0] ^= 1;
    assert!(
        convergence
            .verify(&feed, &signed_update, &[forged], /*now_unix_ms*/ 2_000)
            .is_err()
    );
}

#[test]
fn pq_final_use_external_frontier_refuses_local_snapshot_rollback() {
    let fixture = pq_fixture();
    let snapshot = std::fs::read(fixture.directory.path().join("authority.json")).unwrap();
    let claims = std::fs::read(fixture.directory.path().join("authority.claims")).unwrap();
    drop(
        fixture
            .authority
            .claim(&fixture.signed, &fixture.signed.grant.binding)
            .unwrap(),
    );
    let head = fixture.authority.revocation_head().unwrap();
    drop(fixture.authority);
    std::fs::write(fixture.directory.path().join("authority.json"), snapshot).unwrap();
    std::fs::write(fixture.directory.path().join("authority.claims"), claims).unwrap();
    assert_eq!(
        FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            fixture.directory.path(),
            "security-owner".into(),
            vec![fixture.trust],
            head,
            Arc::new(FixedClock(2_000)),
            fixture.frontier,
        )
        .unwrap_err(),
        FinalUseError::AntiRollbackViolation
    );
}

#[test]
fn pq_final_use_signature_mutation_and_key_pin_fail_before_nonce_write() {
    let fixture = pq_fixture();
    let before = fixture.authority.capacity().unwrap();
    for length in [64, 3_308, 3_310] {
        let mut malformed = fixture.signed.clone();
        malformed.signature.resize(length, 0);
        assert_eq!(
            fixture
                .authority
                .claim(&malformed, &malformed.grant.binding)
                .unwrap_err(),
            FinalUseError::InvalidSignature
        );
    }
    let mut tampered = fixture.signed.clone();
    tampered.signature[3308] ^= 1;
    assert_eq!(
        fixture
            .authority
            .claim(&tampered, &tampered.grant.binding)
            .unwrap_err(),
        FinalUseError::InvalidSignature
    );
    assert_eq!(fixture.authority.capacity().unwrap(), before);
    assert!(
        crate::pq_auth::PqNativeVerifier::from_pinned_spki(fixture.key.public_spki(), [0; 32])
            .is_err()
    );
}

#[test]
fn pq_feed_confirmation_reauthenticates_without_advancing_or_unrevoking() {
    let fixture = pq_fixture();
    let (key, trust) = key(/*seed*/ 39, "feed-key");
    let feed = FinalUseRevocationFeedVerifier::new_pq_with_keys("distributor".into(), vec![trust])
        .unwrap();
    let update = FinalUseRevocationUpdate::new_pq(
        "distributor".into(),
        fixture.authority.revocation_head().unwrap(),
        /*issued_at_unix_ms*/ 1_900,
        /*expires_at_unix_ms*/ 2_500,
    );
    let mut signed = SignedFinalUseRevocationUpdate {
        signature: key
            .sign_exact_message(&update.signing_bytes().unwrap())
            .unwrap()
            .to_vec(),
        update,
    };
    let before = fixture.authority.frontier().unwrap();
    let receipt = feed
        .apply_or_confirm_current(&fixture.authority, &signed, /*now_unix_ms*/ 2_000)
        .unwrap();
    assert_eq!(receipt.revision(), 1);
    assert_eq!(fixture.authority.frontier().unwrap(), before);
    signed.signature[0] ^= 1;
    assert_eq!(
        feed.apply_or_confirm_current(&fixture.authority, &signed, /*now_unix_ms*/ 2_000),
        Err(crate::FinalUseControlError::InvalidSignature)
    );
    signed.signature[0] ^= 1;
    assert_eq!(
        feed.apply_or_confirm_current(&fixture.authority, &signed, /*now_unix_ms*/ 2_500),
        Err(crate::FinalUseControlError::RevocationFeedStale)
    );
    signed.update.head.revision = 2;
    signed
        .update
        .head
        .revoked_grant_ids
        .insert("pq-grant".into());
    signed.signature = key
        .sign_exact_message(&signed.update.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    feed.apply_or_confirm_current(&fixture.authority, &signed, /*now_unix_ms*/ 2_000)
        .unwrap();
    let revoked = fixture.authority.frontier().unwrap();
    signed.update.head.revoked_grant_ids.clear();
    signed.signature = key
        .sign_exact_message(&signed.update.signing_bytes().unwrap())
        .unwrap()
        .to_vec();
    assert_eq!(
        feed.apply_or_confirm_current(&fixture.authority, &signed, /*now_unix_ms*/ 2_000),
        Err(crate::FinalUseControlError::Authority(
            FinalUseError::StaleRevocationHead
        ))
    );
    assert_eq!(fixture.authority.frontier().unwrap(), revoked);
}
