//! Coordinator cold reconstruction and real ThreadStore writer reopen. The
//! original production writer, authority and QueueStore stay open; these tests
//! do not represent an OS process restart or a deployed runtime-host restart.

use super::*;
use pretty_assertions::assert_eq;
use codex_thread_store::{NativeCheckpointExpected, NativeCheckpointState};
use crate::NativeTurnAdmission;
use crate::native_ports::NativeProductionPorts;
use codex_hepta_native_agent::ModelPort;
use crate::native_turn_checkpoint::{decode, encode};

async fn incomplete_provider() -> MockServer {
    let server = MockServer::start().await;
    let created = json!({"type":"response.created","response":{"id":"response-recovery"}});
    Mock::given(method("POST")).and(path("/v1/responses"))
        .respond_with(ResponseTemplate::new(200)
            .set_body_raw(format!("data: {created}\n\n"), "text/event-stream"))
        .mount(&server).await;
    server
}

async fn wait_for_unknown(fixture: &Fixture, operation_id: &str) -> Result<()> {
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if fixture.writer.status(operation_id).await? == LocalOutcomeState::Indeterminate {
                return Ok::<_, anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await?
}

async fn pending_model_diagnostic(fixture: &Fixture, result: &NativeTurnResult) -> String {
    if !matches!(result.outcome, RunOutcome::PendingModel) {
        return "completion observed".to_owned();
    }
    // Failure diagnostics may only observe/reconcile the saved original key.
    // This never admits another operation, claims a grant, or retries POST.
    let observed: Result<_> = async {
        let request = result.state.pending_model.as_ref().context("pending model request")?;
        let response_id = result.state.provider_response_id.as_ref().context("original response id not observed")?;
        let original = fixture.writer.resolve_operation_request(&request.operation_id,
            fixture.native.model.destination_id()).await.context("resolve original operation")?;
        let admission = fixture.native.admission_with_policy(fixture.anchor.checkpoint.clone(),
            fixture.scope.clone(), Generation::new(original.operation_policy_generation)?, &result.run)?;
        let ports = NativeProductionPorts { entry_owner: crate::native_ports::NativeEntryOwner::Agentd,
            admission, model: fixture.native.model.clone(), runtime: fixture.native.runtime.clone(),
        };
        ports.reconcile(request, response_id).await.context("original GET and writer reconciliation")
    }.await;
    match observed {
        Ok(completion) => format!("{completion:#?}"),
        Err(error) => format!("{error:#}"),
    }
}

#[tokio::test]
async fn cold_coordinator_and_thread_reopen_observe_old_policy_without_new_grant_or_post() -> Result<()> {
    let server = incomplete_provider().await;
    let endpoint = format!("{}/v1/responses", server.uri());
    let fixture = Fixture::new(endpoint.clone()).await?;
    let pending = fixture.native.run_turn(&agent(), fixture.handoff().await?, &CancellationToken::new()).await?;
    assert_eq!(pending.outcome, RunOutcome::PendingModel);
    assert_eq!(pending.run.phase, RunPhase::Indeterminate);
    let request = pending.state.pending_model.clone().context("pending original model")?;
    wait_for_unknown(&fixture, &request.operation_id).await?;
    let (before, stored) = NativeThreadTurnOwner::<NativeProductionAdmission>::read_original(
        fixture.live.clone(), fixture.anchor.checkpoint.clone(), Arc::new(ReadOriginalOnly),
    ).await?;
    assert_eq!(encode(&before, &stored)?, encode(&before, &pending.state)?);
    let original_run = before.run.clone().context("actual dispatched coordinator recovery")?;
    assert_eq!((original_run.snapshot.run_id.as_str(), original_run.snapshot.generation,
        original_run.context_digest.as_str(), original_run.compilation_receipt_digest.as_str()),
        (fixture.run.run_id.as_str(), fixture.run.generation,
        fixture.run.context_digest.as_deref().context("context")?,
        fixture.run.compilation_receipt_digest.as_deref().context("compilation")?));
    assert_eq!(before.execution, Some(NativeExecutionBindingV1 {
        cell_id: fixture.scope.cell_id.to_string(), organ_id: fixture.scope.organ_id.to_string(),
        final_scope_id: fixture.scope.final_scope_id.to_string(), policy_generation: 7,
    }));
    let original_operation = fixture.writer.resolve_operation_request(
        &request.operation_id, fixture.native.model.destination_id(),
    ).await?;
    assert_eq!((original_operation.operation_policy_generation, original_operation.payload_json.as_bytes()),
        (7, request.body.as_slice()));
    let old_session = fixture.live.open_native_checkpoint(fixture.anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;

    let Fixture { native, state, writer, live, thread_store: old_thread_store, queue, issuer, final_use, anchor, run, initial, payload,
        scope, _config, _temp } = fixture;
    live.shutdown().await?;
    assert!(live.load_native_checkpoint(&old_session).await.is_err());
    drop(live);
    drop(old_thread_store);
    let stopped = Arc::downgrade(&state);
    drop(state);
    assert!(stopped.upgrade().is_none(), "old coordinator must actually be dropped");

    // Reopen the original Fleet/configuration and empty original coordinator.
    // No replacement production lease, operation, grant issuer or queue exists.
    let identity = _config.identity().clone();
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(identity.fleet_root.clone())?)?;
    let state = Arc::new(AgentdState::new(identity.clone(), registry, /*event_capacity*/ 32)?);
    assert!(state.native_run_receipt(&run.run_id).is_err());
    let CognitiveRuntime::Available(store) = native.host.cognitive_runtime() else {
        anyhow::bail!("original cognitive owner unavailable");
    };
    state.attach_cognitive_store(store)?;
    state.mark_runtime_prerequisites_ready()?;
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    let gate = Arc::new(NativeEntryGate { state: Arc::downgrade(&state), policy_generation: 8 });
    let model = Arc::new(NativeResponsesTarget::new(NativeResponsesTargetConfig {
        responses_url: endpoint, bearer: None, idle_timeout: Duration::from_secs(3),
        max_request_bytes: 8192, max_stream_bytes: 16384,
    }, &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault))?);
    let runtime = Arc::new(NativeRuntimeTarget::new("native-runtime-integration".to_owned(),
        /*max_output_bytes*/ 4096)?);
    let native = AgentdNativeHost { gate, host: native.host, model, runtime, compiler: native.compiler };
    assert!(Arc::ptr_eq(&writer, &native.host.writer()));

    let home = identity.home_root;
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(home.join("state"))?);
    let state_db = StateRuntime::init(sqlite.clone(), "native-test".to_owned()).await?;
    let thread_store = Arc::new(LocalThreadStore::new(LocalThreadStoreConfig {
        codex_home: home.clone(), sqlite, default_model_provider_id: "native-test".to_owned(),
    }, Some(state_db)));
    let thread_id = anchor.checkpoint.thread_id;
    let rollout = home.join("sessions/2026/10/28")
        .join(format!("rollout-2026-10-28T00-00-00-{thread_id}.jsonl"));
    let history = thread_store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id, include_archived: false,
    }).await?;
    let live = LiveThread::resume(thread_store.clone(), ThreadHistoryMode::Paginated, ResumeThreadParams {
        thread_id, rollout_path: Some(rollout), history: Some(history.items.into()), include_archived: false,
        metadata: ThreadPersistenceMetadata { cwd: Some(home), model_provider: "native-test".to_owned(),
            memory_mode: ThreadMemoryMode::Disabled },
    }).await?;
    assert!(live.load_native_checkpoint(&old_session).await.is_err(),
        "old writer epoch cannot be used after real ThreadStore reopen");
    let fixture = Fixture { native, state, writer, live, thread_store, queue, issuer, final_use, anchor, run, initial,
        payload, scope, _config, _temp };

    let observed = Arc::new(AtomicUsize::new(0));
    let observing_state = fixture.state.clone();
    let observing_run = original_run.clone();
    let observed_by_provider = observed.clone();
    Mock::given(method("GET")).and(path("/v1/responses/response-recovery"))
        .respond_with(move |_request: &wiremock::Request| {
            let run_id = &observing_run.snapshot.run_id;
            assert_eq!(observing_state.native_run_receipt(run_id).expect("restored original run").phase,
                RunPhase::Indeterminate);
            assert_eq!(observing_state.native_recovery_record(run_id).expect("original correlation"), observing_run);
            assert!(observing_state.require_native_effect(run_id).is_err());
            observed_by_provider.fetch_add(1, Ordering::SeqCst);
            ResponseTemplate::new(200).set_body_json(json!({"id":"response-recovery","status":"completed",
                "output":[{"type":"message","id":"message-recovered","role":"assistant",
                    "content":[{"type":"output_text","text":"observed original completion"}]}],
                "usage":{"input_tokens":3,"output_tokens":4}}))
        }).mount(&server).await;
    let result = fixture.native.recover_turn(&agent(), NativeTurnRecovery {
        live_thread: fixture.live.clone(), original: fixture.anchor.checkpoint.clone(),
        queue: Some(fixture.queue.clone()),
    }, &CancellationToken::new()).await?;
    let diagnostic = pending_model_diagnostic(&fixture, &result).await;
    assert_eq!((result.outcome, result.run.phase, result.run.terminal_observed),
        (RunOutcome::Completed("observed original completion".to_owned()), RunPhase::Succeeded, true),
        "native recovery state: {:#?}; original observation: {diagnostic}", result.state);
    assert_eq!(observed.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1, "recovery cannot mint another grant");
    let captured = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(captured.iter().map(|request| request.method.to_string()).collect::<Vec<_>>(), vec!["POST", "GET"]);
    assert_eq!(captured[0].body, request.body);
    assert_eq!(fixture.writer.resolve_operation_request(&request.operation_id,
        fixture.native.model.destination_id()).await?, original_operation);
    assert_eq!(fixture.writer.status(&request.operation_id).await?, LocalOutcomeState::Committed);
    let (after, turn) = NativeThreadTurnOwner::<NativeProductionAdmission>::read_original(
        fixture.live.clone(), fixture.anchor.checkpoint.clone(), Arc::new(ReadOriginalOnly),
    ).await?;
    assert_eq!(after, before, "history and original coordinator/policy correlation remain immutable");
    assert_eq!((turn.provider_response_id.as_deref(), turn.model_calls, turn.pending_model.is_none()),
        (Some("response-recovery"), 1, true));
    fixture.assert_queue_persisted_once().await?;
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn real_fleet_draining_generation_preserves_original_observer_checkpoint_and_get() -> Result<()> {
    let server = incomplete_provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    let pending = fixture.native.run_turn(&agent(), fixture.handoff().await?, &CancellationToken::new()).await?;
    assert_eq!(pending.outcome, RunOutcome::PendingModel);
    let request = pending.state.pending_model.as_ref().context("original pending POST")?;
    wait_for_unknown(&fixture, &request.operation_id).await?;
    let original_operation = fixture.writer.resolve_operation_request(&request.operation_id,
        fixture.native.model.destination_id()).await?;
    let session = fixture.live.open_native_checkpoint(fixture.anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let NativeCheckpointLoad::Present(before) = fixture.live.load_native_checkpoint(&session).await? else {
        anyhow::bail!("original checkpoint missing");
    };
    let (original_anchor, _) = decode(&before.state.payload, &fixture.anchor.checkpoint)?;

    // This is the original supervisor's real lifecycle CAS, including its
    // publication lock. It is not a fabricated new spawn identity or daemon
    // restart. The POST entry guard has ended before this transition.
    let identity = fixture.state.identity();
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(identity.fleet_root.clone())?)?;
    let published = registry.compare_and_transition(&identity.agent_id, /*expected_generation*/ 2,
        AgentLifecycle::Draining)?;
    assert_eq!((published.lifecycle, published.generation), (AgentLifecycle::Draining, 3));
    assert_eq!(registry.load_agent(&identity.agent_id)?.lifecycle, published);
    fixture.state.refresh_generation()?;
    assert_eq!(fixture.state.current_generation()?, 3);
    assert!(fixture.state.require_native_effect(&fixture.run.run_id).is_err());
    let admission = fixture.native.admission(fixture.anchor.checkpoint.clone(), fixture.scope.clone(), &pending.run)?;
    assert!(admission.admit_model(&pending.state.binding, pending.state.model_calls, b"{}").await.is_err());

    let observed = Arc::new(AtomicUsize::new(0));
    let observing_state = fixture.state.clone();
    let observing_run_id = fixture.run.run_id.clone();
    let observed_by_provider = observed.clone();
    Mock::given(method("GET")).and(path("/v1/responses/response-recovery"))
        .respond_with(move |_request: &wiremock::Request| {
            assert_eq!(observing_state.current_generation().expect("current real Fleet generation"), 3);
            let original = observing_state.native_run_receipt(&observing_run_id).expect("original run");
            assert_eq!((original.generation, original.phase), (2, RunPhase::Indeterminate));
            assert!(observing_state.require_native_effect(&observing_run_id).is_err());
            observed_by_provider.fetch_add(1, Ordering::SeqCst);
            ResponseTemplate::new(200).set_body_json(json!({"id":"response-recovery","status":"completed",
                "output":[{"type":"message","id":"message-after-drain","role":"assistant",
                    "content":[{"type":"output_text","text":"original completion after Fleet drain"}]}],
                "usage":{"input_tokens":3,"output_tokens":4}}))
        }).mount(&server).await;
    let result = fixture.native.recover_turn(&agent(), NativeTurnRecovery {
        live_thread: fixture.live.clone(), original: fixture.anchor.checkpoint.clone(),
        queue: Some(fixture.queue.clone()),
    }, &CancellationToken::new()).await?;
    let diagnostic = pending_model_diagnostic(&fixture, &result).await;
    assert_eq!((result.outcome, result.run.phase, result.run.generation),
        (RunOutcome::Completed("original completion after Fleet drain".to_owned()), RunPhase::Succeeded, 2),
        "native recovery state: {:#?}; original observation: {diagnostic}", result.state);
    let NativeCheckpointLoad::Present(after) = fixture.live.load_native_checkpoint(&session).await? else {
        anyhow::bail!("observer checkpoint missing");
    };
    assert!(after.version.revision > before.version.revision, "original observer must really commit its result");
    let (after_anchor, after_turn) = decode(&after.state.payload, &fixture.anchor.checkpoint)?;
    assert_eq!(after_anchor, original_anchor, "Fleet change cannot rewrite original run or policy correlation");
    assert_eq!((after_anchor.checkpoint.generation,
        after_anchor.execution.as_ref().context("original policy")?.policy_generation), (2, 7));
    assert_eq!(after_turn.final_answer.as_deref(), Some("original completion after Fleet drain"));
    assert_eq!(fixture.writer.resolve_operation_request(&request.operation_id,
        fixture.native.model.destination_id()).await?, original_operation);
    assert_eq!(fixture.writer.status(&request.operation_id).await?, LocalOutcomeState::Committed);
    assert_eq!(observed.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1);
    assert_eq!(server.received_requests().await.context("HTTP capture")?.iter()
        .map(|request| request.method.to_string()).collect::<Vec<_>>(), vec!["POST", "GET"]);
    assert_eq!(fixture.state.current_generation()?, 3);
    assert!(fixture.state.require_native_effect(&fixture.run.run_id).is_err());
    fixture.assert_queue_persisted_once().await?;
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn storage_only_checkpoint_without_original_run_and_execution_is_held() -> Result<()> {
    let server = provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    // The original owner consumes dispatch so its unchanged checkpoint gate
    // can write. Deliberately omit the run/execution provenance from the stored
    // legacy payload: ambient coordinator state cannot supply those facts.
    let _active = fixture.state.dispatch_native_run(&fixture.run)?;
    let dispatched = fixture.state.native_run_receipt(&fixture.run.run_id)?;
    let admission = fixture.native.admission(fixture.anchor.checkpoint.clone(), fixture.scope.clone(), &dispatched)?;
    let _owner = NativeThreadTurnOwner::create(fixture.live.clone(), fixture.anchor.clone(),
        admission.clone(), admission, &fixture.initial).await?;
    let (stored_anchor, stored_turn) = NativeThreadTurnOwner::<NativeProductionAdmission>::read_original(
        fixture.live.clone(), fixture.anchor.checkpoint.clone(), Arc::new(ReadOriginalOnly),
    ).await?;
    assert!(stored_anchor.run.is_none() && stored_anchor.execution.is_none());
    assert_eq!(encode(&stored_anchor, &stored_turn)?, encode(&fixture.anchor, &fixture.initial)?);
    let writer_cut = fixture.writer.recovery_anchor().await?;
    let error = match fixture.native.recover_turn(&agent(), NativeTurnRecovery {
        live_thread: fixture.live.clone(), original: fixture.anchor.checkpoint.clone(),
        queue: Some(fixture.queue.clone()),
    }, &CancellationToken::new()).await {
        Ok(_) => anyhow::bail!("legacy checkpoint incorrectly entered production recovery"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("no original coordinator recovery"), "held reason: {error:#}");
    assert_eq!(fixture.state.native_run_receipt(&fixture.run.run_id)?, dispatched);
    assert_eq!(fixture.writer.recovery_anchor().await?, writer_cut);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 0);
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    assert_eq!(fixture.queue.list_page(fixture.anchor.checkpoint.thread_id, /*offset*/ 0, /*limit*/ 16).await?.len(), 1);
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn checkpoint_metadata_conflict_cannot_replace_the_existing_original_run() -> Result<()> {
    let server = incomplete_provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    let pending = fixture.native.run_turn(&agent(), fixture.handoff().await?, &CancellationToken::new()).await?;
    let request = pending.state.pending_model.as_ref().context("original model")?;
    wait_for_unknown(&fixture, &request.operation_id).await?;
    let original_run = fixture.state.native_recovery_record(&fixture.run.run_id)?;
    let admission = fixture.native.admission(fixture.anchor.checkpoint.clone(), fixture.scope.clone(), &pending.run)?;
    let session = fixture.live.open_native_checkpoint(fixture.anchor.checkpoint.clone(), NativeCheckpointOpenMode::Recover, admission).await?;
    let NativeCheckpointLoad::Present(head) = fixture.live.load_native_checkpoint(&session).await? else {
        anyhow::bail!("original checkpoint missing");
    };
    let (mut changed, stored) = decode(&head.state.payload, &fixture.anchor.checkpoint)?;
    changed.run.as_mut().context("original run")?.snapshot.body_digest = "9".repeat(64);
    // Deliberate inconsistent lower-level storage input: it is well-formed
    // codec data, but cannot replace immutable metadata of a live original run.
    fixture.live.commit_native_checkpoint(&session, NativeCheckpointExpected::Version(head.version),
        NativeCheckpointState { binding: fixture.anchor.checkpoint.clone(), payload: encode(&changed, &stored)? }).await?;
    let error = match fixture.native.recover_turn(&agent(), NativeTurnRecovery {
        live_thread: fixture.live.clone(), original: fixture.anchor.checkpoint.clone(),
        queue: Some(fixture.queue.clone()),
    }, &CancellationToken::new()).await {
        Ok(_) => anyhow::bail!("conflicting immutable correlation was accepted"),
        Err(error) => error,
    };
    assert!(matches!(error.downcast_ref::<AgentdError>(),
        Some(AgentdError::Protocol(message)) if message == "agent run lifecycle rejected: MixedSnapshot"),
        "immutable original correlation must be rejected by its reducer: {error:#}");
    assert_eq!(fixture.state.native_recovery_record(&fixture.run.run_id)?, original_run);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 1);
    let captured = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(captured.iter().map(|request| request.method.to_string()).collect::<Vec<_>>(), vec!["POST"]);
    assert_eq!(fixture.writer.status(&request.operation_id).await?, LocalOutcomeState::Indeterminate);
    fixture.live.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn checkpoint_observer_cannot_replace_the_same_dispatched_coordinator() -> Result<()> {
    let server = provider().await;
    let fixture = Fixture::new(format!("{}/v1/responses", server.uri())).await?;
    let mut handoff = fixture.handoff().await?;
    let admission = fixture.native.admission(handoff.anchor.checkpoint.clone(), handoff.scope.clone(), &handoff.run)?;
    let active = fixture.state.dispatch_native_run(&handoff.run)?;
    handoff.anchor.run = Some(fixture.state.native_recovery_record(&handoff.run.run_id)?);
    handoff.anchor.execution = Some(NativeExecutionBindingV1 {
        cell_id: handoff.scope.cell_id.to_string(), organ_id: handoff.scope.organ_id.to_string(),
        final_scope_id: handoff.scope.final_scope_id.to_string(), policy_generation: 7,
    });
    let original = handoff.anchor.run.clone().context("real post-dispatch recovery")?;
    let owner = NativeThreadTurnOwner::create(handoff.live_thread, handoff.anchor, admission.clone(),
        admission.clone(), &handoff.initial).await?;
    handoff.queue.as_mut().context("original queue dispatch")?.complete(&owner).await?;
    drop(handoff.queue.take());
    drop(active);
    let dispatched = fixture.state.native_run_receipt(&fixture.run.run_id)?;
    assert_eq!(dispatched.phase, RunPhase::Dispatched);
    let writer_cut = fixture.writer.recovery_anchor().await?;
    let session = fixture.live.open_native_checkpoint(fixture.anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let checkpoint = fixture.live.load_native_checkpoint(&session).await?;
    let error = match fixture.native.recover_turn(&agent(), NativeTurnRecovery {
        live_thread: fixture.live.clone(), original: fixture.anchor.checkpoint.clone(),
        queue: Some(fixture.queue.clone()),
    }, &CancellationToken::new()).await {
        Ok(_) => anyhow::bail!("initial-only recovery admitted a new model effect"),
        Err(error) => error,
    };
    assert!(matches!(error.downcast_ref::<AgentdError>(),
        Some(AgentdError::Protocol(message)) if message == "agent run lifecycle rejected: InvalidTransition"),
        "a live dispatched owner must remain nonreplaceable: {error:#}");
    // Observation must not take over or downgrade the live attempt. Its old
    // checkpoint cannot manufacture a successor or invalidate that owner.
    assert_eq!(fixture.state.native_recovery_record(&fixture.run.run_id)?, original);
    assert_eq!(fixture.state.native_run_receipt(&fixture.run.run_id)?, dispatched);
    assert_eq!(fixture.writer.recovery_anchor().await?, writer_cut);
    assert_eq!(fixture.live.load_native_checkpoint(&session).await?, checkpoint);
    assert_eq!(fixture.issuer.grants.load(Ordering::SeqCst), 0);
    assert!(server.received_requests().await.context("HTTP capture")?.is_empty());
    fixture.assert_queue_persisted_once().await?;
    fixture.live.shutdown().await?;
    Ok(())
}
