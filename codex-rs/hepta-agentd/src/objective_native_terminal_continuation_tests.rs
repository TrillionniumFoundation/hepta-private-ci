//! Continuation from actual terminal checkpoints. The HTTP provider and
//! controlled SSH transport are fixtures; Core, Queue, writer, FinalUse,
//! checkpoint chain and the original runtime process owners are real.

use super::*;
use codex_hepta_native_agent::{ModelRequest, ToolAdmission, ToolCall, TurnBinding};
use codex_hepta_operations::OperationIntentV1;
use crate::native_admission::NativeProductionAdmission;
use crate::native_ports::{NativeEntryOwner, NativeProductionPorts};
use pretty_assertions::assert_eq;

#[derive(Clone, Copy)]
enum TerminalCut { Model, Tool, PendingModel }

#[derive(Clone, Copy)]
enum ProjectionFault { None, Usage, Output }

struct TerminalStop {
    cut: TerminalCut,
    fault: ProjectionFault,
    captured: OnceLock<(NativeTurnAnchorV1, StoredNativeCheckpoint)>,
    ready: tokio::sync::Notify,
    prepares: AtomicUsize,
    continuations: AtomicUsize,
}

struct TerminalExecutor {
    original: Arc<dyn HostedTurnExecutor>,
    native: Arc<AgentdNativeHost>,
    agent: Arc<NativeAgent>,
    stop: Arc<TerminalStop>,
}

impl HostedTurnExecutor for TerminalExecutor {
    fn executor_id(&self) -> &str { self.original.executor_id() }
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            self.stop.prepares.fetch_add(1, Ordering::SeqCst);
            let mut plan = self.original.prepare(input).await?;
            let resolution: Result<_> = (|| {
                let run_id = plan.correlation.get("run_id").context("original plan run missing")?;
                let state = self.native.gate.state()?;
                let run = state.native_run_receipt(run_id)?;
                let prepared = state.load_canonical_prepared(run_id)?.context("original Prepared missing")?;
                let scope = NativeTurnScope {
                    cell_id: StableId::new(plan.correlation.get("cell_id").context("original cell")?)?,
                    organ_id: StableId::new(plan.correlation.get("organ_id").context("original organ")?)?,
                    final_scope_id: StableId::new(plan.correlation.get("final_scope_id").context("original scope")?)?,
                };
                Ok((run, scope, prepared.context().clone()))
            })();
            let (run, scope, context) = resolution.map_err(|error|
                codex_protocol::error::CodexErr::InvalidRequest(format!("terminal cut resolution: {error:#}")))?;
            plan.execution = Box::new(TerminalExecution { native: self.native.clone(), agent: self.agent.clone(),
                stop: self.stop.clone(), run, scope, context });
            Ok(plan)
        })
    }
    fn observe_admission<'a>(&'a self, input: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(input)
    }
    fn resume_preparation<'a>(&'a self, input: HostedPreparationRecoveryInput) -> HostedFuture<'a, HostedTurnPlan> {
        self.original.resume_preparation(input)
    }
    fn supports_checkpoint_continuation(&self) -> bool { self.original.supports_checkpoint_continuation() }
    fn prepare_checkpoint_continuation<'a>(&'a self, input: HostedCheckpointContinuationInput)
        -> HostedFuture<'a, Option<HostedTurnPlan>> {
        self.stop.continuations.fetch_add(1, Ordering::SeqCst);
        self.original.prepare_checkpoint_continuation(input)
    }
    fn recover<'a>(&'a self, input: HostedTurnRecoveryInput) -> HostedFuture<'a, HostedTurnOutcome> {
        self.original.recover(input)
    }
}

struct TerminalExecution {
    native: Arc<AgentdNativeHost>,
    agent: Arc<NativeAgent>,
    stop: Arc<TerminalStop>,
    run: RunReceipt,
    scope: NativeTurnScope,
    context: crate::intelligence_product::NativeContextBindingV1,
}

const CUT_REACHED: &str = "fixture suspended after an original terminal checkpoint";

impl HostedTurnExecution for TerminalExecution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            let result: Result<_> = async {
                let binding = NativeCheckpointBinding { thread_id: turn.thread_id(), turn_id: turn.turn_id().to_owned(),
                    operation_id: self.run.run_id.clone(), generation: self.run.generation,
                    lease_id: self.native.host.writer().lease_id().to_owned() };
                let anchor = NativeTurnAnchorV1 { checkpoint: binding, recovery: turn.recovery().clone(),
                    queue: Some(NativeQueueBindingV1 { queued_item_id: turn.queue().queued_item_id.clone(),
                        client_id: turn.queue().client_id.clone(), payload_sha256: turn.queue().payload_sha256.clone() }),
                    run: None, execution: None, rendered_context_sha256: Some(self.context.rendered_context_digest().to_string()) };
                let prepared = self.native.prepare_hosted_turn(turn.live_thread().clone(), anchor,
                    self.run, self.scope, self.context).await?;
                prepared.confirm_durable().await?;
                turn.confirm_durable().await?;
                let crate::native_host::NativePreparedTurn { owner, admission, turn: mut state, _original } = prepared;
                let ports = NativeProductionPorts { admission, model: self.native.model.clone(), runtime: self.native.runtime.clone(),
                    entry_owner: NativeEntryOwner::Core(Arc::clone(turn.entry())) };
                let outcome = {
                    let recording = TerminalCheckpointOwner { original: &owner, native: &self.native,
                        live: turn.live_thread(), stop: &self.stop };
                    self.agent.run(&recording, &ports, &ports, &mut state, turn.cancellation()).await
                };
                match (self.stop.cut, outcome) {
                    (TerminalCut::PendingModel, Ok(RunOutcome::PendingModel)) => {
                        let (record, anchor, saved) = self.native.read_hosted_checkpoint_record(
                            turn.live_thread(), &owner.anchor().checkpoint).await?;
                        ensure!(saved.pending_model.is_some() && saved.provider_response_id.as_deref() == Some("response-continuation-pending")
                            && saved.last_error.is_some() && !saved.cancelled,
                            "fixture must retain an actual noncancelled Created-only model observation");
                        ensure!(self.stop.captured.set((anchor, record)).is_ok(), "original pending cut was recorded twice");
                    }
                    (TerminalCut::Model | TerminalCut::Tool, Err(error)) => {
                        ensure!(format!("{error:#}").contains(CUT_REACHED) && self.stop.captured.get().is_some(),
                            "native loop failed before the selected terminal cut: {error:#}");
                    }
                    (_, outcome) => anyhow::bail!("native loop did not reach its selected original cut: {outcome:?}"),
                }
                // The same actual owner guard publishes an unknown disposition.
                // No Core Interrupt, fake TurnAborted, or SQL rewrite is used.
                drop(ports); drop(owner); drop(_original);
                self.stop.ready.notify_one();
                Ok(HostedTurnOutcome::PendingObservation)
            }.await;
            result.map_err(|error| codex_protocol::error::CodexErr::InvalidRequest(format!("terminal cut fixture: {error:#}")))
        })
    }
}

struct TerminalCheckpointOwner<'a> {
    original: &'a NativeThreadTurnOwner<NativeProductionAdmission>,
    native: &'a AgentdNativeHost,
    live: &'a codex_thread_store::LiveThread,
    stop: &'a TerminalStop,
}

impl TurnOwner for TerminalCheckpointOwner<'_> {
    async fn verify_current(&self, binding: &TurnBinding) -> Result<()> { self.original.verify_current(binding).await }
    async fn admit_model(&self, binding: &TurnBinding, sequence: usize, body: &[u8]) -> Result<ModelRequest> {
        self.original.admit_model(binding, sequence, body).await
    }
    async fn admit_tool(&self, binding: &TurnBinding, call: &ToolCall) -> Result<ToolAdmission> {
        self.original.admit_tool(binding, call).await
    }
    async fn checkpoint(&self, state: &TurnState) -> Result<()> {
        let selected = state.pending_model.is_none() && state.pending_tool.is_none() && state.final_answer.is_none()
            && state.model_calls == 1 && match self.stop.cut {
                TerminalCut::Model => state.tool_calls == 0 && !state.queued_tools.is_empty(),
                TerminalCut::Tool => state.tool_calls == 1 && state.completed_call_ids.len() == 1 && state.queued_tools.is_empty(),
                TerminalCut::PendingModel => false,
            };
        if !selected { return self.original.checkpoint(state).await; }
        let mut saved = state.clone();
        match self.stop.fault {
            ProjectionFault::None => {}
            ProjectionFault::Usage => { *saved.model_usage.last_mut().context("original usage missing")? = json!({"input_tokens":999,"output_tokens":4}); }
            ProjectionFault::Output => {
                saved.context.last_mut().context("original model output missing")?["arguments"] = json!("{\"changed\":true}");
            }
        }
        // Negative cases inject an inconsistent owner projection through the
        // real public checkpoint API. The original terminal receipt stays real
        // and unchanged; this is a corruption/refusal test, not a fake crash.
        self.original.checkpoint(&saved).await?;
        let (record, anchor, _) = self.native.read_hosted_checkpoint_record(self.live, &self.original.anchor().checkpoint).await?;
        ensure!(self.stop.captured.set((anchor, record)).is_ok(), "terminal cut was recorded twice");
        anyhow::bail!(CUT_REACHED)
    }
}

fn terminal_agent() -> NativeAgent {
    let mut native = agent();
    native.tools = vec![json!({"type":"function","name":"owned_process","description":"Run the owned fixture process",
        "parameters":{"type":"object","properties":{},"additionalProperties":false}})];
    native.limits.model_calls = 2;
    native.limits.tool_timeout = Duration::from_secs(15);
    native
}

async fn terminal_provider(call_id: &str, expected_posts: u64) -> MockServer {
    original_provider(call_id, expected_posts, false).await
}

async fn original_provider(call_id: &str, expected_posts: u64, pending_first: bool) -> MockServer {
    let server = MockServer::start().await;
    let call = json!({"type":"function_call","call_id":call_id,"name":"owned_process","arguments":"{}"});
    let answer = json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"native owner complete"}]});
    let mut replies = [(&call, "response-continuation-tool"), (&answer, "response-continuation-final")].into_iter().map(|(item, id)| {
        [json!({"type":"response.created","response":{"id":id}}),
            json!({"type":"response.output_item.done","item":item}),
            json!({"type":"response.completed","response":{"id":id,"status":"completed","output":[item],
                "usage":{"input_tokens":3,"output_tokens":4}}})]
            .into_iter().map(|event| format!("data: {event}\n\n")).collect::<String>()
    }).collect::<Vec<_>>();
    if pending_first {
        replies[0] = format!("data: {}\n\n", json!({"type":"response.created","response":{"id":"response-continuation-pending"}}));
        // The initial real stream closes after Created. The saved original
        // response can only complete through this original GET endpoint.
        Mock::given(method("GET")).and(path("/v1/responses/response-continuation-pending"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "id":"response-continuation-pending","status":"completed","output":[call],
                "usage":{"input_tokens":3,"output_tokens":4}
            }))).expect(1).mount(&server).await;
    }
    let received = Arc::new(AtomicUsize::new(0));
    Mock::given(method("POST")).and(path("/v1/responses")).respond_with(move |_request: &wiremock::Request| {
        match replies.get(received.fetch_add(1, Ordering::SeqCst)) {
            Some(events) => ResponseTemplate::new(200).set_body_raw(events.clone(), "text/event-stream"),
            None => ResponseTemplate::new(500).set_body_string("unexpected additional original model operation"),
        }
    }).expect(expected_posts).mount(&server).await;
    server
}

async fn terminal_fixture(server: &MockServer, cut: TerminalCut, fault: ProjectionFault,
    compiler: Arc<dyn NativeToolCompiler>) -> Result<(ObjectiveFixture, Arc<TerminalStop>)> {
    let stop = Arc::new(TerminalStop { cut, fault, captured: OnceLock::new(), ready: tokio::sync::Notify::new(),
        prepares: AtomicUsize::new(0), continuations: AtomicUsize::new(0) });
    let captured = stop.clone();
    let fixture = ObjectiveFixture::with_executor_adapter(server, ReplyFault::None, terminal_agent(), compiler,
        move |original, native| Arc::new(TerminalExecutor { original, native, agent: Arc::new(terminal_agent()), stop: captured })).await?;
    fixture.submit(fixture.request.clone()).await?;
    tokio::time::timeout(Duration::from_secs(25), stop.ready.notified()).await.context("original terminal cut was not reached")?;
    let error = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::Error(error) => Some(format!("{error:?}")), _ => None,
    }).await;
    ensure!(error.contains("outcome is unknown"), "original terminal cut must remain technically held: {error}");
    Ok((fixture, stop))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn terminal_continuation_rejects_changed_model_output_and_usage() -> Result<()> {
    for fault in [ProjectionFault::Usage, ProjectionFault::Output] {
        let server = terminal_provider("full-turn", 1).await;
        let (fixture, stop) = terminal_fixture(&server, TerminalCut::Model, fault, Arc::new(NoToolCompiler)).await?;
        assert_terminal_refusal(fixture, stop, &server, "model output or usage differs from the original terminal evidence").await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn terminal_continuation_rejects_an_unexplained_original_scope_operation() -> Result<()> {
    let server = terminal_provider("full-turn", 1).await;
    let (fixture, stop) = terminal_fixture(&server, TerminalCut::Model, ProjectionFault::None, Arc::new(NoToolCompiler)).await?;
    let (anchor, _) = stop.captured.get().context("original terminal checkpoint")?;
    let run = fixture.base.state.native_run_receipt(&anchor.checkpoint.operation_id)?;
    let admission = fixture.base.native.admission_with_policy(anchor.checkpoint.clone(), fixture.base.scope.clone(),
        codex_hepta_types::Generation::new(anchor.execution.as_ref().context("original policy")?.policy_generation)?, &run)?;
    let operation = OperationIntentV1::new(StableId::new("original-scope-unexplained-operation")?,
        StableId::new(fixture.base.writer.owner_agent_id().as_str())?, StableId::new(&admission.model_destination)?,
        Digest32::of_bytes(b"{}"), admission.scope_digest, admission.original_policy_generation, None)?;
    fixture.base.writer.prepare_operation(operation, crate::native_model_target::NATIVE_MODEL_TOPIC_V1, "{}").await?;
    assert_terminal_refusal(fixture, stop, &server, "original execution scope contains an unresolved or non-applied operation").await
}

async fn assert_terminal_refusal(fixture: ObjectiveFixture, stop: Arc<TerminalStop>, server: &MockServer,
    expected_error: &str) -> Result<()> {
    let (anchor, before) = stop.captured.get().context("original terminal cut")?;
    let epoch = idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?;
    fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest { turn_id: anchor.checkpoint.turn_id.clone(),
        expected_epoch: epoch, thread_settings: Default::default(), trace: None }).await?;
    let error = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::Error(error) => Some(format!("{error:?}")), _ => None,
    }).await;
    assert!(error.contains(expected_error), "must reject the original evidence mismatch: {error}");
    idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?;
    let session = fixture.core.thread_store.open_native_checkpoint(anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    assert_eq!(fixture.core.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(before.clone()));
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (1, 1));
    assert_eq!((stop.prepares.load(Ordering::SeqCst), stop.continuations.load(Ordering::SeqCst), fixture.owners.calls.load(Ordering::SeqCst)), (1, 1, 1));
    assert_eq!(server.received_requests().await.context("HTTP capture")?.len(), 1);
    assert_eq!(fixture.base.state.native_run_receipt(&anchor.checkpoint.operation_id)?.phase, RunPhase::Indeterminate);
    fixture.shutdown().await
}

#[cfg(target_os = "linux")]
async fn controlled_terminal_case(root: &std::path::Path, cut: TerminalCut, call_id: &str) -> Result<serde_json::Value> {
    use super::super::super::runtime_acceptance_tests::owned_fixture_compiler;
    tokio::fs::write(root.join("work").join(format!("{call_id}.release")), b"allow the one original child to finish").await?;
    let reconcile_first = matches!(cut, TerminalCut::PendingModel);
    let server = original_provider(call_id, 2, reconcile_first).await;
    let (fixture, stop) = terminal_fixture(&server, cut, ProjectionFault::None, owned_fixture_compiler(root)).await?;
    let (anchor, checkpoint) = stop.captured.get().context("actual terminal checkpoint cut")?;
    let (_, stopped) = crate::native_turn_checkpoint::decode(&checkpoint.state.payload, &anchor.checkpoint)?;
    assert!(stopped.pending_tool.is_none() && stopped.final_answer.is_none() && !stopped.cancelled);
    assert_eq!(stopped.pending_model.is_some(), reconcile_first);
    if reconcile_first {
        assert_eq!(stopped.provider_response_id.as_deref(), Some("response-continuation-pending"));
        assert!(stopped.last_error.is_some());
        let pending = stopped.pending_model.as_ref().context("original pending request")?;
        assert_eq!(fixture.base.writer.status(&pending.operation_id).await?, LocalOutcomeState::Indeterminate);
        assert!(!tokio::fs::try_exists(root.join("work").join(format!("{call_id}.attempts"))).await?);
    }
    assert_eq!(stopped.model_calls, 1);
    assert_eq!(stopped.tool_calls, usize::from(matches!(cut, TerminalCut::Tool)));
    let queue = anchor.queue.as_ref().context("original Queue binding")?;
    let persisted = fixture.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
        queue.client_id.clone(), queue.payload_sha256.clone()).await?.context("original persisted Queue binding")?;
    let session = fixture.core.thread_store.open_native_checkpoint(anchor.checkpoint.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let before = fixture.core.thread_store.load_native_checkpoint_chain(&session).await?;
    let expected_at_cut = if matches!(cut, TerminalCut::Tool) { 2 } else { 1 };
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces),
        (expected_at_cut, expected_at_cut));
    let epoch = idle_epoch(&fixture.core, &anchor.checkpoint.turn_id).await?;
    fixture.core.codex.recover_turn_if_idle(codex_core::RecoverTurnRequest { turn_id: anchor.checkpoint.turn_id.clone(),
        expected_epoch: epoch, thread_settings: Default::default(), trace: None }).await?;
    assert_eq!(completed_turn(&fixture.core).await?, anchor.checkpoint.turn_id);
    let after = fixture.core.thread_store.load_native_checkpoint_chain(&session).await?;
    assert!(after.starts_with(&before), "continuation must preserve the exact complete original prefix");
    let (after_anchor, completed) = crate::native_turn_checkpoint::decode(&after.last().context("continued checkpoint")?.state.payload, &anchor.checkpoint)?;
    assert_eq!(after_anchor, *anchor);
    assert_eq!((completed.model_calls, completed.tool_calls, completed.final_answer.as_deref()), (2, 1, Some("native owner complete")));
    assert_eq!(completed.completed_call_ids, vec![call_id.to_owned()]);
    assert_eq!(fixture.base.queue.observe_persisted_client_binding(anchor.checkpoint.thread_id,
        queue.client_id.clone(), queue.payload_sha256.clone()).await?, Some(persisted));
    assert!(fixture.queue.service()?.list(anchor.checkpoint.thread_id).await?.is_empty());
    let expected_hooks = if reconcile_first { 2 } else { 1 };
    assert_eq!((stop.prepares.load(Ordering::SeqCst), stop.continuations.load(Ordering::SeqCst), fixture.owners.calls.load(Ordering::SeqCst)), (1, expected_hooks, 1));
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (3, 3));
    let requests = server.received_requests().await.context("HTTP capture")?;
    assert_eq!(requests.iter().filter(|request| request.method.as_str() == "POST").count(), 2);
    assert_eq!(requests.iter().filter(|request| request.method.as_str() == "GET").count(), usize::from(reconcile_first));
    assert_eq!(requests.len(), 2 + usize::from(reconcile_first));
    let mut model_keys = BTreeSet::new();
    for request in requests.iter().filter(|request| request.method.as_str() == "POST") {
        let key = request.headers.get("idempotency-key").context("original model key")?.to_str()?;
        assert!(model_keys.insert(key.to_owned()));
        assert_eq!(fixture.base.writer.status(key).await?, LocalOutcomeState::Committed);
    }
    let pending = before.iter().map(|record| crate::native_turn_checkpoint::decode(&record.state.payload, &anchor.checkpoint))
        .collect::<Result<Vec<_>>>()?.into_iter().find_map(|(_, state)| state.pending_tool);
    let pending = match pending {
        Some(pending) => pending,
        None => after.iter().map(|record| crate::native_turn_checkpoint::decode(&record.state.payload, &anchor.checkpoint))
            .collect::<Result<Vec<_>>>()?.into_iter().find_map(|(_, state)| state.pending_tool).context("original tool admission missing")?,
    };
    let key = pending.intent.idempotency_key.as_str();
    let request = fixture.base.writer.resolve_operation_request(key, fixture.base.native.runtime.destination_id()).await?;
    let raw = fixture.base.native.runtime.observe_tool_evidence(&request, &pending.intent).await?.context("original raw output missing")?;
    let output = completed.context.iter().find(|item| item["type"] == "function_call_output" && item["call_id"] == call_id)
        .context("original canonical tool output missing")?;
    let projection: serde_json::Value = serde_json::from_str(output["output"].as_str().context("canonical tool output text")?)?;
    assert_eq!(projection["stdout"], json!(String::from_utf8_lossy(&raw.stdout)));
    assert_eq!(projection["stderr"], json!(String::from_utf8_lossy(&raw.stderr)));
    if call_id == "continuation-raw" {
        assert!(std::str::from_utf8(&raw.stdout).is_err() && std::str::from_utf8(&raw.stderr).is_err(),
            "raw-output case must use real non-UTF8 process bytes");
    }
    assert_eq!(fixture.base.writer.status(key).await?, LocalOutcomeState::Committed);
    assert!(fixture.base.native.host.begin_native_effect(fixture.base.native.runtime.destination_id(), key).await.is_err());
    let attempts = tokio::fs::read_to_string(root.join("work").join(format!("{call_id}.attempts"))).await?;
    assert_eq!(attempts.lines().count(), 1, "the original process must never run twice");
    let history = fixture.core.thread_store.load_latest_model_context(LoadThreadHistoryParams {
        thread_id: fixture.core.session_configured.thread_id, include_archived: false,
    }).await?;
    assert_eq!(history.items.iter().filter(|item| matches!(item, RolloutItem::EventMsg(EventMsg::ItemCompleted(event))
        if matches!(&event.item, TurnItem::UserMessage(message) if message.client_id.as_deref() == Some(queue.client_id.as_str())))).count(), 1);
    assert!(!history.items.iter().any(|item| matches!(item, RolloutItem::EventMsg(EventMsg::TurnAborted(_)))));
    let bindings = history.items.iter().filter_map(|item| match item {
        RolloutItem::TurnRecoveryRequestBinding(binding) if binding.turn_id == anchor.checkpoint.turn_id => Some(binding),
        _ => None,
    }).collect::<Vec<_>>();
    assert_eq!(bindings.len(), 2, "one explicit recovery must record only one original typed successor");
    assert_eq!(bindings[0], &anchor.recovery);
    assert_eq!(bindings[1].generation, bindings[0].generation + 1);
    assert_eq!(bindings[1].replay_applied_from_generation, Some(bindings[0].generation));
    let cut_name = match cut { TerminalCut::Model => "model_terminal", TerminalCut::Tool => "tool_terminal", TerminalCut::PendingModel => "pending_model_get_then_continue" };
    let report = json!({"cut":cut_name, "model_gets":usize::from(reconcile_first), "explicit_recovery_calls":1,
        "typed_recovery_successors":1,"model_posts":2,"real_child_attempts":1,"grants":3,"consumed_nonces":3,"queue_replaced":false,
        "non_utf8_raw_evidence":call_id == "continuation-raw","original_checkpoint_prefix_preserved":true});
    fixture.shutdown().await?;
    Ok(report)
}

#[cfg(target_os = "linux")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires explicit opt-in and the existing isolated original runtime process fixture"]
async fn controlled_original_terminal_checkpoint_continuations() -> Result<()> {
    use super::super::super::runtime_acceptance_tests::checkpoint_continuation_environment;
    let Some(root) = checkpoint_continuation_environment().await? else { return Ok(()); };
    let mut cases = Vec::new();
    for (cut, call_id) in [(TerminalCut::Model, "full-turn"), (TerminalCut::Tool, "continuation-raw"),
        (TerminalCut::PendingModel, "continuation-reconcile")] {
        cases.push(tokio::time::timeout(Duration::from_secs(35), controlled_terminal_case(&root, cut, call_id)).await
            .context("original terminal continuation exceeded its bounded fixture deadline")??);
    }
    tokio::fs::write(root.join("report.json"), serde_json::to_vec_pretty(&json!({
        "schema":"hepta.native.original-terminal-continuation.v1","passed":true,"cases":cases,
        "scope":"same original Core/Queue/ThreadStore/writer/FinalUse and runtime process owner",
        "model_provider":"controlled localhost HTTP/SSE","transport":"existing isolated SSH helper fixture",
        "ordinary_cli_bootstrap":false,"os_restart":false
    }))?).await?;
    Ok(())
}

#[path = "objective_native_lifecycle_recovery_tests.rs"]
mod lifecycle_recovery_tests;
