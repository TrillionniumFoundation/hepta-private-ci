use super::*;
use crate::AuthorityTrustError;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

const WAIT: Duration = Duration::from_secs(2);

struct Clock {
    now: AtomicU64,
    calls: Mutex<Option<mpsc::Sender<()>>>,
}
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if let Some(sender) = self.calls.lock().unwrap().as_ref() {
            sender.send(()).unwrap();
        }
        Ok(self.now.load(Ordering::SeqCst))
    }
}

fn lease() -> AuthorityLease {
    AuthorityLease {
        schema_version: 1,
        lease_id: "original-observation-lease".into(),
        authority_epoch: 7,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: "original-agent".into(),
            operation_class: "runtime.agentd.production_writer".into(),
            destination_id: "original-cognitive-owner".into(),
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    }
}

fn fixture() -> (AuthorityLeaseRegistry, tempfile::TempDir, Arc<Clock>) {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let clock = Arc::new(Clock {
        now: AtomicU64::new(2_000),
        calls: Mutex::new(None),
    });
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "original-observation-owner".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
        clock.clone(),
    )
    .unwrap();
    registry.put_lease(lease(), 0).unwrap();
    (registry, directory, clock)
}

#[test]
fn metadata_progresses_during_dispatch_but_original_dispatch_remains_serial() {
    let (registry, _directory, _clock) = fixture();
    let verifier = registry.verifier();
    let original = lease();
    let first = verifier
        .verify_use(&original.lease_id, original.revision, &original.binding)
        .unwrap();
    let second = verifier
        .verify_use(&original.lease_id, original.revision, &original.binding)
        .unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let (attempt_tx, attempt_rx) = mpsc::channel();
    let (second_tx, second_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let first_verifier = &verifier;
        let first_binding = &original.binding;
        let first_thread = scope.spawn(move || {
            dispatch_authority_lease_with_witness(first_verifier, first, first_binding, |_| {
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(WAIT).unwrap();
                41
            })
            .unwrap()
        });
        entered_rx.recv_timeout(WAIT).unwrap();
        let observation = verifier.observe_original_lease(&original).unwrap();
        assert_eq!(observation.original_store_revision(), 2);
        let second_verifier = &verifier;
        let second_binding = &original.binding;
        let second_thread = scope.spawn(move || {
            attempt_tx.send(()).unwrap();
            second_verifier
                .with_dispatch_boundary(second, second_binding, || {
                    second_tx.send(()).unwrap();
                    42
                })
                .unwrap()
        });
        attempt_rx.recv_timeout(WAIT).unwrap();
        assert!(matches!(
            second_rx.recv_timeout(Duration::from_millis(50)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));
        observation.finish_original_observation().unwrap();
        release_tx.send(()).unwrap();
        assert_eq!(first_thread.join().unwrap().0, 41);
        second_rx.recv_timeout(WAIT).unwrap();
        assert_eq!(second_thread.join().unwrap(), 42);
    });
}

#[test]
fn original_observation_excludes_deadline_revoke_and_cannot_survive_revocation() {
    let (registry, directory, _clock) = fixture();
    let verifier = registry.verifier();
    let original = lease();
    let before = std::fs::read(directory.path().join("authority-leases.json")).unwrap();
    let observation = verifier.observe_original_lease(&original).unwrap();
    assert!(matches!(
        registry.revoke_exact_before(&original, [9; 32], Instant::now() + WAIT),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert_eq!(
        std::fs::read(directory.path().join("authority-leases.json")).unwrap(),
        before
    );
    observation.finish_original_observation().unwrap();
    let receipt = registry
        .revoke_exact_before(&original, [9; 32], Instant::now() + WAIT)
        .unwrap();
    assert_eq!(receipt.previous_lease_revision, original.revision);
    assert_eq!(receipt.lease_revision, original.revision.checked_add(1).unwrap());
    assert!(matches!(
        verifier.observe_original_lease(&original),
        Err(AuthorityLeaseError::Revoked)
    ));
    // New verification reads the current lease first; the original revision is stale.
    assert!(matches!(
        verifier.verify_use(&original.lease_id, original.revision, &original.binding),
        Err(AuthorityLeaseError::RevisionMismatch)
    ));
    assert!(matches!(
        verifier.verify_use(&original.lease_id, receipt.lease_revision, &original.binding),
        Err(AuthorityLeaseError::Revoked)
    ));
}

#[test]
fn observation_panic_fences_new_entries_without_discarding_an_entered_dispatch_result() {
    let (registry, _directory, _clock) = fixture();
    let verifier = registry.verifier();
    let original = lease();
    let token = verifier
        .verify_use(&original.lease_id, original.revision, &original.binding)
        .unwrap();
    let later_token = verifier
        .verify_use(&original.lease_id, original.revision, &original.binding)
        .unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (release_tx, release_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let original_verifier = &verifier;
        let original_binding = &original.binding;
        let worker = scope.spawn(move || {
            dispatch_authority_lease_with_witness(
                original_verifier,
                token,
                original_binding,
                |_| {
                    entered_tx.send(()).unwrap();
                    release_rx.recv_timeout(WAIT).unwrap();
                    "actual-entered-result"
                },
            )
        });
        entered_rx.recv_timeout(WAIT).unwrap();
        let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _original_observation = verifier.observe_original_lease(&original).unwrap();
            panic!("component observation panic");
        }));
        assert!(panic.is_err());
        release_tx.send(()).unwrap();
        let (result, witness) = worker.join().unwrap().unwrap();
        assert_eq!(result, "actual-entered-result");
        assert!(matches!(
            &witness.authority_ref,
            crate::VerifiedUseAuthorityRefV1::AuthorityLease(reference)
                if reference.lease_id == original.lease_id
                    && reference.lease_revision == original.revision
                    && reference.store_revision == 2
        ));
    });
    assert!(matches!(
        verifier.observe_original_lease(&original),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert!(matches!(
        verifier.verify_use(&original.lease_id, original.revision, &original.binding),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert!(matches!(
        registry.revoke(&original.lease_id, original.revision, [8; 32]),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert!(matches!(
        registry.put_lease(original.clone(), original.revision),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert!(matches!(
        verifier.with_dispatch_boundary::<()>(later_token, &original.binding, || panic!(
            "fenced dispatch entered"
        )),
        Err(AuthorityLeaseError::Unavailable)
    ));
}

#[test]
fn original_dispatch_panic_prevents_pending_metadata_publication() {
    let (registry, _directory, _clock) = fixture();
    let verifier = registry.verifier();
    let original = lease();
    let token = verifier
        .verify_use(&original.lease_id, original.revision, &original.binding)
        .unwrap();
    let (entered_tx, entered_rx) = mpsc::channel();
    let (panic_tx, panic_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let original_verifier = &verifier;
        let original_binding = &original.binding;
        let worker = scope.spawn(move || {
            original_verifier.with_dispatch_boundary::<()>(token, original_binding, || {
                entered_tx.send(()).unwrap();
                panic_rx.recv_timeout(WAIT).unwrap();
                panic!("component original dispatch panic");
            })
        });
        entered_rx.recv_timeout(WAIT).unwrap();
        let observation = verifier.observe_original_lease(&original).unwrap();
        panic_tx.send(()).unwrap();
        assert!(worker.join().is_err());
        assert!(matches!(
            observation.finish_original_observation(),
            Err(AuthorityLeaseError::Unavailable)
        ));
    });
    assert!(matches!(
        verifier.read_lease(&original.lease_id),
        Err(AuthorityLeaseError::Unavailable)
    ));
}

#[test]
fn original_clock_is_sampled_after_waiting_for_the_observation_fence() {
    let (registry, _directory, clock) = fixture();
    let verifier = registry.verifier();
    let original = lease();
    let observation = verifier.observe_original_lease(&original).unwrap();
    let (called_tx, called_rx) = mpsc::channel();
    *clock.calls.lock().unwrap() = Some(called_tx);
    let (attempt_tx, attempt_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let worker = scope.spawn(|| {
            attempt_tx.send(()).unwrap();
            matches!(
                verifier.observe_original_lease(&original),
                Err(AuthorityLeaseError::Expired)
            )
        });
        attempt_rx.recv_timeout(WAIT).unwrap();
        assert!(matches!(
            called_rx.recv_timeout(Duration::from_millis(50)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));
        clock
            .now
            .store(original.expires_at_unix_ms, Ordering::SeqCst);
        observation.finish_original_observation().unwrap();
        assert!(worker.join().unwrap());
    });
}

struct FailingFrontier {
    head: Mutex<AuthorityLeaseFrontier>,
    fail: AtomicBool,
}
impl AuthorityFrontierStore<AuthorityLeaseFrontier> for FailingFrontier {
    fn load(&self, _owner_id: &str) -> Result<AuthorityLeaseFrontier, AuthorityTrustError> {
        Ok(*self.head.lock().unwrap())
    }

    fn compare_and_set(
        &self,
        _owner_id: &str,
        expected: &AuthorityLeaseFrontier,
        next: &AuthorityLeaseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if self.fail.load(Ordering::SeqCst) {
            return Err(AuthorityTrustError::Unavailable);
        }
        let mut current = self.head.lock().unwrap();
        if *current != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *current = *next;
        Ok(())
    }
}

#[test]
fn actual_durable_frontier_failure_fences_both_original_and_metadata_entries() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let clock = Arc::new(Clock {
        now: AtomicU64::new(2_000),
        calls: Mutex::new(None),
    });
    let frontier = Arc::new(FailingFrontier {
        head: Mutex::new(AuthorityLeaseFrontier::for_empty_epoch(7).unwrap()),
        fail: AtomicBool::new(false),
    });
    let registry = AuthorityLeaseRegistry::open_state_dir_with_trust(
        directory.path(),
        "original-failed-owner".into(),
        clock,
        frontier.clone(),
    )
    .unwrap();
    let original = lease();
    registry.put_lease(original.clone(), 0).unwrap();
    let verifier = registry.verifier();
    frontier.fail.store(true, Ordering::SeqCst);
    assert!(matches!(
        registry.revoke(&original.lease_id, original.revision, [9; 32]),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert!(matches!(
        verifier.observe_original_lease(&original),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert!(matches!(
        verifier.verify_use(&original.lease_id, original.revision, &original.binding),
        Err(AuthorityLeaseError::Unavailable)
    ));
    assert!(matches!(
        registry.frontier(),
        Err(AuthorityLeaseError::Unavailable)
    ));
}

#[test]
fn matching_id_and_revision_cannot_extend_or_replace_the_original_lease() {
    let (registry, directory, _clock) = fixture();
    let verifier = registry.verifier();
    let original = lease();
    let before = std::fs::read(directory.path().join("authority-leases.json")).unwrap();
    let mut extended = original.clone();
    extended.expires_at_unix_ms += 1;
    assert!(matches!(
        verifier.observe_original_lease(&extended),
        Err(AuthorityLeaseError::RevisionMismatch)
    ));
    let mut rebound = original.clone();
    rebound.binding.payload_sha256 = [9; 32];
    assert!(matches!(
        verifier.observe_original_lease(&rebound),
        Err(AuthorityLeaseError::RevisionMismatch)
    ));
    let mut foreign_epoch = original.clone();
    foreign_epoch.authority_epoch += 1;
    assert!(matches!(
        verifier.observe_original_lease(&foreign_epoch),
        Err(AuthorityLeaseError::EpochMismatch)
    ));
    verifier
        .observe_original_lease(&original)
        .unwrap()
        .finish_original_observation()
        .unwrap();
    assert_eq!(
        std::fs::read(directory.path().join("authority-leases.json")).unwrap(),
        before
    );
}
