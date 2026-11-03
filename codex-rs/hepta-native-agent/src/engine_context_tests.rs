//! Byte-boundary regressions use the existing real HTTP loop fixtures. They do
//! not assert tokenizer counts or substitute fixtures for production receipts.

use super::*;
use anyhow::Context;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn oversized_initial_item_is_rejected_before_model_admission() -> Result<()> {
    enum Fragment { Input, Instructions, ToolDefinition }
    for fragment in [Fragment::Input, Fragment::Instructions, Fragment::ToolDefinition] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        agent.limits.context_bytes = 64 * 1024;
        match fragment {
            Fragment::Input => {
                let empty = json!({"role":"user", "content":""});
                let overhead = serde_json::to_vec(&empty)?.len();
                state.context = vec![json!({"role":"user", "content":"x".repeat(8 * 1024 - overhead)})];
                // A serialized item at the boundary remains accepted without rewriting.
                let request: Value = serde_json::from_slice(&agent.model_request_body(&state)?)?;
                assert_eq!(request["input"], json!(state.context));
                state.context[0]["content"] = json!("x".repeat(8 * 1024 - overhead + 1));
            }
            Fragment::Instructions => agent.instructions = "\n".repeat(4096),
            Fragment::ToolDefinition => agent.tools[0]["description"] = json!("\n".repeat(4096)),
        }
        let original = state.context.clone();
        assert_eq!(agent.model_request_body(&state).expect_err("oversized fragment cannot form a request").to_string(),
            "native context item exceeds serialized byte limit");
        let (model, requests) = model_server(Vec::new()).await?;
        let error = agent
            .run(owner.as_ref(), &tools, &model, &mut state, &CancellationToken::new())
            .await
            .expect_err("oversized initial fragment must be held");
        assert_eq!(error.to_string(), "native context item exceeds serialized byte limit");
        assert_eq!(state.context, original);
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 0);
        assert!(owner.snapshots.lock().unwrap().is_empty());
        assert!(requests.lock().unwrap().is_empty());
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn whole_model_batch_is_checked_before_any_context_or_pending_state_change() -> Result<()> {
    for accumulated_limit in [false, true] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        agent.limits.context_bytes = if accumulated_limit { 8 * 1024 } else { 64 * 1024 };
        if accumulated_limit {
            state.context = vec![json!({"role":"user", "content":"i".repeat(4_000)})];
        }
        let original_context = state.context.clone();
        let items = vec![
            json!({"type":"function_call", "call_id":"call-original", "name":"probe", "arguments":"{}"}),
            json!({"type":"message", "role":"assistant", "content":[{
                "type":"output_text", "text":"x".repeat(if accumulated_limit { 4_500 } else { 8 * 1024 })
            }]}),
        ];
        let mut events = vec![json!({"type":"response.created", "response":{"id":"resp-bound"}})];
        events.extend(items.iter().map(|item| json!({"type":"response.output_item.done", "item":item})));
        let terminal = json!({"id":"resp-bound", "status":"completed", "output":items, "usage":{"output_tokens":5}});
        events.push(json!({"type":"response.completed", "response":terminal}));
        let stream = events.into_iter().map(|event| format!("data: {event}\n\n")).collect();
        let (model, requests) = model_server(vec![stream, terminal.to_string()]).await?;
        let expected_error = if accumulated_limit {
            "retained native context exceeds context byte budget"
        } else {
            "native context item exceeds serialized byte limit"
        };
        let mut original_request = None;
        for _ in 0..2 {
            let error = agent
                .run(owner.as_ref(), &tools, &model, &mut state, &CancellationToken::new())
                .await
                .expect_err("complete oversized output must remain pending");
            assert_eq!(error.to_string(), expected_error);
            assert_eq!(state.context, original_context);
            assert!(state.queued_tools.is_empty());
            assert!(state.pending_tool.is_none());
            assert!(state.model_usage.is_empty());
            assert_eq!(state.final_answer, None);
            assert_eq!(state.provider_response_id.as_deref(), Some("resp-bound"));
            let request = state.pending_model.as_ref().expect("original POST remains pending");
            let identity = (request.operation_id.clone(), request.body.clone());
            if let Some(original) = &original_request {
                assert_eq!(&identity, original);
            } else {
                original_request = Some(identity);
            }
            // Recovery starts with the owner's actual last committed snapshot.
            state = owner.snapshots.lock().unwrap().last().unwrap().clone();
        }
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
        let requests = requests.lock().unwrap();
        assert_eq!(requests.len(), 2);
        assert_eq!(requests[1]["request_line"], "GET /v1/responses/resp-bound HTTP/1.1");
    }
    Ok(())
}

#[tokio::test]
async fn escaped_tool_output_stays_pending_without_truncation_or_another_dispatch() -> Result<()> {
    let (mut agent, owner, tools, mut state) = fixture(Behavior::EscapedOutput)?;
    agent.limits.context_bytes = 64 * 1024;
    let (model, requests) = model_server(vec![tool_body(true)]).await?;
    let original_input = state.context.clone();
    let mut original_intent = None;
    for _ in 0..2 {
        let error = agent
            .run(owner.as_ref(), &tools, &model, &mut state, &CancellationToken::new())
            .await
            .expect_err("escaped output exceeding the serialized item cap must remain pending");
        assert_eq!(error.to_string(), "native context item exceeds serialized byte limit");
        let mut expected_context = original_input.clone();
        expected_context.push(json!({"type":"function_call", "call_id":"call-original", "name":"probe", "arguments":"{}"}));
        assert_eq!(state.context, expected_context);
        assert!(state.completed_call_ids.is_empty());
        assert_eq!(state.final_answer, None);
        let pending = state.pending_tool.as_ref().expect("original tool remains pending");
        assert!(pending.submission_attempted);
        assert!(!pending.cancel_requested);
        if let Some(original) = &original_intent {
            assert_eq!(&pending.intent, original);
        } else {
            original_intent = Some(pending.intent.clone());
        }
        state = owner.snapshots.lock().unwrap().last().unwrap().clone();
    }
    assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
    assert_eq!(requests.lock().unwrap().len(), 1);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 2);
    let original = original_intent.expect("original intent");
    let ToolObservation::Terminal { receipt, stdout, stderr } = tools.observe(&original).await? else {
        anyhow::bail!("original fixture terminal disappeared");
    };
    receipt.validate_against(&original)?;
    assert_eq!(stdout, vec![0; 4096]);
    assert!(stderr.is_empty());
    assert_eq!(receipt.tool_outcome.stdout_digest, Some(Digest32::of_bytes(&stdout)));
    // The original bytes fit the raw budget; serialization expansion is the
    // rejection reason. The terminal evidence is never shortened to fit.
    assert_eq!(stdout.len(), agent.limits.tool_output_bytes);
    Ok(())
}


enum PresentationMode { Excerpt, Oversized, Never, ChangedBytes }

struct PresentingTools {
    original: Tools,
    mode: PresentationMode,
    presentations: AtomicUsize,
}

impl ToolPort for PresentingTools {
    async fn execute_or_observe(&self, intent: &RuntimeToolIntentV1, arguments: &[u8]) -> Result<ToolObservation> {
        let mut observed = self.original.execute_or_observe(intent, arguments).await?;
        if matches!(self.mode, PresentationMode::ChangedBytes)
            && let ToolObservation::Terminal { stdout, .. } = &mut observed {
            stdout.push(0);
        }
        Ok(observed)
    }

    async fn observe(&self, intent: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        self.original.observe(intent).await
    }

    async fn cancel(&self, intent: &RuntimeToolIntentV1) -> Result<()> {
        self.original.cancel(intent).await
    }

    async fn present_output(&self, intent: &RuntimeToolIntentV1, receipt: &RuntimeReceiptV1,
        stdout: &[u8], stderr: &[u8]) -> Result<String> {
        self.presentations.fetch_add(1, Ordering::SeqCst);
        receipt.validate_against(intent)?;
        assert_eq!(receipt.tool_outcome.stdout_digest, Some(Digest32::of_bytes(stdout)));
        assert_eq!(receipt.tool_outcome.stderr_digest, Some(Digest32::of_bytes(stderr)));
        match self.mode {
            PresentationMode::Excerpt => Ok(json!({
                "exit_code": receipt.tool_outcome.exit_code,
                "retained_operation": intent.idempotency_key.as_str(),
                "stdout_bytes": stdout.len(), "stdout_sha256": Digest32::of_bytes(stdout).to_string(),
                "stderr_bytes": stderr.len(), "stderr_sha256": Digest32::of_bytes(stderr).to_string(),
                "excerpt": "binary output retained by fixture tool owner",
            }).to_string()),
            PresentationMode::Oversized => Ok("x".repeat(8 * 1024)),
            PresentationMode::Never => std::future::pending().await,
            PresentationMode::ChangedBytes => anyhow::bail!("unverified output reached presentation"),
        }
    }
}

#[tokio::test]
async fn bounded_presentation_uses_verified_complete_bytes_for_model_feedback() -> Result<()> {
    let (mut agent, owner, original, mut state) = fixture(Behavior::EscapedOutput)?;
    agent.limits.context_bytes = 64 * 1024;
    let tools = PresentingTools { original, mode: PresentationMode::Excerpt, presentations: AtomicUsize::new(0) };
    let (model, requests) = model_server(vec![tool_body(true), answer_body()]).await?;
    assert_eq!(agent.run(owner.as_ref(), &tools, &model, &mut state, &CancellationToken::new()).await?,
        RunOutcome::Completed("42".to_owned()));
    let output: Value = serde_json::from_str(state.context[2]["output"].as_str().context("model tool feedback")?)?;
    assert_eq!(output["stdout_bytes"], 4096);
    assert_eq!(output["stdout_sha256"], Digest32::of_bytes(&vec![0; 4096]).to_string());
    assert_eq!(tools.presentations.load(Ordering::SeqCst), 1);
    assert_eq!(tools.original.starts.load(Ordering::SeqCst), 1);
    assert_eq!(requests.lock().unwrap().len(), 2);
    assert!(state.pending_tool.is_none());
    Ok(())
}

#[tokio::test]
async fn output_gate_rejects_changed_evidence_before_presentation_and_bounds_rendering() -> Result<()> {
    for mode in [PresentationMode::ChangedBytes, PresentationMode::Oversized] {
        let expected_presentations = usize::from(matches!(mode, PresentationMode::Oversized));
        let (agent, owner, original, mut state) = fixture(Behavior::Success)?;
        let tools = PresentingTools { original, mode, presentations: AtomicUsize::new(0) };
        let (model, requests) = model_server(vec![tool_body(true)]).await?;
        assert!(agent.run(owner.as_ref(), &tools, &model, &mut state, &CancellationToken::new()).await.is_err());
        assert_eq!(tools.presentations.load(Ordering::SeqCst), expected_presentations);
        assert!(state.pending_tool.as_ref().context("original pending tool")?.submission_attempted);
        assert!(state.completed_call_ids.is_empty());
        assert_eq!(state.context.len(), 2);
        assert_eq!(tools.original.starts.load(Ordering::SeqCst), 1);
        assert_eq!(requests.lock().unwrap().len(), 1);
    }
    Ok(())
}

#[tokio::test]
async fn presentation_deadline_recovers_the_same_tool_without_another_start() -> Result<()> {
    let (agent, owner, original, mut state) = fixture(Behavior::Success)?;
    let tools = PresentingTools { original, mode: PresentationMode::Never, presentations: AtomicUsize::new(0) };
    let (model, requests) = model_server(vec![tool_body(true)]).await?;
    for _ in 0..2 {
        assert_eq!(agent.run(owner.as_ref(), &tools, &model, &mut state, &CancellationToken::new()).await?,
            RunOutcome::PendingTool);
        assert!(state.last_error.as_deref().context("presentation failure")?.contains("presentation deadline"));
        state = owner.snapshots.lock().unwrap().last().context("original durable pending state")?.clone();
        assert!(state.pending_tool.as_ref().context("pending operation")?.submission_attempted);
        assert!(state.completed_call_ids.is_empty());
    }
    assert_eq!(tools.original.starts.load(Ordering::SeqCst), 1);
    assert_eq!(tools.presentations.load(Ordering::SeqCst), 2);
    assert_eq!(requests.lock().unwrap().len(), 1);
    Ok(())
}
