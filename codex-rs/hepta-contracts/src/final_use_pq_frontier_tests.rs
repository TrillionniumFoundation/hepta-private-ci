//! Final admission observes the external owner after claim and asynchronous work.
//! Real durable directories share an in-memory trusted frontier fixture.

use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;

fn second_durable_owner(
    fixture: &PqFixture,
) -> PqTestResult<(FinalUseAuthority, tempfile::TempDir)> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    for name in ["authority.json", "authority.claims"] {
        std::fs::copy(
            fixture.directory.path().join(name),
            directory.path().join(name),
        )?;
    }
    let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        directory.path(),
        "security-owner".into(),
        vec![fixture.trust.clone()],
        fixture.authority.revocation_head()?,
        Arc::new(FixedClock(2_000)),
        fixture.frontier.clone(),
    )?;
    Ok((authority, directory))
}

#[test]
fn pq_final_use_retained_owner_refuses_external_revocation_at_token_entry() -> PqTestResult {
    let fixture = pq_fixture()?;
    let binding = &fixture.signed.grant.binding;
    let token = fixture.authority.claim(&fixture.signed, binding)?;
    let same_owner = fixture.authority.clone();
    let (current, _current_directory) = second_durable_owner(&fixture)?;
    let before = std::fs::read(fixture.directory.path().join("authority.claims"))?;
    let mut head = current.revocation_head()?;
    head.revision += 1;
    head.revoked_grant_ids
        .insert(fixture.signed.grant.grant_id.clone());
    current.update_revocations(head)?;

    assert_eq!(
        token.enter(binding).unwrap_err(),
        FinalUseError::AntiRollbackViolation
    );
    assert_eq!(same_owner.capacity(), Err(FinalUseError::Unavailable));
    assert_eq!(
        std::fs::read(fixture.directory.path().join("authority.claims"))?,
        before
    );
    assert_eq!(current.capacity()?.used_nonces, 1);

    // The current durable owner still serves a new signed grant. Refusing the
    // stale owner cannot reset the shared frontier or refund its spent nonce.
    let mut fresh = fixture.signed.clone();
    fresh.grant.grant_id = "current-owner-grant".into();
    fresh.grant.nonce = [4; 32];
    fresh.signature = fixture
        .key
        .sign_exact_message(&fresh.grant.signing_bytes()?)?
        .to_vec();
    let token = current.claim(&fresh, binding)?;
    assert!(token.enter(binding)?.matches(binding));
    assert_eq!(current.capacity()?.used_nonces, 2);
    Ok(())
}

#[test]
fn pq_final_use_dispatch_rejects_external_nonce_progress_with_unchanged_head() -> PqTestResult {
    let fixture = pq_fixture()?;
    let binding = &fixture.signed.grant.binding;
    let token = fixture.authority.claim(&fixture.signed, binding)?;
    let before = fixture.authority.frontier()?;
    let (current, _current_directory) = second_durable_owner(&fixture)?;
    let mut other = fixture.signed.clone();
    other.grant.grant_id = "other-owner-grant".into();
    other.grant.nonce = [4; 32];
    other.signature = fixture
        .key
        .sign_exact_message(&other.grant.signing_bytes()?)?
        .to_vec();
    drop(current.claim(&other, binding)?);
    let after = current.frontier()?;
    assert_eq!(before.authority_epoch, after.authority_epoch);
    assert_eq!(before.revocation_revision, after.revocation_revision);
    assert_ne!(before.state_sha256, after.state_sha256);

    let mut called = false;
    assert_eq!(
        fixture
            .authority
            .with_dispatch_boundary(token, binding, || called = true),
        Err(FinalUseError::AntiRollbackViolation)
    );
    assert!(!called, "dispatch must not cross the stale owner boundary");
    assert_eq!(
        current.claim(&fixture.signed, binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    assert_eq!(current.capacity()?.used_nonces, 2);
    Ok(())
}

#[test]
fn pq_final_use_async_entry_observes_external_progress_after_future_creation() -> PqTestResult {
    let fixture = pq_fixture()?;
    let binding = &fixture.signed.grant.binding;
    let token = fixture.authority.claim(&fixture.signed, binding)?;
    let (current, _current_directory) = second_durable_owner(&fixture)?;
    let mut called = false;
    let mut effect = Box::pin(
        fixture
            .authority
            .with_verified_use_async(token, binding, || {
                called = true;
                std::future::ready(())
            }),
    );
    let mut head = current.revocation_head()?;
    head.revision += 1;
    current.update_revocations(head)?;

    assert_eq!(
        effect
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop())),
        Poll::Ready(Err(FinalUseError::AntiRollbackViolation))
    );
    drop(effect);
    assert!(
        !called,
        "the future must revalidate before invoking its effect"
    );
    assert_eq!(current.capacity()?.used_nonces, 1);
    Ok(())
}

struct UnavailableFrontier {
    inner: Arc<MemoryFinalUseFrontier>,
    unavailable: AtomicBool,
}

impl AuthorityFrontierStore<FinalUseFrontier> for UnavailableFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if self.unavailable.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        self.inner.load(owner_id)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if self.unavailable.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        self.inner.compare_and_set(owner_id, expected, next)
    }
}

#[test]
fn pq_final_use_external_unavailability_fences_consumer_without_refunding_claim() -> PqTestResult {
    let fixture = pq_fixture()?;
    let head = fixture.authority.revocation_head()?;
    drop(fixture.authority);
    let frontier = Arc::new(UnavailableFrontier {
        inner: fixture.frontier,
        unavailable: AtomicBool::new(false),
    });
    let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        fixture.directory.path(),
        "security-owner".into(),
        vec![fixture.trust.clone()],
        head.clone(),
        Arc::new(FixedClock(2_000)),
        frontier.clone(),
    )?;
    let binding = &fixture.signed.grant.binding;
    let token = authority.claim(&fixture.signed, binding)?;
    let spent = frontier.load("security-owner")?;
    frontier.unavailable.store(true, Ordering::SeqCst);
    // Non-authorizing local telemetry does not fetch remote authorization.
    assert_eq!(authority.capacity()?.used_nonces, 1);
    let mut called = false;
    assert_eq!(
        authority.with_verified_use(token, binding, || called = true),
        Err(FinalUseError::Unavailable)
    );
    assert!(
        !called,
        "frontier uncertainty must refuse before consumer entry"
    );
    frontier.unavailable.store(false, Ordering::SeqCst);
    assert_eq!(authority.capacity(), Err(FinalUseError::Unavailable));
    assert_eq!(frontier.load("security-owner")?, spent);
    drop(authority);

    let reopened = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        fixture.directory.path(),
        "security-owner".into(),
        vec![fixture.trust],
        head,
        Arc::new(FixedClock(2_000)),
        frontier,
    )?;
    assert_eq!(
        reopened.claim(&fixture.signed, binding).unwrap_err(),
        FinalUseError::AlreadyClaimed
    );
    assert_eq!(reopened.capacity()?.used_nonces, 1);
    Ok(())
}
