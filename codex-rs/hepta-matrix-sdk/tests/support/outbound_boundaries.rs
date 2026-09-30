use super::*;

struct StalledTransport {
    txn_ids: Mutex<Vec<MatrixTransactionId>>,
}

impl MatrixOutboundTransport for StalledTransport {
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a> {
        Box::pin(async move {
            self.txn_ids
                .lock()
                .map_err(|_| MatrixTransportError::Permanent)?
                .push(record.stable_txn_id.clone());
            std::future::pending().await
        })
    }
}

#[tokio::test]
async fn stalled_request_returns_before_reclaim_and_retry_uses_completion_time() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let agent_layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&agent_layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    let transport = StalledTransport {
        txn_ids: Mutex::new(Vec::new()),
    };
    let config = OutboxDispatchConfig {
        lease_ms: 100,
        retry_delay_ms: 500,
        max_retry_delay_ms: 500,
        max_attempts: 3,
        claim_limit: 1,
        idle_poll: Duration::from_millis(10),
    };
    let stats = tokio::time::timeout(
        Duration::from_secs(1),
        dispatch_outbox_once(&store, &transport, &config, &CancellationToken::new(), 100),
    )
    .await??;
    assert_eq!(
        (
            stats.claimed,
            stats.retry_scheduled,
            stats.permanent_failure
        ),
        (1, 1, 0)
    );
    let retry = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("retry record disappeared")?;
    assert!(retry.updated_at_ms >= 199);
    assert_eq!(retry.next_attempt_at_ms, retry.updated_at_ms + 500);
    assert_eq!(retry.state, OutboxState::RetryScheduled);
    assert_eq!(
        *transport
            .txn_ids
            .lock()
            .map_err(|_| "transaction log poisoned")?,
        vec![original.stable_txn_id]
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn cancelled_dispatch_does_not_acquire_a_durable_attempt() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let agent_layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&agent_layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    let transport = FakeTransport::new([Ok(event("$must-not-send")?)]);
    let cancel = CancellationToken::new();
    cancel.cancel();
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &OutboxDispatchConfig::default(),
        &cancel,
        100,
    )
    .await?;
    assert_eq!((stats.claimed, stats.cancelled), (0, true));
    assert_eq!(
        store.outbox_for_txn(&original.stable_txn_id).await?,
        Some(original)
    );
    assert!(transport.txn_ids()?.is_empty());
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn crashed_last_attempt_is_parked_after_reclaim_without_another_network_request() -> TestResult
{
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let agent_layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&agent_layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    let last_attempt = store
        .claim_outbox(/*now_ms*/ 10, /*lease_ms*/ 20, /*limit*/ 1)
        .await?;
    assert_eq!(last_attempt.len(), 1);
    store.close().await;
    let reopened = MatrixDurableStore::open(&agent_layout, MatrixDurableConfig::default()).await?;
    let transport = FakeTransport::new([Ok(event("$forbidden-extra-put")?)]);
    let config = OutboxDispatchConfig {
        max_attempts: 1,
        claim_limit: 1,
        ..OutboxDispatchConfig::default()
    };
    let stats = dispatch_outbox_once(
        &reopened,
        &transport,
        &config,
        &CancellationToken::new(),
        31,
    )
    .await?;
    assert_eq!(
        (
            stats.claimed,
            stats.needs_reconciliation,
            stats.sent,
            stats.permanent_failure
        ),
        (1, 1, 0, 0)
    );
    assert!(transport.txn_ids()?.is_empty());
    let unresolved = reopened.unresolved_outbox(/*limit*/ 10).await?;
    assert_eq!(unresolved.len(), 1);
    assert_eq!(
        (unresolved[0].stable_txn_id.clone(), unresolved[0].attempts),
        (original.stable_txn_id, 2)
    );
    assert!(
        reopened
            .claim_outbox(
                /*now_ms*/ 100_000, /*lease_ms*/ 20, /*limit*/ 1
            )
            .await?
            .is_empty()
    );
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn later_request_rejection_cannot_disprove_an_earlier_lost_acknowledgement() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let agent_layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&agent_layout).await?;
    let original = enqueue_final(&store, &agent_id, 10).await?;
    // The first request may already exist on the homeserver; a later 403 only
    // establishes that the second request was rejected under current credentials.
    let transport = FakeTransport::new([
        Err(MatrixTransportError::Retryable),
        Err(MatrixTransportError::Permanent),
    ]);
    let config = OutboxDispatchConfig {
        claim_limit: 1,
        ..OutboxDispatchConfig::default()
    };
    let cancel = CancellationToken::new();
    let first = dispatch_outbox_once(&store, &transport, &config, &cancel, 100).await?;
    assert_eq!((first.retry_scheduled, first.needs_reconciliation), (1, 0));
    let retry = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("retry record disappeared")?;
    let second = dispatch_outbox_once(
        &store,
        &transport,
        &config,
        &cancel,
        retry.next_attempt_at_ms,
    )
    .await?;
    assert_eq!(
        (second.needs_reconciliation, second.permanent_failure),
        (1, 0)
    );
    let unresolved = store
        .outbox_for_txn(&original.stable_txn_id)
        .await?
        .ok_or("unresolved record disappeared")?;
    assert_eq!(
        (
            unresolved.state,
            unresolved.attempts,
            unresolved.sent_event_id
        ),
        (OutboxState::InFlight, 2, None)
    );
    let markers = store.unresolved_outbox(/*limit*/ 10).await?;
    assert_eq!(markers.len(), 1);
    store.close().await;
    let reopened = MatrixDurableStore::open(&agent_layout, MatrixDurableConfig::default()).await?;
    assert_eq!(reopened.unresolved_outbox(/*limit*/ 10).await?, markers);
    let settled = dispatch_outbox_once(&reopened, &transport, &config, &cancel, 100_000).await?;
    assert_eq!((settled.claimed, transport.txn_ids()?.len()), (0, 2));
    reopened.close().await;
    Ok(())
}

struct RevokeAfterFirstTransport {
    store: MatrixDurableStore,
    txn_ids: Mutex<Vec<MatrixTransactionId>>,
}

impl MatrixOutboundTransport for RevokeAfterFirstTransport {
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a> {
        Box::pin(async move {
            self.txn_ids
                .lock()
                .map_err(|_| MatrixTransportError::Permanent)?
                .push(record.stable_txn_id.clone());
            tokio::time::sleep(Duration::from_millis(20)).await;
            self.store
                .apply_sync_decision_v2(&MatrixSyncDecisionV2::Commit {
                    batch: MatrixSyncBatchV2 {
                        schema_version: 2,
                        operation_id: "leave-while-first-send-in-flight".to_string(),
                        checkpoint_revision: 1,
                        checkpoint_generation: 1,
                        expected_next_batch: None,
                        next_batch: "left-room".to_string(),
                        observed_at_ms: 130,
                        mutations: vec![MatrixSyncMutationV2 {
                            source_event_id: event("$room-left")
                                .map_err(|_| MatrixTransportError::Permanent)?,
                            room_id: record.room_id.clone(),
                            sender: user(AGENT_MXID)
                                .map_err(|_| MatrixTransportError::Permanent)?,
                            binding_revision: 1,
                            generation: 1,
                            origin_server_ts_ms: 129,
                            received_at_ms: 130,
                            body: MatrixSyncMutationBodyV2::RoomLeave {
                                departed_user_id: user(AGENT_MXID)
                                    .map_err(|_| MatrixTransportError::Permanent)?,
                            },
                        }],
                    },
                })
                .await
                .map_err(|_| MatrixTransportError::Permanent)?;
            event("$first-send-ack").map_err(|_| MatrixTransportError::Permanent)
        })
    }
}

#[tokio::test]
async fn room_revocation_during_first_send_prevents_later_batch_send() -> TestResult {
    let temp = TempDir::new()?;
    let agent_id = agent(FIRST_AGENT)?;
    let agent_layout = layout(&temp, &agent_id)?;
    let store = prepared_store(&agent_layout).await?;
    let first = enqueue_final(&store, &agent_id, 10).await?;
    let later_txn = transaction_id("later-final", 1)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: "later-final".to_string(),
            revision: 1,
            txn_id: later_txn.clone(),
            room_id: room(ALLOWED_ROOM)?,
            kind: OutboxKind::Final,
            payload: b"must not send after leave".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 11,
        })
        .await?;
    let transport = RevokeAfterFirstTransport {
        store: store.clone(),
        txn_ids: Mutex::new(Vec::new()),
    };
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &OutboxDispatchConfig::default(),
        &CancellationToken::new(),
        100,
    )
    .await?;
    assert_eq!((stats.claimed, stats.sent), (1, 1));
    assert_eq!(
        *transport
            .txn_ids
            .lock()
            .map_err(|_| "transaction log poisoned")?,
        vec![first.stable_txn_id]
    );
    let later = store
        .outbox_for_txn(&later_txn)
        .await?
        .ok_or("later outbox missing")?;
    assert_eq!((later.state, later.attempts), (OutboxState::Pending, 0));
    store.close().await;
    Ok(())
}
