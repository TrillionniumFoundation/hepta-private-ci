//! Actual private checkpoint and admission recovery, with no runtime or network.

use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use anyhow::Result;
use codex_hepta_native_agent::PendingTool;
use codex_hepta_native_agent::ToolCall;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_native_agent::TurnOwner;
use codex_hepta_native_agent::TurnState;
use codex_hepta_types::Digest32;
use codex_hepta_types::RuntimeToolIntentV1;
use serde_json::Value;
use serde_json::json;
use tokio_util::sync::CancellationToken;

use crate::owner::FixtureConfig;
use crate::owner::SessionOwner;
use crate::runtime_bridge::AdmissionResolver;

struct Fixture {
    _temporary: tempfile::TempDir,
    session_root: PathBuf,
    config: FixtureConfig,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temporary = tempfile::tempdir()?;
        std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))?;
        let script = temporary.path().join("probe.py");
        let data = temporary.path().join("data.txt");
        let script_bytes =
            b"# Fixture is hashed, never executed by these tests.\nprint('fixture')\n";
        let data_bytes = b"3\n7\n11\n";
        for (path, bytes) in [
            (&script, script_bytes.as_slice()),
            (&data, data_bytes.as_slice()),
        ] {
            let mut file = OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(path)?;
            file.write_all(bytes)?;
            file.sync_all()?;
        }
        let config = FixtureConfig {
            representative: false,
            host: "fixture".to_owned(),
            script: script.to_string_lossy().into_owned(),
            script_sha256: Digest32::of_bytes(script_bytes).to_string(),
            data: data.to_string_lossy().into_owned(),
            data_sha256: Digest32::of_bytes(data_bytes).to_string(),
            cwd: temporary.path().to_string_lossy().into_owned(),
            tool_timeout_seconds: 10,
        };
        let session_root = temporary.path().join("session");
        Ok(Self {
            _temporary: temporary,
            session_root,
            config,
        })
    }

    fn policy() -> Value {
        json!({"model":"fixed-model","responses_url":"http://127.0.0.1:1/v1/responses",
            "context_bytes":8192,"tool_output_bytes":4096,"operation":"run"})
    }

    fn open(&self) -> Result<(SessionOwner, TurnState)> {
        self.open_with("original input", Self::policy())
    }

    fn open_with(&self, input: &str, policy: Value) -> Result<(SessionOwner, TurnState)> {
        SessionOwner::open(
            self.session_root.clone(),
            "original-session",
            input,
            self.config.clone(),
            policy,
        )
    }
}

fn call(task: &str) -> ToolCall {
    ToolCall {
        call_id: "original-call".to_owned(),
        name: "hepta_probe".to_owned(),
        arguments: serde_json::to_vec(&json!({"task":task})).unwrap(),
    }
}

#[tokio::test]
async fn pending_model_restart_preserves_original_operation_and_exact_post_bytes() -> Result<()> {
    let fixture = Fixture::new()?;
    let (owner, mut state) = fixture.open()?;
    let body =
        br#"{"model":"fixed-model","input":[{"role":"user","content":"a\nb"}],"stream":true}"#;
    let request = owner.admit_model(&state.binding, 0, body).await?;
    let operation = request.operation_id.clone();
    let binding = state.binding.clone();
    state.pending_model = Some(request);
    state.model_calls = 1;
    state.provider_response_id = Some("response-original".to_owned());
    state.last_error = Some("stream ended before its terminal observation".to_owned());
    owner.checkpoint(&state).await?;
    drop(owner);

    let (restored_owner, restored) = fixture.open()?;
    assert_eq!(restored.binding, binding);
    assert_eq!(restored.model_calls, 1);
    assert_eq!(
        restored.provider_response_id.as_deref(),
        Some("response-original")
    );
    assert_eq!(restored.last_error, state.last_error);
    assert_eq!(
        restored.pending_model.as_ref().unwrap().operation_id,
        operation
    );
    assert_eq!(restored.pending_model.as_ref().unwrap().body, body);
    assert!(restored.final_answer.is_none());
    let repeated = restored_owner
        .admit_model(&restored.binding, 0, body)
        .await?;
    assert_eq!(repeated.operation_id, operation);
    assert_eq!(repeated.body, body);
    assert!(
        restored_owner
            .admit_model(&restored.binding, 0, b"{\"changed\":true}")
            .await
            .is_err()
    );
    assert_eq!(
        std::fs::read_dir(&fixture.session_root)?
            .filter_map(|entry| entry.ok())
            .filter(|entry| entry.file_name().to_string_lossy().starts_with("model-"))
            .count(),
        1
    );
    Ok(())
}

#[tokio::test]
async fn pending_tool_restart_preserves_full_compiled_request_and_cancellation() -> Result<()> {
    let fixture = Fixture::new()?;
    let (owner, mut state) = fixture.open()?;
    let proposal = call("sum");
    let admission = owner.admit_tool(&state.binding, &proposal).await?;
    let original = owner.load_call(&proposal)?;
    assert_eq!(admission.arguments, serde_json::to_vec(&original.params)?);
    let intent = admission.intent.clone();
    let arguments = admission.arguments.clone();
    state.pending_tool = Some(PendingTool {
        call: proposal.clone(),
        intent: admission.intent,
        arguments: admission.arguments,
        submission_attempted: true,
        cancel_requested: true,
    });
    state.tool_calls = 1;
    state.cancelled = true;
    state.last_error = Some("start acknowledgement lost; original operation pending".to_owned());
    owner.checkpoint(&state).await?;
    drop(owner);

    let (restored_owner, restored) = fixture.open()?;
    let pending = restored.pending_tool.as_ref().unwrap();
    assert_eq!(pending.call, proposal);
    assert_eq!(pending.intent, intent);
    assert_eq!(pending.arguments, arguments);
    assert!(pending.submission_attempted);
    assert!(pending.cancel_requested);
    assert!(restored.cancelled);
    assert_eq!(restored.tool_calls, 1);
    assert!(restored.final_answer.is_none());
    let resolved = restored_owner.resolve(&pending.intent)?;
    assert_eq!(resolved.intent, intent);
    assert_eq!(resolved.arguments, arguments);
    assert_eq!(
        resolved.params.idempotency_key,
        original.params.idempotency_key
    );
    assert_eq!(
        serde_json::to_vec(&resolved.params)?,
        serde_json::to_vec(&original.params)?
    );
    assert_eq!(
        resolved.intent.cell.deadline_ms,
        original.intent.cell.deadline_ms
    );
    assert!(!fixture.session_root.join("jobs").exists());
    Ok(())
}

#[test]
fn changed_input_or_model_policy_cannot_reopen_the_original_session() -> Result<()> {
    let fixture = Fixture::new()?;
    let (owner, _) = fixture.open()?;
    drop(owner);
    let mut altered_policy = Fixture::policy();
    altered_policy["model"] = json!("replacement-model");
    for (input, policy) in [
        ("different input", Fixture::policy()),
        ("original input", altered_policy),
    ] {
        let error = fixture
            .open_with(input, policy)
            .err()
            .expect("changed manifest must be refused");
        assert!(
            error.to_string().contains("immutable admission changed"),
            "{error:#}"
        );
    }
    let (_, restored) = fixture.open()?;
    assert!(restored.pending_model.is_none());
    assert!(restored.pending_tool.is_none());
    Ok(())
}

#[tokio::test]
async fn changed_tool_proposal_cannot_reuse_the_same_call_id() -> Result<()> {
    let fixture = Fixture::new()?;
    let (owner, state) = fixture.open()?;
    let original = owner.admit_tool(&state.binding, &call("sum")).await?;
    let changed = owner.admit_tool(&state.binding, &call("digest")).await;
    assert!(changed.is_err());
    assert!(
        changed
            .err()
            .unwrap()
            .to_string()
            .contains("model proposal changed")
    );
    let mut renamed = call("sum");
    renamed.name = "arbitrary_tool".to_owned();
    assert!(owner.admit_tool(&state.binding, &renamed).await.is_err());
    let still_original = owner.load_call(&call("sum"))?;
    assert_eq!(still_original.intent, original.intent);
    assert_eq!(still_original.arguments, original.arguments);
    assert_eq!(
        std::fs::read_dir(&fixture.session_root)?
            .filter_map(|entry| entry.ok())
            .filter(|entry| entry.file_name().to_string_lossy().starts_with("tool-"))
            .count(),
        1
    );
    Ok(())
}

#[tokio::test]
async fn checkpoint_gap_or_corruption_refuses_recovery_without_rolling_back() -> Result<()> {
    for corruption in ["gap", "invalid-json", "predecessor"] {
        let fixture = Fixture::new()?;
        let (owner, mut state) = fixture.open()?;
        owner.checkpoint(&state).await?;
        state.last_error = Some("latest state must never be silently skipped".to_owned());
        owner.checkpoint(&state).await?;
        drop(owner);
        let first = fixture.session_root.join("snapshot-00000000.json");
        let second = fixture.session_root.join("snapshot-00000001.json");
        match corruption {
            "gap" => std::fs::rename(&first, fixture.session_root.join("retained-original.json"))?,
            "invalid-json" => std::fs::write(&second, b"{")?,
            "predecessor" => {
                let mut record: Value = serde_json::from_slice(&std::fs::read(&second)?)?;
                record["previous"] = json!("unrelated predecessor");
                std::fs::write(&second, serde_json::to_vec(&record)?)?;
            }
            _ => unreachable!(),
        }
        assert!(
            fixture.open().is_err(),
            "{corruption} must not restore an earlier checkpoint"
        );
    }
    Ok(())
}

#[test]
fn concurrent_owners_cannot_claim_the_same_session() -> Result<()> {
    let fixture = Fixture::new()?;
    let (original_owner, _) = fixture.open()?;
    let error = fixture
        .open()
        .err()
        .expect("second live owner must be refused");
    assert!(error.to_string().contains("already owned"), "{error:#}");
    original_owner.check(&original_owner.binding)?;
    drop(original_owner);
    let (replacement, _) = fixture.open()?;
    replacement.check(&replacement.binding)?;
    Ok(())
}

#[derive(Default)]
struct RecoveryTools {
    starts: AtomicUsize,
    observations: AtomicUsize,
    cancellations: AtomicUsize,
}

impl ToolPort for RecoveryTools {
    async fn execute_or_observe(
        &self,
        _: &RuntimeToolIntentV1,
        _: &[u8],
    ) -> Result<ToolObservation> {
        self.starts.fetch_add(1, Ordering::SeqCst);
        anyhow::bail!("cancelled admission must not cross its first submission boundary")
    }

    async fn observe(&self, _: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        self.observations.fetch_add(1, Ordering::SeqCst);
        Ok(ToolObservation::Accepted)
    }

    async fn cancel(&self, _: &RuntimeToolIntentV1) -> Result<()> {
        self.cancellations.fetch_add(1, Ordering::SeqCst);
        anyhow::bail!("unsubmitted original operation has no job to cancel")
    }
}

#[tokio::test]
async fn external_tool_cancellation_before_submission_survives_reopen_and_fresh_token() -> Result<()>
{
    let fixture = Fixture::new()?;
    let (owner, mut state) = fixture.open()?;
    let proposal = call("sum");
    let tools = RecoveryTools::default();
    let cancelled = CancellationToken::new();
    cancelled.cancel();
    let result = crate::tool_session::run_tool(
        &owner,
        &tools,
        &mut state,
        proposal.clone(),
        Duration::from_secs(1),
        &cancelled,
    )
    .await?;
    assert_eq!(result["status"], "pending_tool");
    let original = owner.load_call(&proposal)?;
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.cancellations.load(Ordering::SeqCst), 1);
    drop(owner);

    let (owner, mut restored) = fixture.open()?;
    assert!(restored.cancelled);
    assert!(restored.pending_tool.as_ref().unwrap().cancel_requested);
    assert!(!restored.pending_tool.as_ref().unwrap().submission_attempted);
    let result = crate::tool_session::run_tool(
        &owner,
        &tools,
        &mut restored,
        proposal,
        Duration::from_secs(1),
        &CancellationToken::new(),
    )
    .await?;
    assert_eq!(result["status"], "pending_tool");
    assert_eq!(tools.starts.load(Ordering::SeqCst), 0);
    assert_eq!(tools.observations.load(Ordering::SeqCst), 1);
    assert_eq!(tools.cancellations.load(Ordering::SeqCst), 1);
    let pending = restored.pending_tool.as_ref().unwrap();
    assert_eq!(pending.intent, original.intent);
    assert_eq!(pending.arguments, original.arguments);
    assert!(!pending.submission_attempted);
    assert!(restored.final_answer.is_none());
    drop(owner);
    let (_, persisted) = fixture.open()?;
    assert!(
        !persisted
            .pending_tool
            .as_ref()
            .unwrap()
            .submission_attempted
    );
    Ok(())
}

#[tokio::test]
async fn external_tool_recovery_honors_each_persisted_cancellation_marker() -> Result<()> {
    for (cancel_requested, cancelled) in [(true, false), (false, true)] {
        let fixture = Fixture::new()?;
        let (owner, mut state) = fixture.open()?;
        let proposal = call("sum");
        let admission = owner.admit_tool(&state.binding, &proposal).await?;
        let original = admission.intent.clone();
        state.pending_tool = Some(PendingTool {
            call: proposal.clone(),
            intent: admission.intent,
            arguments: admission.arguments,
            submission_attempted: false,
            cancel_requested,
        });
        state.tool_calls = 1;
        state.cancelled = cancelled;
        owner.checkpoint(&state).await?;
        drop(owner);

        let (owner, mut restored) = fixture.open()?;
        let tools = RecoveryTools::default();
        for _ in 0..2 {
            let result = crate::tool_session::run_tool(
                &owner,
                &tools,
                &mut restored,
                proposal.clone(),
                Duration::from_secs(1),
                &CancellationToken::new(),
            )
            .await?;
            assert_eq!(result["status"], "pending_tool");
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
        drop(owner);
        let (_, persisted) = fixture.open()?;
        assert!(
            !persisted
                .pending_tool
                .as_ref()
                .unwrap()
                .submission_attempted
        );
    }
    Ok(())
}

#[path = "helper_cancel_tests.rs"]
mod helper_cancel_tests;

