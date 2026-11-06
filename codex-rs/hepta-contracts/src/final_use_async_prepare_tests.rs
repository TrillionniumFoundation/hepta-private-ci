use super::*;
use crate::AuthorityClock;
use crate::AuthorityTrustError;
use crate::FinalUseRevocations;
use crate::FinalUseWitnessRefV1;
use crate::SignedFinalUseGrant;
use crate::VerifiedUseAuthorityRefV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::task::Context;
use std::task::Poll;
use std::task::Waker;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

#[derive(Debug)]
struct Clock {
    now: AtomicU64,
    unavailable: AtomicBool,
}
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if self.unavailable.load(Ordering::SeqCst) {
            Err(AuthorityTrustError::Unavailable)
        } else {
            Ok(self.now.load(Ordering::SeqCst))
        }
    }
}

struct Fixture {
    authority: FinalUseAuthority,
    signed: SignedFinalUseGrant,
    clock: Arc<Clock>,
    directory: tempfile::TempDir,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "preparation-owner".into(),
            authority_epoch: 9,
            grant_id: "effect-one".into(),
            nonce: [5; 32],
            binding: FinalUseBinding {
                subject_id: "agent-one".into(),
                destination_id: "provider:fixture".into(),
                request_sha256: [1; 32],
                scope_sha256: [2; 32],
                payload_sha256: [3; 32],
            },
            not_before_unix_ms: 1_000,
            expires_at_unix_ms: 10_000,
        };
        let signed = SignedFinalUseGrant {
            signature: issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec(),
            grant,
        };
        let directory = tempfile::tempdir()?;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
        let clock = Arc::new(Clock {
            now: AtomicU64::new(2_000),
            unavailable: AtomicBool::new(false),
        });
        let authority = FinalUseAuthority::open_state_dir_with_clock(
            directory.path(),
            "preparation-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
            clock.clone(),
        )?;
        Ok(Self {
            authority,
            signed,
            clock,
            directory,
        })
    }
    fn revoked_head(&self) -> FinalUseRevocations {
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([self.signed.grant.grant_id.clone()]),
        }
    }
}

fn poll<F: Future>(future: Pin<&mut F>) -> Poll<F::Output> {
    future.poll(&mut Context::from_waker(Waker::noop()))
}
async fn await_gate(gate: &AtomicBool) -> Result<u64, &'static str> {
    std::future::poll_fn(|_| {
        if gate.load(Ordering::SeqCst) {
            Poll::Ready(Ok(37))
        } else {
            Poll::Pending
        }
    })
    .await
}

#[test]
fn preparation_witness_is_distinct_and_the_fence_spans_both_awaits() -> TestResult {
    let f = Fixture::new()?;
    let binding = &f.signed.grant.binding;
    let token = f.authority.claim(&f.signed, binding)?;
    let preparation = AtomicBool::new(false);
    let consumer = AtomicBool::new(false);
    let observed = Mutex::new(None);
    let entered = AtomicUsize::new(0);
    let mut future = Box::pin(f.authority.with_prepared_verified_use_async(
        token,
        binding,
        |evidence| {
            let observed = &observed;
            let preparation = &preparation;
            async move {
                *observed.lock().map_err(|_| "witness lock")? =
                    Some(evidence.observation().clone());
                await_gate(preparation).await
            }
        },
        |prepared| {
            entered.fetch_add(1, Ordering::SeqCst);
            assert_eq!(prepared, 37);
            await_gate(&consumer)
        },
    ));
    assert_eq!(poll(future.as_mut()), Poll::Pending);
    assert_eq!(
        *observed.lock().map_err(|_| "witness lock")?,
        Some(VerifiedUseTokenWitnessV1 {
            schema_version: 1,
            authority_epoch: 9,
            verified_at_unix_ms: 2_000,
            boundary: VerifiedUseBoundaryV1::PreparationEntry,
            authority_ref: VerifiedUseAuthorityRefV1::FinalUse(FinalUseWitnessRefV1 {
                signer_id: "preparation-owner".into(),
                grant_id: "effect-one".into(),
                revocation_revision: 1,
                binding_sha256: super::super::final_use_binding_witness_sha256(binding)?,
            }),
        })
    );
    assert_eq!(entered.load(Ordering::SeqCst), 0);
    assert_eq!(
        f.authority.update_revocations(f.revoked_head()),
        Err(FinalUseError::DispatchInProgress)
    );
    f.clock.now.store(2_500, Ordering::SeqCst);
    preparation.store(true, Ordering::SeqCst);
    assert_eq!(poll(future.as_mut()), Poll::Pending);
    assert_eq!(entered.load(Ordering::SeqCst), 1);
    assert_eq!(
        f.authority.update_revocations(f.revoked_head()),
        Err(FinalUseError::DispatchInProgress)
    );
    consumer.store(true, Ordering::SeqCst);
    assert_eq!(poll(future.as_mut()), Poll::Ready(Ok(Ok(37))));
    drop(future);
    f.authority.update_revocations(f.revoked_head())?;
    Ok(())
}

#[test]
fn preparation_wait_rechecks_expiry_rollback_and_clock_availability() -> TestResult {
    for expected in [
        FinalUseError::Expired,
        FinalUseError::NotYetValid,
        FinalUseError::Unavailable,
    ] {
        let f = Fixture::new()?;
        let binding = &f.signed.grant.binding;
        let token = f.authority.claim(&f.signed, binding)?;
        let gate = AtomicBool::new(false);
        let contacts = AtomicUsize::new(0);
        let mut future = Box::pin(f.authority.with_prepared_verified_use_async(
            token,
            binding,
            |_| await_gate(&gate),
            |_| async {
                contacts.fetch_add(1, Ordering::SeqCst);
                Ok::<_, &'static str>(())
            },
        ));
        assert_eq!(poll(future.as_mut()), Poll::Pending);
        match expected {
            FinalUseError::Expired => f.clock.now.store(10_000, Ordering::SeqCst),
            FinalUseError::NotYetValid => f.clock.now.store(999, Ordering::SeqCst),
            FinalUseError::Unavailable => f.clock.unavailable.store(true, Ordering::SeqCst),
            other => return Err(format!("unexpected test case {other}").into()),
        }
        gate.store(true, Ordering::SeqCst);
        assert_eq!(poll(future.as_mut()), Poll::Ready(Err(expected)));
        assert_eq!(contacts.load(Ordering::SeqCst), 0);
        drop(future);
        f.clock.now.store(2_000, Ordering::SeqCst);
        f.clock.unavailable.store(false, Ordering::SeqCst);
        assert_eq!(
            f.authority.claim(&f.signed, binding).err(),
            Some(FinalUseError::AlreadyClaimed)
        );
        f.authority.update_revocations(f.revoked_head())?;
    }
    Ok(())
}

#[test]
fn preparation_failure_never_enters_the_consumer_and_releases_fence() -> TestResult {
    let f = Fixture::new()?;
    let token = f.authority.claim(&f.signed, &f.signed.grant.binding)?;
    let contacts = AtomicUsize::new(0);
    let mut future = Box::pin(f.authority.with_prepared_verified_use_async(
        token,
        &f.signed.grant.binding,
        |_| async { Err::<(), _>("owner persistence failed") },
        |()| async {
            contacts.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    ));
    assert_eq!(
        poll(future.as_mut()),
        Poll::Ready(Ok(Err("owner persistence failed")))
    );
    assert_eq!(contacts.load(Ordering::SeqCst), 0);
    drop(future);
    f.authority.update_revocations(f.revoked_head())?;
    Ok(())
}

#[test]
fn preparation_cancel_preserves_consumed_nonce_after_reopen() -> TestResult {
    let f = Fixture::new()?;
    let binding = &f.signed.grant.binding;
    let token = f.authority.claim(&f.signed, binding)?;
    let gate = AtomicBool::new(false);
    let contacts = AtomicUsize::new(0);
    let mut future = Box::pin(f.authority.with_prepared_verified_use_async(
        token,
        binding,
        |_| await_gate(&gate),
        |_| async {
            contacts.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    ));
    assert_eq!(poll(future.as_mut()), Poll::Pending);
    drop(future);
    assert_eq!(contacts.load(Ordering::SeqCst), 0);
    let head = f.authority.revocation_head()?;
    drop(f.authority);
    let reopened = FinalUseAuthority::open_state_dir_with_clock(
        f.directory.path(),
        "preparation-owner".into(),
        SigningKey::from_bytes(&[47; 32]).verifying_key().to_bytes(),
        head,
        f.clock,
    )?;
    assert_eq!(
        reopened.claim(&f.signed, binding).err(),
        Some(FinalUseError::AlreadyClaimed)
    );
    Ok(())
}

#[test]
fn mismatched_owner_or_binding_rejects_before_preparation() -> TestResult {
    for wrong_owner in [false, true] {
        let f = Fixture::new()?;
        let other = Fixture::new()?;
        let token = f.authority.claim(&f.signed, &f.signed.grant.binding)?;
        let mut binding = f.signed.grant.binding.clone();
        if !wrong_owner {
            binding.payload_sha256 = [11; 32];
        }
        let authority = if wrong_owner {
            &other.authority
        } else {
            &f.authority
        };
        let prepared = AtomicUsize::new(0);
        let contacts = AtomicUsize::new(0);
        let mut future = Box::pin(authority.with_prepared_verified_use_async(
            token,
            &binding,
            |_| async {
                prepared.fetch_add(1, Ordering::SeqCst);
                Ok::<_, &'static str>(())
            },
            |()| async {
                contacts.fetch_add(1, Ordering::SeqCst);
                Ok(())
            },
        ));
        assert_eq!(
            poll(future.as_mut()),
            Poll::Ready(Err(FinalUseError::BindingMismatch))
        );
        assert_eq!(
            (
                prepared.load(Ordering::SeqCst),
                contacts.load(Ordering::SeqCst)
            ),
            (0, 0)
        );
    }
    Ok(())
}

#[test]
fn consumer_cancellation_releases_the_preparation_fence() -> TestResult {
    let f = Fixture::new()?;
    let token = f.authority.claim(&f.signed, &f.signed.grant.binding)?;
    let entered = AtomicUsize::new(0);
    let mut future = Box::pin(f.authority.with_prepared_verified_use_async(
        token,
        &f.signed.grant.binding,
        |_| async { Ok::<_, &'static str>(()) },
        |()| async {
            entered.fetch_add(1, Ordering::SeqCst);
            std::future::pending::<Result<(), &'static str>>().await
        },
    ));
    assert_eq!(poll(future.as_mut()), Poll::Pending);
    assert_eq!(entered.load(Ordering::SeqCst), 1);
    assert_eq!(
        f.authority.update_revocations(f.revoked_head()),
        Err(FinalUseError::DispatchInProgress)
    );
    drop(future);
    f.authority.update_revocations(f.revoked_head())?;
    Ok(())
}

#[test]
fn preparation_and_consumer_panics_release_the_active_fence() -> TestResult {
    #[derive(Clone, Copy)]
    enum PanicAt {
        Preparation,
        Consumer,
    }
    for stage in [PanicAt::Preparation, PanicAt::Consumer] {
        let f = Fixture::new()?;
        let token = f.authority.claim(&f.signed, &f.signed.grant.binding)?;
        let failure = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let mut future = Box::pin(f.authority.with_prepared_verified_use_async(
                token,
                &f.signed.grant.binding,
                |_| async {
                    if matches!(stage, PanicAt::Preparation) {
                        panic!("preparation crash");
                    }
                    Ok::<_, &'static str>(())
                },
                |()| async {
                    if matches!(stage, PanicAt::Consumer) {
                        panic!("consumer crash");
                    }
                    Ok(())
                },
            ));
            poll(future.as_mut())
        }));
        assert!(failure.is_err());
        f.authority.update_revocations(f.revoked_head())?;
    }
    Ok(())
}
