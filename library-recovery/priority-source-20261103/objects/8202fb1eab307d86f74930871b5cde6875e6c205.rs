//! Deadline checks after writer reservation and inside the final-use consumer.
use super::*;
use std::future::Future;
use std::task::Poll;

#[tokio::test]
async fn expired_writer_wait_cannot_enter_effect_and_releases_transaction() {
    let directory = tempfile::tempdir().expect("temp");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await.expect("open");
    let operation = intent(b"lock-delayed effect");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store.claim_next(&operation.destination, &stable_id("worker:blocked"),
        generation(1), Duration::from_secs(30)).await.expect("claim").expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 91);
    let mut authorized = store.authorize_dispatch(&authority, &signed, &claim).await.expect("authorize");
    let deadline = now_millis().expect("clock") + 1_000;
    sqlx::query("UPDATE cross_owner_outbox SET lease_until_ms = ?").bind(deadline)
        .execute(&store.pool).await.expect("shorten fixture lease");
    authorized.claim.expires_at_unix_ms = u64::try_from(deadline).expect("deadline");
    let blocker = store.pool.begin_with("BEGIN IMMEDIATE").await.expect("block");
    let calls = std::sync::atomic::AtomicUsize::new(0);
    let effect = store.execute_authorized(authorized, |_| {
        calls.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        DispatchEffect::Dispatched { value: (), dispatch_digest: Digest32::of_bytes(b"late effect"),
            acknowledgement_digest: Some(Digest32::of_bytes(b"ack")) }
    });
    tokio::pin!(effect);
    std::future::poll_fn(|context| {
        assert!(effect.as_mut().poll(context).is_pending()); Poll::Ready(())
    }).await;
    let now = now_millis().expect("clock");
    assert!(now < deadline, "fixture starts while live");
    tokio::time::sleep(Duration::from_millis(u64::try_from(deadline - now).expect("remaining") + 10)).await;
    blocker.commit().await.expect("release blocker");
    assert!(matches!(effect.await, Err(DurableOperationError::StaleLease)));
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 0);
    tokio::time::timeout(Duration::from_secs(5), store.recover_expired_leases())
        .await.expect("no leaked transaction").expect("recover");
    assert_eq!(store.operation(&operation.scope_id, &operation.operation_id)
        .await.expect("lookup").expect("row").state, DurableOperationState::Indeterminate);
    let mut current = operation;
    current.operation_id = stable_id("operation:current-control");
    store.prepare_intent(&current).await.expect("prepare control");
    let claim = store.claim_next(&current.destination, &stable_id("worker:control"),
        generation(1), Duration::from_secs(30)).await.expect("claim").expect("row");
    let (authority, signed, _control_dir) = authority_fixture(&claim.intent, 92);
    let authorized = store.authorize_dispatch(&authority, &signed, &claim).await.expect("authorize");
    store.execute_authorized(authorized, |_| {
        calls.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        DispatchEffect::Dispatched { value: (), dispatch_digest: Digest32::of_bytes(b"live effect"),
            acknowledgement_digest: Some(Digest32::of_bytes(b"live ack")) }
    }).await.expect("live lease enters");
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
}

#[tokio::test]
async fn expired_writer_wait_cannot_renew_or_mutate_outbox() {
    let directory = tempfile::tempdir().expect("temp");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await.expect("open");
    let operation = intent(b"delayed renewal");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store.claim_next(&operation.destination, &stable_id("worker:renewal"),
        generation(1), Duration::from_secs(30)).await.expect("claim").expect("row");
    let mut claim = store.renew_claim(&claim, Duration::from_secs(30)).await.expect("live renewal");
    let deadline = now_millis().expect("clock") + 1_000;
    sqlx::query("UPDATE cross_owner_outbox SET lease_until_ms = ?").bind(deadline)
        .execute(&store.pool).await.expect("shorten fixture lease");
    claim.expires_at_unix_ms = u64::try_from(deadline).expect("deadline");
    let before = store.outbox_status(&operation.destination, &operation.scope_id, &operation.operation_id)
        .await.expect("before");
    let blocker = store.pool.begin_with("BEGIN IMMEDIATE").await.expect("block");
    let renewal = store.renew_claim(&claim, Duration::from_secs(30));
    tokio::pin!(renewal);
    std::future::poll_fn(|context| {
        assert!(renewal.as_mut().poll(context).is_pending()); Poll::Ready(())
    }).await;
    let now = now_millis().expect("clock");
    assert!(now < deadline, "fixture starts while live");
    tokio::time::sleep(Duration::from_millis(u64::try_from(deadline - now).expect("remaining") + 10)).await;
    blocker.commit().await.expect("release blocker");
    assert!(matches!(renewal.await, Err(DurableOperationError::StaleLease)));
    assert_eq!(store.outbox_status(&operation.destination, &operation.scope_id, &operation.operation_id)
        .await.expect("after"), before);
    tokio::time::timeout(Duration::from_secs(5), store.recover_expired_leases())
        .await.expect("no leaked transaction").expect("recover");
}

#[tokio::test]
async fn rollback_clock_rejection_releases_writer_reservation() {
    let directory = tempfile::tempdir().expect("temp");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await.expect("open");
    let operation = intent(b"future clock watermark");
    store.prepare_intent(&operation).await.expect("prepare");
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ?")
        .bind(now_millis().expect("clock") + 60_000).execute(&store.pool).await.expect("future fixture");
    assert!(matches!(store.claim_next(&operation.destination, &stable_id("worker:rollback"),
        generation(1), Duration::from_secs(30)).await, Err(DurableOperationError::ClockRollback)));
    let reservation = tokio::time::timeout(Duration::from_secs(5), store.pool.begin_with("BEGIN IMMEDIATE"))
        .await.expect("clock rejection released reservation").expect("reservation");
    reservation.rollback().await.expect("release control reservation");
}

#[tokio::test]
async fn final_use_consumer_checks_persisted_deadline_over_claim_metadata() {
    let directory = tempfile::tempdir().expect("temp");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await.expect("open");
    let operation = intent(b"final-use deadline");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store.claim_next(&operation.destination, &stable_id("worker:final"),
        generation(1), Duration::from_secs(30)).await.expect("claim").expect("row");
    let (authority, signed, _authority_dir) = authority_fixture(&claim.intent, 93);
    let authorized = store.authorize_dispatch(&authority, &signed, &claim).await.expect("authorize");
    let now = now_millis().expect("clock");
    let expired = u64::try_from(now - 1).expect("deadline");
    assert!(claim.expires_at_unix_ms > expired);
    let mut calls = 0;
    let result = authorized.enter(now, expired, |_| {
        calls += 1;
        DispatchEffect::Dispatched { value: (), dispatch_digest: Digest32::of_bytes(b"late effect"),
            acknowledgement_digest: None }
    });
    assert!(matches!(result, Err(DurableOperationError::StaleLease)));
    assert_eq!(calls, 0);
}
