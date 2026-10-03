use super::*;
use std::future::Future;
use std::pin::Pin;
use std::task::Poll;

async fn poll_waiter(mut future: Pin<&mut impl Future>) {
    std::future::poll_fn(|context| {
        assert!(future.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
}

#[tokio::test]
async fn claim_waiter_uses_the_clock_after_the_preceding_writer() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("open");
    let operation = intent(b"clock writer queue");
    store.prepare_intent(&operation).await.expect("prepare");
    let mut writer = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer");
    let worker = stable_id("worker:waiting");
    let mut waiting = std::pin::pin!(store.claim_next(
        &operation.destination,
        &worker,
        generation(1),
        Duration::from_secs(30),
    ));
    poll_waiter(waiting.as_mut()).await;
    tokio::time::sleep(Duration::from_millis(2)).await;
    let written_at = now_millis().expect("current clock");
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ?")
        .bind(written_at)
        .execute(&mut *writer)
        .await
        .expect("preceding writer");
    writer.commit().await.expect("commit preceding writer");
    let claim = waiting.await.expect("claim after writer").expect("claim");
    assert!(claim.expires_at_unix_ms >= written_at as u64 + 30_000);
}

#[tokio::test]
async fn exact_claim_waiter_observes_current_eligibility() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("open");
    let operation = intent(b"exact queued clock");
    store.prepare_intent(&operation).await.expect("prepare");
    let mut writer = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer");
    let worker = stable_id("worker:exact-waiting");
    let mut waiting = std::pin::pin!(store.claim_operation(
        &operation.scope_id,
        &operation.operation_id,
        &worker,
        generation(1),
        Duration::from_secs(30),
    ));
    poll_waiter(waiting.as_mut()).await;
    tokio::time::sleep(Duration::from_millis(2)).await;
    let eligible_at = now_millis().expect("current clock");
    sqlx::query("UPDATE cross_owner_outbox SET next_eligible_at_ms = ?")
        .bind(eligible_at)
        .execute(&mut *writer)
        .await
        .expect("preceding eligibility update");
    writer.commit().await.expect("commit preceding writer");
    let claim = waiting
        .await
        .expect("claim after writer")
        .expect("eligible claim");
    assert!(claim.expires_at_unix_ms >= eligible_at as u64 + 30_000);
}

#[tokio::test]
async fn current_clock_still_rejects_a_future_durable_frontier() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("open");
    let operation = intent(b"actual clock rollback");
    store.prepare_intent(&operation).await.expect("prepare");
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ?")
        .bind(now_millis().expect("current clock") + 60_000)
        .execute(&store.pool)
        .await
        .expect("future frontier");
    assert!(matches!(
        store
            .claim_next(
                &operation.destination,
                &stable_id("worker:rolled-back-clock"),
                generation(1),
                Duration::from_secs(30),
            )
            .await,
        Err(DurableOperationError::ClockRollback)
    ));
}

#[cfg(unix)]
#[tokio::test]
async fn dispatch_waiter_rejects_a_lease_that_expired_behind_the_writer() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("open");
    let operation = intent(b"expired while waiting");
    store.prepare_intent(&operation).await.expect("prepare");
    let (authority, signed, _authority_dir) = authority_fixture(&operation, 29);
    let claim = store
        .claim_next(
            &operation.destination,
            &stable_id("worker:dispatch-waiting"),
            generation(1),
            Duration::from_secs(30),
        )
        .await
        .expect("claim")
        .expect("row");
    let mut writer = store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("writer");
    let mut waiting = std::pin::pin!(store.authorize_dispatch(&authority, &signed, &claim));
    poll_waiter(waiting.as_mut()).await;
    let expires_at = now_millis().expect("expiry clock") + 1;
    sqlx::query("UPDATE cross_owner_outbox SET lease_until_ms = ?")
        .bind(expires_at)
        .execute(&mut *writer)
        .await
        .expect("expire original lease");
    while now_millis().expect("current clock") <= expires_at {
        tokio::time::sleep(Duration::from_millis(2)).await;
    }
    writer.commit().await.expect("commit preceding writer");
    assert!(matches!(
        waiting.await,
        Err(DurableOperationError::StaleLease)
    ));
    assert_eq!(
        store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("lookup")
            .expect("operation")
            .state,
        DurableOperationState::Prepared
    );
}
