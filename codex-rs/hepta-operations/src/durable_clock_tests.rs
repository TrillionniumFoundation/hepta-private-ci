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

#[tokio::test]
async fn exact_claim_cannot_erase_a_future_durable_frontier() {
    let directory = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("open");
    let operation = intent(b"exact claim rollback");
    store.prepare_intent(&operation).await.expect("prepare");
    sqlx::query("UPDATE operation_ledger SET updated_at_ms = ?")
        .bind(now_millis().expect("current clock") + 60_000)
        .execute(&store.pool)
        .await
        .expect("persisted future frontier");
    let before = (
        store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("operation before"),
        store
            .outbox_status(
                &operation.destination,
                &operation.scope_id,
                &operation.operation_id,
            )
            .await
            .expect("outbox before"),
    );
    assert!(matches!(
        store
            .claim_operation(
                &operation.scope_id,
                &operation.operation_id,
                &stable_id("worker:exact-clock-rollback"),
                generation(/*value*/ 1),
                Duration::from_secs(30),
            )
            .await,
        Err(DurableOperationError::ClockRollback)
    ));
    assert_eq!(
        (
            store
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("operation after"),
            store
                .outbox_status(
                    &operation.destination,
                    &operation.scope_id,
                    &operation.operation_id,
                )
                .await
                .expect("outbox after"),
        ),
        before
    );
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

#[cfg(unix)]
#[tokio::test]
async fn delayed_effect_entry_rejects_expired_and_adopted_dispatches() {
    enum Delay {
        Expired,
        WriterWait,
        Adopted,
    }
    for delay in [Delay::Expired, Delay::WriterWait, Delay::Adopted] {
        let directory = tempfile::tempdir().expect("tempdir");
        let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
            .await
            .expect("open");
        let operation = intent(b"delayed effect entry");
        store.prepare_intent(&operation).await.expect("prepare");
        let claim = store
            .claim_operation(
                &operation.scope_id,
                &operation.operation_id,
                &stable_id("worker:delayed-entry"),
                generation(/*value*/ 1),
                Duration::from_secs(30),
            )
            .await
            .expect("claim")
            .expect("row");
        let (authority, signed, _authority_dir) =
            authority_fixture(&claim.intent, /*nonce*/ 44);
        let authorized = store
            .authorize_dispatch(&authority, &signed, &claim)
            .await
            .expect("admission");
        let mut writer = store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .expect("writer");
        let expires_at = now_millis().expect("expiry clock") + 1;
        sqlx::query("UPDATE cross_owner_outbox SET lease_until_ms = ?")
            .bind(expires_at)
            .execute(&mut *writer)
            .await
            .expect("shorten lease");
        let mut calls = 0;
        let (result, before) = {
            let mut waiting = std::pin::pin!(store.execute_authorized(authorized, |_| {
                calls += 1;
                DispatchEffect::Dispatched {
                    value: (),
                    dispatch_digest: Digest32::of_bytes(b"must not dispatch"),
                    acknowledgement_digest: None,
                }
            }));
            match delay {
                Delay::Expired => {
                    writer.commit().await.expect("shortened lease");
                    wait_for_clock_after(expires_at).await;
                }
                Delay::WriterWait => {
                    poll_waiter(waiting.as_mut()).await;
                    wait_for_clock_after(expires_at).await;
                    writer.commit().await.expect("release preceding writer");
                }
                Delay::Adopted => {
                    writer.rollback().await.expect("keep original lease");
                    store
                        .adopt_unsettled_generation(
                            &operation.scope_id,
                            &operation.operation_id,
                            generation(/*value*/ 2),
                        )
                        .await
                        .expect("new owner");
                }
            }
            let before = store
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("before denied entry");
            (waiting.await, before)
        };
        assert!(matches!(result, Err(DurableOperationError::StaleLease)));
        assert_eq!(calls, 0);
        assert_eq!(
            store
                .operation(&operation.scope_id, &operation.operation_id)
                .await
                .expect("after denied entry"),
            before
        );
    }
}

#[cfg(unix)]
struct EntryWaitClock {
    calls: std::sync::atomic::AtomicUsize,
    waits: std::sync::atomic::AtomicUsize,
}

#[cfg(unix)]
impl codex_hepta_contracts::AuthorityClock for EntryWaitClock {
    fn now_unix_ms(&self) -> Result<u64, codex_hepta_contracts::AuthorityTrustError> {
        use codex_hepta_contracts::AuthorityClock;
        use std::sync::atomic::Ordering;
        // Construction samples once and claim samples twice. Delay only the
        // final authority check before its synchronous consumer is invoked.
        if self.calls.fetch_add(1, Ordering::SeqCst) == 3 {
            self.waits.fetch_add(1, Ordering::SeqCst);
            std::thread::sleep(Duration::from_millis(750));
        }
        codex_hepta_contracts::SystemAuthorityClock.now_unix_ms()
    }
}

#[cfg(unix)]
#[tokio::test]
async fn effect_entry_checks_lease_after_authority_wait() {
    use std::sync::Arc;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    let directory = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("open");
    let operation = intent(b"consumer lease wait");
    store.prepare_intent(&operation).await.expect("prepare");
    let claim = store
        .claim_operation(
            &operation.scope_id,
            &operation.operation_id,
            &stable_id("worker:consumer-wait"),
            generation(/*value*/ 1),
            Duration::from_secs(30),
        )
        .await
        .expect("claim")
        .expect("row");
    let (_, signed, authority_dir) = authority_fixture(&claim.intent, /*nonce*/ 45);
    let clock = Arc::new(EntryWaitClock {
        calls: AtomicUsize::new(/*v*/ 0),
        waits: AtomicUsize::new(/*v*/ 0),
    });
    let authority = FinalUseAuthority::open_state_dir_with_clock(
        authority_dir.path(),
        "security-owner".to_owned(),
        ed25519_dalek::SigningKey::from_bytes(&[47; 32])
            .verifying_key()
            .to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        clock.clone(),
    )
    .expect("clock-injected authority");
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await
        .expect("admission");
    sqlx::query("UPDATE cross_owner_outbox SET lease_until_ms = ?")
        .bind(now_millis().expect("consumer lease clock") + 500)
        .execute(&store.pool)
        .await
        .expect("expire during authority wait");
    let before = store
        .operation(&operation.scope_id, &operation.operation_id)
        .await
        .expect("before entry");
    let mut calls = 0;
    let result = store
        .execute_authorized(authorized, |_| {
            calls += 1;
            DispatchEffect::Dispatched {
                value: (),
                dispatch_digest: Digest32::of_bytes(b"must not dispatch after authority wait"),
                acknowledgement_digest: None,
            }
        })
        .await;
    assert!(matches!(result, Err(DurableOperationError::StaleLease)));
    assert_eq!(clock.waits.load(Ordering::SeqCst), 1);
    assert_eq!(calls, 0);
    assert_eq!(
        store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("after denied entry"),
        before
    );
}
