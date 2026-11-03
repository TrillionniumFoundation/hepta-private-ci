//! Actual production-writer/FinalUse/ThreadStore close and reopen across a
//! real Fleet relaunch. This exercises the original owners in this process;
//! provider HTTP and independently retained authority are fixtures. It does
//! not claim OS-process restart or full daemon/systemd startup qualification.

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::NativeTurnAdmission;
use crate::native_turn_checkpoint::{decode, encode};

async fn incomplete_provider() -> MockServer {
    let server = MockServer::start().await;
    let created = json!({"type":"response.created","response":{"id":"response-cold-writer"}});
    Mock::given(method("POST")).and(path("/v1/responses"))
        .respond_with(ResponseTemplate::new(200)
            .set_body_raw(format!("data: {created}\n\n"), "text/event-stream"))
        .expect(1).mount(&server).await;
    server
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cold_writer_and_fleet_relaunch_observe_original_model_once() -> Result<()> {
    let server = incomplete_provider().await;
    let endpoint = format!("{}/v1/responses", server.uri());
    let fixture = Fixture::new(endpoint.clone()).await?;
    let pending = fixture.native.run_turn(&agent(), fixture.handoff().await?, &CancellationToken::new()).await?;
    assert_eq!((pending.outcome, pending.run.phase), (RunOutcome::PendingModel, RunPhase::Indeterminate));
    let request = pending.state.pending_model.as_ref().context("original pending POST")?.clone();
    assert_eq!(pending.state.provider_response_id.as_deref(), Some("response-cold-writer"));
    tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            if fixture.writer.status(&request.operation_id).await? == LocalOutcomeState::Indeterminate {
                return Ok::<_, anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }).await.context("original POST did not settle as unknown")??;
    let original_operation = fixture.writer.resolve_operation_request(&request.operation_id,
        fixture.native.model.destination_id()).await?;
    assert_eq!((original_operation.operation_policy_generation, original_operation.payload_json.as_bytes()),
        (7, request.body.as_slice()));
    let old_session = fixture.live.open_native_checkpoint(fixture.anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let NativeCheckpointLoad::Present(before) = fixture.live.load_native_checkpoint(&old_session).await? else {
        anyhow::bail!("original pending checkpoint missing before writer close");
    };
    let (original_anchor, stored_turn) = decode(&before.state.payload, &fixture.anchor.checkpoint)?;
    let original_run = original_anchor.run.as_ref().context("original dispatched run binding")?.clone();
    assert_eq!(encode(&original_anchor, &stored_turn)?, encode(&original_anchor, &pending.state)?);
    assert_eq!((original_run.snapshot.generation,
        original_anchor.execution.as_ref().context("original policy binding")?.policy_generation), (2, 7));
    fixture.assert_queue_persisted_once().await?;

    // Retain the already verified authority including its opaque token. There
    // is no new grant, deserialization, lease rotation or synthetic new cut.
    let authority = fixture.writer.authority().clone();
    let token_digest = authority.fencing_token_digest()?;
    let lease_id = fixture.writer.lease_id().to_owned();
    let lease_generation = fixture.writer.generation();
    let database_path = fixture.writer.database_path().to_owned();
    let exact_cut = fixture.writer.recovery_anchor().await?;
    let final_head = fixture.final_use.revocation_head()?;
    let final_frontier = fixture.final_use.frontier()?;
    let final_capacity = fixture.final_use.capacity()?;
    assert_eq!((lease_generation, final_capacity.used_nonces, fixture.issuer.grants.load(Ordering::SeqCst)), (1, 1, 1));
    let identity = fixture._config.identity().clone();
    assert_eq!((identity.spawn_generation, fixture.state.current_generation()?), (1, 2));
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(identity.fleet_root.clone())?)?;
    let draining = registry.compare_and_transition(&identity.agent_id, 2, AgentLifecycle::Draining)?;
    assert_eq!((draining.lifecycle, draining.generation), (AgentLifecycle::Draining, 3));
    fixture.state.refresh_generation()?;
    assert_eq!(fixture.state.current_generation()?, 3);
    assert!(fixture.state.require_native_effect(&fixture.run.run_id).is_err());
    {
        let admission = fixture.native.admission(fixture.anchor.checkpoint.clone(), fixture.scope.clone(), &pending.run)?;
        assert!(admission.admit_model(&pending.state.binding, pending.state.model_calls, b"{}").await.is_err());
    }
    let stopped = registry.compare_and_transition(&identity.agent_id, 3, AgentLifecycle::Stopped)?;
    assert_eq!((stopped.lifecycle, stopped.generation), (AgentLifecycle::Stopped, 4));
    assert_eq!(fixture.writer.recovery_anchor().await?, exact_cut,
        "the Fleet lifecycle transition cannot rotate or append to the writer lease");

    let old_writer = Arc::downgrade(&fixture.writer);
    let old_host = Arc::downgrade(&fixture.native.host);
    let old_state = Arc::downgrade(&fixture.state);
    let old_thread_store = Arc::downgrade(&fixture.thread_store);
    let old_queue = Arc::downgrade(&fixture.queue);
    let Fixture { native, state, writer, live, thread_store, queue, issuer, final_use, anchor, run,
        initial, payload, scope, _config, _temp } = fixture;
    live.shutdown().await?;
    assert!(live.load_native_checkpoint(&old_session).await.is_err());
    drop(live);
    drop(thread_store);
    drop(queue);
    drop(native);
    drop(state);
    drop(writer);
    drop(final_use);
    drop(_config);
    assert!(old_host.upgrade().is_none(), "the original host must really close");
    assert!(old_writer.upgrade().is_none(), "all original production writer references must really close");
    assert!(old_state.upgrade().is_none(), "the original coordinator must really close");
    assert!(old_thread_store.upgrade().is_none(), "the original ThreadStore handle must really close");
    assert!(old_queue.upgrade().is_none(), "the original QueueStore handle must really close");
    assert!(issuer.state.upgrade().is_none(), "retaining the external test issuer must not retain the old owner");

    let starting = registry.compare_and_transition(&identity.agent_id, 4, AgentLifecycle::Starting)?;
    assert_eq!((starting.lifecycle, starting.generation), (AgentLifecycle::Starting, 5));
    let config = AgentdConfig::load(identity.fleet_root.clone(), identity.agent_id.clone(),
        /*spawn_generation*/ 5, identity.home_root.clone(), identity.run_root.clone(),
        identity.home_root.clone(), identity.workspace.clone())?;
    let retained_authority = authority.clone();
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |candidate: &ProductionAuthorityLease, owner: &AgentId| {
            if candidate == &retained_authority && &candidate.agent_id == owner { Ok(()) }
            else { Err("cold reopen changed the retained original fixture authority".to_owned()) }
        });
    let recovered = AgentdProductionWriterHost::open_with_recovery(&config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&exact_cut), authority.clone(), verifier,
        lease_id.clone(), lease_generation).await?;
    let writer = recovered.writer();
    assert_eq!(writer.authority(), &authority);
    assert_eq!(writer.authority().fencing_token_digest()?, token_digest);
    assert_eq!((writer.lease_id(), writer.generation()), (lease_id.as_str(), lease_generation));
    // Original cognitive recovery materializes a fresh physical projection
    // (the filename includes a nonce) under the same private owner root. The
    // independently retained cut, lease and authority identify continuity.
    assert_eq!(writer.database_path().parent(), database_path.parent());
    assert_ne!(writer.database_path(), database_path.as_path());
    assert_eq!(writer.recovery_anchor().await?, exact_cut,
        "exact-cut cold reopen cannot manufacture a new writer event or lease");
    assert_eq!(writer.resolve_operation_request(&request.operation_id,
        original_operation.operation_destination_id.as_str()).await?, original_operation);
    writer.verify_current_authority().await?;
    let state = Arc::new(AgentdState::new(config.identity().clone(), registry.clone(), /*event_capacity*/ 32)?);
    assert!(state.native_run_receipt(&run.run_id).is_err());
    let CognitiveRuntime::Available(store) = recovered.cognitive_runtime() else {
        anyhow::bail!("exact-cut reopened cognitive owner unavailable");
    };
    state.attach_cognitive_store(store)?;
    state.mark_runtime_prerequisites_ready()?;

    // This is the same durable FinalUse directory and original pinned issuer
    // and revocation head. Reopen would fail if an old authority handle lived.
    let final_use = FinalUseAuthority::open_state_dir(&_temp.path().canonicalize()?.join("final-use"),
        "native-test-issuer".to_owned(), issuer.key.verifying_key().to_bytes(), final_head)?;
    assert_eq!(final_use.frontier()?, final_frontier);
    assert_eq!(final_use.capacity()?, final_capacity);
    let gate = Arc::new(NativeEntryGate { state: Arc::downgrade(&state), policy_generation: 8 });
    let model = Arc::new(NativeResponsesTarget::new(NativeResponsesTargetConfig {
        responses_url: endpoint, bearer: None, idle_timeout: Duration::from_secs(3),
        max_request_bytes: 8192, max_stream_bytes: 16384,
    }, &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault))?);
    let runtime = Arc::new(NativeRuntimeTarget::new("native-runtime-integration".to_owned(), 4096)?);
    let host = Arc::new(recovered.attach_target(final_use.clone(), model.clone(), issuer.clone())?
        .attach_additional_target(final_use.clone(), runtime.clone())?);
    let config = config.with_production_writer_host(host.clone())?;
    assert_eq!((config.identity().spawn_generation, host.writer().generation()), (5, 1));
    let native = AgentdNativeHost { gate, host, model, runtime, compiler: Arc::new(NoToolCompiler) };
    assert!(Arc::ptr_eq(&writer, &native.host.writer()));
    let running = registry.compare_and_transition(&identity.agent_id, 5, AgentLifecycle::Running)?;
    assert_eq!((running.lifecycle, running.generation), (AgentLifecycle::Running, 6));
    state.refresh_generation()?;
    state.mark_app_server_ready()?;
    assert_eq!(state.current_generation()?, 6);

    let home = identity.home_root.clone();
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::try_from(home.join("state"))?);
    let state_db = StateRuntime::init(sqlite.clone(), "native-test".to_owned()).await?;
    let queue = Arc::new(LocalQueueStore::new(state_db.clone()));
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
    assert!(live.load_native_checkpoint(&old_session).await.is_err(), "old ThreadStore writer epoch must remain invalid");
    let session = live.open_native_checkpoint(anchor.checkpoint.clone(), NativeCheckpointOpenMode::Recover,
        Arc::new(ReadOriginalOnly)).await?;
    assert_eq!(live.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(before.clone()));
    assert_eq!(writer.recovery_anchor().await?, exact_cut);
    let fixture = Fixture { native, state, writer, live, thread_store, queue, issuer, final_use, anchor, run,
        initial, payload, scope, _config: config, _temp };
    fixture.assert_queue_persisted_once().await?;

    let observed = Arc::new(AtomicUsize::new(0));
    let observing_state = fixture.state.clone();
    let observing_run = original_run.clone();
    let observed_by_provider = observed.clone();
    Mock::given(method("GET")).and(path("/v1/responses/response-cold-writer"))
        .respond_with(move |_request: &wiremock::Request| {
            assert_eq!((observing_state.identity().spawn_generation,
                observing_state.current_generation().expect("current Fleet generation")), (5, 6));
            let run_id = &observing_run.snapshot.run_id;
            let run = observing_state.native_run_receipt(run_id).expect("original run restored for observation");
            assert_eq!((run.generation, run.phase), (2, RunPhase::Indeterminate));
            assert_eq!(observing_state.native_recovery_record(run_id).expect("original recovery identity"), observing_run);
            assert!(observing_state.require_native_effect(run_id).is_err());
            observed_by_provider.fetch_add(1, Ordering::SeqCst);
            ResponseTemplate::new(200).set_body_json(json!({"id":"response-cold-writer","status":"completed",
                "output":[{"type":"message","id":"message-after-cold-writer","role":"assistant",
                    "content":[{"type":"output_text","text":"original completion after writer reopen"}]}],
                "usage":{"input_tokens":3,"output_tokens":4}}))
        }).expect(1).mount(&server).await;
    let result = fixture.native.recover_turn(&agent(), NativeTurnRecovery {
        live_thread: fixture.live.clone(), original: fixture.anchor.checkpoint.clone(),
        queue: Some(fixture.queue.clone()),
    }, &CancellationToken::new()).await?;
    assert_eq!((result.outcome, result.run.phase, result.run.generation, result.run.terminal_observed),
        (RunOutcome::Completed("original completion after writer reopen".to_owned()), RunPhase::Succeeded, 2, true),
        "cold writer recovery state: {:#?}", result.state);
    assert_eq!((observed.load(Ordering::SeqCst), fixture.issuer.grants.load(Ordering::SeqCst)), (1, 1));
    assert_eq!(fixture.final_use.frontier()?, final_frontier);
    assert_eq!(fixture.final_use.capacity()?, final_capacity);
    let captured = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(captured.iter().map(|request| request.method.to_string()).collect::<Vec<_>>(), vec!["POST", "GET"]);
    assert_eq!(captured[0].body, request.body);
    assert_eq!(captured[0].headers.get("idempotency-key").context("original POST operation header")?.to_str()?,
        request.operation_id);
    assert_eq!(fixture.writer.resolve_operation_request(&request.operation_id,
        fixture.native.model.destination_id()).await?, original_operation);
    assert_eq!(fixture.writer.status(&request.operation_id).await?, LocalOutcomeState::Committed);
    assert_ne!(fixture.writer.recovery_anchor().await?, exact_cut, "observed completion must commit to the reopened original writer");
    let NativeCheckpointLoad::Present(after) = fixture.live.load_native_checkpoint(&session).await? else {
        anyhow::bail!("original observer checkpoint missing after GET");
    };
    assert!(after.version.revision > before.version.revision);
    let (after_anchor, after_turn) = decode(&after.state.payload, &fixture.anchor.checkpoint)?;
    assert_eq!(after_anchor, original_anchor, "new launch cannot rewrite the original run, turn, policy or lease binding");
    assert_eq!((after_turn.provider_response_id.as_deref(), after_turn.model_calls, after_turn.pending_model.is_none()),
        (Some("response-cold-writer"), 1, true));
    assert_eq!(after_turn.final_answer.as_deref(), Some("original completion after writer reopen"));
    assert_eq!((fixture.state.identity().spawn_generation, fixture.state.current_generation()?,
        fixture.native.gate.policy_generation, fixture.writer.generation()), (5, 6, 8, 1));
    assert!(fixture.state.require_native_effect(&fixture.run.run_id).is_err());
    let original_admission = fixture.native.admission_with_policy(fixture.anchor.checkpoint.clone(),
        fixture.scope.clone(), Generation::new(7)?, &result.run)?;
    assert!(original_admission.admit_model(&after_turn.binding, after_turn.model_calls, b"{}").await.is_err());
    fixture.assert_queue_persisted_once().await?;
    let history = fixture.history().await?;
    let outputs = history.items.iter().filter(|item| matches!(item,
        RolloutItem::ResponseItem(envelope) if matches!(&envelope.item,
            codex_protocol::models::ResponseItem::Message { role, .. } if role == "assistant"))).count();
    assert_eq!(outputs, 1, "original observer completion must enter history once");
    fixture.live.shutdown().await?;
    Ok(())
}
