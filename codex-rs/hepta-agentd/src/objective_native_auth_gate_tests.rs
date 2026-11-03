//! Changes after the real resolver/preparation and signed grant, before the
//! physical model POST. The original checkpoint and writer keep the unknown
//! operation; a denied entrance never consumes its FinalUse nonce.

use pretty_assertions::assert_eq;

use super::*;

pub(super) async fn wait_for_held_original_turn(test: &TestCodex, turn_id: &str, wait: Duration) -> Result<()> {
    let observed = core_test_support::wait_for_event_with_timeout(&test.codex,
        |event| matches!(event, EventMsg::Error(_) | EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_)), wait).await;
    ensure!(matches!(&observed, EventMsg::Error(error) if !error.message.is_empty()),
        "denied original entry created a terminal outcome: {observed:?}");
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if test.codex.recovery_epoch_if_idle(turn_id).await.is_some() { break; }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await.context("original Core did not flush/release its readable held tail")?;
    // These fixtures have no compaction. Read the original paginated owner;
    // the recovery-epoch witness above still uses the strict full-tail scan.
    let history = test.thread_store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: test.session_configured.thread_id, include_archived: false,
    }).await?;
    assert!(history.items.iter().any(|item| matches!(item,
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == turn_id)));
    assert!(history.items.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnComplete(event)) if event.turn_id == turn_id)));
    assert!(history.items.iter().all(|item| !matches!(item,
        RolloutItem::EventMsg(EventMsg::TurnAborted(event)) if event.turn_id.as_deref() == Some(turn_id))));
    Ok(())
}

async fn rejected_at_physical_entry(fixture: &ObjectiveFixture, server: &MockServer,
    expected_reason: &str) -> Result<()> {
    // Dispatch is asynchronous. A route change may also make the producer's
    // post-response check return held; the original durable turn is observed
    // in either case and is never submitted again here.
    let submitted = fixture.submit(fixture.request.clone()).await;
    let started = tokio::time::timeout(Duration::from_secs(4), wait_for_event_match(&fixture.core.codex, |event| {
        match event { EventMsg::TurnStarted(started) => Some(started.turn_id.clone()), _ => None }
    })).await.with_context(|| format!("original turn did not start; ingress: {submitted:?}"))?;
    wait_for_held_original_turn(&fixture.core, &started, Duration::from_secs(15)).await?;
    let record = fixture.host.original_record(&fixture.request.body.run_id)?;
    let binding = NativeCheckpointBinding {
        thread_id: fixture.core.session_configured.thread_id, turn_id: started,
        operation_id: record.snapshot.run_id.to_string(), generation: record.snapshot.generation,
        lease_id: fixture.base.writer.lease_id().to_owned(),
    };
    let session = fixture.core.thread_store.open_native_checkpoint(binding.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let NativeCheckpointLoad::Present(checkpoint) = fixture.core.thread_store.load_native_checkpoint(&session).await? else {
        anyhow::bail!("the rejected entry lost its original ThreadStore checkpoint");
    };
    let (anchor, turn) = crate::native_turn_checkpoint::decode(&checkpoint.state.payload, &binding)?;
    let error = turn.last_error.as_deref().context("physical rejection must retain its concrete error")?;
    ensure!(error.contains("durable run-start authentication is not current") && error.contains(expected_reason),
        "wrong physical gate rejected the entry: {error}");
    let request = turn.pending_model.as_ref().context("original pending operation")?;
    assert_eq!((turn.model_calls, turn.final_answer.is_none(), turn.provider_response_id.is_none()), (1, true, true));
    assert_eq!(anchor.checkpoint, binding);
    assert_eq!(fixture.base.state.native_run_receipt(&record.snapshot.run_id.to_string())?.phase, RunPhase::Indeterminate);
    assert!(record.admission.deadline_unix_micros / 1_000 > now_ms()?, "this must not be a run-deadline failure");
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if fixture.base.writer.status(&request.operation_id).await? == LocalOutcomeState::Indeterminate {
                return Ok::<_, anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await??;
    let original = fixture.base.writer.resolve_operation_request(&request.operation_id,
        fixture.base.native.model.destination_id()).await?;
    assert_eq!((original.occurrence_key.as_str(), original.payload_json.as_bytes()),
        (request.operation_id.as_str(), request.body.as_slice()));
    assert_eq!(fixture.core.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(checkpoint));
    assert_eq!(fixture.host.original_record(&record.snapshot.run_id.to_string())?, record);
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.base.issuer.grants.load(Ordering::SeqCst),
        fixture.base.final_use.capacity()?.used_nonces), (1, 1, 0));
    assert!(server.received_requests().await.context("model HTTP capture")?.is_empty());
    assert_eq!(*fixture.queue.modes.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?, vec![ThreadQueueReconcileMode::AllowIfAbsent]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_objective_revocation_and_key_rotation_after_grant_stop_model_entry() -> Result<()> {
    for (revoked, key_epoch, reason) in [(true, 1, "Revoked"), (false, 2, "IssuerMismatch")] {
        let server = provider().await;
        let fixture = ObjectiveFixture::new(&server, ReplyFault::None).await?;
        fixture.change_trust_at_grant(revoked, key_epoch)?;
        tokio::time::timeout(Duration::from_secs(10), rejected_at_physical_entry(&fixture, &server, reason)).await??;
        fixture.shutdown().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_objective_ttl_expiring_after_grant_stops_model_entry_without_nonce_use() -> Result<()> {
    tokio::time::timeout(Duration::from_secs(20), async {
        let server = provider().await;
        // Only this fixture waits for an actual ten-second AuthBus TTL. The
        // product agent budgets and the original five-minute run deadline do
        // not change. The test's model wait must not mask the final auth gate.
        let mut native_agent = agent();
        native_agent.limits.model_timeout = Duration::from_secs(15);
        let mut fixture = ObjectiveFixture::with_agent(&server, ReplyFault::None, native_agent).await?;
        let expires = now_ms()? + 10_000;
        let mut request = fixture.request.clone();
        request.expires_at_ms = expires;
        fixture.sign(&mut request)?;
        fixture.request = request;
        let reached = Arc::new(AtomicBool::new(false));
        let observed = reached.clone();
        *fixture.base.issuer.before_grant_return.lock().expect("issuer callback") = Some(Box::new(move || {
            let entered = crate::authbus_ingress::now_ms()?;
            if entered >= expires {
                return Err(AgentdError::Invalid("test missed the pre-expiry physical-entry window".to_owned()));
            }
            observed.store(true, Ordering::SeqCst);
            // This is a bounded independent issuer callback. It neither
            // modifies the original signed record nor changes any clock.
            std::thread::sleep(Duration::from_millis(expires - entered + 1));
            Ok(())
        }));
        let result = rejected_at_physical_entry(&fixture, &server, "Expired").await;
        ensure!(reached.load(Ordering::SeqCst), "test never reached the original pre-expiry issuer callback");
        result?;
        fixture.shutdown().await
    }).await.context("physical TTL qualification exceeded its twenty-second test bound")?
}
