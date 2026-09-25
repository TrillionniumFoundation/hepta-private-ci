use std::sync::Arc;

use codex_extension_api::ExtensionData;
use codex_extension_api::ToolCallOutcome;
use codex_extension_api::ToolCallSource;
use codex_extension_api::ToolPayload;
use codex_extension_api::ToolPolicyContributor;
use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyInput;
use codex_extension_api::ToolPolicyTerminalInput;
use codex_hepta_contracts::ActionId;
use codex_hepta_contracts::GovernanceDecision;
use codex_hepta_contracts::GovernanceMode;
use codex_hepta_contracts::HandlerOutcome;
use codex_hepta_contracts::PolicyPhase;
use codex_hepta_contracts::ReceiptId;
use codex_hepta_contracts::ToolActionSource;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_state::StateRuntime;
use codex_utils_absolute_path::AbsolutePathBuf;
use tempfile::TempDir;

use super::GovernanceState;
use super::HeptaGovernanceExtension;
use super::governance_state;
use super::handler_outcome;

fn sqlite_config(temp: &TempDir) -> SqliteConfig {
    SqliteConfig::new_for_testing(
        AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute temp path"),
    )
}

fn stores() -> (ExtensionData, ExtensionData, ExtensionData) {
    (
        ExtensionData::new("session-1"),
        ExtensionData::new("thread-1"),
        ExtensionData::new("turn-1"),
    )
}

#[test]
fn join_error_terminal_preserves_stable_indeterminate_reason() {
    assert_eq!(
        handler_outcome(
            ToolCallOutcome::Indeterminate {
                reason_code: "handler_task_join_error",
            },
            true,
        ),
        HandlerOutcome::Indeterminate {
            reason_code: "handler_task_join_error".to_string(),
        },
    );
}

#[tokio::test]
async fn durable_attempt_preserves_effective_payload_and_code_mode_identity() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let tool_name = "exec_command".into();
    let original = ToolPayload::Function {
        arguments: r#"{"command":"echo original"}"#.to_string(),
    };
    let effective = ToolPayload::Function {
        arguments: r#"{"command":"echo rewritten"}"#.to_string(),
    };
    let source = ToolCallSource::CodeMode {
        cell_id: "cell-7".to_string(),
        runtime_tool_call_id: "runtime-9".to_string(),
    };

    let admission = state
        .evaluate(
            ToolPolicyInput {
                session_store: &session,
                thread_store: &thread,
                turn_store: &turn,
                attempt_id: "attempt-original",
                turn_id: "turn-1",
                call_id: "call-1",
                tool_name: &tool_name,
                source: source.clone(),
                payload: &original,
            },
            PolicyPhase::Admission,
        )
        .await
        .expect("admission");
    assert_eq!(admission, ToolPolicyDecision::Allow);

    state
        .evaluate(
            ToolPolicyInput {
                session_store: &session,
                thread_store: &thread,
                turn_store: &turn,
                attempt_id: "attempt-original",
                turn_id: "turn-1",
                call_id: "call-1",
                tool_name: &tool_name,
                source: source.clone(),
                payload: &effective,
            },
            PolicyPhase::Authorization,
        )
        .await
        .expect("authorization");
    state
        .terminal(ToolPolicyTerminalInput {
            session_store: &session,
            thread_store: &thread,
            turn_store: &turn,
            attempt_id: "attempt-original",
            turn_id: "turn-1",
            call_id: "call-1",
            tool_name: &tool_name,
            source,
            outcome: ToolCallOutcome::Completed { success: true },
            host_accepted: true,
        })
        .await
        .expect("terminal");

    let action_id = ActionId::for_tool_call("thread-1", "turn-1", "call-1");
    let stored = evidence
        .get_receipt(&ReceiptId::for_action(&action_id))
        .await
        .expect("read receipt")
        .expect("receipt exists")
        .receipt;
    assert_ne!(
        stored.admission.action.payload_sha256,
        stored
            .authorization
            .as_ref()
            .expect("authorization")
            .action
            .payload_sha256
    );
    assert_eq!(
        stored.admission.action.source,
        ToolActionSource::CodeMode {
            cell_id: "cell-7".to_string(),
            runtime_tool_call_id: "runtime-9".to_string(),
        }
    );
    assert_eq!(
        stored.outcome,
        HandlerOutcome::HandlerCompleted {
            reported_success: true,
        }
    );
    assert_eq!(stored.admission.decision, GovernanceDecision::NotEvaluated);
    assert_eq!(
        stored.authorization.expect("authorization").decision,
        GovernanceDecision::NotEvaluated
    );
}

#[tokio::test]
async fn enforce_blocks_authorized_pending_replay_after_restart() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let (session, thread, turn) = stores();
    let tool_name = "exec_command".into();
    let payload = ToolPayload::Function {
        arguments: r#"{"command":"touch must-not-replay"}"#.to_string(),
    };
    let input = || ToolPolicyInput {
        session_store: &session,
        thread_store: &thread,
        turn_store: &turn,
        attempt_id: "attempt-original",
        turn_id: "turn-1",
        call_id: "call-replay",
        tool_name: &tool_name,
        source: ToolCallSource::Direct,
        payload: &payload,
    };
    let first = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    assert_eq!(
        first
            .evaluate(input(), PolicyPhase::Admission)
            .await
            .expect("admission"),
        ToolPolicyDecision::Allow
    );
    assert_eq!(
        first
            .evaluate(input(), PolicyPhase::Authorization)
            .await
            .expect("authorization"),
        ToolPolicyDecision::Allow
    );
    drop(first);

    let restarted = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let replay_input = ToolPolicyInput {
        session_store: &session,
        thread_store: &thread,
        turn_store: &turn,
        attempt_id: "attempt-replay",
        turn_id: "turn-1",
        call_id: "call-replay",
        tool_name: &tool_name,
        source: ToolCallSource::Direct,
        payload: &payload,
    };
    let replay = restarted
        .evaluate(replay_input, PolicyPhase::Admission)
        .await
        .expect("replay is a typed block");
    assert!(matches!(
        replay,
        ToolPolicyDecision::Block { ref reason_code, .. }
            if reason_code == "hepta_action_replay"
    ));
    restarted
        .terminal(ToolPolicyTerminalInput {
            session_store: &session,
            thread_store: &thread,
            turn_store: &turn,
            attempt_id: "attempt-replay",
            turn_id: "turn-1",
            call_id: "call-replay",
            tool_name: &tool_name,
            source: ToolCallSource::Direct,
            outcome: ToolCallOutcome::Blocked,
            host_accepted: false,
        })
        .await
        .expect("replay terminal cannot mutate original evidence");

    let action_id = ActionId::for_tool_call("thread-1", "turn-1", "call-replay");
    let stored = evidence
        .get_action_evidence(&action_id)
        .await
        .expect("pending evidence");
    assert!(stored.admission.is_some());
    assert!(stored.authorization.is_some());
    assert!(stored.receipt.is_none());
}

#[tokio::test]
async fn replay_terminal_cannot_consume_the_original_attempt_claim() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let tool_name = "exec_command".into();
    let payload = ToolPayload::Function {
        arguments: "{}".to_string(),
    };
    let input = |attempt_id| ToolPolicyInput {
        session_store: &session,
        thread_store: &thread,
        turn_store: &turn,
        attempt_id,
        turn_id: "turn-1",
        call_id: "call-race",
        tool_name: &tool_name,
        source: ToolCallSource::Direct,
        payload: &payload,
    };
    state
        .evaluate(input("attempt-original"), PolicyPhase::Admission)
        .await
        .expect("original admission");
    let replay = state
        .evaluate(input("attempt-replay"), PolicyPhase::Admission)
        .await
        .expect("typed replay block");
    assert!(matches!(replay, ToolPolicyDecision::Block { .. }));

    // Deliberately deliver the original Blocked terminal before the replay's
    // admission-block terminal. Attempt-scoped ownership prevents callback
    // ordering from swapping their meaning.
    state
        .terminal(ToolPolicyTerminalInput {
            session_store: &session,
            thread_store: &thread,
            turn_store: &turn,
            attempt_id: "attempt-original",
            turn_id: "turn-1",
            call_id: "call-race",
            tool_name: &tool_name,
            source: ToolCallSource::Direct,
            outcome: ToolCallOutcome::Blocked,
            host_accepted: true,
        })
        .await
        .expect("original terminal");
    state
        .terminal(ToolPolicyTerminalInput {
            session_store: &session,
            thread_store: &thread,
            turn_store: &turn,
            attempt_id: "attempt-replay",
            turn_id: "turn-1",
            call_id: "call-race",
            tool_name: &tool_name,
            source: ToolCallSource::Direct,
            outcome: ToolCallOutcome::Blocked,
            host_accepted: false,
        })
        .await
        .expect("replay terminal");

    let action_id = ActionId::for_tool_call("thread-1", "turn-1", "call-race");
    let receipt = evidence
        .get_receipt(&ReceiptId::for_action(&action_id))
        .await
        .expect("read receipt")
        .expect("original receipt")
        .receipt;
    assert!(receipt.host_accepted);
    assert_eq!(receipt.outcome, HandlerOutcome::Blocked);
}

#[tokio::test]
async fn shadow_replay_cannot_borrow_a_stale_original_claim() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let state = GovernanceState::enabled(GovernanceMode::Shadow, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let tool_name = "exec_command".into();
    let payload = ToolPayload::Function {
        arguments: "{}".to_string(),
    };
    let input = |attempt_id| ToolPolicyInput {
        session_store: &session,
        thread_store: &thread,
        turn_store: &turn,
        attempt_id,
        turn_id: "turn-1",
        call_id: "call-shadow-replay",
        tool_name: &tool_name,
        source: ToolCallSource::Direct,
        payload: &payload,
    };
    state
        .evaluate(input("attempt-original"), PolicyPhase::Admission)
        .await
        .expect("original admission");
    state
        .evaluate(input("attempt-original"), PolicyPhase::Authorization)
        .await
        .expect("original authorization");

    // Simulate a panic by leaving the original authorized action pending.
    assert_eq!(
        state
            .evaluate(input("attempt-replay"), PolicyPhase::Admission)
            .await
            .expect("shadow observes replay"),
        ToolPolicyDecision::Allow
    );
    assert_eq!(
        state
            .evaluate(input("attempt-replay"), PolicyPhase::Authorization)
            .await
            .expect("shadow continues"),
        ToolPolicyDecision::Allow
    );
    state
        .terminal(ToolPolicyTerminalInput {
            session_store: &session,
            thread_store: &thread,
            turn_store: &turn,
            attempt_id: "attempt-replay",
            turn_id: "turn-1",
            call_id: "call-shadow-replay",
            tool_name: &tool_name,
            source: ToolCallSource::Direct,
            outcome: ToolCallOutcome::Completed { success: true },
            host_accepted: true,
        })
        .await
        .expect("replay terminal is ignored");

    let action_id = ActionId::for_tool_call("thread-1", "turn-1", "call-shadow-replay");
    let stored = evidence
        .get_action_evidence(&action_id)
        .await
        .expect("pending evidence");
    assert!(stored.authorization.is_some());
    assert!(stored.receipt.is_none());
}

#[tokio::test]
async fn cancellation_after_authorization_is_indeterminate() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let tool_name = "exec_command".into();
    let payload = ToolPayload::Function {
        arguments: "{}".to_string(),
    };
    let input = || ToolPolicyInput {
        session_store: &session,
        thread_store: &thread,
        turn_store: &turn,
        attempt_id: "attempt-cancelled",
        turn_id: "turn-1",
        call_id: "call-cancelled",
        tool_name: &tool_name,
        source: ToolCallSource::Direct,
        payload: &payload,
    };
    state
        .evaluate(input(), PolicyPhase::Admission)
        .await
        .expect("admission");
    state
        .evaluate(input(), PolicyPhase::Authorization)
        .await
        .expect("authorization");
    state
        .terminal(ToolPolicyTerminalInput {
            session_store: &session,
            thread_store: &thread,
            turn_store: &turn,
            attempt_id: "attempt-cancelled",
            turn_id: "turn-1",
            call_id: "call-cancelled",
            tool_name: &tool_name,
            source: ToolCallSource::Direct,
            outcome: ToolCallOutcome::Aborted,
            host_accepted: true,
        })
        .await
        .expect("terminal");

    let action_id = ActionId::for_tool_call("thread-1", "turn-1", "call-cancelled");
    let receipt = evidence
        .get_receipt(&ReceiptId::for_action(&action_id))
        .await
        .expect("read receipt")
        .expect("receipt")
        .receipt;
    assert_eq!(
        receipt.outcome,
        HandlerOutcome::Indeterminate {
            reason_code: "cancelled_after_authorization".to_string(),
        }
    );
}

#[tokio::test]
async fn terminal_cannot_substitute_the_tool_identity() {
    let temp = TempDir::new().expect("temp dir");
    let evidence = Arc::new(
        HeptaEvidenceStore::open(&sqlite_config(&temp))
            .await
            .expect("open evidence"),
    );
    let state = GovernanceState::enabled(GovernanceMode::Enforce, Ok(evidence.clone()));
    let (session, thread, turn) = stores();
    let admitted_name = "exec_command".into();
    let substituted_name = "write_stdin".into();
    let payload = ToolPayload::Function {
        arguments: "{}".to_string(),
    };
    state
        .evaluate(
            ToolPolicyInput {
                session_store: &session,
                thread_store: &thread,
                turn_store: &turn,
                attempt_id: "attempt-substitution",
                turn_id: "turn-1",
                call_id: "call-substitution",
                tool_name: &admitted_name,
                source: ToolCallSource::Direct,
                payload: &payload,
            },
            PolicyPhase::Admission,
        )
        .await
        .expect("admission");
    let error = state
        .terminal(ToolPolicyTerminalInput {
            session_store: &session,
            thread_store: &thread,
            turn_store: &turn,
            attempt_id: "attempt-substitution",
            turn_id: "turn-1",
            call_id: "call-substitution",
            tool_name: &substituted_name,
            source: ToolCallSource::Direct,
            outcome: ToolCallOutcome::Blocked,
            host_accepted: true,
        })
        .await
        .expect_err("substituted terminal identity must fail closed");
    assert_eq!(error.reason_code(), "hepta_terminal_binding_drift");
    assert_eq!(evidence.pending_action_count().await.expect("pending"), 1);
}

#[tokio::test]
async fn enforce_fails_closed_but_shadow_allows_when_evidence_is_unavailable() {
    let (session, thread, turn) = stores();
    let tool_name = "exec_command".into();
    let payload = ToolPayload::Function {
        arguments: "{}".to_string(),
    };
    let input = || ToolPolicyInput {
        session_store: &session,
        thread_store: &thread,
        turn_store: &turn,
        attempt_id: "attempt-unavailable",
        turn_id: "turn-1",
        call_id: "call-1",
        tool_name: &tool_name,
        source: ToolCallSource::Direct,
        payload: &payload,
    };
    let unavailable = Err(Arc::<str>::from("offline"));
    let enforced = GovernanceState::enabled(GovernanceMode::Enforce, unavailable.clone());
    let error = enforced
        .evaluate(input(), PolicyPhase::Admission)
        .await
        .expect_err("enforce must fail closed");
    assert_eq!(error.reason_code(), "hepta_evidence_unavailable");

    let shadow = GovernanceState::enabled(GovernanceMode::Shadow, unavailable);
    assert_eq!(
        shadow
            .evaluate(input(), PolicyPhase::Admission)
            .await
            .expect("shadow continues"),
        ToolPolicyDecision::Allow
    );
}

#[tokio::test]
async fn disabled_feature_does_not_initialize_the_evidence_backend() {
    let temp = TempDir::new().expect("temp dir");
    let state_db = StateRuntime::init(sqlite_config(&temp), "test-provider".to_string())
        .await
        .expect("initialize state runtime");
    let evidence_path = temp.path().join("hepta_evidence_1.sqlite");
    assert!(
        !evidence_path.exists(),
        "state runtime initialization must not create the Hepta evidence database"
    );
    let extension = HeptaGovernanceExtension {
        enabled: |_: &()| false,
        mode: GovernanceMode::Enforce,
        state_db: Some(state_db),
        evidence: tokio::sync::OnceCell::new(),
    };
    let thread = ExtensionData::new("thread-1");

    extension.initialize_thread(&(), &thread).await;

    assert!(extension.evidence.get().is_none());
    assert!(
        !evidence_path.exists(),
        "feature-off thread initialization must not create the Hepta evidence database"
    );
    assert!(!extension.is_active(&thread));
    let state = thread
        .get::<GovernanceState>()
        .expect("disabled governance state");
    assert!(!state.enabled);
}

#[test]
fn missing_thread_state_is_observational_in_shadow_and_fatal_in_enforce() {
    let thread = ExtensionData::new("thread-without-lifecycle");
    assert!(
        governance_state(&thread, GovernanceMode::Shadow)
            .expect("shadow continues")
            .is_none()
    );
    let error = match governance_state(&thread, GovernanceMode::Enforce) {
        Ok(_) => panic!("enforce must fail closed"),
        Err(error) => error,
    };
    assert_eq!(error.reason_code(), "hepta_governance_state_missing");
}
