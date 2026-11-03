//! Original control ACKs survive real Agentd/Objective-journal replacement.
//! Core is shut down only after its technical held task is idle. The same
//! writer, FinalUse, Queue and ThreadStore remain; this is not an OS crash.

use super::*;
use pretty_assertions::assert_eq;

struct ReopenedObjective {
    base: Fixture,
    live: LiveThread,
    _host: Arc<ObjectiveRuntimeHost>,
}

async fn control(state: &AgentdState, method: crate::AgentdMethod) -> Result<crate::AgentRunReceipt> {
    let reply = state.response(901, state.identity().spawn_generation, method).await?;
    match reply.payload {
        crate::AgentdPayload::RunReceipt(receipt) => Ok(receipt),
        crate::AgentdPayload::RunCancellation(cancel) => Ok(cancel.receipt),
        other => anyhow::bail!("original control did not acknowledge a lifecycle decision: {other:?}"),
    }
}

async fn reopen(fixture: ObjectiveFixture, anchor: &NativeTurnAnchorV1,
    native_agent: NativeAgent) -> Result<ReopenedObjective> {
    let ObjectiveFixture { mut base, core, queue, host, .. } = fixture;
    let thread_store = core.thread_store.clone();
    let rollout_path = core.codex.rollout_path();
    let metadata = ThreadPersistenceMetadata { cwd: Some(core.config.cwd.to_path_buf()),
        model_provider: core.config.model_provider_id.clone(), memory_mode: ThreadMemoryMode::Disabled };
    // An idle technical hold has no task to cancel. Normal shutdown closes the
    // original history writer; it must not manufacture a terminal checkpoint.
    core.codex.shutdown_and_wait().await?;
    drop(core);
    let old = base.state;
    let authbus = old.authbus.get().cloned().context("original AuthBus")?;
    let runner = old.intelligence_product.get().cloned().context("original seven-owner runner")?;
    let invocation = old.intelligence_invocation.get().cloned().context("original invocation provider")?;
    let stopped_state = Arc::downgrade(&old);
    let stopped_journal = Arc::downgrade(&host);
    drop(host); drop(old);
    ensure!(stopped_state.upgrade().is_none() && stopped_journal.upgrade().is_none(),
        "both old Agentd and original Objective journal must actually be dropped");
    let identity = base._config.identity().clone();
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(identity.fleet_root.clone())?)?;
    let state = Arc::new(AgentdState::new(identity.clone(), registry, 32)?);
    ensure!(state.native_run_receipt(&anchor.checkpoint.operation_id).is_err(), "new coordinator was not empty");
    let CognitiveRuntime::Available(store) = base.native.host.cognitive_runtime() else {
        anyhow::bail!("same original writer owner unavailable");
    };
    state.attach_cognitive_store(store)?;
    state.mark_runtime_prerequisites_ready()?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    ensure!(state.authbus.set(authbus).is_ok() && state.intelligence_product.set(runner).is_ok()
        && state.intelligence_invocation.set(invocation).is_ok(), "original owners already installed");
    let mut reopened = ObjectiveRuntimeHost::open(&identity, &identity.home_root.join("objective-profile.json"))?;
    reopened.queue_transport = queue;
    let host = Arc::new(reopened);
    ensure!(state.objective_runtime.set(host.clone()).is_ok(), "original journal already installed");
    base.native.gate = Arc::new(NativeEntryGate { state: Arc::downgrade(&state),
        policy_generation: base.native.gate.policy_generation });
    let native = Arc::new(AgentdNativeHost { gate: base.native.gate.clone(), host: base.native.host.clone(),
        model: base.native.model.clone(), runtime: base.native.runtime.clone(), compiler: base.native.compiler.clone() });
    NativeHostedRuntimeConfig::CanonicalObjective { agent: Arc::new(native_agent), scope: base.scope.clone() }
        .attach(&state, native)?;
    base.state = state;
    ensure!(Arc::ptr_eq(&base.writer, &base.native.host.writer()), "cold owner replaced its original writer");
    let history = thread_store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: anchor.checkpoint.thread_id, include_archived: false,
    }).await?;
    let live = LiveThread::resume(thread_store, ThreadHistoryMode::Paginated, ResumeThreadParams {
        thread_id: anchor.checkpoint.thread_id, rollout_path, history: Some(history.items.into()),
        include_archived: false, metadata,
    }).await?;
    Ok(ReopenedObjective { base, live, _host: host })
}

async fn checkpoint(fixture: &ObjectiveFixture, binding: &NativeCheckpointBinding) -> Result<StoredNativeCheckpoint> {
    let session = fixture.core.thread_store.open_native_checkpoint(binding.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    match fixture.core.thread_store.load_native_checkpoint(&session).await? {
        NativeCheckpointLoad::Present(record) => Ok(record),
        _ => anyhow::bail!("original checkpoint missing"),
    }
}

async fn deny_fresh(cold: &ReopenedObjective, anchor: &NativeTurnAnchorV1,
    receipt: &RunReceipt) -> Result<()> {
    ensure!(!matches!(cold.base.state.load_canonical_prepared(&receipt.run_id), Ok(Some(_))),
        "accepted lifecycle decision reopened canonical preparation");
    let policy = codex_hepta_types::Generation::new(anchor.execution.as_ref().context("original policy")?.policy_generation)?;
    let admission = cold.base.native.admission_with_policy(anchor.checkpoint.clone(), cold.base.scope.clone(), policy, receipt)?;
    ensure!(admission.fresh_revision.is_none() && admission.observation_revision == receipt.revision,
        "restored lifecycle owner acquired a fresh execution revision");
    ensure!(admission.admit_model(&anchor.turn_binding()?, 1, b"{}").await.is_err(),
        "cancelled or closed original run admitted another model operation");
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn acknowledged_cancellation_reopens_original_pending_observation_without_fresh_effects() -> Result<()> {
    let server = MockServer::start().await;
    let stop = Arc::new(TerminalStop { cut: TerminalCut::PendingModel, fault: ProjectionFault::None,
        captured: OnceLock::new(), ready: tokio::sync::Notify::new(), prepares: AtomicUsize::new(0), continuations: AtomicUsize::new(0) });
    let captured = stop.clone();
    let fixture = ObjectiveFixture::with_executor_adapter(&server, ReplyFault::None, agent(), Arc::new(NoToolCompiler),
        move |original, native| Arc::new(TerminalExecutor { original, native, agent: Arc::new(agent()), stop: captured })).await?;
    let ack: Arc<std::sync::Mutex<Option<std::result::Result<crate::AgentRunReceipt, String>>>> = Arc::new(std::sync::Mutex::new(None));
    let recorded = ack.clone();
    let state = Arc::downgrade(&fixture.base.state);
    let run_id = fixture.request.body.run_id.clone();
    let runtime = tokio::runtime::Handle::current();
    Mock::given(method("POST")).and(path("/v1/responses")).respond_with(move |_request: &wiremock::Request| {
        // The real model POST already crossed the final entry gate. Accept
        // the original control cancellation before returning its Created data.
        let result = std::thread::scope(|threads| threads.spawn(|| runtime.block_on(async {
            let state = state.upgrade().context("original control owner disappeared")?;
            let current = state.native_run_receipt(&run_id)?;
            control(&state, crate::AgentdMethod::RunCancel { run_id: run_id.clone(),
                expected_revision: current.revision, reason: "operator_requested_stop".to_owned() }).await
        })).join()).map_err(|_| anyhow::anyhow!("original control request thread panicked"))
            .and_then(|result| result).map_err(|error| format!("{error:#}"));
        let success = result.is_ok();
        match recorded.lock() {
            Ok(mut slot) => *slot = Some(result),
            Err(_) => return ResponseTemplate::new(500),
        }
        if !success { return ResponseTemplate::new(500); }
        ResponseTemplate::new(200).set_body_raw(format!("data: {}\n\n",
            json!({"type":"response.created","response":{"id":"response-continuation-pending"}})), "text/event-stream")
    }).expect(1).mount(&server).await;
    fixture.submit(fixture.request.clone()).await?;
    tokio::time::timeout(Duration::from_secs(15), stop.ready.notified()).await?;
    wait_for_event_match(&fixture.core.codex, |event| matches!(event, EventMsg::Error(_)).then_some(())).await;
    let (anchor, before) = stop.captured.get().context("original pending checkpoint")?;
    idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?;
    let acknowledged = ack.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?.take()
        .context("original control ACK missing")?.map_err(anyhow::Error::msg)?;
    assert_eq!(acknowledged.phase, crate::AgentRunPhase::Cancelling);
    let (_, saved) = crate::native_turn_checkpoint::decode(&before.state.payload, &anchor.checkpoint)?;
    assert!(!saved.cancelled && anchor.run.as_ref().context("original run")?.cancel_reason.is_none());
    let request = saved.pending_model.clone().context("original pending request")?;
    let operation = fixture.base.writer.resolve_operation_request(&request.operation_id,
        fixture.base.native.model.destination_id()).await?;
    let queue = anchor.queue.as_ref().context("original Queue binding")?;
    let persisted = fixture.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
        queue.client_id.clone(), queue.payload_sha256.clone()).await?.context("original persisted Queue tuple")?;
    let cold = reopen(fixture, anchor, agent()).await?;
    let observer = cold.base.state.restore_native_run(anchor.run.clone().context("original anchor run")?)?;
    assert_eq!(observer.cancel_reason.as_deref(), Some("operator_requested_stop"));
    assert!(observer.revision >= acknowledged.revision);
    assert_eq!(observer.phase, RunPhase::Indeterminate);
    deny_fresh(&cold, anchor, &observer).await?;
    Mock::given(method("GET")).and(path("/v1/responses/response-continuation-pending"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({"id":"response-continuation-pending","status":"completed",
            "output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"original observation settled"}]}],
            "usage":{"input_tokens":3,"output_tokens":4}}))).expect(1).mount(&server).await;
    let result = cold.base.native.recover_turn(&agent(), NativeTurnRecovery { live_thread: cold.live.clone(),
        original: anchor.checkpoint.clone(), queue: Some(cold.base.queue.clone()) }, &CancellationToken::new()).await?;
    assert_eq!(result.outcome, codex_hepta_native_agent::RunOutcome::Cancelled);
    assert_eq!(result.run.phase, RunPhase::Cancelled);
    assert!(result.state.pending_model.is_none() && result.state.pending_tool.is_none());
    assert_eq!(result.state.final_answer.as_deref(), Some("original observation settled"));
    assert_eq!((result.state.model_calls, result.state.tool_calls), (1, 0));
    assert_eq!(cold.base.writer.status(&request.operation_id).await?, LocalOutcomeState::Committed);
    assert_eq!(cold.base.writer.resolve_operation_request(&request.operation_id,
        cold.base.native.model.destination_id()).await?, operation);
    let (after_anchor, _) = cold.base.native.read_hosted_checkpoint(&cold.live, &anchor.checkpoint).await?;
    assert_eq!(&after_anchor, anchor, "current journal facts must not rewrite the immutable original checkpoint anchor");
    assert_eq!(cold.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
        queue.client_id.clone(), queue.payload_sha256.clone()).await?, Some(persisted));
    assert_eq!((cold.base.issuer.grants.load(Ordering::SeqCst), cold.base.final_use.capacity()?.used_nonces), (1, 1));
    assert_eq!(server.received_requests().await.context("HTTP capture")?.iter().map(|r| r.method.as_str()).collect::<Vec<_>>(), vec!["POST", "GET"]);
    cold.live.shutdown().await?;
    cold.base.live.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn acknowledged_control_lifecycle_blocks_pristine_and_terminal_checkpoint_revival() -> Result<()> {
    // Cancellation and terminal ACKs are reopened without Release. The other
    // two cases additionally exercise actual Core A/B recovery after Release.
    for (phase, release, terminal_cut) in [(None, false, false),
        (Some(crate::AgentRunPhase::Succeeded), false, false),
        (Some(crate::AgentRunPhase::Cancelled), true, false),
        (Some(crate::AgentRunPhase::Failed), true, true)] {
        let (fixture, anchor, before, retained, native_agent, server) = if terminal_cut {
            let server = terminal_provider("full-turn", 1).await;
            let (fixture, stop) = terminal_fixture(&server, TerminalCut::Model, ProjectionFault::None, Arc::new(NoToolCompiler)).await?;
            let (anchor, before) = stop.captured.get().context("original terminal cut")?.clone();
            (fixture, anchor, before, None, terminal_agent(), server)
        } else {
            let server = provider().await;
            let point = if phase.is_none() { StopPoint::RetainOldWorker } else { StopPoint::Pristine };
            let (fixture, stop) = stopped_fixture(&server, point).await?;
            let (anchor, before, _) = stop.captured.get().context("original pristine cut")?.clone();
            let retained = stop.retained_worker.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?.take();
            (fixture, anchor, before, retained, agent(), server)
        };
        idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?;
        let original = fixture.base.state.native_run_receipt(&anchor.checkpoint.operation_id)?;
        let acknowledged = control(&fixture.base.state, match phase {
            Some(phase) => crate::AgentdMethod::RunObserveTerminal { run_id: original.run_id.clone(),
                expected_revision: original.revision, phase, terminal_observed: true },
            None => crate::AgentdMethod::RunCancel { run_id: original.run_id.clone(),
                expected_revision: original.revision, reason: "cancel_before_first_effect".to_owned() },
        }).await?;
        drop(retained);
        assert_eq!(checkpoint(&fixture, &anchor.checkpoint).await?, before,
            "the successful control ACK must not depend on a rewritten native checkpoint");
        let queue = anchor.queue.as_ref().context("original Queue binding")?;
        let persisted = fixture.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
            queue.client_id.clone(), queue.payload_sha256.clone()).await?.context("original persisted Queue tuple")?;
        let mut expected_checkpoint = before.clone();
        if release {
            let released = control(&fixture.base.state, crate::AgentdMethod::RunReleaseClosed {
                run_id: original.run_id.clone(), expected_revision: acknowledged.revision }).await?;
            assert_eq!(released.phase, acknowledged.phase);
            assert!(fixture.base.state.native_run_receipt(&original.run_id).is_err());
            let epoch = idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?;
            fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest {
                turn_id: anchor.checkpoint.turn_id.clone(), expected_epoch: epoch,
                thread_settings: Default::default(), trace: None }).await?;
            let terminal = wait_for_event_match(&fixture.core.codex, |event| matches!(event,
                EventMsg::Error(_) | EventMsg::TurnAborted(_) | EventMsg::TurnComplete(_)).then_some(event.clone())).await;
            assert!(!matches!(terminal, EventMsg::TurnComplete(_)), "a closed original run executed a new completion");
            if matches!(terminal, EventMsg::Error(_)) { idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?; }
            let observed = checkpoint(&fixture, &anchor.checkpoint).await?;
            let (observed_anchor, _) = crate::native_turn_checkpoint::decode(&observed.state.payload, &anchor.checkpoint)?;
            assert_eq!(observed_anchor, anchor);
            let (_, mut cancelled) = crate::native_turn_checkpoint::decode(&before.state.payload, &anchor.checkpoint)?;
            cancelled.cancelled = true;
            assert!(observed.state.payload == before.state.payload
                || (phase == Some(crate::AgentRunPhase::Cancelled)
                    && observed.state.payload == crate::native_turn_checkpoint::encode(&anchor, &cancelled)?),
                "closed observation may project cancellation but cannot execute a new step");
            expected_checkpoint = observed;
        }
        let cold = reopen(fixture, &anchor, native_agent).await?;
        let observer = cold.base.state.restore_native_run(anchor.run.clone().context("original run")?)?;
        assert!(observer.revision >= acknowledged.revision);
        match phase {
            None => assert_eq!((observer.phase, observer.cancel_reason.as_deref()),
                (RunPhase::Indeterminate, Some("cancel_before_first_effect"))),
            Some(crate::AgentRunPhase::Succeeded) => assert_eq!(observer.phase, RunPhase::Succeeded),
            Some(crate::AgentRunPhase::Cancelled) => assert_eq!(observer.phase, RunPhase::Cancelled),
            Some(crate::AgentRunPhase::Failed) => assert_eq!(observer.phase, RunPhase::Failed),
            _ => anyhow::bail!("unexpected test lifecycle phase"),
        }
        deny_fresh(&cold, &anchor, &observer).await?;
        assert_eq!((cold.base.issuer.grants.load(Ordering::SeqCst), cold.base.final_use.capacity()?.used_nonces),
            (usize::from(terminal_cut), usize::from(terminal_cut)));
        assert_eq!(server.received_requests().await.context("HTTP capture")?.len(), usize::from(terminal_cut));
        let session = cold.live.open_native_checkpoint(anchor.checkpoint.clone(),
            NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
        assert_eq!(cold.live.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(expected_checkpoint));
        assert_eq!(cold.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
            queue.client_id.clone(), queue.payload_sha256.clone()).await?, Some(persisted));
        cold.live.shutdown().await?;
        cold.base.live.shutdown().await?;
    }
    Ok(())
}
