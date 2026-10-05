//! Public owner persistence and failure boundaries shared by Unix and Windows.
#![cfg(any(unix, windows))]

use std::collections::BTreeSet;
use std::path::Path;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

#[derive(Debug)]
struct FixedClock;

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(2_000)
    }
}

fn open_final_use(root: &Path) -> Result<FinalUseAuthority, FinalUseError> {
    FinalUseAuthority::open_state_dir_with_clock(
        root,
        "security-owner".into(),
        SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        Arc::new(FixedClock),
    )
}

fn signed_grant() -> Result<SignedFinalUseGrant, FinalUseError> {
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".into(),
        authority_epoch: 9,
        grant_id: "grant-one".into(),
        nonce: [5; 32],
        binding: FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "provider:heptabao".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    };
    let signature = SigningKey::from_bytes(&[47; 32])
        .sign(&grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

fn open_leases(
    root: &Path,
    frontier: AuthorityLeaseFrontier,
) -> Result<AuthorityLeaseRegistry, AuthorityLeaseError> {
    AuthorityLeaseRegistry::open_state_dir_with_clock(
        root,
        "security-owner".into(),
        frontier,
        Arc::new(FixedClock),
    )
}

fn lease() -> AuthorityLease {
    AuthorityLease {
        schema_version: 1,
        lease_id: "lease-one".into(),
        authority_epoch: 9,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: "agent-one".into(),
            operation_class: "provider.read".into(),
            destination_id: "provider:heptabao".into(),
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    }
}

#[test]
fn final_use_preserves_claims_and_revocations_across_reopen() {
    let temporary = tempfile::tempdir().unwrap();
    let root = temporary.path().join("final-use");
    let owner = open_final_use(&root).unwrap();
    assert_eq!(
        open_final_use(&root).unwrap_err(),
        FinalUseError::StateLocked
    );
    let signed = signed_grant().unwrap();
    let token = owner.claim(&signed, &signed.grant.binding).unwrap();
    assert_eq!(
        owner.with_verified_use(token, &signed.grant.binding, || 7),
        Ok(7)
    );
    drop(owner);

    let owner = open_final_use(&root).unwrap();
    assert_eq!(
        owner.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    let revoked = FinalUseRevocations {
        authority_epoch: 9,
        revision: 2,
        revoked_grant_ids: BTreeSet::from([signed.grant.grant_id.clone()]),
    };
    owner.update_revocations(revoked.clone()).unwrap();
    drop(owner);
    let owner = open_final_use(&root).unwrap();
    assert_eq!(owner.revocation_head().unwrap(), revoked);
    assert_eq!(
        owner.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Revoked
    );
}

#[test]
fn missing_claim_journal_fences_owner_without_recreating_state() {
    let temporary = tempfile::tempdir().unwrap();
    let root = temporary.path().join("final-use");
    let owner = open_final_use(&root).unwrap();
    let signed = signed_grant().unwrap();
    let journal = root.join("authority.claims");
    std::fs::remove_file(&journal).unwrap();
    assert_eq!(
        owner.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Unavailable
    );
    assert!(!journal.exists());
    assert_eq!(
        owner.claim(&signed, &signed.grant.binding).unwrap_err(),
        FinalUseError::Unavailable
    );
    drop(owner);
    assert_eq!(
        open_final_use(&root).unwrap_err(),
        FinalUseError::InvalidTrust
    );
    assert!(!journal.exists());
}

#[test]
fn authority_lease_preserves_revocation_and_exclusive_owner() {
    let temporary = tempfile::tempdir().unwrap();
    let root = temporary.path().join("leases");
    let initial = AuthorityLeaseFrontier::for_empty_epoch(9).unwrap();
    let owner = open_leases(&root, initial).unwrap();
    assert_eq!(
        open_leases(&root, initial).unwrap_err(),
        AuthorityLeaseError::StateLocked
    );
    let lease = lease();
    owner
        .put_lease(lease.clone(), /*expected_revision*/ 0)
        .unwrap();
    let verifier = owner.verifier();
    let token = verifier
        .verify_use(&lease.lease_id, 1, &lease.binding)
        .unwrap();
    assert_eq!(
        verifier.with_verified_use(token, &lease.binding, || 11),
        Ok(11)
    );
    owner.revoke(&lease.lease_id, 1, [9; 32]).unwrap();
    let revoked = owner.read_revocation(&lease.lease_id).unwrap();
    let frontier = owner.frontier().unwrap();
    drop(verifier);
    drop(owner);
    let owner = open_leases(&root, frontier).unwrap();
    assert_eq!(owner.read_revocation(&lease.lease_id).unwrap(), revoked);
    assert_eq!(
        owner
            .verifier()
            .verify_use(&lease.lease_id, 2, &lease.binding)
            .unwrap_err(),
        AuthorityLeaseError::Revoked
    );
}

#[test]
fn initialized_owners_reject_missing_snapshots() {
    let temporary = tempfile::tempdir().unwrap();
    let final_root = temporary.path().join("final-use");
    drop(open_final_use(&final_root).unwrap());
    std::fs::remove_file(final_root.join("authority.json")).unwrap();
    assert_eq!(
        open_final_use(&final_root).unwrap_err(),
        FinalUseError::InvalidTrust
    );
    assert!(!final_root.join("authority.json").exists());

    let lease_root = temporary.path().join("leases");
    let frontier = AuthorityLeaseFrontier::for_empty_epoch(9).unwrap();
    drop(open_leases(&lease_root, frontier).unwrap());
    std::fs::remove_file(lease_root.join("authority-leases.json")).unwrap();
    assert_eq!(
        open_leases(&lease_root, frontier).unwrap_err(),
        AuthorityLeaseError::AntiRollbackViolation
    );
    assert!(!lease_root.join("authority-leases.json").exists());
}

#[test]
fn owners_reject_hard_linked_snapshots_before_loading_them() {
    let temporary = tempfile::tempdir().unwrap();
    let final_root = temporary.path().join("final-use");
    drop(open_final_use(&final_root).unwrap());
    std::fs::hard_link(final_root.join("authority.json"), final_root.join("alias")).unwrap();
    assert_eq!(
        open_final_use(&final_root).unwrap_err(),
        FinalUseError::UnsafeStateDirectory
    );

    let lease_root = temporary.path().join("leases");
    let frontier = AuthorityLeaseFrontier::for_empty_epoch(9).unwrap();
    drop(open_leases(&lease_root, frontier).unwrap());
    std::fs::hard_link(
        lease_root.join("authority-leases.json"),
        lease_root.join("alias"),
    )
    .unwrap();
    assert_eq!(
        open_leases(&lease_root, frontier).unwrap_err(),
        AuthorityLeaseError::UnsafeStateDirectory
    );
}
