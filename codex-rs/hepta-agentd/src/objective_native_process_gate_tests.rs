//! Signed Objective model-to-process entry under the existing opt-in runtime
//! namespace. The issuer hook changes only original trust/time; actual jobs,
//! child launch, FinalUse and production operations remain their original owners.

use pretty_assertions::assert_eq;

use super::*;
use std::path::Path;
use std::sync::Mutex;

use serde_json::Value;
use super::super::runtime_acceptance_tests::{objective_process_environment, owned_fixture_compiler};

#[derive(Clone, Copy)]
enum AuthChange { Revoke, Expire }

impl AuthChange {
    fn reason(self) -> &'static str {
        match self { Self::Revoke => "Revoked", Self::Expire => "Expired" }
    }
}

async fn tool_provider() -> MockServer {
    let server = MockServer::start().await;
    let call = json!({"type":"function_call", "call_id":"full-turn", "name":"owned_process", "arguments":"{}"});
    let events = [
        json!({"type":"response.created", "response":{"id":"response-objective-tool"}}),
        json!({"type":"response.output_item.done", "item":call}),
        json!({"type":"response.completed", "response":{"id":"response-objective-tool", "status":"completed", "output":[call],
            "usage":{"input_tokens":3,"output_tokens":4}}}),
    ].into_iter().map(|event| format!("data: {event}\n\n")).collect::<String>();
    Mock::given(method("POST")).and(path("/v1/responses"))
        .respond_with(ResponseTemplate::new(200).set_body_raw(events, "text/event-stream"))
        .expect(1).mount(&server).await;
    server
}

fn change_on_tool_grant(fixture: &ObjectiveFixture, change: AuthChange,
    reached: Arc<AtomicBool>, checked_reason: Arc<Mutex<Option<String>>>) -> Result<()> {
    // Reuse the issuer's existing one-shot callback. The first (model) grant
    // arms the second (tool) callback only after its mutex was released.
    // A single-model-call budget excludes a second model grant in this test.
    fixture.change_trust_at_grant(true, /*key_epoch*/ 1)?;
    let revoke = fixture.base.issuer.before_grant_return.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?
        .take().context("original trust change callback")?;
    let issuer = Arc::downgrade(&fixture.base.issuer);
    let state = fixture.base.state.clone();
    let host = fixture.host.clone();
    let run_id = fixture.request.body.run_id.clone();
    let expires = fixture.request.expires_at_ms;
    let second_issuer = issuer.clone();
    let tool_callback = Box::new(move || {
        let current = second_issuer.upgrade().ok_or_else(|| AgentdError::Invalid("original issuer gone".to_owned()))?;
        if current.grants.load(Ordering::SeqCst) != 2 {
            return Err(AgentdError::Invalid("test expected the original tool's second grant".to_owned()));
        }
        reached.store(true, Ordering::SeqCst);
        match change {
            AuthChange::Revoke => revoke()?,
            AuthChange::Expire => {
                let entered = crate::authbus_ingress::now_ms()?;
                if entered >= expires {
                    return Err(AgentdError::Invalid("test missed the process pre-expiry entry window".to_owned()));
                }
                std::thread::sleep(Duration::from_millis(expires - entered + 1));
            }
        }
        let record = host.original_record(&run_id)?;
        let error = state.require_current_run_start(&record).err().ok_or_else(||
            AgentdError::Invalid("test did not invalidate the original Objective trust".to_owned()))?;
        let reason = error.to_string();
        if !reason.contains("durable run-start authentication is not current") || !reason.contains(change.reason()) {
            return Err(AgentdError::Invalid(format!("test reached another gate: {reason}")));
        }
        *checked_reason.lock().map_err(|error| AgentdError::Invalid(format!("checked auth reason: {error}")))? = Some(reason);
        Ok(())
    });
    *fixture.base.issuer.before_grant_return.lock().map_err(|error| anyhow::anyhow!(error.to_string()))? = Some(Box::new(move || {
        let original = issuer.upgrade().ok_or_else(|| AgentdError::Invalid("original issuer gone".to_owned()))?;
        if original.grants.load(Ordering::SeqCst) != 1 {
            return Err(AgentdError::Invalid("test expected the original model's first grant".to_owned()));
        }
        let mut callback = original.before_grant_return.lock().map_err(|error| AgentdError::Invalid(format!("issuer callback: {error}")))?;
        if callback.is_some() { return Err(AgentdError::Invalid("test callback was already armed".to_owned())); }
        *callback = Some(tool_callback);
        Ok(())
    }));
    Ok(())
}

async fn original_job(root: &Path, key: &str) -> Result<(std::path::PathBuf, Vec<u8>, Value)> {
    let mut jobs = tokio::fs::read_dir(root.join("state/jobs")).await?;
    let mut matches = Vec::new();
    while let Some(entry) = jobs.next_entry().await? {
        if entry.path().extension().and_then(|part| part.to_str()) != Some("json") { continue; }
        let bytes = tokio::fs::read(entry.path()).await?;
        let record: Value = serde_json::from_slice(&bytes)?;
        if record["idempotency_key"].as_str() == Some(key) { matches.push((entry.path(), bytes, record)); }
    }
    ensure!(matches.len() == 1, "original process key must identify one durable runtime job");
    matches.pop().context("original process record")
}

async fn no_physical_child(root: &Path) -> Result<()> {
    assert!(!tokio::fs::try_exists(root.join("work/full-turn.attempts")).await?, "a real workload child ran");
    assert!(!tokio::fs::try_exists(root.join("work/full-turn.marker")).await?, "a real workload child produced its marker");
    if tokio::fs::try_exists(root.join("transport.jsonl")).await? {
        let trace = tokio::fs::read_to_string(root.join("transport.jsonl")).await?;
        let events = trace.lines().map(serde_json::from_str::<Value>).collect::<serde_json::Result<Vec<_>>>()?;
        assert!(events.iter().all(|event| event["launch"] != true), "a process launch crossed the real transport boundary");
    }
    Ok(())
}

async fn exercise(root: &Path, change: AuthChange) -> Result<Value> {
    let started = std::time::Instant::now();
    let phase = |name: &str| eprintln!("OBJECTIVE_PROCESS_GATE case={} phase={name} elapsed_ms={}",
        change.reason(), started.elapsed().as_millis());
    phase("start");
    let server = tool_provider().await;
    let mut native = agent();
    native.tools = vec![json!({"type":"function", "name":"owned_process", "description":"Run the owned fixture process",
        "parameters":{"type":"object","properties":{},"additionalProperties":false}})];
    native.limits.tool_timeout = Duration::from_secs(15);
    let mut fixture = ObjectiveFixture::with_compiler(&server, ReplyFault::None, native, owned_fixture_compiler(root)).await?;
    phase("original_fixture_ready");
    if matches!(change, AuthChange::Expire) {
        let mut request = fixture.request.clone();
        request.expires_at_ms = now_ms()? + 10_000;
        fixture.sign(&mut request)?;
        fixture.request = request;
    }
    let reached = Arc::new(AtomicBool::new(false));
    let checked_reason = Arc::new(Mutex::new(None));
    change_on_tool_grant(&fixture, change, reached.clone(), checked_reason.clone())?;
    phase("before_signed_ingress");
    let submission = fixture.submit(fixture.request.clone()).await;
    phase("signed_ingress_returned");
    let turn_id = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::TurnStarted(started) => Some(started.turn_id.clone()), _ => None,
    }).await;
    phase("original_turn_started");
    super::auth_gate_tests::wait_for_held_original_turn(&fixture.core, &turn_id, Duration::from_secs(20)).await?;
    phase("original_turn_held");
    ensure!(reached.load(Ordering::SeqCst), "test never reached the original process grant; ingress: {submission:?}");
    let auth_reason = checked_reason.lock().map_err(|error| anyhow::anyhow!(error.to_string()))?.clone().context("original auth rejection missing")?;
    let record = fixture.host.original_record(&fixture.request.body.run_id)?;
    let original = NativeCheckpointBinding {
        thread_id: fixture.core.session_configured.thread_id, turn_id,
        operation_id: record.snapshot.run_id.to_string(), generation: record.snapshot.generation,
        lease_id: fixture.base.writer.lease_id().to_owned(),
    };
    let session = fixture.core.thread_store.open_native_checkpoint(original.clone(),
        NativeCheckpointOpenMode::Recover, Arc::new(ReadOriginalOnly)).await?;
    let NativeCheckpointLoad::Present(checkpoint) = fixture.core.thread_store.load_native_checkpoint(&session).await? else {
        anyhow::bail!("the original tool checkpoint disappeared");
    };
    let (anchor, state) = crate::native_turn_checkpoint::decode(&checkpoint.state.payload, &original)?;
    let pending = state.pending_tool.as_ref().context("original pending process intent")?;
    assert_eq!(anchor.checkpoint, original);
    assert_eq!((state.model_calls, state.tool_calls, state.pending_model.is_none(), state.final_answer.is_none()), (1, 1, true, true));
    assert!(pending.submission_attempted);
    assert_eq!(pending.call.call_id, "full-turn");
    assert!(state.context.iter().any(|item| item["type"] == "function_call" && item["call_id"] == "full-turn"));
    let run = fixture.base.state.native_run_receipt(&record.snapshot.run_id.to_string())?;
    assert_eq!(run.phase, RunPhase::Indeterminate);
    ensure!(run.deadline_ms > now_ms()?, "process rejection must not be a run-deadline failure");
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    let requests = server.received_requests().await.context("model HTTP capture")?;
    assert_eq!(requests.len(), 1, "only the original model call may reach the provider");
    let model_key = requests[0].headers.get("idempotency-key").context("original model operation")?.to_str()?;
    assert_eq!(fixture.base.writer.status(model_key).await?, LocalOutcomeState::Committed);
    let key = pending.intent.idempotency_key.as_str();
    let destination = fixture.base.native.runtime.destination_id();
    let operation = fixture.base.writer.resolve_operation_request(key, destination).await?;
    assert_eq!(operation.payload_json.as_bytes(), pending.arguments.as_slice());
    assert_eq!(fixture.base.writer.status(key).await?, LocalOutcomeState::Indeterminate);
    let params = fixture.base.native.runtime.original_params(&operation)?;
    let (job_path, before_job, job) = original_job(root, key).await?;
    phase("original_job_verified");
    assert_eq!(job["launch_state"], "launch_unknown");
    assert!(!tokio::fs::try_exists(root.join("remote/jobs").join(job["id"].as_str().context("original job id")?).join("launch.json")).await?);
    no_physical_child(root).await?;
    assert_eq!((fixture.base.issuer.grants.load(Ordering::SeqCst), fixture.base.final_use.capacity()?.used_nonces), (2, 1),
        "only the completed model may consume FinalUse; the tool must consume none");
    assert!(fixture.base.native.host.begin_native_effect(destination, key).await.is_err(), "unknown original tool must not mint another dispatch");
    let entries = AtomicUsize::new(0);
    phase("before_original_reobservation");
    let observed: Value = serde_json::from_str(&hepta_runtime::native::execute_or_observe_with_entry(params, |_| -> Result<()> {
        entries.fetch_add(1, Ordering::SeqCst);
        anyhow::bail!("existing unknown process must not reach physical entry again")
    }).await?)?;
    phase("original_reobservation_returned");
    assert_eq!((&observed["job"]["id"], &observed["reused"], &observed["retried_launch"]), (&job["id"], &json!(true), &json!(false)));
    assert_eq!(entries.load(Ordering::SeqCst), 0);
    assert_eq!(tokio::fs::read(job_path).await?, before_job);
    assert_eq!(fixture.base.writer.resolve_operation_request(key, destination).await?, operation);
    assert_eq!(fixture.core.thread_store.load_native_checkpoint(&session).await?, NativeCheckpointLoad::Present(checkpoint));
    assert_eq!(fixture.host.original_record(&record.snapshot.run_id.to_string())?, record);
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.base.issuer.grants.load(Ordering::SeqCst),
        fixture.base.final_use.capacity()?.used_nonces), (1, 2, 1));
    no_physical_child(root).await?;
    let result = json!({"case":change.reason(), "model_posts":1, "model_writer":"committed",
        "tool_operation":key, "job_id":job["id"], "tool_writer":"indeterminate", "auth_rejection":auth_reason,
        "final_use_grants":2, "model_nonce_consumed":1, "tool_nonce_consumed":0,
        "real_child_attempts":0, "transport_launches":0, "recreated_operations":0});
    phase("before_original_shutdown");
    fixture.shutdown().await?;
    phase("original_shutdown_complete");
    Ok(result)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires explicit opt-in, Linux bwrap namespaces, and original runtime process owner"]
async fn controlled_signed_objective_process_entry_gates() -> Result<()> {
    let Some(root) = objective_process_environment().await? else { return Ok(()); };
    let mut cases = Vec::new();
    for change in [AuthChange::Revoke, AuthChange::Expire] {
        cases.push(tokio::time::timeout(Duration::from_secs(25), exercise(&root, change)).await
            .with_context(|| format!("Objective process gate {} exceeded its bounded test deadline", change.reason()))??);
    }
    tokio::fs::write(root.join("report.json"), serde_json::to_vec_pretty(&json!({
        "schema":"hepta.native.objective-process-entry.v1", "passed":true,
        "scope":"signed Objective + original seven owners/Core Queue/ThreadStore + model tool intent + original writer/FinalUse + runtime process entry",
        "transport":"same controlled fixture and unchanged runtime helper", "ssh_systemd_jobctl_qualification":"held",
        "model_provider":"localhost HTTP/SSE fixture", "cases":cases,
    }))?).await?;
    Ok(())
}
