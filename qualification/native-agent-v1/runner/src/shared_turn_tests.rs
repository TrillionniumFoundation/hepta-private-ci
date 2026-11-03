//! Real file-backed shared owner; fake tool observations have no runtime effect.

use super::*;
use crate::owner::FixtureConfig;
use codex_hepta_types::*;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct Fixture {
    _root: tempfile::TempDir,
    session: PathBuf,
    config: FixtureConfig,
}

impl Fixture {
    fn new() -> Result<Self> {
        let root = tempfile::tempdir()?;
        let script = root.path().join("fixture.py");
        let data = root.path().join("data.txt");
        std::fs::write(&script, b"not executed")?;
        std::fs::write(&data, b"original data")?;
        let config = FixtureConfig {
            representative: false,
            host: "fixture".to_owned(),
            script: script.to_string_lossy().into_owned(),
            script_sha256: Digest32::of_bytes(b"not executed").to_string(),
            data: data.to_string_lossy().into_owned(),
            data_sha256: Digest32::of_bytes(b"original data").to_string(),
            cwd: root.path().to_string_lossy().into_owned(),
            tool_timeout_seconds: 2,
        };
        Ok(Self {
            session: root.path().join("session"),
            _root: root,
            config,
        })
    }
    fn open(&self) -> Result<(SessionOwner, TurnState)> {
        SessionOwner::open(
            self.session.clone(),
            "same-Codex-turn",
            "original input",
            self.config.clone(),
            json!({"scope":"hepta.qualification.turn-owner.v2", "parent_thread_id":"thread-original",
                "parent_turn_id":"turn-original", "max_calls":2}),
        )
    }
    fn open_legacy(&self) -> Result<(SessionOwner, TurnState)> {
        SessionOwner::open(
            self.session.clone(),
            "same-Codex-turn:legacy-call",
            "original input",
            self.config.clone(),
            json!({"original_per_call_policy":"retained without migration"}),
        )
    }
    fn admissions(&self) -> usize {
        std::fs::read_dir(&self.session)
            .unwrap()
            .filter_map(|row| row.ok())
            .filter(|row| row.file_name().to_string_lossy().starts_with("tool-"))
            .count()
    }
}

fn call(id: &str, task: &str) -> ToolCall {
    ToolCall {
        call_id: id.to_owned(),
        name: "hepta_probe".to_owned(),
        arguments: serde_json::to_vec(&json!({"task":task})).unwrap(),
    }
}

#[derive(Default)]
struct Tools {
    fail_dispatch: AtomicBool,
    starts: AtomicUsize,
    observations: AtomicUsize,
}

impl ToolPort for Tools {
    async fn execute_or_observe(
        &self,
        intent: &RuntimeToolIntentV1,
        arguments: &[u8],
    ) -> Result<ToolObservation> {
        assert_eq!(intent.arguments_digest, Digest32::of_bytes(arguments));
        self.starts.fetch_add(1, Ordering::SeqCst);
        if self.fail_dispatch.load(Ordering::SeqCst) {
            anyhow::bail!("original start acknowledgement lost");
        }
        self.observe(intent).await
    }
    async fn observe(&self, intent: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        self.observations.fetch_add(1, Ordering::SeqCst);
        let stdout = b"original terminal\n".to_vec();
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
        Ok(())
    }
}

#[derive(Default)]
struct PresentationTools {
    original: Tools,
    hold: AtomicBool,
    presentations: AtomicUsize,
}

impl ToolPort for PresentationTools {
    async fn execute_or_observe(
        &self,
        intent: &RuntimeToolIntentV1,
        arguments: &[u8],
    ) -> Result<ToolObservation> {
        self.original.execute_or_observe(intent, arguments).await
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
        if self.hold.load(Ordering::SeqCst) {
            return std::future::pending::<Result<String>>().await;
        }
        self.original
            .present_output(intent, receipt, stdout, stderr)
            .await
    }
}

#[tokio::test]
async fn same_turn_reopens_original_owner_and_keeps_each_admitted_tool_identity() -> Result<()> {
    let fixture = Fixture::new()?;
    let tools = Tools::default();
    let policy = ToolSessionPolicy::SharedTurn { max_calls: 2 };
    let cancel = CancellationToken::new();
    let (owner, mut state) = fixture.open()?;
    let first = call("first-original", "sum");
    let second = call("second-original", "lines");
    let result = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        first.clone(),
        Duration::from_secs(1),
        &cancel,
        policy,
    )
    .await?;
    assert_eq!(result["status"], "completed");
    let original = owner.load_call(&first)?;
    let binding = state.binding.clone();
    assert!(state.final_answer.is_none());
    drop(owner);

    let (owner, mut state) = fixture.open()?;
    assert_eq!(state.binding, binding);
    assert_eq!(state.completed_call_ids, vec![first.call_id.clone()]);
    let result = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        second.clone(),
        Duration::from_secs(1),
        &cancel,
        policy,
    )
    .await?;
    assert_eq!(result["status"], "completed");
    assert_eq!(state.tool_calls, 2);
    assert!(state.final_answer.is_none());
    assert_eq!(
        state
            .context
            .iter()
            .filter(|item| item["type"] == "function_call")
            .count(),
        2
    );
    assert_eq!(
        state
            .context
            .iter()
            .filter(|item| item["type"] == "function_call_output")
            .count(),
        2
    );
    let unchanged = owner.load_call(&first)?;
    assert_eq!(unchanged.intent, original.intent);
    assert_eq!(unchanged.arguments, original.arguments);
    assert_eq!(
        unchanged.params.idempotency_key,
        original.params.idempotency_key
    );
    let reused = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        first.clone(),
        Duration::from_secs(1),
        &cancel,
        policy,
    )
    .await?;
    assert_eq!(reused["reused"], true);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 2);
    assert!(
        run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            call("first-original", "digest"),
            Duration::from_secs(1),
            &cancel,
            policy
        )
        .await
        .is_err()
    );
    assert!(
        run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            call("third", "digest"),
            Duration::from_secs(1),
            &cancel,
            policy
        )
        .await
        .is_err()
    );
    assert_eq!(fixture.admissions(), 2);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 2);
    Ok(())
}

#[tokio::test]
async fn unknown_and_cancelled_shared_turns_cannot_admit_a_replacement_tool() -> Result<()> {
    let fixture = Fixture::new()?;
    let tools = Tools::default();
    tools.fail_dispatch.store(true, Ordering::SeqCst);
    let policy = ToolSessionPolicy::SharedTurn { max_calls: 2 };
    let cancel = CancellationToken::new();
    let (owner, mut state) = fixture.open()?;
    let original_call = call("unknown-original", "sum");
    let pending = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call.clone(),
        Duration::from_secs(1),
        &cancel,
        policy,
    )
    .await?;
    assert_eq!(pending["status"], "pending_tool");
    let original = state
        .pending_tool
        .as_ref()
        .context("original pending")?
        .clone();
    assert!(original.submission_attempted);
    assert!(
        run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            call("replacement", "lines"),
            Duration::from_secs(1),
            &cancel,
            policy
        )
        .await
        .is_err()
    );
    assert_eq!(fixture.admissions(), 1);
    drop(owner);
    let (owner, mut state) = fixture.open()?;
    let resumed = state.pending_tool.as_ref().context("restored original")?;
    assert_eq!(resumed.intent, original.intent);
    assert_eq!(resumed.arguments, original.arguments);
    let observed = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call,
        Duration::from_secs(1),
        &cancel,
        policy,
    )
    .await?;
    assert_eq!(observed["status"], "completed");
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 1);
    state.cancelled = true;
    owner.checkpoint(&state).await?;
    assert!(
        run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            call("after-cancel", "digest"),
            Duration::from_secs(1),
            &cancel,
            policy
        )
        .await
        .is_err()
    );
    assert_eq!(fixture.admissions(), 1);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn cancellation_before_admission_stays_closed_after_reopen_with_a_fresh_token() -> Result<()>
{
    let fixture = Fixture::new()?;
    let tools = Tools::default();
    let policy = ToolSessionPolicy::SharedTurn { max_calls: 2 };
    let (owner, mut state) = fixture.open()?;
    let binding = state.binding.clone();
    let context = state.context.clone();
    let original_call = call("never-admitted", "sum");
    let cancel = CancellationToken::new();
    cancel.cancel();
    let error = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call.clone(),
        Duration::from_secs(1),
        &cancel,
        policy,
    )
    .await
    .err()
    .context("pre-cancelled turn admitted a tool")?;
    assert!(
        error
            .to_string()
            .contains("cancelled turn cannot admit another tool")
    );
    assert!(state.cancelled);
    assert!(state.pending_tool.is_none());
    assert_eq!(state.tool_calls, 0);
    assert_eq!(state.context, context);
    assert_eq!(fixture.admissions(), 0);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 0);
    drop(owner);

    let (owner, mut state) = fixture.open()?;
    assert_eq!(state.binding, binding);
    assert!(
        state.cancelled,
        "the original owner must retain the pre-admission cancellation"
    );
    let fresh = CancellationToken::new();
    for candidate in [original_call, call("replacement-after-reopen", "lines")] {
        assert!(
            run_tool_with_policy(
                &owner,
                &tools,
                &mut state,
                candidate,
                Duration::from_secs(1),
                &fresh,
                policy
            )
            .await
            .is_err()
        );
    }
    assert!(state.pending_tool.is_none());
    assert_eq!(state.context, context);
    assert_eq!(state.tool_calls, 0);
    assert_eq!(fixture.admissions(), 0);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn legacy_pending_is_observed_without_rederiving_or_dispatching_its_operation() -> Result<()>
{
    let fixture = Fixture::new()?;
    let (owner, mut state) = fixture.open_legacy()?;
    let original_call = call("legacy-call", "sum");
    let admitted = owner.admit_tool(&state.binding, &original_call).await?;
    let original_intent = admitted.intent.clone();
    let original_arguments = admitted.arguments.clone();
    state.pending_tool = Some(PendingTool {
        call: original_call.clone(),
        intent: admitted.intent,
        arguments: admitted.arguments,
        submission_attempted: false,
        cancel_requested: false,
    });
    state.tool_calls = 1;
    owner.checkpoint(&state).await?;
    let original_manifest = std::fs::read(fixture.session.join("manifest.json"))?;
    drop(owner);
    assert!(
        fixture.open().is_err(),
        "a new shared-turn policy cannot migrate the old per-call owner"
    );
    assert_eq!(
        std::fs::read(fixture.session.join("manifest.json"))?,
        original_manifest
    );
    let (owner, mut state) = fixture.open_legacy()?;
    let tools = Tools::default();
    let result = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call.clone(),
        Duration::from_secs(1),
        &CancellationToken::new(),
        ToolSessionPolicy::ObserveOriginal,
    )
    .await?;
    assert_eq!(result["status"], "completed");
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 1);
    assert_eq!(owner.load_call(&original_call)?.intent, original_intent);
    assert_eq!(
        owner.load_call(&original_call)?.arguments,
        original_arguments
    );
    assert!(
        run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            call("another", "lines"),
            Duration::from_secs(1),
            &CancellationToken::new(),
            ToolSessionPolicy::ObserveOriginal
        )
        .await
        .is_err()
    );
    assert_eq!(fixture.admissions(), 1);
    Ok(())
}

#[tokio::test]
async fn shared_deadline_stays_closed_after_original_terminal_reconciliation() -> Result<()> {
    let fixture = Fixture::new()?;
    let tools = Tools::default();
    let policy = ToolSessionPolicy::SharedTurn { max_calls: 2 };
    let cancel = CancellationToken::new();
    let original_call = call("deadline-original", "sum");
    let (owner, mut state) = fixture.open()?;
    // Restore an original attempted operation, then expire observation at a
    // deterministic zero deadline. No timing race or new launch is required.
    let admitted = owner.admit_tool(&state.binding, &original_call).await?;
    state.pending_tool = Some(PendingTool {
        call: original_call.clone(),
        intent: admitted.intent,
        arguments: admitted.arguments,
        submission_attempted: true,
        cancel_requested: false,
    });
    state.tool_calls = 1;
    owner.checkpoint(&state).await?;
    let result = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call.clone(),
        Duration::ZERO,
        &cancel,
        policy,
    )
    .await?;
    assert_eq!(result["status"], "pending_tool");
    assert!(state.cancelled);
    let original = state
        .pending_tool
        .as_ref()
        .context("original pending")?
        .clone();
    assert!(original.cancel_requested);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    drop(owner);
    let (owner, mut state) = fixture.open()?;
    assert!(
        state.cancelled,
        "deadline stop must survive reopening the original owner"
    );
    let result = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call.clone(),
        Duration::from_secs(1),
        &CancellationToken::new(),
        policy,
    )
    .await?;
    assert_eq!(result["status"], "completed");
    assert_eq!(owner.load_call(&original_call)?.intent, original.intent);
    assert_eq!(
        owner.load_call(&original_call)?.arguments,
        original.arguments
    );
    assert!(state.pending_tool.is_none());
    assert!(
        run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            call("after-deadline", "lines"),
            Duration::from_secs(1),
            &CancellationToken::new(),
            policy
        )
        .await
        .is_err()
    );
    assert_eq!(fixture.admissions(), 1);
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn shared_presentation_deadline_stays_closed_after_original_terminal_reconciliation()
-> Result<()> {
    let fixture = Fixture::new()?;
    let tools = PresentationTools::default();
    tools.hold.store(true, Ordering::SeqCst);
    let policy = ToolSessionPolicy::SharedTurn { max_calls: 2 };
    let original_call = call("presentation-deadline-original", "sum");
    let (owner, mut state) = fixture.open()?;
    let admitted = owner.admit_tool(&state.binding, &original_call).await?;
    let original_intent = admitted.intent.clone();
    let original_arguments = admitted.arguments.clone();
    state.context.push(json!({"type":"function_call", "call_id":original_call.call_id,
        "name":original_call.name, "arguments":String::from_utf8(original_call.arguments.clone())?}));
    state.pending_tool = Some(PendingTool {
        call: original_call.clone(),
        intent: admitted.intent,
        arguments: admitted.arguments,
        submission_attempted: true,
        cancel_requested: false,
    });
    state.tool_calls = 1;
    owner.checkpoint(&state).await?;

    // The observation completes immediately, but presentation never resolves.
    // Only the presentation timeout can return after that callback is polled.
    let result = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call.clone(),
        Duration::from_secs(1),
        &CancellationToken::new(),
        policy,
    )
    .await?;
    assert_eq!(result["status"], "pending_tool");
    assert_eq!(tools.presentations.load(Ordering::SeqCst), 1);
    assert!(
        state
            .last_error
            .as_deref()
            .is_some_and(|error| error.contains("presentation deadline"))
    );
    assert!(
        state.cancelled,
        "the shared turn budget includes output presentation"
    );
    assert_eq!(tools.original.starts.load(Ordering::SeqCst), 0);
    drop(owner);

    tools.hold.store(false, Ordering::SeqCst);
    let (owner, mut state) = fixture.open()?;
    assert!(state.cancelled);
    assert_eq!(
        state
            .pending_tool
            .as_ref()
            .context("original pending tool")?
            .intent,
        original_intent
    );
    let mut result = run_tool_with_policy(
        &owner,
        &tools,
        &mut state,
        original_call.clone(),
        Duration::from_secs(1),
        &CancellationToken::new(),
        policy,
    )
    .await?;
    if result["status"] == "pending_tool" {
        // The persisted stop may first acknowledge cancellation of this same
        // original intent. A subsequent call can only observe that intent.
        assert!(
            state
                .pending_tool
                .as_ref()
                .context("original cancellation")?
                .cancel_requested
        );
        result = run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            original_call.clone(),
            Duration::from_secs(1),
            &CancellationToken::new(),
            policy,
        )
        .await?;
    }
    assert_eq!(result["status"], "completed");
    assert!(state.pending_tool.is_none());
    assert!(state.cancelled);
    assert_eq!(owner.load_call(&original_call)?.intent, original_intent);
    assert_eq!(
        owner.load_call(&original_call)?.arguments,
        original_arguments
    );
    assert!(
        run_tool_with_policy(
            &owner,
            &tools,
            &mut state,
            call("after-presentation-deadline", "lines"),
            Duration::from_secs(1),
            &CancellationToken::new(),
            policy
        )
        .await
        .is_err()
    );
    assert_eq!(fixture.admissions(), 1);
    assert_eq!(tools.original.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.original.observations.load(Ordering::SeqCst), 2);
    assert_eq!(tools.presentations.load(Ordering::SeqCst), 2);
    Ok(())
}
