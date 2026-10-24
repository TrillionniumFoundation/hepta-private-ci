use super::*;
use crate::IssuerPurpose;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;

async fn dispatched(
    store: &AuthBusAuthorityStore,
    reservation: &QuotaReservation,
) -> QuotaReservation {
    store
        .mark_dispatch_attempted(
            &reservation.reservation_id,
            reservation.revision,
            reservation.effect_digest,
            sample(5, 1_500),
        )
        .await
        .expect("actual dispatch reservation")
}

async fn unchanged(
    store: &AuthBusAuthorityStore,
    quota: &QuotaSnapshot,
    reservation: &QuotaReservation,
) {
    assert_eq!(
        store.quota_snapshot(&quota.quota_key).await.expect("quota"),
        *quota
    );
    assert_eq!(
        store
            .reservation(&reservation.reservation_id)
            .await
            .expect("reservation"),
        *reservation
    );
}

#[tokio::test]
async fn unregistered_self_signed_settlement_is_rejected_without_quota_change() {
    let (_root, store, _, reservation) = configured().await;
    let reservation = dispatched(&store, &reservation).await;
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota");
    let key = SigningKey::from_bytes(&[61; 32]);
    let signed = evidence(&key, &reservation, SettlementStatus::Rejected, 0, 1_600);
    assert!(matches!(
        store.settle(&issuer(&key), &signed, sample(6, 1_600)).await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
    unchanged(&store, &quota, &reservation).await;
}

#[tokio::test]
async fn registered_epoch_cannot_use_a_caller_substituted_key() {
    let key = SigningKey::from_bytes(&[62; 32]);
    let (_root, store, _, reservation) = registered(&key).await;
    let reservation = dispatched(&store, &reservation).await;
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota");
    let substituted = SigningKey::from_bytes(&[63; 32]);
    let signed = evidence(
        &substituted,
        &reservation,
        SettlementStatus::Completed,
        1,
        1_600,
    );
    assert!(matches!(
        store
            .settle(&issuer(&substituted), &signed, sample(6, 1_600))
            .await,
        Err(AuthBusAuthorityError::SettlementIssuerMismatch)
    ));
    unchanged(&store, &quota, &reservation).await;
}

#[tokio::test]
async fn caller_epoch_cannot_invent_a_durable_registration() {
    let key = SigningKey::from_bytes(&[64; 32]);
    let (_root, store, _, reservation) = registered(&key).await;
    let reservation = dispatched(&store, &reservation).await;
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota");
    let mut hint = issuer(&key);
    hint.key_epoch = Generation::new(2).expect("generation");
    let mut signed = evidence(&key, &reservation, SettlementStatus::Completed, 1, 1_600);
    signed.claims.key_epoch = hint.key_epoch;
    signed.signature = key.sign(&signed.claims.signing_bytes()).to_bytes();
    assert!(matches!(
        store.settle(&hint, &signed, sample(6, 1_600)).await,
        Err(AuthBusAuthorityError::IssuerMissing)
    ));
    unchanged(&store, &quota, &reservation).await;
}

#[tokio::test]
async fn snapshot_taken_before_actual_revocation_cannot_settle() {
    let key = SigningKey::from_bytes(&[65; 32]);
    let (_root, store, _, reservation) = registered(&key).await;
    let reservation = dispatched(&store, &reservation).await;
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota");
    let hint = store
        .settlement_issuer(
            &id("issuer:settlement"),
            Generation::new(1).expect("generation"),
        )
        .await
        .expect("actual current registration");
    store
        .revoke_issuer(
            IssuerPurpose::Settlement,
            &hint.issuer_id,
            hint.key_epoch,
            /*expected_revision*/ 1,
        )
        .await
        .expect("actual owner revocation");
    let signed = evidence(&key, &reservation, SettlementStatus::Rejected, 0, 1_600);
    assert!(matches!(
        store.settle(&hint, &signed, sample(6, 1_600)).await,
        Err(AuthBusAuthorityError::SettlementIssuerRevoked)
    ));
    unchanged(&store, &quota, &reservation).await;
}

struct ReleaseOnDrop(Arc<(Mutex<bool>, Condvar)>);
impl Drop for ReleaseOnDrop {
    fn drop(&mut self) {
        let (released, changed) = &*self.0;
        *released.lock().expect("release gate") = true;
        changed.notify_all();
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_settlement_observes_revocation_committed_by_another_owner() {
    let key = SigningKey::from_bytes(&[66; 32]);
    let (root, store, _, reservation) = registered(&key).await;
    let reservation = dispatched(&store, &reservation).await;
    let quota = store
        .quota_snapshot(&reservation.quota_key)
        .await
        .expect("quota");
    let hint = store
        .settlement_issuer(
            &id("issuer:settlement"),
            Generation::new(1).expect("generation"),
        )
        .await
        .expect("current registration before revoke");
    let other = AuthBusAuthorityStore::open(&root.path().join("authbus.sqlite"))
        .await
        .expect("second actual durable owner");
    let at_commit = Arc::new(Notify::new());
    let gate = ReleaseOnDrop(Arc::new((Mutex::new(false), Condvar::new())));
    let once = Arc::new(AtomicBool::new(true));
    let mut connections = Vec::new();
    for _ in 0..5 {
        connections.push(other.pool.acquire().await.expect("real revoker connection"));
    }
    for connection in &mut connections {
        let (at_commit, gate, once) = (at_commit.clone(), gate.0.clone(), once.clone());
        connection
            .lock_handle()
            .await
            .expect("safe SQLite handle")
            .set_commit_hook(move || {
                if !once.swap(false, Ordering::SeqCst) {
                    return true;
                }
                at_commit.notify_one();
                let (released, changed) = &*gate;
                let (released, timeout) = changed
                    .wait_timeout_while(
                        released.lock().expect("commit gate"),
                        Duration::from_secs(4),
                        |released| !*released,
                    )
                    .expect("bounded commit wait");
                *released && !timeout.timed_out()
            });
    }
    drop(connections);
    let in_database = Arc::new(Notify::new());
    let armed = Arc::new(AtomicBool::new(false));
    let mut connections = Vec::new();
    for _ in 0..5 {
        connections.push(
            store
                .pool
                .acquire()
                .await
                .expect("real settlement connection"),
        );
    }
    for connection in &mut connections {
        let (entered, armed) = (in_database.clone(), armed.clone());
        connection
            .lock_handle()
            .await
            .expect("safe SQLite handle")
            .set_progress_handler(/*num_ops*/ 1, move || {
                if armed.swap(false, Ordering::SeqCst) {
                    entered.notify_one();
                }
                true
            });
    }
    drop(connections);
    let revoke = tokio::spawn(async move {
        other
            .revoke_issuer(
                IssuerPurpose::Settlement,
                &id("issuer:settlement"),
                Generation::new(1).expect("generation"),
                /*expected_revision*/ 1,
            )
            .await
    });
    tokio::time::timeout(Duration::from_secs(2), at_commit.notified())
        .await
        .expect("actual revoke entered COMMIT");
    let signed = evidence(&key, &reservation, SettlementStatus::Rejected, 0, 1_600);
    let settlement = store.settle(&hint, &signed, sample(6, 1_600));
    tokio::pin!(settlement);
    armed.store(true, Ordering::SeqCst);
    let queued = tokio::time::timeout(Duration::from_secs(2), async {
        tokio::select! {
            result = &mut settlement => Some(result),
            () = in_database.notified() => None,
        }
    })
    .await;
    let revoker_still_holds_commit = !revoke.is_finished();
    // Release even if the assertion below will fail; the native worker never
    // retains a dangling test gate. The callback itself also has a finite wait.
    drop(gate);
    let revoked = tokio::time::timeout(Duration::from_secs(3), revoke)
        .await
        .expect("revocation completes")
        .expect("revoker task")
        .expect("actual revoke commits");
    assert_eq!(revoked.state, crate::IssuerLifecycleState::Revoked);
    let early = queued.expect("settle entered actual SQLite VM while revoke held its commit");
    let result = match early {
        Some(result) => result,
        None => tokio::time::timeout(Duration::from_secs(3), &mut settlement)
            .await
            .expect("settlement completes"),
    };
    assert!(revoker_still_holds_commit);
    assert!(matches!(
        result,
        Err(AuthBusAuthorityError::SettlementIssuerRevoked)
    ));
    unchanged(&store, &quota, &reservation).await;
}
