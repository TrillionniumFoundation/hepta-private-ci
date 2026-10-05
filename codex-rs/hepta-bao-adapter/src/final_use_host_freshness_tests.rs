//! Deterministic checks of the publication exclusion boundary. The probe clock
//! uses try_lock rather than scheduling delays to detect sampling outside the
//! host's freshness critical section. All keys and times here are fixtures.

use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::TryLockError;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::BaoFinalUseHost;
use super::BaoFinalUseHostError;
use super::RegisteredBaoConsumer;

struct ProbeClock {
    now: AtomicU64,
    fail: AtomicBool,
    sampled_without_exclusion: AtomicBool,
    host: OnceLock<Weak<BaoFinalUseHost>>,
}

impl AuthorityClock for ProbeClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if let Some(host) = self.host.get().and_then(Weak::upgrade) {
            match host.revocation_fresh_until_unix_ms.try_lock() {
                Ok(_) => self.sampled_without_exclusion.store(true, Ordering::SeqCst),
                Err(TryLockError::WouldBlock) => {}
                Err(TryLockError::Poisoned(_)) => {
                    self.sampled_without_exclusion.store(true, Ordering::SeqCst);
                }
            }
        }
        if self.fail.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(self.now.load(Ordering::SeqCst))
    }
}

struct Fixture {
    host: Arc<BaoFinalUseHost>,
    clock: Arc<ProbeClock>,
    distributor: SigningKey,
    _directory: tempfile::TempDir,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let issuer = SigningKey::from_bytes(&[41; 32]);
        let approver = SigningKey::from_bytes(&[42; 32]);
        let distributor = SigningKey::from_bytes(&[43; 32]);
        let clock = Arc::new(ProbeClock {
            now: AtomicU64::new(10),
            fail: AtomicBool::new(false),
            sampled_without_exclusion: AtomicBool::new(false),
            host: OnceLock::new(),
        });
        // The owner can sample its injected clock at construction, before the
        // host exists. Only subsequent host samples are inspected by the probe.
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: Default::default(),
            },
            clock.clone(),
        )
        .unwrap();
        let host = Arc::new(
            BaoFinalUseHost::new(
                authority,
                FinalUseApprovalVerifier::new(
                    "approver".into(),
                    approver.verifying_key().to_bytes(),
                )
                .unwrap(),
                FinalUseRevocationFeedVerifier::new(
                    "distributor".into(),
                    distributor.verifying_key().to_bytes(),
                )
                .unwrap(),
                clock.clone(),
                [RegisteredBaoConsumer::new("consumer".into(), Arc::new(|_| Ok(()))).unwrap()],
            )
            .unwrap(),
        );
        clock.host.set(Arc::downgrade(&host)).unwrap();
        Self {
            host,
            clock,
            distributor,
            _directory: directory,
        }
    }

    fn update(&self, revision: u64, expires_at: u64) -> SignedFinalUseRevocationUpdate {
        let update = FinalUseRevocationUpdate::new(
            "distributor".into(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision,
                revoked_grant_ids: Default::default(),
            },
            1,
            expires_at,
        );
        SignedFinalUseRevocationUpdate {
            signature: self
                .distributor
                .sign(&update.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            update,
        }
    }
}

#[test]
fn signed_head_update_and_freshness_publication_share_exclusion() {
    let fixture = Fixture::new();
    fixture
        .host
        .apply_revocation_update(&fixture.update(/*revision*/ 2, /*expires_at*/ 100))
        .unwrap();
    assert!(
        !fixture
            .clock
            .sampled_without_exclusion
            .load(Ordering::SeqCst)
    );
    fixture
        .host
        .apply_revocation_update(&fixture.update(/*revision*/ 3, /*expires_at*/ 20))
        .unwrap();
    fixture.clock.now.store(20, Ordering::SeqCst);
    assert_eq!(
        fixture.host.ensure_revocation_fresh(),
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
}

#[test]
fn freshness_reader_samples_time_inside_publication_exclusion() {
    let fixture = Fixture::new();
    fixture
        .host
        .apply_revocation_update(&fixture.update(/*revision*/ 2, /*expires_at*/ 100))
        .unwrap();
    fixture
        .clock
        .sampled_without_exclusion
        .store(false, Ordering::SeqCst);
    assert_eq!(fixture.host.ensure_revocation_fresh(), Ok(()));
    assert!(
        !fixture
            .clock
            .sampled_without_exclusion
            .load(Ordering::SeqCst)
    );
}

#[test]
fn rejected_signature_and_failed_clock_preserve_accepted_freshness() {
    let fixture = Fixture::new();
    fixture
        .host
        .apply_revocation_update(&fixture.update(/*revision*/ 2, /*expires_at*/ 100))
        .unwrap();
    let mut forged = fixture.update(/*revision*/ 3, /*expires_at*/ 200);
    forged.signature[0] ^= 1;
    assert!(fixture.host.apply_revocation_update(&forged).is_err());
    fixture.clock.fail.store(true, Ordering::SeqCst);
    assert_eq!(
        fixture
            .host
            .apply_revocation_update(&fixture.update(/*revision*/ 3, /*expires_at*/ 200)),
        Err(BaoFinalUseHostError::Trust(
            AuthorityTrustError::Unavailable
        ))
    );
    assert_eq!(
        *fixture.host.revocation_fresh_until_unix_ms.lock().unwrap(),
        100
    );
    fixture.clock.fail.store(false, Ordering::SeqCst);
    fixture
        .host
        .apply_revocation_update(&fixture.update(/*revision*/ 3, /*expires_at*/ 20))
        .unwrap();
    fixture.clock.now.store(20, Ordering::SeqCst);
    assert_eq!(
        fixture.host.ensure_revocation_fresh(),
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
}

#[test]
fn concurrent_signed_updates_cannot_reverse_freshness_publication() {
    use std::sync::Mutex;
    use std::sync::mpsc;
    use std::time::Duration;

    let fixture = Fixture::new();
    let (applied_tx, applied_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let release_rx = Mutex::new(release_rx);
    *fixture.host.after_revocation_applied.lock().unwrap() = Some(Arc::new(move |receipt| {
        if receipt.revision() == 2 {
            applied_tx.send(()).unwrap();
            release_rx.lock().unwrap().recv().unwrap();
        }
    }));
    let old = fixture.update(/*revision*/ 2, /*expires_at*/ 100);
    let newer = fixture.update(/*revision*/ 3, /*expires_at*/ 20);
    let old_host = Arc::clone(&fixture.host);
    let old_thread = std::thread::spawn(move || old_host.apply_revocation_update(&old));
    // The old authority head has committed, but its freshness is unpublished.
    applied_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    let publication_is_excluded = match fixture.host.revocation_fresh_until_unix_ms.try_lock() {
        Ok(_) => false,
        Err(TryLockError::WouldBlock) => true,
        Err(TryLockError::Poisoned(_)) => panic!("unexpected poisoned gate"),
    };
    let (newer_tx, newer_rx) = mpsc::channel();
    let newer_host = Arc::clone(&fixture.host);
    let newer_thread = std::thread::spawn(move || {
        newer_tx
            .send(newer_host.apply_revocation_update(&newer))
            .unwrap();
    });
    // On the old implementation this deliberately publishes revision 3 first,
    // then lets revision 2 overwrite its shorter expiry. With the repair, the
    // held exclusion proves that revision 3 cannot pass the publication gate.
    let newer_result = if publication_is_excluded {
        release_tx.send(()).unwrap();
        newer_rx.recv_timeout(Duration::from_secs(5)).unwrap()
    } else {
        let result = newer_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        release_tx.send(()).unwrap();
        result
    };
    old_thread.join().unwrap().unwrap();
    newer_result.unwrap();
    newer_thread.join().unwrap();
    assert_eq!(
        fixture.host.authority.revocation_head().unwrap().revision,
        3
    );
    fixture.clock.now.store(20, Ordering::SeqCst);
    assert_eq!(
        fixture.host.ensure_revocation_fresh(),
        Err(BaoFinalUseHostError::StaleRevocationFeed)
    );
    assert_eq!(
        *fixture.host.revocation_fresh_until_unix_ms.lock().unwrap(),
        20
    );
}

#[test]
fn publication_panics_fail_closed_before_and_after_authority_application() {
    let fixture = Fixture::new();
    let host = Arc::clone(&fixture.host);
    assert!(
        std::thread::spawn(move || {
            let _guard = host.revocation_fresh_until_unix_ms.lock().unwrap();
            panic!("fixture publication panic");
        })
        .join()
        .is_err()
    );
    assert_eq!(
        fixture
            .host
            .apply_revocation_update(&fixture.update(/*revision*/ 2, /*expires_at*/ 100)),
        Err(BaoFinalUseHostError::Unavailable)
    );
    assert_eq!(
        fixture.host.authority.revocation_head().unwrap().revision,
        1
    );
    assert_eq!(
        fixture.host.ensure_revocation_fresh(),
        Err(BaoFinalUseHostError::Unavailable)
    );

    let fixture = Fixture::new();
    fixture
        .host
        .apply_revocation_update(&fixture.update(/*revision*/ 2, /*expires_at*/ 100))
        .unwrap();
    *fixture.host.after_revocation_applied.lock().unwrap() = Some(Arc::new(|_| {
        panic!("fixture panic after durable application");
    }));
    let host = Arc::clone(&fixture.host);
    let update = fixture.update(/*revision*/ 3, /*expires_at*/ 20);
    assert!(
        std::thread::spawn(move || host.apply_revocation_update(&update))
            .join()
            .is_err()
    );
    assert_eq!(
        fixture.host.authority.revocation_head().unwrap().revision,
        3
    );
    fixture.clock.now.store(20, Ordering::SeqCst);
    assert_eq!(
        fixture.host.ensure_revocation_fresh(),
        Err(BaoFinalUseHostError::Unavailable)
    );
}
