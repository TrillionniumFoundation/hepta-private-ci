use super::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

async fn authorize(
    store: &DurableOperationStore,
    nonce: u8,
) -> TestResult<(AuthorizedDispatch, tempfile::TempDir)> {
    let operation = intent(b"effect entry");
    store.prepare_intent(&operation).await?;
    let claim = store
        .claim_operation(
            &operation.scope_id,
            &operation.operation_id,
            &stable_id("worker:effect-entry"),
            generation(/*value*/ 1),
            Duration::from_secs(60),
        )
        .await?
        .ok_or("claim prepared operation")?;
    let (authority, signed, directory) = authority_fixture(&operation, nonce);
    let authorized = store
        .authorize_dispatch(&authority, &signed, &claim)
        .await?;
    Ok((authorized, directory))
}

#[tokio::test]
async fn recovered_dispatch_cannot_enter_using_an_older_authorization() -> TestResult {
    let directory = tempfile::tempdir()?;
    let store = DurableOperationStore::open(&directory.path().join("source.sqlite3")).await?;
    let (authorized, _authority_directory) = authorize(&store, /*nonce*/ 71).await?;
    let claim = authorized.claim().clone();
    // Shorten the fixture's lease within the schema contract, let the actual
    // clock expire it, then run the real owner recovery transition.
    sqlx::query("UPDATE cross_owner_outbox SET lease_until_ms = updated_at_ms + 1")
        .execute(&store.pool)
        .await?;
    tokio::time::sleep(Duration::from_millis(5)).await;
    store.recover_expired_leases().await?;
    let before = store
        .operation(&claim.intent.scope_id, &claim.intent.operation_id)
        .await?;
    let mut calls = 0;
    let result = store
        .execute_authorized(authorized, |_| {
            calls += 1;
            DispatchEffect::Dispatched {
                value: (),
                dispatch_digest: Digest32::of_bytes(b"must not enter"),
                acknowledgement_digest: None,
            }
        })
        .await;
    assert!(matches!(result, Err(DurableOperationError::StaleLease)));
    assert_eq!(calls, 0);
    assert_eq!(
        store
            .operation(&claim.intent.scope_id, &claim.intent.operation_id)
            .await?,
        before
    );
    assert_eq!(
        before.ok_or("recovered operation")?.state,
        DurableOperationState::Indeterminate
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn a_recorded_dispatch_cannot_reenter_the_adapter() -> TestResult {
    let directory = tempfile::tempdir()?;
    let store = DurableOperationStore::open(&directory.path().join("source.sqlite3")).await?;
    let (authorized, _authority_directory) = authorize(&store, /*nonce*/ 72).await?;
    let before = store
        .record_dispatch(
            authorized.claim(),
            Digest32::of_bytes(b"already dispatched"),
        )
        .await?;
    let mut calls = 0;
    assert!(matches!(
        store
            .execute_authorized(authorized, |_| {
                calls += 1;
                DispatchEffect::NotDispatched {
                    value: (),
                    reason_digest: Digest32::of_bytes(b"must not enter"),
                    retry_after: Duration::ZERO,
                }
            })
            .await,
        Err(DurableOperationError::InvalidTransition {
            from: DurableOperationState::Dispatched,
            to: "execute_authorized",
        })
    ));
    assert_eq!(calls, 0);
    assert_eq!(
        store
            .operation(&before.intent.scope_id, &before.intent.operation_id)
            .await?,
        Some(before)
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn adapter_entry_excludes_concurrent_recovery_but_allows_wal_reads() -> TestResult {
    let directory = tempfile::tempdir()?;
    let store = DurableOperationStore::open(&directory.path().join("source.sqlite3")).await?;
    let (authorized, _authority_directory) = authorize(&store, /*nonce*/ 73).await?;
    let claim = authorized.claim().clone();
    let competitor_path = store.path().to_path_buf();
    let competitor_claim = claim.clone();
    let (ready_tx, ready_rx) = tokio::sync::oneshot::channel();
    let (enter_tx, enter_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = tokio::sync::oneshot::channel();
    let (observed_tx, observed_rx) = std::sync::mpsc::sync_channel(1);
    let competitor_thread = std::thread::spawn(move || {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("competitor runtime");
        runtime.block_on(async {
            // Create, use and close the pool on one live runtime. Returning a
            // SQLx connection can schedule runtime work; the effect callback
            // must not block the runtime that owns those return tasks.
            let competitor = DurableOperationStore::open(&competitor_path)
                .await
                .expect("competitor store");
            let mut connections = Vec::new();
            for _ in 0..competitor.pool.options().get_max_connections() {
                let mut connection = competitor.pool.acquire().await.expect("connection");
                sqlx::query("PRAGMA busy_timeout = 0")
                    .execute(&mut *connection)
                    .await
                    .expect("zero contention wait");
                connections.push(connection);
            }
            drop(connections);
            ready_tx.send(()).expect("fixture ready");
            enter_rx.await.expect("effect entered");
            let recovery = competitor.recover_expired_leases().await;
            assert!(
                matches!(
                    &recovery,
                    Err(DurableOperationError::Unavailable(message))
                        if message.contains("locked")
                ),
                "competing recovery must reach SQLite contention: {recovery:?}"
            );
            let observed = competitor
                .operation(
                    &competitor_claim.intent.scope_id,
                    &competitor_claim.intent.operation_id,
                )
                .await
                .expect("WAL read")
                .expect("source operation");
            assert_eq!(observed.state, DurableOperationState::Dispatching);
            assert_eq!(observed.writer_fence, competitor_claim.fence);
            observed_tx.send(()).expect("WAL observation complete");
            // Dropping the sender on an owner error/cancellation also wakes us;
            // the worker never waits for a release that can no longer arrive.
            release_rx.await.expect("effect transaction released");
            competitor
                .recover_expired_leases()
                .await
                .expect("same competitor recovers after entry");
            competitor.close().await;
        });
    });
    ready_rx.await?;
    store
        .execute_authorized(authorized, |_| {
            enter_tx.send(()).expect("start competing recovery");
            observed_rx
                .recv_timeout(Duration::from_secs(10))
                .expect("locked recovery and concurrent WAL read");
            DispatchEffect::Dispatched {
                value: (),
                dispatch_digest: Digest32::of_bytes(b"entered under current fence"),
                acknowledgement_digest: Some(Digest32::of_bytes(b"acknowledged")),
            }
        })
        .await?;
    release_tx.send(()).expect("release competing recovery");
    competitor_thread.join().expect("competing recovery");
    let after = store
        .operation(&claim.intent.scope_id, &claim.intent.operation_id)
        .await?
        .ok_or("operation")?;
    assert_eq!(after.state, DurableOperationState::Dispatched);
    store.close().await;
    Ok(())
}
