//! Controlled expiry while waiting for the original owner/revocation mutex.
use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

struct EntryClock {
    now: AtomicU64,
    sampled: Mutex<Option<mpsc::Sender<u64>>>,
}
impl AuthorityClock for EntryClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let now = self.now.load(Ordering::SeqCst);
        if let Some(sender) = self.sampled.lock().unwrap().as_ref() {
            let _ = sender.send(now);
        }
        Ok(now)
    }
}

#[derive(Clone, Copy)]
enum Boundary {
    Consumer,
    Dispatch,
}

fn expires_while_waiting(boundary: Boundary) {
    let directory = tempfile::tempdir().unwrap();
    let clock = Arc::new(EntryClock {
        now: AtomicU64::new(1_000),
        sampled: Mutex::new(None),
    });
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        &directory.path().join("original-owner"),
        "entry-clock-owner".into(),
        AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
        clock.clone(),
    )
    .unwrap();
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: "entry-clock-lease".into(),
        revision: 1,
        authority_epoch: 1,
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 5_000,
        binding: AuthorityLeaseBinding {
            principal_id: "original-consumer".into(),
            operation_class: "local-entry".into(),
            destination_id: "no-effect".into(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
        },
    };
    registry
        .put_lease(lease.clone(), /*expected_revision*/ 0)
        .unwrap();
    let verifier = registry.verifier();
    let token = verifier
        .verify_use(&lease.lease_id, lease.revision, &lease.binding)
        .unwrap();
    let guard = verifier.lock_state().unwrap();
    let (sampled_tx, sampled_rx) = mpsc::channel();
    *clock.sampled.lock().unwrap() = Some(sampled_tx);
    let (started_tx, started_rx) = mpsc::channel();
    let entered = Arc::new(AtomicBool::new(false));
    let attempted = entered.clone();
    let worker_verifier = verifier.clone();
    let worker = std::thread::spawn(move || {
        started_tx.send(()).unwrap();
        let entry = || attempted.store(true, Ordering::SeqCst);
        match boundary {
            Boundary::Consumer => worker_verifier.with_verified_use(token, &lease.binding, entry),
            Boundary::Dispatch => {
                worker_verifier.with_dispatch_boundary(token, &lease.binding, entry)
            }
        }
    });
    started_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    // This is a controlled owner-lock wait, with no wall-clock expiry/sleep.
    // The old implementation reports its pre-lock 1000ms sample here; the
    // corrected implementation samples only once the owner fence is released.
    let pre_lock_sample = sampled_rx.recv_timeout(Duration::from_millis(100));
    clock.now.store(5_000, Ordering::SeqCst);
    drop(guard);
    assert_eq!(
        worker.join().unwrap(),
        Err(AuthorityLeaseError::Expired),
        "sample before releasing owner fence: {pre_lock_sample:?}"
    );
    assert!(!entered.load(Ordering::SeqCst));
}

#[test]
fn consumer_entry_rechecks_time_after_waiting_for_owner_fence() {
    expires_while_waiting(Boundary::Consumer);
}

#[test]
fn dispatch_entry_rechecks_time_after_waiting_for_owner_fence() {
    expires_while_waiting(Boundary::Dispatch);
}
