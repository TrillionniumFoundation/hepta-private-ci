//! Cancellation after the original prepared-journal fsync and before its
//! original QueueStore call. No preparation, queue or effect owner is mocked.

use pretty_assertions::assert_eq;

use super::*;

#[derive(Debug, Eq, PartialEq)]
struct OriginalJournalObservation {
    length: u64,
    #[cfg(unix)]
    bytes: Vec<u8>,
}

fn original_journal_observation(fixture: &ObjectiveFixture) -> Result<OriginalJournalObservation> {
    let path = fixture.base.state.identity().home_root.join("objective-run-start-v1/journal.bin");
    // Windows preserves the original journal's exclusive read lock. Every
    // platform checks that no bytes were appended together with the exact
    // original records/opaque receipts below; Unix also compares all bytes.
    Ok(OriginalJournalObservation {
        length: fs::metadata(&path)?.len(),
        #[cfg(unix)]
        bytes: fs::read(path)?,
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_objective_prepared_fsync_then_dropped_relay_enqueues_original_client_once() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::HoldBeforeQueue).await?;
    {
        // The actual submit future has completed seven-owner preparation and
        // returned from append_prepared/fsync before reaching this transport.
        // Drop that future at the observable boundary; do not synthesize a
        // prepared record, queue receipt or coordinator transition.
        let submit = fixture.submit(fixture.request.clone());
        tokio::pin!(submit);
        tokio::select! {
            result = &mut submit => {
                anyhow::bail!("submit left the original pre-queue failpoint: {result:?}");
            }
            reached = tokio::time::timeout(Duration::from_secs(15), fixture.queue.wait_until_held()) => {
                reached.context("original prepared-to-queue failpoint was not reached")?;
            }
        }
    }
    let record = fixture.host.original_record(&fixture.request.body.run_id)?;
    let prepared = fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?
        .context("original fsynced preparation disappeared after submit cancellation")?;
    assert_eq!(prepared.original(), &record);
    let before_journal = original_journal_observation(&fixture)?;
    let input = fixture.base.state.canonical_queued_input(&record)?;
    assert_eq!(fixture.base.state.native_run_receipt(&input.run_id)?.phase, RunPhase::ContextAttached);
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.queue.reconciles.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 0, 0, 0));
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    assert!(server.received_requests().await.context("model HTTP capture")?.is_empty());

    let replay = fixture.submit(fixture.request.clone()).await?;
    assert!(replay.idempotent);
    assert_eq!(replay.disposition, "canonical_queue_accepted");
    let turn_id = completed_turn(&fixture.core).await?;
    assert_eq!(fixture.queue.reconciles.load(Ordering::SeqCst), 1,
        "the cancelled transport must leave exactly one actual original QueueStore call to perform");
    let original = NativeCheckpointBinding {
        thread_id: fixture.core.session_configured.thread_id, turn_id,
        operation_id: record.snapshot.run_id.to_string(), generation: record.snapshot.generation,
        lease_id: fixture.base.writer.lease_id().to_owned(),
    };
    let session = fixture.core.thread_store.open_native_checkpoint(original.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let NativeCheckpointLoad::Present(stored) = fixture.core.thread_store.load_native_checkpoint(&session).await? else {
        anyhow::bail!("replayed original client has no original ThreadStore checkpoint");
    };
    let (anchor, state) = crate::native_turn_checkpoint::decode(&stored.state.payload, &original)?;
    let queue = anchor.queue.as_ref().context("original queue binding")?;
    assert_eq!(anchor.checkpoint, original);
    assert_eq!((&queue.client_id, &queue.payload_sha256), (&input.client_user_message_id, &input.input_payload_sha256));
    assert_eq!((state.model_calls, state.tool_calls, state.pending_model.is_none(), state.pending_tool.is_none(),
        state.final_answer.as_deref()), (1, 0, true, true, Some("native owner complete")));

    // Successful execution adds its actual Closed fact to the original
    // journal. Replaying that completed run may only observe the original
    // persisted client, without another journal frame, input or execution.
    let completed_journal = original_journal_observation(&fixture)?;
    assert!(completed_journal.length > before_journal.length,
        "the original terminal decision must remain durable");
    assert!(!fixture.base.state.native_continuation_allowed(&input.run_id)?);
    let completed_replay = fixture.submit(fixture.request.clone()).await?;
    assert!(completed_replay.idempotent);
    assert_eq!((&completed_replay.publication_digest, &completed_replay.chain_digest),
        (&replay.publication_digest, &replay.chain_digest),
        "observation must retain the original publication receipt, not the later journal head");
    assert_eq!(fixture.host.original_record(&input.run_id)?, record);
    assert_eq!(fixture.host.observe_committed_prepared(&input.run_id)?, Some(prepared));
    assert_eq!(original_journal_observation(&fixture)?, completed_journal);
    assert_eq!(fixture.core.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(stored));
    assert_eq!(*fixture.queue.modes.lock().expect("modes"), vec![ThreadQueueReconcileMode::AllowIfAbsent,
        ThreadQueueReconcileMode::AllowIfAbsent, ThreadQueueReconcileMode::ReconcileOnly]);
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.queue.reconciles.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 2, 1, 1));
    assert_eq!(fixture.base.state.native_run_receipt(&input.run_id)?.phase, RunPhase::Succeeded);
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    let history = fixture.core.thread_store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: fixture.core.session_configured.thread_id, include_archived: false,
    }).await?;
    let inputs = history.items.iter().filter(|item| matches!(item,
        RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
            TurnItem::UserMessage(message) if message.client_id.as_deref() == Some(input.client_user_message_id.as_str())))).count();
    let outputs = history.items.iter().filter(|item| matches!(item,
        RolloutItem::ResponseItem(envelope) if matches!(&envelope.item,
            codex_protocol::models::ResponseItem::Message { role, .. } if role == "assistant"))).count();
    let requests = server.received_requests().await.context("model HTTP capture")?;
    assert_eq!((inputs, outputs, requests.len()), (1, 1, 1));
    let operation = requests[0].headers.get("idempotency-key").context("original operation header")?.to_str()?;
    assert_eq!(fixture.base.writer.status(operation).await?, LocalOutcomeState::Committed);
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_objective_run_start_only_replay_never_repeats_owner_preparation() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::None).await?;
    fixture.owners.fail_before_prepare.store(true, Ordering::SeqCst);
    let error = fixture.submit(fixture.request.clone()).await
        .expect_err("fixture must stop after original RunStart publication");
    assert!(error.to_string().contains("fixture stopped before original canonical preparation"), "unexpected failure: {error:#}");
    let original = fixture.host.original_record(&fixture.request.body.run_id)?;
    assert!(original.authenticated_payload.is_some());
    assert!(fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?.is_none());
    assert!(fixture.base.state.native_run_receipt(&fixture.request.body.run_id).is_err());
    let before_journal = original_journal_observation(&fixture)?;
    // Preparation would now succeed if invoked. The durable absence must keep
    // the retry held instead of silently rebuilding the seven-owner outcome.
    fixture.owners.fail_before_prepare.store(false, Ordering::SeqCst);
    let replay = fixture.submit(fixture.request.clone()).await
        .expect_err("RunStart alone must not authorize another preparation or queue row");
    assert!(replay.to_string().contains("original canonical preparation is not durable; outcome remains unknown"),
        "unexpected held reason: {replay:#}");
    assert_eq!(fixture.host.original_record(&fixture.request.body.run_id)?, original);
    assert!(fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?.is_none());
    assert!(fixture.base.state.native_run_receipt(&fixture.request.body.run_id).is_err());
    assert_eq!(original_journal_observation(&fixture)?, before_journal);
    assert!(fixture.queue.modes.lock().expect("modes").is_empty());
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.queue.reconciles.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 0, 0, 0));
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    assert!(server.received_requests().await.context("model HTTP capture")?.is_empty());
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stopped_original_replay_observes_missing_queue_without_reopening_admission() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::BeforeQueue).await?;
    assert!(fixture.submit(fixture.request.clone()).await.is_err());
    let run_id = fixture.request.body.run_id.clone();
    let record = fixture.host.original_record(&run_id)?;
    let prepared = fixture.host.observe_committed_prepared(&run_id)?.context("original prepared audit fact")?;
    let input = fixture.base.state.canonical_queued_input(&record)?;
    let admitted = fixture.base.state.native_run_receipt(&run_id)?;
    assert_eq!(admitted.phase, RunPhase::ContextAttached);

    // Cancel through the real original Agentd control reducer and journal.
    // No checkpoint, terminal result, or stop fact is fabricated by the test.
    fixture.base.state.response(/*request_id*/ 901, fixture.base.state.identity().spawn_generation,
        crate::AgentdMethod::RunCancel {
            run_id: run_id.clone(), expected_revision: admitted.revision,
            reason: "cancel_before_original_queue".to_owned(),
        }).await?;
    let cancelled = fixture.base.state.native_run_receipt(&run_id)?;
    assert_eq!(cancelled.phase, RunPhase::Cancelled);
    assert_eq!(cancelled.cancel_reason.as_deref(), Some("cancel_before_original_queue"));
    assert!(!fixture.base.state.native_continuation_allowed(&run_id)?);
    let stopped_journal = original_journal_observation(&fixture)?;

    for _ in 0..2 {
        let held = fixture.submit(fixture.request.clone()).await
            .expect_err("a stopped original run cannot create its missing queue input");
        assert!(held.to_string().contains("queue has no matching durable admission"), "held reason: {held:#}");
        assert_eq!(fixture.base.state.native_run_receipt(&run_id)?, cancelled);
        assert_eq!(original_journal_observation(&fixture)?, stopped_journal);
    }
    assert!(fixture.base.state.load_canonical_prepared(&run_id).is_err(),
        "the audit receipt cannot restore fresh canonical preparation");
    assert!(crate::objective_queue_relay::relay(&fixture.base.state, &record,
        ThreadQueueReconcileMode::AllowIfAbsent, fixture.queue.as_ref()).await.is_err(),
        "a caller cannot bypass the stopped-run fence by choosing a creating queue mode");

    let mut changed = fixture.request.clone();
    changed.sequence += 1;
    changed.body.queued_input.as_mut().context("original queued text")?.text.push_str(" changed after stop");
    fixture.sign(&mut changed)?;
    let rejected = fixture.submit(changed).await.expect_err("a fresh signature cannot replace a stopped original run");
    assert!(matches!(rejected.downcast_ref::<AgentdError>(), Some(AgentdError::GenerationFenced(_))),
        "changed stopped replay must remain generation fenced: {rejected:#}");

    assert_eq!(fixture.host.original_record(&run_id)?, record);
    assert_eq!(fixture.host.observe_committed_prepared(&run_id)?, Some(prepared));
    assert_eq!(fixture.base.state.native_run_receipt(&run_id)?, cancelled);
    assert_eq!(original_journal_observation(&fixture)?, stopped_journal);
    assert_eq!(*fixture.queue.modes.lock().expect("modes"), vec![ThreadQueueReconcileMode::AllowIfAbsent,
        ThreadQueueReconcileMode::ReconcileOnly, ThreadQueueReconcileMode::ReconcileOnly]);
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    assert!(fixture.base.queue.observe_persisted_client_binding(fixture.core.session_configured.thread_id,
        input.client_user_message_id, input.input_payload_sha256).await?.is_none());
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.queue.reconciles.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 2, 0, 0));
    assert!(server.received_requests().await.context("model HTTP capture")?.is_empty());
    fixture.shutdown().await
}
