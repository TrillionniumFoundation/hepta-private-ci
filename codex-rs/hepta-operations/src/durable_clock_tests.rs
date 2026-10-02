use super::*;

use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::AtomicI64;
use std::sync::atomic::Ordering;
use std::task::Poll;

fn operation() -> OperationIntentV1 {
    OperationIntentV1 {
        scope_id: StableId::new("scope:serialized-clock").expect("scope"),
        operation_id: StableId::new("operation:serialized-clock").expect("operation"),
        expected_predecessor: None,
        destination: StableId::new("destination:serialized-clock").expect("destination"),
        payload_digest: Digest32::of_bytes(b"payload"),
        owner_generation: Generation::new(1).expect("generation"),
    }
}

#[tokio::test]
async fn waiting_prepare_observes_time_after_prior_writer_commits() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let mut first = DurableOperationStore::open(&path).await.expect("first");
    let mut second = DurableOperationStore::open(&path).await.expect("second");
    let clock = Arc::new(AtomicI64::new(100));
    first.clock_override = Some(Arc::clone(&clock));
    second.clock_override = Some(Arc::clone(&clock));
    let intent = operation();
    first
        .prepare_intent(&intent)
        .await
        .expect("initial prepare");
    let mut writer = first
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer");
    let pending = second.prepare_intent(&intent);
    tokio::pin!(pending);
    // Poll while serialization is held, rather than assuming a scheduler sleep
    // reached BEGIN. Pre-lock sampling captures 100 here and will be stale.
    std::future::poll_fn(|context| {
        assert!(pending.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    clock.store(200, Ordering::SeqCst);
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = 200")
        .execute(&mut *writer)
        .await
        .expect("prior writer advances committed time");
    writer.commit().await.expect("release writer");
    let prepared = pending.await.expect("serialized time is not rollback");
    assert_eq!(prepared.disposition, PrepareDisposition::AlreadyPresent);
    // A genuinely backward clock still fails, including an idempotent retry.
    clock.store(199, Ordering::SeqCst);
    assert!(matches!(
        first.prepare_intent(&intent).await,
        Err(DurableOperationError::ClockRollback)
    ));
}

#[tokio::test]
async fn lease_expiring_while_renewal_waits_cannot_be_extended() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let mut owner = DurableOperationStore::open(&path).await.expect("owner");
    let clock = Arc::new(AtomicI64::new(100));
    owner.clock_override = Some(Arc::clone(&clock));
    let intent = operation();
    owner.prepare_intent(&intent).await.expect("prepare");
    let claim = owner
        .claim_next(
            &intent.destination,
            &StableId::new("worker:serialized-clock").expect("worker"),
            intent.owner_generation,
            Duration::from_millis(10),
        )
        .await
        .expect("claim")
        .expect("lease");
    let writer = owner
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer");
    let pending = owner.renew_claim(&claim, Duration::from_millis(10));
    tokio::pin!(pending);
    std::future::poll_fn(|context| {
        assert!(pending.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    clock.store(111, Ordering::SeqCst);
    writer.commit().await.expect("release writer");
    assert!(matches!(
        pending.await,
        Err(DurableOperationError::StaleLease)
    ));
    let status = owner
        .outbox_status(&intent.destination, &intent.scope_id, &intent.operation_id)
        .await
        .expect("status")
        .expect("outbox");
    assert_eq!(status.fence, claim.fence);
    assert_eq!(status.lease_until_unix_ms, Some(110));
}

#[tokio::test]
async fn genuine_clock_rollback_rejects_idempotent_prepare() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let mut owner = DurableOperationStore::open(&path).await.expect("owner");
    let clock = Arc::new(AtomicI64::new(200));
    owner.clock_override = Some(Arc::clone(&clock));
    let intent = operation();
    let initial = owner.prepare_intent(&intent).await.expect("prepare");
    clock.store(199, Ordering::SeqCst);
    assert!(matches!(
        owner.prepare_intent(&intent).await,
        Err(DurableOperationError::ClockRollback)
    ));
    let retained = owner
        .operation(&intent.scope_id, &intent.operation_id)
        .await
        .expect("operation read")
        .expect("operation");
    assert_eq!(retained, initial.record);
}
