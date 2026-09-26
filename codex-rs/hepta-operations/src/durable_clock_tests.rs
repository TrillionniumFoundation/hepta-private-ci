//! A waiter must observe time after the peer commit it will validate against.
use super::*;

#[tokio::test]
async fn queued_prepare_samples_time_after_peer_commit_without_weakening_clock_floor() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("operations.sqlite3");
    let first = DurableOperationStore::open(&path).await.expect("first");
    let second = DurableOperationStore::open(&path).await.expect("second");
    let operation = intent(b"clock-queue");
    first.prepare_intent(&operation).await.expect("initial");
    let mut tx = first
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .expect("peer lock");
    let pending = second.prepare_intent(&operation);
    tokio::pin!(pending);
    assert!(
        tokio::time::timeout(Duration::from_millis(25), &mut pending)
            .await
            .is_err(),
        "peer transaction must hold the caller at admission"
    );
    let committed_at = now_millis().expect("wall observation");
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ? WHERE operation_id = ?")
        .bind(committed_at)
        .bind(operation.operation_id.as_str())
        .execute(&mut *tx)
        .await
        .expect("peer current state");
    tx.commit().await.expect("peer commit");
    let receipt = pending.await.expect("queue delay is not clock regression");
    assert_eq!(receipt.disposition, PrepareDisposition::AlreadyPresent);

    // A genuinely future persisted floor must still reject the same request.
    let future = now_millis()
        .expect("clock")
        .checked_add(60_000)
        .expect("bounded future");
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ? WHERE operation_id = ?")
        .bind(future)
        .bind(operation.operation_id.as_str())
        .execute(&first.pool)
        .await
        .expect("future floor fixture");
    assert!(matches!(
        second.prepare_intent(&operation).await,
        Err(DurableOperationError::ClockRollback)
    ));
}
