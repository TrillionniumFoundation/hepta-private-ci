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
        assert_eq!(result, Err(AuthorityLeaseError::Unavailable));
        assert_eq!(registry.frontier()?, frontier);
        assert_eq!(
            std::fs::read(directory.path().join("authority-leases.json"))?,
            bytes
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
