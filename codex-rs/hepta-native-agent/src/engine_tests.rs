//! End-to-end loop tests exercise stream loss and original-operation recovery.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Result;
use anyhow::bail;
use codex_hepta_types::*;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

use crate::*;

enum CancelOnCheckpoint {
    Model(CancellationToken),
    Tool(CancellationToken),
}

enum RevokeOnCheckpoint {
    Model,
    Tool,
}

struct Owner {
    generation: AtomicU64,
    model_admissions: AtomicUsize,
    snapshots: Mutex<Vec<TurnState>>,
    cancel_on_checkpoint: Mutex<Option<CancelOnCheckpoint>>,
    revoke_on_checkpoint: Mutex<Option<RevokeOnCheckpoint>>,
}

impl TurnOwner for Owner {
    async fn verify_current(&self, binding: &TurnBinding) -> Result<()> {
        if self.generation.load(Ordering::SeqCst) != binding.generation.get() {
            bail!("stale generation");
        }
        Ok(())
    }

    async fn checkpoint(&self, state: &TurnState) -> Result<()> {
        self.verify_current(&state.binding).await?;
        self.snapshots.lock().unwrap().push(state.clone());
        match self.cancel_on_checkpoint.lock().unwrap().as_ref() {
            Some(CancelOnCheckpoint::Model(cancel))
                if state.pending_model.is_some() && !state.cancelled =>
            {
                cancel.cancel()
            }
            Some(CancelOnCheckpoint::Tool(cancel))
                if state.pending_tool.as_ref().is_some_and(|pending| {
                    pending.submission_attempted && !pending.cancel_requested
                }) =>
            {
                cancel.cancel()
            }
            _ => {}
        }
        let revoke = match self.revoke_on_checkpoint.lock().unwrap().as_ref() {
            Some(RevokeOnCheckpoint::Model) => state.pending_model.is_some(),
            Some(RevokeOnCheckpoint::Tool) => state
                .pending_tool
                .as_ref()
                .is_some_and(|pending| pending.submission_attempted),
            None => false,
        };
        if revoke {
            // Model a host replacement after this exact snapshot is durable.
            self.generation.fetch_add(1, Ordering::SeqCst);
        }
        Ok(())
    }

    async fn admit_model(
        &self,
        binding: &TurnBinding,
        sequence: usize,
        exact_body: &[u8],
    ) -> Result<ModelRequest> {
        self.verify_current(binding).await?;
        self.model_admissions.fetch_add(1, Ordering::SeqCst);
        Ok(ModelRequest {
            operation_id: format!("{}:model:{sequence}", binding.operation_id),
            body: exact_body.to_vec(),
        })
    }

    async fn admit_tool(&self, binding: &TurnBinding, call: &ToolCall) -> Result<ToolAdmission> {
        self.verify_current(binding).await?;
        let organ = StableId::new("organ:fixture")?;
        let arguments = serde_json::to_vec(
            &json!({"compiled":true,"model":serde_json::from_slice::<Value>(&call.arguments)?}),
        )?;
        let arguments_digest = Digest32::of_bytes(&arguments);
        let intent = RuntimeToolIntentV1 {
            cell: CellExecutionIntentV1 {
                operation_id: StableId::new(format!("{}:{}", binding.operation_id, call.call_id))?,
                cell_id: StableId::new("cell:fixture")?,
                organ_id: organ.clone(),
                generation: binding.generation,
                kind: ExecutionIntentKindV1::RuntimeTool,
                codex_binding: None,
                input_digest: Digest32::of_bytes(&call.arguments),
                final_payload: FinalPayloadDigestV1 {
                    scope_id: organ,
                    generation: binding.generation,
                    payload_kind: StableId::new("tool.arguments")?,
                    digest: arguments_digest,
                },
                deadline_ms: u64::MAX,
            },
            tool_id: StableId::new(&call.name)?,
            arguments_digest,
            idempotency_key: StableId::new(format!("{}:{}", binding.operation_id, call.call_id))?,
            host_scope: StableId::new("fixture:host")?,
        };
        Ok(ToolAdmission { intent, arguments })
    }
}

enum Behavior {
    Success,
    LostAcknowledgement,
    NeverTerminal,
}

struct Tools {
    behavior: Behavior,
    dispatch_polls: AtomicUsize,
    starts: AtomicUsize,
    observations: AtomicUsize,
    cancellations: AtomicUsize,
    owner: Arc<Owner>,
}

impl ToolPort for Tools {
    async fn execute_or_observe(
        &self,
        intent: &RuntimeToolIntentV1,
        arguments: &[u8],
    ) -> Result<ToolObservation> {
        // Async function bodies start on their first poll, not construction.
        self.dispatch_polls.fetch_add(1, Ordering::SeqCst);
        assert_eq!(intent.arguments_digest, Digest32::of_bytes(arguments));
        assert_eq!(
            serde_json::from_slice::<Value>(arguments)?["compiled"],
            true
        );
        assert!(self.owner.snapshots.lock().unwrap().iter().any(|state| {
            state
                .pending_tool
                .as_ref()
                .is_some_and(|pending| pending.submission_attempted && pending.intent == *intent)
        }));
        self.starts.fetch_add(1, Ordering::SeqCst);
        if matches!(self.behavior, Behavior::LostAcknowledgement) {
            bail!("job accepted; response deliberately lost");
        }
        self.observe(intent).await
    }

    async fn observe(&self, intent: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        self.observations.fetch_add(1, Ordering::SeqCst);
        if matches!(self.behavior, Behavior::NeverTerminal) {
            return Ok(ToolObservation::Accepted);
        }
        let stdout = b"42\n".to_vec();
        let stderr = Vec::new();
        let tool_outcome = ToolOutcomeV1 {
            terminal_observed: true,
            exit_code: Some(0),
            stdout_digest: Some(Digest32::of_bytes(&stdout)),
            stderr_digest: Some(Digest32::of_bytes(&stderr)),
            retryable: false,
        };
        Ok(ToolObservation::Terminal {
            receipt: RuntimeReceiptV1 {
                execution: ExecutionReceiptV1 {
                    operation_id: intent.cell.operation_id.clone(),
                    intent_digest: intent.cell.intent_digest(),
                    generation: intent.cell.generation,
                    final_payload_digest: intent.cell.final_payload.clone(),
                    outcome_digest: Some(tool_outcome.outcome_digest()),
                    status: ExecutionStatusV1::Completed,
                    recovery: RecoveryDispositionV1::None,
                    authority: AuthorityPosture::DENY_ALL,
                },
                runtime_intent_digest: intent.intent_digest(),
                tool_outcome,
            },
            stdout,
            stderr,
        })
    }

    async fn cancel(&self, _: &RuntimeToolIntentV1) -> Result<()> {
        self.cancellations.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

fn fixture(behavior: Behavior) -> Result<(NativeAgent, Arc<Owner>, Tools, TurnState)> {
    let owner = Arc::new(Owner {
        generation: AtomicU64::new(1),
        model_admissions: AtomicUsize::new(0),
        snapshots: Mutex::new(Vec::new()),
        cancel_on_checkpoint: Mutex::new(None),
        revoke_on_checkpoint: Mutex::new(None),
    });
    let tools = Tools {
        behavior,
        dispatch_polls: AtomicUsize::new(0),
        starts: AtomicUsize::new(0),
        observations: AtomicUsize::new(0),
        cancellations: AtomicUsize::new(0),
        owner: Arc::clone(&owner),
    };
    let agent = NativeAgent {
        model_name: "fixed-fixture".to_owned(),
        instructions: "Use the provided tool and report its result.".to_owned(),
        tools: vec![
            json!({"type":"function","name":"probe","description":"Compute a value","parameters":{"type":"object","properties":{}}}),
        ],
        store_responses: true,
        limits: Limits {
            context_bytes: 16 * 1024,
            output_tokens: 128,
            model_calls: 3,
            tool_calls: 2,
            tool_output_bytes: 4096,
            model_timeout: Duration::from_secs(2),
            tool_timeout: Duration::from_millis(40),
            observation_interval: Duration::from_millis(2),
        },
    };
    let state = TurnState::new(
        TurnBinding {
            thread_id: StableId::new("thread:original")?,
            turn_id: StableId::new("turn:original")?,
            operation_id: StableId::new("operation:original")?,
            generation: Generation::new(1)?,
        },
        "Calculate the value.".to_owned(),
    );
    Ok((agent, owner, tools, state))
}

fn body(response_id: &str, item: Value, complete: bool) -> String {
    let mut events = vec![
        json!({"type":"response.created","response":{"id":response_id}}),
        json!({"type":"response.output_item.done","item":item}),
    ];
    if complete {
        events.push(json!({"type":"response.completed","response":{
            "id":response_id,"status":"completed","usage":{"input_tokens":10,"output_tokens":5}
        }}));
    }
    events
        .into_iter()
        .map(|event| format!("data: {event}\n\n"))
        .collect()
}

fn tool_body(complete: bool) -> String {
    body(
        "resp-tool",
        json!({"type":"function_call","call_id":"call-original","name":"probe","arguments":"{}"}),
        complete,
    )
}

fn answer_body() -> String {
    body(
        "resp-answer",
        json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"42"}]}),
        true,
    )
}

async fn model_server(bodies: Vec<String>) -> Result<(ResponsesModel, Arc<Mutex<Vec<Value>>>)> {
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let requests = Arc::new(Mutex::new(Vec::new()));
    let captured = Arc::clone(&requests);
    tokio::spawn(async move {
        for body in bodies {
            let (mut socket, _) = listener.accept().await?;
            let mut data = Vec::new();
            let mut buffer = [0_u8; 4096];
            let header_end = loop {
                let n = socket.read(&mut buffer).await?;
                if n == 0 {
                    return Ok::<(), anyhow::Error>(());
                }
                data.extend_from_slice(&buffer[..n]);
                if let Some(at) = data.windows(4).position(|v| v == b"\r\n\r\n") {
                    break at + 4;
                }
            };
            let headers = String::from_utf8_lossy(&data[..header_end]);
            let length: usize = headers
                .lines()
                .find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("content-length")
                        .then(|| value.trim().parse().ok())
                        .flatten()
                })
                .unwrap_or(0);
            while data.len() < header_end + length {
                let n = socket.read(&mut buffer).await?;
                if n == 0 {
                    bail!("request body incomplete");
                }
                data.extend_from_slice(&buffer[..n]);
            }
            let captured_request = if length == 0 {
                json!({"request_line":String::from_utf8_lossy(&data[..header_end]).lines().next()})
            } else {
                serde_json::from_slice(&data[header_end..header_end + length])?
            };
            captured.lock().unwrap().push(captured_request);
            let content_type = if body.starts_with('{') {
                "application/json"
            } else {
                "text/event-stream"
            };
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            socket.write_all(response.as_bytes()).await?;
            socket.shutdown().await?;
        }
        Ok(())
    });
    Ok((
        ResponsesModel::new(
            &HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
            format!("http://{address}/v1/responses"),
            None,
            Duration::from_secs(2),
            64 * 1024,
        )?,
        requests,
    ))
}

#[tokio::test]
async fn real_stream_tool_feedback_and_final_answer_complete_one_turn() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    let (model, requests) = model_server(vec![tool_body(true), answer_body()]).await?;
    assert_eq!(
        agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new()
            )
            .await?,
        RunOutcome::Completed("42".to_owned())
    );
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    let requests = requests.lock().unwrap();
    assert_eq!(requests.len(), 2);
    assert_eq!(requests[1]["input"][2]["type"], "function_call_output");
    assert!(
        requests[1]["input"][2]["output"]
            .as_str()
            .unwrap()
            .contains("42")
    );
    Ok(())
}

#[tokio::test]
async fn lost_tool_acknowledgement_recovers_original_operation_without_another_start() -> Result<()>
{
    let (agent, owner, tools, mut state) = fixture(Behavior::LostAcknowledgement)?;
    let (model, _) = model_server(vec![tool_body(true), answer_body()]).await?;
    let cancel = CancellationToken::new();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingTool
    );
    let original = state.pending_tool.as_ref().unwrap().intent.clone();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::Completed("42".to_owned())
    );
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    assert!(
        owner
            .snapshots
            .lock()
            .unwrap()
            .iter()
            .filter_map(|s| s.pending_tool.as_ref())
            .all(|pending| pending.intent == original)
    );
    Ok(())
}

#[tokio::test]
async fn model_disconnect_never_executes_staged_tool_or_resubmits_post() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    let (model, requests) = model_server(vec![tool_body(false)]).await?;
    let cancel = CancellationToken::new();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingModel
    );
    let original = state.pending_model.as_ref().unwrap().operation_id.clone();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingModel
    );
    assert_eq!(state.pending_model.as_ref().unwrap().operation_id, original);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(requests.lock().unwrap().len(), 1);
    Ok(())
}

#[tokio::test]
async fn tool_timeout_requests_cancel_and_remains_pending_until_observed_terminal() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::NeverTerminal)?;
    let (model, _) = model_server(vec![tool_body(true)]).await?;
    let cancel = CancellationToken::new();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingTool
    );
    assert_eq!(tools.cancellations.load(Ordering::SeqCst), 1);
    assert!(state.pending_tool.as_ref().unwrap().cancel_requested);
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingTool
    );
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    assert_eq!(state.final_answer, None);
    Ok(())
}

async fn checkpoint_unsubmitted_tool(
    owner: &Owner,
    state: &mut TurnState,
) -> Result<RuntimeToolIntentV1> {
    let call = ToolCall {
        call_id: "call-before-start".to_owned(),
        name: "probe".to_owned(),
        arguments: b"{}".to_vec(),
    };
    let admission = owner.admit_tool(&state.binding, &call).await?;
    let intent = admission.intent.clone();
    state.pending_tool = Some(PendingTool {
        call,
        intent: admission.intent,
        arguments: admission.arguments,
        submission_attempted: false,
        cancel_requested: false,
    });
    state.tool_calls = 1;
    owner.checkpoint(state).await?;
    Ok(intent)
}

#[tokio::test]
async fn cancellation_before_first_tool_submission_survives_a_fresh_token_restart() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::NeverTerminal)?;
    let original = checkpoint_unsubmitted_tool(owner.as_ref(), &mut state).await?;
    let (model, requests) = model_server(Vec::new()).await?;
    let cancelled = CancellationToken::new();
    cancelled.cancel();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancelled)
            .await?,
        RunOutcome::PendingTool,
    );
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.cancellations.load(Ordering::SeqCst), 1);

    // Restore the owner's committed snapshot, rather than reusing only live state.
    let mut restored = owner.snapshots.lock().unwrap().last().unwrap().clone();
    assert!(restored.cancelled);
    assert!(restored.pending_tool.as_ref().unwrap().cancel_requested);
    assert!(!restored.pending_tool.as_ref().unwrap().submission_attempted);
    assert_eq!(
        agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut restored,
                &CancellationToken::new()
            )
            .await?,
        RunOutcome::PendingTool,
    );
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 1);
    assert_eq!(tools.cancellations.load(Ordering::SeqCst), 1);
    assert!(requests.lock().unwrap().is_empty());
    let pending = restored.pending_tool.as_ref().unwrap();
    assert_eq!(pending.intent, original);
    assert!(!pending.submission_attempted);
    assert!(
        owner
            .snapshots
            .lock()
            .unwrap()
            .iter()
            .filter_map(|s| s.pending_tool.as_ref())
            .all(|saved| saved.intent == original && !saved.submission_attempted)
    );
    Ok(())
}

#[tokio::test]
async fn either_persisted_cancellation_marker_forbids_a_first_tool_submission() -> Result<()> {
    for (cancel_requested, cancelled) in [(true, false), (false, true)] {
        let (agent, owner, tools, mut state) = fixture(Behavior::NeverTerminal)?;
        let original = checkpoint_unsubmitted_tool(owner.as_ref(), &mut state).await?;
        state.pending_tool.as_mut().unwrap().cancel_requested = cancel_requested;
        state.cancelled = cancelled;
        owner.checkpoint(&state).await?;
        let mut restored = owner.snapshots.lock().unwrap().last().unwrap().clone();
        let (model, _) = model_server(Vec::new()).await?;
        for _ in 0..2 {
            assert_eq!(
                agent
                    .run(
                        owner.as_ref(),
                        &tools,
                        &model,
                        &mut restored,
                        &CancellationToken::new()
                    )
                    .await?,
                RunOutcome::PendingTool,
            );
        }
        let pending = restored.pending_tool.as_ref().unwrap();
        assert_eq!(pending.intent, original);
        assert!(!pending.submission_attempted);
        assert!(pending.cancel_requested);
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
        assert_eq!(
            tools.cancellations.load(Ordering::SeqCst),
            if cancelled { 1 } else { 0 }
        );
        assert_eq!(
            tools.observations.load(Ordering::SeqCst),
            if cancelled { 1 } else { 2 }
        );
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn stale_generation_cannot_resume_pending_tool() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::LostAcknowledgement)?;
    let (model, _) = model_server(vec![tool_body(true)]).await?;
    let cancel = CancellationToken::new();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingTool
    );
    owner.generation.store(2, Ordering::SeqCst);
    assert!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await
            .is_err()
    );
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn assembled_context_budget_is_checked_before_model_admission() -> Result<()> {
    let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    agent.limits.context_bytes = 8;
    let (model, requests) = model_server(Vec::new()).await?;
    assert!(
        agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new()
            )
            .await
            .is_err()
    );
    assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 0);
    assert!(requests.lock().unwrap().is_empty());
    Ok(())
}

#[tokio::test]
async fn disconnected_model_is_recovered_by_original_response_get_without_replaying_post()
-> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    let observed = json!({
        "id":"resp-tool", "status":"completed",
        "output":[{"type":"function_call","call_id":"call-original","name":"probe","arguments":"{}"}],
        "usage":{"input_tokens":10,"output_tokens":5}
    }).to_string();
    let (model, requests) = model_server(vec![tool_body(false), observed, answer_body()]).await?;
    let cancel = CancellationToken::new();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingModel
    );
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    let original = state.pending_model.as_ref().unwrap().operation_id.clone();
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::Completed("42".to_owned())
    );
    assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 2);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    let requests = requests.lock().unwrap();
    assert_eq!(requests.len(), 3);
    assert_eq!(
        requests[1]["request_line"],
        "GET /v1/responses/resp-tool HTTP/1.1"
    );
    assert!(
        owner
            .snapshots
            .lock()
            .unwrap()
            .iter()
            .filter_map(|s| s.pending_model.as_ref())
            .any(|pending| pending.operation_id == original)
    );
    Ok(())
}

#[tokio::test]
async fn cancellation_during_submission_checkpoint_never_polls_first_dispatch() -> Result<()> {
    let (model, requests) = model_server(Vec::new()).await?;
    // Exercise multiple scheduler choices: an unbiased select may otherwise
    // hide the two-ready-branches race by choosing cancellation on one run.
    for _ in 0..32 {
        let (agent, owner, tools, mut state) = fixture(Behavior::NeverTerminal)?;
        let original = checkpoint_unsubmitted_tool(owner.as_ref(), &mut state).await?;
        let cancel = CancellationToken::new();
        *owner.cancel_on_checkpoint.lock().unwrap() =
            Some(CancelOnCheckpoint::Tool(cancel.clone()));
        assert!(!cancel.is_cancelled());
        assert_eq!(
            agent
                .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
                .await?,
            RunOutcome::PendingTool
        );
        assert!(cancel.is_cancelled());
        assert_eq!(tools.dispatch_polls.load(Ordering::SeqCst), 0);
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
        assert_eq!(tools.observations.load(Ordering::SeqCst), 0);
        assert_eq!(tools.cancellations.load(Ordering::SeqCst), 1);

        let mut restored = owner.snapshots.lock().unwrap().last().unwrap().clone();
        let pending = restored.pending_tool.as_ref().unwrap();
        assert!(restored.cancelled);
        assert!(pending.submission_attempted);
        assert!(pending.cancel_requested);
        assert_eq!(pending.intent, original);
        assert_eq!(
            agent
                .run(
                    owner.as_ref(),
                    &tools,
                    &model,
                    &mut restored,
                    &CancellationToken::new()
                )
                .await?,
            RunOutcome::PendingTool
        );
        assert_eq!(tools.dispatch_polls.load(Ordering::SeqCst), 0);
        assert_eq!(tools.observations.load(Ordering::SeqCst), 1);
        assert_eq!(tools.cancellations.load(Ordering::SeqCst), 1);
        assert_eq!(restored.pending_tool.as_ref().unwrap().intent, original);
    }
    assert!(requests.lock().unwrap().is_empty());
    Ok(())
}

#[tokio::test]
async fn cancellation_during_model_checkpoint_keeps_original_post_pending_without_sending_it()
-> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    let (model, requests) = model_server(vec![answer_body()]).await?;
    let cancel = CancellationToken::new();
    *owner.cancel_on_checkpoint.lock().unwrap() = Some(CancelOnCheckpoint::Model(cancel.clone()));
    assert!(!cancel.is_cancelled());
    assert_eq!(
        agent
            .run(owner.as_ref(), &tools, &model, &mut state, &cancel)
            .await?,
        RunOutcome::PendingModel
    );
    assert!(cancel.is_cancelled());
    assert!(state.cancelled);
    assert!(state.provider_response_id.is_none());
    let original = state.pending_model.as_ref().unwrap().clone();
    let mut restored = owner.snapshots.lock().unwrap().last().unwrap().clone();
    assert_eq!(
        agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut restored,
                &CancellationToken::new()
            )
            .await?,
        RunOutcome::PendingModel
    );
    assert_eq!(
        restored.pending_model.as_ref().unwrap().operation_id,
        original.operation_id
    );
    assert_eq!(restored.pending_model.as_ref().unwrap().body, original.body);
    assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
    assert_eq!(restored.model_calls, 1);
    assert_eq!(tools.dispatch_polls.load(Ordering::SeqCst), 0);
    assert!(requests.lock().unwrap().is_empty());
    assert!(restored.final_answer.is_none());
    Ok(())
}

#[tokio::test]
async fn owner_revoked_after_model_checkpoint_cannot_send_the_admitted_post() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::Success)?;
    // A regression would reach this real HTTP peer before any response checkpoint
    // discovers the stale owner; merely asserting run() failed would miss it.
    let (model, requests) = model_server(vec![answer_body()]).await?;
    *owner.revoke_on_checkpoint.lock().unwrap() = Some(RevokeOnCheckpoint::Model);
    let error = agent
        .run(
            owner.as_ref(),
            &tools,
            &model,
            &mut state,
            &CancellationToken::new(),
        )
        .await
        .unwrap_err();
    assert_eq!(error.to_string(), "stale generation");
    assert!(requests.lock().unwrap().is_empty());

    let mut restored = owner.snapshots.lock().unwrap().last().unwrap().clone();
    let original = restored.pending_model.as_ref().unwrap().clone();
    let binding = restored.binding.clone();
    assert_eq!(restored.provider_response_id, None);
    assert_eq!(restored.final_answer, None);
    assert_eq!(
        agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut restored,
                &CancellationToken::new(),
            )
            .await
            .unwrap_err()
            .to_string(),
        "stale generation"
    );
    let pending = restored.pending_model.as_ref().unwrap();
    assert_eq!(
        (
            restored.binding,
            pending.operation_id.clone(),
            pending.body.clone(),
        ),
        (binding, original.operation_id, original.body)
    );
    assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
    assert_eq!(owner.snapshots.lock().unwrap().len(), 1);
    assert_eq!(tools.dispatch_polls.load(Ordering::SeqCst), 0);
    assert!(requests.lock().unwrap().is_empty());
    Ok(())
}

#[tokio::test]
async fn owner_revoked_after_tool_checkpoint_cannot_poll_first_dispatch() -> Result<()> {
    let (agent, owner, tools, mut state) = fixture(Behavior::NeverTerminal)?;
    let original = checkpoint_unsubmitted_tool(owner.as_ref(), &mut state).await?;
    let binding = state.binding.clone();
    let (model, requests) = model_server(Vec::new()).await?;
    *owner.revoke_on_checkpoint.lock().unwrap() = Some(RevokeOnCheckpoint::Tool);
    assert_eq!(
        agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new(),
            )
            .await
            .unwrap_err()
            .to_string(),
        "stale generation"
    );
    let mut restored = owner.snapshots.lock().unwrap().last().unwrap().clone();
    assert_eq!(restored.binding, binding);
    let pending = restored.pending_tool.as_ref().unwrap();
    assert_eq!(
        (
            pending.intent.clone(),
            pending.submission_attempted,
            pending.cancel_requested,
        ),
        (original.clone(), true, false)
    );
    assert_eq!(
        agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut restored,
                &CancellationToken::new(),
            )
            .await
            .unwrap_err()
            .to_string(),
        "stale generation"
    );
    assert_eq!(restored.pending_tool.as_ref().unwrap().intent, original);
    assert_eq!(owner.snapshots.lock().unwrap().len(), 2);
    assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 0);
    assert_eq!(
        (
            tools.dispatch_polls.load(Ordering::SeqCst),
            tools.starts.load(Ordering::SeqCst),
            tools.observations.load(Ordering::SeqCst),
            tools.cancellations.load(Ordering::SeqCst),
        ),
        (0, 0, 0, 0)
    );
    assert!(requests.lock().unwrap().is_empty());
    Ok(())
}
