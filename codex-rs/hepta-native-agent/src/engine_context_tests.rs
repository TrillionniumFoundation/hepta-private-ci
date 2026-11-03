//! Byte-boundary regressions use the existing real HTTP loop fixtures. They do
//! not assert tokenizer counts or substitute fixtures for production receipts.

use super::*;
use anyhow::Context;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn oversized_initial_item_is_rejected_before_model_admission() -> Result<()> {
    enum Fragment {
        Input,
        Instructions,
        System,
        Developer,
        ToolDefinition,
    }
    for fragment in [
        Fragment::Input,
        Fragment::Instructions,
        Fragment::System,
        Fragment::Developer,
        Fragment::ToolDefinition,
    ] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        agent.limits.context_bytes = 128 * 1024;
        let policy = agent.context_policy()?;
        match fragment {
            Fragment::Input => {
                let empty = json!({"role":"user", "content":""});
                let overhead = serde_json::to_vec(&empty)?.len();
                state.context = vec![
                    json!({"role":"user", "content":"x".repeat(policy.message_item_bytes - overhead)}),
                ];
                // A serialized item at the boundary remains accepted without rewriting.
                let request: Value = serde_json::from_slice(&agent.model_request_body(&state)?)?;
                assert_eq!(request["input"], json!(state.context));
                state.context[0]["content"] =
                    json!("x".repeat(policy.message_item_bytes - overhead + 1));
            }
            Fragment::Instructions => agent.instructions = "\n".repeat(policy.host_item_bytes / 2),
            Fragment::System | Fragment::Developer => {
                let role = if matches!(fragment, Fragment::System) {
                    "system"
                } else {
                    "developer"
                };
                let empty = json!({"type":"message", "role":role, "content":""});
                let overhead = serde_json::to_vec(&empty)?.len();
                state.context = vec![json!({"type":"message", "role":role,
                    "content":"x".repeat(policy.host_item_bytes - overhead)})];
                let request: Value = serde_json::from_slice(&agent.model_request_body(&state)?)?;
                assert_eq!(request["input"], json!(state.context));
                state.context[0]["content"] =
                    json!("x".repeat(policy.host_item_bytes - overhead + 1));
            }
            Fragment::ToolDefinition => agent.tools[0]["description"] = json!("\n".repeat(4096)),
        }
        let original = state.context.clone();
        assert_eq!(
            agent
                .model_request_body(&state)
                .expect_err("oversized fragment cannot form a request")
                .to_string(),
            "native context item exceeds serialized byte limit"
        );
        let (model, requests) = model_server(Vec::new()).await?;
        let error = agent
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new(),
            )
            .await
            .expect_err("oversized initial fragment must be held");
        assert_eq!(
            error.to_string(),
            "native context item exceeds serialized byte limit"
        );
        assert_eq!(state.context, original);
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 0);
        assert!(owner.snapshots.lock().unwrap().is_empty());
        assert!(requests.lock().unwrap().is_empty());
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn excessive_output_budget_is_held_before_admission_or_any_http() -> Result<()> {
    for output_tokens in [8193, u32::MAX] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        agent.limits.output_tokens = output_tokens;
        let original = state.context.clone();
        let (model, requests) = model_server(Vec::new()).await?;
        assert_eq!(
            agent.model_request_body(&state).unwrap_err().to_string(),
            "native requested output token budget must be between 1 and 8192"
        );
        assert_eq!(
            agent
                .run(
                    owner.as_ref(),
                    &tools,
                    &model,
                    &mut state,
                    &CancellationToken::new()
                )
                .await
                .unwrap_err()
                .to_string(),
            "native requested output token budget must be between 1 and 8192"
        );
        assert_eq!(state.context, original);
        assert!(state.pending_model.is_none());
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 0);
        assert!(owner.snapshots.lock().unwrap().is_empty());
        assert!(requests.lock().unwrap().is_empty());
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn oversized_tool_call_cannot_borrow_a_long_message_role() -> Result<()> {
    for role in ["user", "assistant"] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        agent.limits.context_bytes = 64 * 1024;
        let original = state.context.clone();
        let item = json!({"type":"function_call", "role":role, "call_id":"call-original", "name":"probe",
            "arguments":json!({"data":"x".repeat(8192)}).to_string()});
        let terminal = json!({"id":"resp-role-disguise", "status":"completed", "output":[item],
            "usage":{"input_tokens":10,"output_tokens":5}});
        let wire = [
            json!({"type":"response.created", "response":{"id":"resp-role-disguise"}}),
            json!({"type":"response.output_item.done", "item":item}),
            json!({"type":"response.completed", "response":terminal}),
        ]
        .into_iter()
        .map(|event| format!("data: {event}\n\n"))
        .collect();
        let (model, requests) =
            model_server_with_limit(vec![wire, terminal.to_string()], 128 * 1024).await?;
        let mut operation = None;
        for _ in 0..2 {
            assert_eq!(
                agent
                    .run(
                        owner.as_ref(),
                        &tools,
                        &model,
                        &mut state,
                        &CancellationToken::new()
                    )
                    .await
                    .unwrap_err()
                    .to_string(),
                "native context item exceeds serialized byte limit"
            );
            assert_eq!(state.context, original);
            assert!(state.queued_tools.is_empty());
            assert!(state.pending_tool.is_none());
            let pending = state
                .pending_model
                .as_ref()
                .context("original model remains pending")?;
            let identity = (pending.operation_id.clone(), pending.body.clone());
            if let Some(before) = &operation {
                assert_eq!(&identity, before);
            } else {
                operation = Some(identity);
            }
            state = owner
                .snapshots
                .lock()
                .unwrap()
                .last()
                .context("original committed state")?
                .clone();
        }
        assert_eq!(owner.model_admissions.load(Ordering::SeqCst), 1);
        assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
        let requests = requests.lock().unwrap();
        assert_eq!(requests.len(), 2);
        assert_eq!(
            requests[1]["request_line"],
            "GET /v1/responses/resp-role-disguise HTTP/1.1"
        );
    }
    Ok(())
}

#[test]
fn injected_instruction_limit_preserves_original_long_chat_and_frozen_output_cap() -> Result<()> {
    let (mut agent, _, _, mut state) = fixture(Behavior::Success)?;
    agent.limits.context_bytes = 128 * 1024;
    agent.limits.output_tokens = 8192;
    agent.instructions = "x".repeat(8190); // The JSON string quotes are included.
    let text = "细胞学习与工具反馈。".repeat(700);
    assert!(text.len() > 20 * 1024);
    state.context = vec![
        json!({"role":"user", "content":text}),
        json!({"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":text}]}),
    ];
    let original = state.context.clone();
    let request: Value = serde_json::from_slice(&agent.model_request_body(&state)?)?;
    assert_eq!(request["instructions"], agent.instructions);
    assert_eq!(request["input"], json!(original));
    assert_eq!(request["max_output_tokens"], 8192);
    assert_eq!(state.context, original);
    agent.instructions.push('x');
    assert_eq!(
        agent.model_request_body(&state).unwrap_err().to_string(),
        "native context item exceeds serialized byte limit"
    );
    assert_eq!(state.context, original);
    Ok(())
}

#[tokio::test]
async fn whole_model_batch_is_checked_before_any_context_or_pending_state_change() -> Result<()> {
    for accumulated_limit in [false, true] {
        let (mut agent, owner, tools, mut state) = fixture(Behavior::Success)?;
        agent.limits.context_bytes = if accumulated_limit {
            8 * 1024
        } else {
            64 * 1024
        };
        if accumulated_limit {
            state.context = vec![json!({"role":"user", "content":"i".repeat(4_000)})];
        }
        let original_context = state.context.clone();
        let items = vec![
            json!({"type":"function_call", "call_id":"call-original", "name":"probe", "arguments":"{}"}),
            json!({"type":"message", "role":"assistant", "content":[{
                "type":"output_text", "text":"x".repeat(if accumulated_limit { 4_500 } else { 64 * 1024 })
            }]}),
        ];
        let mut events = vec![json!({"type":"response.created", "response":{"id":"resp-bound"}})];
        events.extend(
            items
                .iter()
                .map(|item| json!({"type":"response.output_item.done", "item":item})),
        );
        let terminal = json!({"id":"resp-bound", "status":"completed", "output":items, "usage":{"output_tokens":5}});
        events.push(json!({"type":"response.completed", "response":terminal}));
        let stream = events
            .into_iter()
            .map(|event| format!("data: {event}\n\n"))
            .collect();
        let (model, requests) =
            model_server_with_limit(vec![stream, terminal.to_string()], 256 * 1024).await?;
        let expected_error = if accumulated_limit {
            "retained native context exceeds context byte budget"
        } else {
            "native context item exceeds serialized byte limit"
        };
        let mut original_request = None;
        for _ in 0..2 {
            let error = agent
                .run(
                    owner.as_ref(),
                    &tools,
                    &model,
                    &mut state,
                    &CancellationToken::new(),
                )
                .await
                .expect_err("complete oversized output must remain pending");
            assert_eq!(error.to_string(), expected_error);
            assert_eq!(state.context, original_context);
            assert!(state.queued_tools.is_empty());
            assert!(state.pending_tool.is_none());
            assert!(state.model_usage.is_empty());
            assert_eq!(state.final_answer, None);
            assert_eq!(state.provider_response_id.as_deref(), Some("resp-bound"));
            let request = state
                .pending_model
                .as_ref()
                .expect("original POST remains pending");
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
        assert_eq!(
            requests[1]["request_line"],
            "GET /v1/responses/resp-bound HTTP/1.1"
        );
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
            .run(
                owner.as_ref(),
                &tools,
                &model,
                &mut state,
                &CancellationToken::new(),
            )
            .await
            .expect_err("escaped output exceeding the serialized item cap must remain pending");
        assert_eq!(
            error.to_string(),
            "native context item exceeds serialized byte limit"
        );
        let mut expected_context = original_input.clone();
        expected_context.push(json!({"type":"function_call", "call_id":"call-original", "name":"probe", "arguments":"{}"}));
        assert_eq!(state.context, expected_context);
        assert!(state.completed_call_ids.is_empty());
        assert_eq!(state.final_answer, None);
        let pending = state
            .pending_tool
            .as_ref()
            .expect("original tool remains pending");
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
    let ToolObservation::Terminal {
        receipt,
        stdout,
        stderr,
    } = tools.observe(&original).await?
    else {
        anyhow::bail!("original fixture terminal disappeared");
    };
    receipt.validate_against(&original)?;
    assert_eq!(stdout, vec![0; 4096]);
    assert!(stderr.is_empty());
    assert_eq!(
        receipt.tool_outcome.stdout_digest,
        Some(Digest32::of_bytes(&stdout))
    );
    // The original bytes fit the raw budget; serialization expansion is the
    // rejection reason. The terminal evidence is never shortened to fit.
    assert_eq!(stdout.len(), agent.limits.tool_output_bytes);
    Ok(())
}

enum PresentationMode {
    Excerpt,
    Oversized,
    Never,
    ChangedBytes,
}

struct PresentingTools {
    original: Tools,
    mode: PresentationMode,
    presentations: AtomicUsize,
}

impl ToolPort for PresentingTools {
    async fn execute_or_observe(
        &self,
        intent: &RuntimeToolIntentV1,
        arguments: &[u8],
    ) -> Result<ToolObservation> {
        let mut observed = self.original.execute_or_observe(intent, arguments).await?;
        if matches!(self.mode, PresentationMode::ChangedBytes)
            && let ToolObservation::Terminal { stdout, .. } = &mut observed
        {
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

    async fn present_output(
        &self,
        intent: &RuntimeToolIntentV1,
        receipt: &RuntimeReceiptV1,
        stdout: &[u8],
        stderr: &[u8],
    ) -> Result<String> {
        self.presentations.fetch_add(1, Ordering::SeqCst);
        receipt.validate_against(intent)?;
        assert_eq!(
            receipt.tool_outcome.stdout_digest,
            Some(Digest32::of_bytes(stdout))
        );
        assert_eq!(
            receipt.tool_outcome.stderr_digest,
            Some(Digest32::of_bytes(stderr))
        );
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
    let tools = PresentingTools {
        original,
        mode: PresentationMode::Excerpt,
        presentations: AtomicUsize::new(0),
    };
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
    let output: Value = serde_json::from_str(
        state.context[2]["output"]
            .as_str()
            .context("model tool feedback")?,
    )?;
    assert_eq!(output["stdout_bytes"], 4096);
    assert_eq!(
        output["stdout_sha256"],
        Digest32::of_bytes(&vec![0; 4096]).to_string()
    );
    assert_eq!(tools.presentations.load(Ordering::SeqCst), 1);
    assert_eq!(tools.original.starts.load(Ordering::SeqCst), 1);
    assert_eq!(requests.lock().unwrap().len(), 2);
    assert!(state.pending_tool.is_none());
    Ok(())
}

#[tokio::test]
async fn output_gate_rejects_changed_evidence_before_presentation_and_bounds_rendering()
-> Result<()> {
    for mode in [PresentationMode::ChangedBytes, PresentationMode::Oversized] {
        let expected_presentations = usize::from(matches!(mode, PresentationMode::Oversized));
        let (agent, owner, original, mut state) = fixture(Behavior::Success)?;
        let tools = PresentingTools {
            original,
            mode,
            presentations: AtomicUsize::new(0),
        };
        let (model, requests) = model_server(vec![tool_body(true)]).await?;
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
        assert_eq!(
            tools.presentations.load(Ordering::SeqCst),
            expected_presentations
        );
        assert!(
            state
                .pending_tool
                .as_ref()
                .context("original pending tool")?
                .submission_attempted
        );
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
    let tools = PresentingTools {
        original,
        mode: PresentationMode::Never,
        presentations: AtomicUsize::new(0),
    };
    let (model, requests) = model_server(vec![tool_body(true)]).await?;
    for _ in 0..2 {
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
            RunOutcome::PendingTool
        );
        assert!(
            state
                .last_error
                .as_deref()
                .context("presentation failure")?
                .contains("presentation deadline")
        );
        state = owner
            .snapshots
            .lock()
            .unwrap()
            .last()
            .context("original durable pending state")?
            .clone();
        assert!(
            state
                .pending_tool
                .as_ref()
                .context("pending operation")?
                .submission_attempted
        );
        assert!(state.completed_call_ids.is_empty());
    }
    assert_eq!(tools.original.starts.load(Ordering::SeqCst), 1);
    assert_eq!(tools.presentations.load(Ordering::SeqCst), 2);
    assert_eq!(requests.lock().unwrap().len(), 1);
    Ok(())
}

#[test]
fn historical_request_excerpts_preserve_owner_history_pairs_and_current_exchange() -> Result<()> {
    let (mut agent, _, _, mut state) = fixture(Behavior::Success)?;
    agent.limits.context_bytes = 2400;
    state.context.extend([
        json!({"type":"function_call","call_id":"old-call","name":"probe","arguments":"{}"}),
        json!({"type":"function_call_output","call_id":"old-call","output":"细胞".repeat(900)}),
        json!({"type":"function_call","call_id":"current-call","name":"probe","arguments":"{\"current\":true}"}),
        json!({"type":"function_call_output","call_id":"current-call","output":"current result must stay exact"}),
    ]);
    let original = state.context.clone();
    let body = agent.model_request_body(&state)?;
    assert!(body.len() <= agent.limits.context_bytes);
    assert_eq!(body, agent.model_request_body(&state)?);
    assert_eq!(state.context, original);
    let request: Value = serde_json::from_slice(&body)?;
    let projected = request["input"].as_array().context("projected input")?;
    assert_eq!(projected.len(), original.len());
    for index in [0, 1, 3, 4] {
        assert_eq!(projected[index], original[index]);
    }
    assert_eq!(projected[2]["call_id"], original[2]["call_id"]);
    let excerpt = projected[2]["output"]
        .as_str()
        .context("historical excerpt")?;
    assert!(excerpt.contains(CONTEXT_PROJECTION_VERSION));
    assert!(excerpt.contains(&Digest32::of_bytes(&serde_json::to_vec(&original[2])?).to_string()));
    assert!(excerpt.contains("Omitted content remains in host history"));
    Ok(())
}

#[test]
fn budget_never_discards_current_inputs_or_latest_tool_evidence() -> Result<()> {
    let (mut agent, _, _, mut state) = fixture(Behavior::Success)?;
    agent.limits.context_bytes = 1200;
    state.context.extend([
        json!({"type":"function_call","call_id":"current-call","name":"probe","arguments":"{}"}),
        json!({"type":"function_call_output","call_id":"current-call","output":"x".repeat(1800)}),
    ]);
    let original = state.context.clone();
    assert!(agent.model_request_body(&state).is_err());
    assert_eq!(state.context, original);
    // The most recent user request remains intact even after older exchanges.
    state
        .context
        .push(json!({"role":"user","content":"u".repeat(1800)}));
    let original = state.context.clone();
    assert!(agent.model_request_body(&state).is_err());
    assert_eq!(state.context, original);
    Ok(())
}

#[test]
fn request_projection_preserves_the_entire_latest_parallel_exchange() -> Result<()> {
    let (mut agent, _, _, mut state) = fixture(Behavior::Success)?;
    agent.limits.context_bytes = 1800;
    state.context.extend([
        json!({"type":"function_call","call_id":"old","name":"probe","arguments":"{}"}),
        json!({"type":"function_call_output","call_id":"old","output":"old evidence".repeat(400)}),
        json!({"type":"message","role":"assistant","content":[{"type":"output_text","text":"current rationale".repeat(200),"annotations":[]}]}),
        json!({"type":"function_call","call_id":"parallel-a","name":"probe","arguments":"{}"}),
        json!({"type":"reasoning","summary":[]}),
        json!({"type":"function_call","call_id":"parallel-b","name":"probe","arguments":"{}"}),
        json!({"type":"function_call_output","call_id":"parallel-a","output":"first original result"}),
        json!({"type":"function_call_output","call_id":"parallel-b","output":"second original result"}),
    ]);
    let original = state.context.clone();
    // Excerpting old evidence is insufficient: the current model response
    // itself exceeds this request budget and must hold, without rewriting it.
    assert!(agent.model_request_body(&state).is_err());
    assert_eq!(state.context, original);
    agent.limits.context_bytes = 5200;
    let body = agent.model_request_body(&state)?;
    let request: Value = serde_json::from_slice(&body)?;
    for index in 3..original.len() {
        assert_eq!(request["input"][index], original[index]);
    }
    assert_ne!(request["input"][2], original[2]);
    assert_eq!(state.context, original);
    Ok(())
}

#[test]
fn explicit_context_policy_versions_and_bounds_are_part_of_the_host_binding() -> Result<()> {
    let (mut agent, _, _, _) = fixture(Behavior::Success)?;
    assert_ne!(CONTEXT_POLICY_VERSION, LEGACY_CONTEXT_POLICY_VERSION);
    agent.limits.context_bytes = 8 * 1024;
    let small = agent.context_policy()?;
    assert_eq!(small.message_item_bytes, 8 * 1024);
    agent.limits.context_bytes = 32 * 1024;
    let chat = agent.context_policy()?;
    assert_eq!(chat.message_item_bytes, 32 * 1024);
    assert_eq!(chat.host_item_bytes, 8 * 1024);
    assert_eq!(chat.tool_item_bytes, 8 * 1024);
    assert_ne!(small.binding_value(), chat.binding_value());
    assert_eq!(chat.binding_value()["version"], CONTEXT_POLICY_VERSION);
    assert_eq!(
        chat.binding_value()["request_projection_version"],
        CONTEXT_PROJECTION_VERSION
    );
    assert_eq!(chat.binding_value()["max_requested_output_tokens"], 8192);
    assert_eq!(
        chat.binding_value()["requested_output_tokens"],
        agent.limits.output_tokens
    );
    assert_eq!(
        chat.binding_value()["tokenizer_validation"],
        "not_performed"
    );
    agent.limits.output_tokens = 8192;
    assert_ne!(
        agent.context_policy()?.binding_value(),
        chat.binding_value()
    );
    agent.limits.context_bytes = 128 * 1024;
    assert_eq!(agent.context_policy()?.message_item_bytes, 64 * 1024);
    agent.limits.context_bytes = usize::MAX;
    assert!(agent.context_policy().is_err());
    Ok(())
}
