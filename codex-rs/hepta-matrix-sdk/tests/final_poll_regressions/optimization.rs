use super::*;
use codex_hepta_matrix_store::MatrixDispatchAttemptEventKind;
use codex_hepta_matrix_store::OutboxState;
use pretty_assertions::assert_eq;

struct QueueInspectingTransport {
    store: MatrixDurableStore,
    ids: Vec<MatrixTransactionId>,
    cancel: Option<CancellationToken>,
}

impl MatrixOutboundTransport for QueueInspectingTransport {
    fn identity(&self) -> Result<MatrixOutboundIdentity, MatrixTransportError> {
        Ok(MatrixOutboundIdentity {
            homeserver_id: "https://example.test".to_string(),
            matrix_user_id: "@agent:example.test".to_string(),
            device_id: "DEVICE".to_string(),
            session_generation: 1,
        })
    }

    fn send<'a>(
        &'a self,
        record: &'a OutboxRecord,
        _seal: MatrixRawSendSeal,
    ) -> MatrixSendFuture<'a> {
        Box::pin(async move {
            for id in &self.ids {
                let other = self
                    .store
                    .outbox_for_txn(id)
                    .await
                    .map_err(|_| MatrixTransportError::ResponseLost)?
                    .ok_or(MatrixTransportError::ResponseLost)?;
                if other.outbox_id > record.outbox_id {
                    // These assertions execute while the current transport is
                    // pending, not after its later leases could have expired.
                    assert_eq!(other.attempts, 0);
                    assert_eq!(other.lease_until_ms, None);
                }
            }
            for _ in 0..4 {
                tokio::task::yield_now().await;
            }
            if let Some(cancel) = &self.cancel {
                cancel.cancel();
                return std::future::pending().await;
            }
            MatrixEventId::parse(format!("$jit-{}", record.outbox_id))
                .map_err(|_| MatrixTransportError::ResponseLost)
        })
    }
}

#[tokio::test]
async fn queued_messages_have_no_speculative_lease_and_pass_limit_is_preserved() -> TestResult {
    let (_temp, store, ids) = fixture(/*count*/ 3).await?;
    let authority = Authorizer::new()?;
    let transport = QueueInspectingTransport {
        store: store.clone(),
        ids: ids.clone(),
        cancel: None,
    };
    let configuration = OutboxDispatchConfig {
        claim_limit: 2,
        ..config()
    };
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &configuration,
        &CancellationToken::new(),
        now_ms()?,
    )
    .await?;
    assert_eq!(stats.claimed, 2);
    assert_eq!(stats.entered_attempts, 2);
    assert_eq!(stats.claim_to_first_poll_samples, 2);
    assert_eq!(stats.payload_digest_checks, 2);
    assert!(stats.transport_polls > stats.payload_digest_checks);
    assert!(stats.dynamic_checks >= stats.transport_polls);
    let queued = store
        .outbox_for_txn(&ids[2])
        .await?
        .ok_or("third message missing")?;
    assert_eq!(queued.attempts, 0);
    assert_eq!(queued.state, OutboxState::Pending);
    assert_eq!(queued.lease_until_ms, None);
    let next = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &configuration,
        &CancellationToken::new(),
        now_ms()?,
    )
    .await?;
    assert_eq!(next.claimed, 1);
    assert_eq!(next.transport_accepted, 1);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn cancel_after_entry_keeps_current_unknown_without_touching_later_messages() -> TestResult {
    let (_temp, store, ids) = fixture(/*count*/ 3).await?;
    let authority = Authorizer::new()?;
    let cancel = CancellationToken::new();
    let transport = QueueInspectingTransport {
        store: store.clone(),
        ids: ids.clone(),
        cancel: Some(cancel.clone()),
    };
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config(),
        &cancel,
        now_ms()?,
    )
    .await?;
    assert!(stats.cancelled);
    assert_eq!(stats.claimed, 1);
    assert_eq!(stats.entered_attempts, 1);
    assert_eq!(stats.pre_entry_failures, 0);
    assert_eq!(stats.indeterminate, 1);
    let events = store.dispatch_attempt_events(&ids[0]).await?;
    assert!(events.iter().all(|event| !matches!(
        event.event_kind,
        MatrixDispatchAttemptEventKind::Canceled | MatrixDispatchAttemptEventKind::Revoked
    )));
    for id in &ids[1..] {
        assert!(store.dispatch_attempt_events(id).await?.is_empty());
        assert_eq!(
            store
                .outbox_for_txn(id)
                .await?
                .ok_or("queued message missing")?
                .attempts,
            0
        );
    }
    store.close().await;
    Ok(())
}
