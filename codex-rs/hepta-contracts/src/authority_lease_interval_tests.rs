//! Regression tests for interval-valued time on the existing lease owner.
//! Fixtures do not constitute production time or custody attestations.

use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

struct IntervalClock(Mutex<Result<(u64, u64), AuthorityTrustError>>);

impl IntervalClock {
    fn set(&self, now: u64, uncertainty: u64) -> Result<(), AuthorityTrustError> {
        *self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)? = Ok((now, uncertainty));
        Ok(())
    }

    fn unavailable(&self) -> Result<(), AuthorityTrustError> {
        *self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)? = Err(AuthorityTrustError::Unavailable);
        Ok(())
    }
}

impl AuthorityClock for IntervalClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.now_with_uncertainty().map(|(now, _)| now)
    }

    fn now_with_uncertainty(&self) -> Result<(u64, u64), AuthorityTrustError> {
        *self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?
    }
}

fn lease() -> AuthorityLease {
    AuthorityLease {
        schema_version: 1,
        lease_id: "interval-lease".into(),
        authority_epoch: 7,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: "interval-agent".into(),
            operation_class: "fleet.allocate".into(),
            destination_id: "runtime.fleet".into(),
            scope_sha256: Sha256::digest(b"interval-scope").into(),
            payload_sha256: Sha256::digest(b"interval-payload").into(),
        },
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 3_000,
    }
}

fn fixture() -> Result<
    (
        AuthorityLeaseRegistry,
        Arc<IntervalClock>,
        tempfile::TempDir,
    ),
    Box<dyn std::error::Error>,
> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let clock = Arc::new(IntervalClock(Mutex::new(Ok((2_000, 10)))));
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "interval-owner".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7)?,
        clock.clone(),
    )?;
    registry.put_lease(lease(), 0)?;
    Ok((registry, clock, directory))
}

#[test]
fn interval_lease_requires_definite_start_and_strict_expiry() {
    let (registry, clock, _directory) = fixture().unwrap();
    let verifier = registry.verifier();
    let lease = lease();
    for (now, uncertainty, expected) in [
        (1_009, 10, Some(AuthorityLeaseError::NotYetValid)),
        (1_010, 10, None),
        (2_989, 10, None),
        (2_990, 10, Some(AuthorityLeaseError::Expired)),
        (3_000, 0, Some(AuthorityLeaseError::Expired)),
    ] {
        clock.set(now, uncertainty).unwrap();
        let result = verifier.verify_use(&lease.lease_id, 1, &lease.binding);
        match expected {
            Some(error) => assert_eq!(result.unwrap_err(), error),
            None => assert!(result.is_ok()),
        }
    }
}

#[test]
fn every_final_lease_boundary_rechecks_the_interval() {
    let (registry, clock, _directory) = fixture().unwrap();
    let verifier = registry.verifier();
    let lease = lease();
    let calls = AtomicUsize::new(0);
    for boundary in 0..5 {
        clock.set(2_000, 10).unwrap();
        if boundary == 4 {
            let bound = verifier
                .bind_dispatch(&lease.lease_id, 1, &lease.binding)
                .unwrap();
            clock.set(2_990, 10).unwrap();
            let result = bound.dispatch(|_| calls.fetch_add(1, Ordering::SeqCst));
            assert_eq!(result.unwrap_err(), AuthorityLeaseError::Expired);
            continue;
        }
        let token = verifier
            .verify_use(&lease.lease_id, 1, &lease.binding)
            .unwrap();
        clock.set(2_990, 10).unwrap();
        let result = match boundary {
            0 => verifier.with_verified_use(token, &lease.binding, || {
                calls.fetch_add(1, Ordering::SeqCst);
            }),
            1 => verifier.with_dispatch_boundary(token, &lease.binding, || {
                calls.fetch_add(1, Ordering::SeqCst);
            }),
            2 => deliver_authority_lease_with_witness(&verifier, token, &lease.binding, || {
                calls.fetch_add(1, Ordering::SeqCst);
            })
            .map(|_| ()),
            _ => dispatch_authority_lease_with_witness(&verifier, token, &lease.binding, |_| {
                calls.fetch_add(1, Ordering::SeqCst);
            })
            .map(|_| ()),
        };
        assert_eq!(result, Err(AuthorityLeaseError::Expired));
    }
    assert_eq!(calls.load(Ordering::SeqCst), 0);
}

#[test]
fn final_lease_interval_is_sampled_after_waiting_for_owner_lock() {
    let (registry, clock, _directory) = fixture().unwrap();
    let verifier = registry.verifier();
    let lease = lease();
    let token = verifier
        .verify_use(&lease.lease_id, 1, &lease.binding)
        .unwrap();
    let owner = Arc::clone(&verifier.0);
    let lock = owner.state.lock().unwrap();
    let (started, waiting) = mpsc::channel();
    let (completed, result) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        started.send(()).unwrap();
        completed
            .send(verifier.with_dispatch_boundary(token, &lease.binding, || ()))
            .unwrap();
    });
    waiting.recv_timeout(Duration::from_secs(2)).unwrap();
    assert!(result.recv_timeout(Duration::from_millis(50)).is_err());
    // The centre has not reached expiry; only the uncertainty interval has.
    clock.set(2_990, 10).unwrap();
    drop(lock);
    assert_eq!(
        result.recv_timeout(Duration::from_secs(2)).unwrap(),
        Err(AuthorityLeaseError::Expired)
    );
    worker.join().unwrap();
}

#[test]
fn interval_pruning_waits_for_definite_expiry_and_preserves_lineage() {
    let (registry, clock, _directory) = fixture().unwrap();
    clock.set(3_000, 10).unwrap();
    assert_eq!(registry.prune_expired_leases(1), Ok(0));
    assert!(registry.read_lease("interval-lease").unwrap().is_some());
    clock.set(3_010, 10).unwrap();
    assert_eq!(registry.prune_expired_leases(1), Ok(1));
    assert_eq!(registry.capacity().unwrap().retired_lease_ids, 1);
    assert_eq!(
        registry.put_lease(lease(), 0).unwrap_err(),
        AuthorityLeaseError::RevisionMismatch
    );
}

#[test]
fn invalid_interval_arithmetic_is_not_saturated_into_admission() {
    let (registry, clock, _directory) = fixture().unwrap();
    for (now, uncertainty) in [(0, 0), (5, 10), (u64::MAX, 1), (100_000, 60_001)] {
        clock.set(now, uncertainty).unwrap();
        assert_eq!(
            registry
                .verifier()
                .verify_use("interval-lease", 1, &lease().binding)
                .unwrap_err(),
            AuthorityLeaseError::InvalidTrust
        );
        assert_eq!(
            registry.prune_expired_leases(1),
            Err(AuthorityLeaseError::InvalidTrust)
        );
    }
}

#[test]
fn unavailable_trust_denies_mutation_but_not_exact_receipt_read() {
    let (registry, clock, _directory) = fixture().unwrap();
    let reason = Sha256::digest(b"interval-revocation-reason").into();
    let receipt = registry.revoke("interval-lease", 1, reason).unwrap();
    let before = registry.frontier().unwrap();
    clock.unavailable().unwrap();
    assert_eq!(
        registry.revoke("interval-lease", 1, reason).unwrap(),
        receipt
    );
    assert!(
        registry
            .read_revocation("interval-lease")
            .unwrap()
            .is_some()
    );
    assert_eq!(
        registry.advance_epoch(before.store_revision, 8),
        Err(AuthorityLeaseError::Unavailable)
    );
    let mut next = lease();
    next.lease_id = "another-interval-lease".into();
    assert_eq!(
        registry.put_lease(next, 0).unwrap_err(),
        AuthorityLeaseError::Unavailable
    );
    assert_eq!(registry.frontier().unwrap(), before);
}

#[test]
fn borrowed_store_encoding_preserves_exact_v2_bytes() {
    let (registry, _clock, directory) = fixture().unwrap();
    registry
        .revoke(
            "interval-lease",
            1,
            Sha256::digest(b"encoding-revoke").into(),
        )
        .unwrap();
    let state = registry.lock_state().unwrap();
    let owned = Stored {
        schema_version: STORE_SCHEMA_VERSION,
        owner_id: registry.owner_id().to_owned(),
        state: state.clone(),
    };
    let borrowed = StoredRef {
        schema_version: STORE_SCHEMA_VERSION,
        owner_id: registry.owner_id(),
        state: &state,
    };
    let bytes = serde_json::to_vec(&owned).unwrap();
    assert_eq!(serde_json::to_vec(&borrowed).unwrap(), bytes);
    assert_eq!(
        std::fs::read(directory.path().join("authority-leases.json")).unwrap(),
        bytes
    );
    let reopened: Stored = serde_json::from_slice(&bytes).unwrap();
    assert!(state_valid(&reopened.state));
    assert_eq!(
        frontier_for_state(&reopened.state),
        frontier_for_state(&state)
    );
}
