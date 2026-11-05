//! Real original state/clock contention; no Root authority is simulated.
use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

type Pause = (mpsc::Sender<()>, mpsc::Receiver<()>);
#[derive(Default)]
struct Clock(Mutex<Option<Pause>>);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        if let Some((entered, release)) = self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .take()
        {
            entered
                .send(())
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            release
                .recv_timeout(Duration::from_secs(2))
                .map_err(|_| AuthorityTrustError::Unavailable)?;
        }
        Ok(10_000)
    }
}
fn fixture(
    clock: Arc<Clock>,
) -> Result<(AuthorityLeaseRegistry, tempfile::TempDir), Box<dyn std::error::Error>> {
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        directory.path(),
        "bounded-original-owner".into(),
        AuthorityLeaseFrontier::for_empty_epoch(1)?,
        clock,
    )?;
    registry.put_lease(
        AuthorityLease {
            schema_version: 1,
            lease_id: "bounded-original-lease".into(),
            authority_epoch: 1,
            revision: 1,
            binding: AuthorityLeaseBinding {
                principal_id: "original-owner".into(),
                operation_class: "original-effect".into(),
                destination_id: "original-note".into(),
                scope_sha256: [1; 32],
                payload_sha256: [2; 32],
            },
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 30_000,
        },
        0,
    )?;
    Ok((registry, directory))
}
fn arm(
    clock: &Clock,
) -> Result<(mpsc::Receiver<()>, mpsc::Sender<()>), Box<dyn std::error::Error>> {
    let (entered, observe) = mpsc::channel();
    let (release, wait) = mpsc::channel();
    *clock.0.lock().map_err(|_| "clock lock")? = Some((entered, wait));
    Ok((observe, release))
}

#[test]
fn same_registry_busy_or_late_clock_cannot_revoke_after_original_deadline()
-> Result<(), Box<dyn std::error::Error>> {
    for hold_state in [true, false] {
        let clock = Arc::new(Clock::default());
        let (registry, directory) = fixture(clock.clone())?;
        let frontier = registry.frontier()?;
        let bytes = std::fs::read(directory.path().join("authority-leases.json"))?;
        let (entered, release) = arm(&clock)?;
        let held = if hold_state {
            Some(registry.0.state.lock().map_err(|_| "state lock")?)
        } else {
            None
        };
        let end = Instant::now() + Duration::from_millis(300);
        let result = std::thread::scope(|scope| -> Result<_, Box<dyn std::error::Error>> {
            let worker =
                scope.spawn(|| registry.revoke_before("bounded-original-lease", 1, [9; 32], end));
            entered.recv_timeout(Duration::from_secs(2))?;
            if hold_state {
                release.send(())?;
            }
            // Retain the REAL original lock or clock read across the SAME end.
            // Neither original CAS nor persistence is mocked or replaced.
            std::thread::sleep(
                end.saturating_duration_since(Instant::now()) + Duration::from_millis(1),
            );
            drop(held);
            if !hold_state {
                release.send(())?;
            }
            Ok(worker.join().map_err(|_| "revoke worker panic")?)
        })?;
        assert_eq!(
            (
                result,
                registry.frontier()?,
                std::fs::read(directory.path().join("authority-leases.json"))?
            ),
            (Err(AuthorityLeaseError::Unavailable), frontier, bytes)
        );
        assert!(
            registry
                .read_revocation("bounded-original-lease")?
                .is_none()
        );
    }
    Ok(())
}

#[test]
fn bounded_revoke_retains_original_cas_receipt_and_idempotence()
-> Result<(), Box<dyn std::error::Error>> {
    let (registry, _directory) = fixture(Arc::new(Clock::default()))?;
    let end = Instant::now() + Duration::from_secs(1);
    let receipt = registry.revoke_before("bounded-original-lease", 1, [9; 32], end)?;
    let frontier = registry.frontier()?;
    assert_eq!(
        registry.revoke_before("bounded-original-lease", 1, [9; 32], end)?,
        receipt
    );
    assert_eq!(registry.frontier()?, frontier);
    assert_eq!(
        registry.revoke_before("bounded-original-lease", 1, [8; 32], end),
        Err(AuthorityLeaseError::Revoked)
    );
    assert_eq!(registry.frontier()?, frontier);
    Ok(())
}

#[test]
fn exact_original_revoke_checks_every_retained_lease_field_and_same_reason_retry()
-> Result<(), Box<dyn std::error::Error>> {
    let (registry, _directory) = fixture(Arc::new(Clock::default()))?;
    let original = registry
        .read_lease("bounded-original-lease")?
        .ok_or("original absent")?
        .lease;
    let frontier = registry.frontier()?;
    let end = Instant::now() + Duration::from_secs(1);
    for field in 0..8 {
        let mut changed = original.clone();
        match field {
            0 => changed.authority_epoch += 1,
            1 => changed.revision += 1,
            2 => changed.binding.principal_id.push('x'),
            3 => changed.binding.operation_class.push('x'),
            4 => changed.binding.destination_id.push('x'),
            5 => changed.binding.scope_sha256[0] ^= 1,
            6 => changed.binding.payload_sha256[0] ^= 1,
            7 => changed.expires_at_unix_ms += 1,
            _ => unreachable!(),
        }
        assert!(
            registry
                .revoke_exact_before(&changed, [7; 32], end)
                .is_err()
        );
        assert_eq!(registry.frontier()?, frontier);
        assert!(registry.read_revocation(&original.lease_id)?.is_none());
    }
    let receipt = registry.revoke_exact_before(&original, [7; 32], end)?;
    let revoked = registry.frontier()?;
    assert_eq!(
        registry.revoke_exact_before(&original, [7; 32], end)?,
        receipt
    );
    assert_eq!(registry.frontier()?, revoked);
    assert_eq!(
        registry.revoke_exact_before(&original, [8; 32], end),
        Err(AuthorityLeaseError::Revoked)
    );
    let mut changed = original.clone();
    changed.binding.destination_id.push('x');
    assert!(
        registry
            .revoke_exact_before(&changed, [7; 32], end)
            .is_err()
    );
    assert_eq!(registry.frontier()?, revoked);
    Ok(())
}

#[test]
fn exact_revoke_refuses_reused_id_after_epoch_change_while_original_clock_is_paused()
-> Result<(), Box<dyn std::error::Error>> {
    let clock = Arc::new(Clock::default());
    let (registry, _directory) = fixture(Arc::clone(&clock))?;
    let original = registry
        .read_lease("bounded-original-lease")?
        .ok_or("original absent")?
        .lease;
    let (entered, release) = arm(&clock)?;
    let end = Instant::now() + Duration::from_secs(2);
    let result = std::thread::scope(|scope| -> Result<_, Box<dyn std::error::Error>> {
        let worker = scope.spawn(|| registry.revoke_exact_before(&original, [9; 32], end));
        entered.recv_timeout(Duration::from_secs(2))?;
        let previous = registry.frontier()?;
        registry.advance_epoch(previous.store_revision, 2)?;
        let mut replacement = original.clone();
        replacement.authority_epoch = 2;
        replacement.binding.destination_id = "different-original-target".into();
        registry.put_lease(replacement, 0)?;
        let frontier = registry.frontier()?;
        release.send(())?;
        let result = worker.join().map_err(|_| "exact revoke worker panic")?;
        Ok((result, frontier))
    })?;
    assert_eq!(result.0, Err(AuthorityLeaseError::EpochMismatch));
    assert_eq!(registry.frontier()?, result.1);
    assert!(registry.read_revocation(&original.lease_id)?.is_none());
    Ok(())
}

#[test]
fn exact_revoke_refuses_concurrent_successor_revision_and_elapsed_deadline()
-> Result<(), Box<dyn std::error::Error>> {
    let clock = Arc::new(Clock::default());
    let (registry, _directory) = fixture(Arc::clone(&clock))?;
    let original = registry
        .read_lease("bounded-original-lease")?
        .ok_or("original absent")?
        .lease;
    let (entered, release) = arm(&clock)?;
    let end = Instant::now() + Duration::from_secs(2);
    let result = std::thread::scope(|scope| -> Result<_, Box<dyn std::error::Error>> {
        let worker = scope.spawn(|| registry.revoke_exact_before(&original, [9; 32], end));
        entered.recv_timeout(Duration::from_secs(2))?;
        let mut successor = original.clone();
        successor.revision += 1;
        successor.expires_at_unix_ms += 1;
        registry.put_lease(successor, original.revision)?;
        let frontier = registry.frontier()?;
        release.send(())?;
        Ok((
            worker.join().map_err(|_| "exact revoke worker panic")?,
            frontier,
        ))
    })?;
    assert_eq!(result.0, Err(AuthorityLeaseError::RevisionMismatch));
    assert_eq!(registry.frontier()?, result.1);
    let current = registry
        .read_lease(&original.lease_id)?
        .ok_or("successor absent")?
        .lease;
    let elapsed = Instant::now()
        .checked_sub(Duration::from_secs(1))
        .ok_or("clock range")?;
    assert_eq!(
        registry.revoke_exact_before(&current, [9; 32], elapsed),
        Err(AuthorityLeaseError::Unavailable)
    );
    assert_eq!(registry.frontier()?, result.1);
    assert!(registry.read_revocation(&original.lease_id)?.is_none());
    Ok(())
}
