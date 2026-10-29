//! Protected authority time remains authoritative through cloned and opaque roles.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct TestClock(AtomicU64);
impl AuthorityClock for TestClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

#[test]
fn protected_clock_rejects_future_evidence_and_retained_expiry_despite_caller_time() {
    let (mut root, mut signed) = distribution(/*generation*/ 1);
    root.valid_from *= 1_000;
    root.expires_at *= 1_000;
    signed.issued_at *= 1_000;
    signed.expires_at *= 1_000;
    signed.distribution.effective_at *= 1_000;
    for signer in &mut signed.distribution.trust.signers {
        signer.principal.authenticated_at *= 1_000;
        signer.principal.expires_at *= 1_000;
    }
    signed.signature = sign_pq(&key(/*seed*/ 99), &signed.signing_bytes().unwrap());
    let activated =
        activate_learning_trust(&root, signed, /*previous*/ None, /*now*/ 50_000).unwrap();
    let frontier = frontier(&activated);
    let activated = activated.with_trust_frontier(binding(), frontier).unwrap();
    let clock = Arc::new(TestClock(AtomicU64::new(50)));
    let verifier = activated
        .verifier()
        .clone()
        .with_microsecond_authority_clock(clock.clone())
        .unwrap();
    let payload = b"protected-clock-admission";
    let mut signed = evidence(
        &verifier,
        "generator",
        LearningEvidenceRoleV1::Generator,
        payload,
    );
    signed.issued_at = 49_000;
    signed.expires_at = 90_000;
    signed.signature = sign_pq(&key(/*seed*/ 41), &signed.signing_bytes());
    let opaque = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &signed,
            payload,
            /*now*/ 50_000,
        )
        .unwrap();
    let mut future = signed.clone();
    future.issued_at = 55_000;
    future.signature = sign_pq(&key(/*seed*/ 41), &future.signing_bytes());
    assert!(matches!(
        verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &future,
            payload,
            /*now*/ 56_000,
        ),
        Err(crate::SignedEvidenceError::ValidityWindow)
    ));
    // Untrusted caller wall time never becomes the authorization clock.
    assert_eq!(opaque.validate_at(/*supplied_now*/ 1), Ok(50_000));
    assert_eq!(opaque.validate_at(/*supplied_now*/ 95_000), Ok(50_000));
    let mut observer = evidence(
        &verifier,
        "observer",
        LearningEvidenceRoleV1::Observer,
        payload,
    );
    observer.issued_at = 49_000;
    observer.expires_at = 90_000;
    observer.signature = sign_pq(&key(/*seed*/ 42), &observer.signing_bytes());
    let observer = verifier
        .verify(
            LearningEvidenceRoleV1::Observer,
            &observer,
            payload,
            /*now*/ 50_000,
        )
        .unwrap();
    assert!(crate::verify_signed_actor_separation(&opaque, &observer, /*now*/ 1).is_ok());
    assert!(crate::verify_verified_role_separation(&opaque, &observer, /*now*/ u64::MAX).is_ok());
    clock.0.store(90, Ordering::SeqCst);
    assert!(matches!(
        verifier.verify(
            LearningEvidenceRoleV1::Generator,
            &signed,
            payload,
            /*now*/ 50_000
        ),
        Err(crate::SignedEvidenceError::ValidityWindow)
    ));
    assert!(matches!(
        opaque.validate_at(/*supplied_now*/ 50_000),
        Err(crate::SignedEvidenceError::ValidityWindow)
    ));
    clock.0.store(49, Ordering::SeqCst);
    assert!(matches!(
        opaque.validate_at(/*supplied_now*/ 50_000),
        Err(crate::SignedEvidenceError::ValidityWindow)
    ));
}
