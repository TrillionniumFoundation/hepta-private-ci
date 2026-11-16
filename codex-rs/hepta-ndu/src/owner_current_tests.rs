use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use pretty_assertions::assert_eq;

use super::*;
use crate::NduCurrentProjectionV1;
use crate::NduProjectionReadRequestV1;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        match self.0.load(Ordering::SeqCst) {
            0 => Err(AuthorityTrustError::Unavailable),
            now => Ok(now),
        }
    }
}

fn feed(now: u64, epoch: u64, revision: u64, revoked: &[&str]) -> SignedFinalUseRevocationUpdate {
    let update = FinalUseRevocationUpdate::new(
        "ndu-feed".into(),
        FinalUseRevocations {
            authority_epoch: epoch,
            revision,
            revoked_grant_ids: revoked.iter().map(|id| (*id).to_owned()).collect(),
        },
        now - 1_000,
        now + 120_000,
    );
    let signature = SigningKey::from_bytes(&[92; 32])
        .sign(&must(update.signing_bytes()))
        .to_bytes()
        .to_vec();
    SignedFinalUseRevocationUpdate { update, signature }
}

fn current_fixture() -> (Fixture, Arc<Clock>) {
    let mut fixture = fixture();
    for label in ["first", "second"] {
        let mutation = append_mutation(label);
        let signed = fixture.sign(&mutation, label);
        must(fixture.owner.apply_mutation(&signed, mutation));
    }
    select(&mut fixture, "first", "select-first");
    let now = must(SystemTime::now().duration_since(UNIX_EPOCH)).as_millis() as u64;
    let clock = Arc::new(Clock(AtomicU64::new(now)));
    let verifier = must(FinalUseRevocationFeedVerifier::new(
        "ndu-feed".into(),
        SigningKey::from_bytes(&[92; 32]).verifying_key().to_bytes(),
    ));
    fixture.owner = fixture.owner.with_current_reads(verifier, clock.clone());
    (fixture, clock)
}

fn select(fixture: &mut Fixture, label: &str, operation: &str) {
    let mutation = NduOwnerMutationV1::SelectProjection {
        identity_digest: digest(operation),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        projection_digest: digest(&format!("{label}-projection")),
    };
    let signed = fixture.sign(&mutation, operation);
    must(fixture.owner.apply_mutation(&signed, mutation));
}

fn request(label: &str) -> NduProjectionReadRequestV1 {
    NduProjectionReadRequestV1 {
        request_id: digest(label),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
    }
}

fn read(fixture: &mut Fixture, label: &str) -> NduCurrentProjectionV1 {
    let request = request(label);
    let binding = must(fixture.owner.current_projection_binding(&request));
    let signed = fixture.sign_binding(binding, label);
    must(fixture.owner.read_current_projection(&request, &signed))
}

#[test]
fn current_read_requires_local_authenticated_feed_and_exact_single_use_grant() {
    let plain = fixture();
    assert!(
        plain
            .owner
            .current_projection_binding(&request("plain"))
            .is_err()
    );
    let (mut fixture, clock) = current_fixture();
    assert!(
        fixture
            .owner
            .current_projection_binding(&request("missing-feed"))
            .is_err()
    );
    let now = clock.0.load(Ordering::SeqCst);
    let signed_feed = feed(now, /*epoch*/ 1, /*revision*/ 2, &[]);
    let mut forged = signed_feed.clone();
    forged.signature[0] ^= 1;
    assert!(fixture.owner.apply_read_revocation_update(&forged).is_err());
    assert!(
        fixture
            .owner
            .current_projection_binding(&request("forged-feed"))
            .is_err()
    );
    must(fixture.owner.apply_read_revocation_update(&signed_feed));
    let requested = request("read-first");
    let binding = must(fixture.owner.current_projection_binding(&requested));
    let signed = fixture.sign_binding(binding, "read-first");
    assert!(matches!(
        fixture
            .owner
            .read_current_projection(&request("wrong-request"), &signed),
        Err(NduOwnerError::Authority(FinalUseError::BindingMismatch))
    ));
    let proof = must(fixture.owner.read_current_projection(&requested, &signed));
    let before = must(fixture.authority.frontier());
    for _ in 0..3 {
        must(fixture.owner.revalidate_current_projection(&proof));
    }
    assert_eq!(must(fixture.authority.frontier()), before);
    assert_eq!(proof.request(), &requested);
    assert!(matches!(
        fixture.owner.read_current_projection(&requested, &signed),
        Err(NduOwnerError::Authority(FinalUseError::AlreadyClaimed))
    ));
    let another = read(&mut fixture, "read-second");
    assert_eq!(proof.digest(), another.digest());
}

#[test]
fn selection_aba_and_revocation_invalidate_same_payload_proof() {
    let (mut fixture, clock) = current_fixture();
    must(fixture.owner.apply_read_revocation_update(&feed(
        clock.0.load(Ordering::SeqCst),
        /*epoch*/ 1,
        /*revision*/ 2,
        &[],
    )));
    let proof = read(&mut fixture, "before-aba");
    select(&mut fixture, "second", "select-second");
    select(&mut fixture, "first", "select-first-again");
    let later = read(&mut fixture, "after-aba");
    assert_eq!(proof.projection_digest(), later.projection_digest());
    assert!(later.selection_sequence() > proof.selection_sequence());
    assert!(later.journal_sequence() > proof.journal_sequence());
    assert!(fixture.owner.revalidate_current_projection(&proof).is_err());
    must(fixture.owner.revalidate_current_projection(&later));
    let mutation = NduOwnerMutationV1::RevokeProjection {
        identity_digest: digest("revoke-first"),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        projection_digest: later.projection_digest(),
    };
    let signed = fixture.sign(&mutation, "revoke-first");
    must(fixture.owner.apply_mutation(&signed, mutation));
    assert!(fixture.owner.revalidate_current_projection(&later).is_err());
}

#[test]
fn refreshed_feed_revoked_grant_and_epoch_change_fence_old_proofs() {
    let (mut fixture, clock) = current_fixture();
    let now = clock.0.load(Ordering::SeqCst);
    must(fixture.owner.apply_read_revocation_update(&feed(
        now,
        /*epoch*/ 1,
        /*revision*/ 2,
        &[],
    )));
    let old = read(&mut fixture, "old-read");
    must(fixture.owner.apply_read_revocation_update(&feed(
        now,
        /*epoch*/ 1,
        /*revision*/ 3,
        &[],
    )));
    assert!(fixture.owner.revalidate_current_projection(&old).is_err());
    let revoked = read(&mut fixture, "revoked-read");
    must(fixture.owner.apply_read_revocation_update(&feed(
        now,
        /*epoch*/ 1,
        /*revision*/ 4,
        &["revoked-read"],
    )));
    assert!(matches!(
        fixture.owner.revalidate_current_projection(&revoked),
        Err(NduOwnerError::Authority(FinalUseError::Revoked))
    ));
    must(fixture.owner.apply_read_revocation_update(&feed(
        now,
        /*epoch*/ 2,
        /*revision*/ 5,
        &[],
    )));
    assert!(matches!(
        fixture.owner.revalidate_current_projection(&revoked),
        Err(NduOwnerError::Authority(FinalUseError::EpochMismatch))
    ));
}

#[test]
fn grant_expiry_feed_expiry_clock_failure_and_other_owner_refuse() {
    let (mut fixture, clock) = current_fixture();
    let now = clock.0.load(Ordering::SeqCst);
    must(fixture.owner.apply_read_revocation_update(&feed(
        now,
        /*epoch*/ 1,
        /*revision*/ 2,
        &[],
    )));
    let proof = read(&mut fixture, "timed-read");
    clock.0.store(now - 1, Ordering::SeqCst);
    assert!(matches!(
        fixture.owner.revalidate_current_projection(&proof),
        Err(NduOwnerError::Authority(FinalUseError::NotYetValid))
    ));
    clock.0.store(now + 61_000, Ordering::SeqCst);
    assert!(matches!(
        fixture.owner.revalidate_current_projection(&proof),
        Err(NduOwnerError::Authority(FinalUseError::Expired))
    ));
    clock.0.store(now + 120_000, Ordering::SeqCst);
    assert!(matches!(
        fixture.owner.revalidate_current_projection(&proof),
        Err(NduOwnerError::InvalidContext(
            "authenticated revocation feed stale"
        ))
    ));
    clock.0.store(0, Ordering::SeqCst);
    assert!(matches!(
        fixture.owner.revalidate_current_projection(&proof),
        Err(NduOwnerError::Authority(FinalUseError::Unavailable))
    ));
    clock.0.store(now, Ordering::SeqCst);
    let (other, _) = current_fixture();
    assert!(matches!(
        other.owner.revalidate_current_projection(&proof),
        Err(NduOwnerError::InvalidContext("current projection owner"))
    ));
    must(fixture.owner.revalidate_current_projection(&proof));
}
