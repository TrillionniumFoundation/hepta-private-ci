use super::*;
use pretty_assertions::assert_eq;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::mpsc;

enum Stage {
    Checking,
    Complete(Box<Result<SignedFinalUseGrant, HostIssuerError>>),
}

struct VerificationClock {
    inner: Arc<dyn AuthorityClock>,
    armed: AtomicBool,
    stage: mpsc::Sender<Stage>,
    proceed: Mutex<mpsc::Receiver<()>>,
}

impl AuthorityClock for VerificationClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if self.armed.swap(false, Ordering::SeqCst) {
            self.stage
                .send(Stage::Checking)
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            self.proceed
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?
                .recv_timeout(Duration::from_secs(15))
                .map_err(|_| AuthorityTrustError::Unavailable)?;
        }
        self.inner.now_unix_ms()
    }
}

#[test]
fn concurrent_shorter_revision_cannot_reuse_an_older_cloned_expiry() {
    let fixture = Fixture::new();
    let (stage_tx, stage_rx) = mpsc::channel();
    let (proceed_tx, proceed_rx) = mpsc::channel();
    let clock = Arc::new(VerificationClock {
        inner: fixture.clock.clone(),
        armed: AtomicBool::new(false),
        stage: stage_tx.clone(),
        proceed: Mutex::new(proceed_rx),
    });
    let frontier = Arc::new(
        HostAuthorityFrontierStore::initialize(
            fixture.root.clone(),
            "racing-leases".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
        )
        .unwrap(),
    );
    let path = fixture._directory.path().join("racing-leases");
    std::fs::create_dir(&path).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    let registry = Arc::new(
        AuthorityLeaseRegistry::open_state_dir_with_trust(
            &path,
            "racing-leases".into(),
            clock.clone(),
            frontier,
        )
        .unwrap(),
    );
    let now = fixture.clock.now_unix_ms().unwrap();
    let first = AuthorityLease {
        schema_version: 1,
        lease_id: "racing-lease".into(),
        authority_epoch: 1,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: fixture.binding.subject_id.clone(),
            operation_class: "runtime.agentd.production_operation".into(),
            destination_id: fixture.binding.destination_id.clone(),
            scope_sha256: fixture.binding.scope_sha256,
            payload_sha256: fixture.binding.payload_sha256,
        },
        issued_at_unix_ms: now,
        expires_at_unix_ms: now + 60_000,
    };
    registry.put_lease(first.clone(), 0).unwrap();
    let replacement = AuthorityLease {
        revision: 2,
        expires_at_unix_ms: now + 20_000,
        ..first
    };
    let issuer = Arc::new(fixture.issuer);
    clock.armed.store(true, Ordering::SeqCst);
    let worker_issuer = issuer.clone();
    let worker_registry = registry.clone();
    let worker_binding = fixture.binding.clone();
    let worker = std::thread::spawn(move || {
        let result = worker_issuer.issue(
            &worker_registry.verifier(),
            "racing-lease",
            2,
            &worker_binding,
        );
        stage_tx.send(Stage::Complete(Box::new(result))).unwrap();
    });
    let first_stage = stage_rx.recv_timeout(Duration::from_secs(15)).unwrap();
    registry.put_lease(replacement.clone(), 1).unwrap();
    let result = match first_stage {
        Stage::Checking => {
            // Old code deterministically updates the lease after read_lease
            // and before verify_use acquires the registry state lock.
            proceed_tx.send(()).unwrap();
            match stage_rx.recv_timeout(Duration::from_secs(15)).unwrap() {
                Stage::Complete(result) => *result,
                Stage::Checking => panic!("unexpected second clock barrier"),
            }
        }
        Stage::Complete(result) => *result,
    };
    worker.join().unwrap();
    if let Ok(grant) = &result {
        assert!(
            grant.grant.expires_at_unix_ms <= replacement.expires_at_unix_ms,
            "a replacement's shorter expiry must bound the grant"
        );
    }
    assert_eq!(
        result,
        Err(HostIssuerError::Lease(
            AuthorityLeaseError::RevisionMismatch
        ))
    );
    clock.armed.store(false, Ordering::SeqCst);
    let fresh = issuer
        .issue(&registry.verifier(), "racing-lease", 2, &fixture.binding)
        .unwrap();
    assert!(fresh.grant.expires_at_unix_ms <= replacement.expires_at_unix_ms);
}
