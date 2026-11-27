use std::sync::Arc;
use std::time::Duration;

use codex_protocol::items::CommandExecutionItem;
use codex_protocol::items::CommandExecutionStatus;
use codex_protocol::items::TurnItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ReviewDecision;
use pretty_assertions::assert_eq;
use tokio::sync::Mutex;
use tokio::sync::oneshot;

use super::ExecApprovalTerminal;
use super::PendingExecApprovalCancellation;
use crate::session::tests::make_session_and_context_with_rx;
use crate::state::TurnState;
use crate::unified_exec::async_watcher::emit_exec_end_for_unified_exec;
use crate::unified_exec::async_watcher::emit_failed_exec_end_for_unified_exec;
use crate::unified_exec::head_tail_buffer::HeadTailBuffer;

fn new_terminal() -> Arc<ExecApprovalTerminal> {
    Arc::new(ExecApprovalTerminal::new(
        "launch-turn".to_string(),
        "parent-call".to_string(),
    ))
}

fn register_pending(
    state: &mut TurnState,
    approval_id: &str,
    approval_turn_id: &str,
    terminal: &Arc<ExecApprovalTerminal>,
) -> oneshot::Receiver<ReviewDecision> {
    let (sender, receiver) = oneshot::channel();
    let binding = PendingExecApprovalCancellation::new(
        approval_turn_id.to_string(),
        "parent-call",
        Arc::clone(terminal),
    )
    .expect("matching parent");
    assert!(
        state
            .insert_pending_approval_with_exec_cancellation(
                approval_id.to_string(),
                sender,
                Some(binding),
            )
            .is_none()
    );
    receiver
}

#[test]
fn only_the_live_pending_approval_can_cancel_its_execution() {
    for scenario in [
        "matching",
        "wrong-id",
        "wrong-turn",
        "closed",
        "removed",
        "cleared",
    ] {
        let terminal = new_terminal();
        let mut state = TurnState::default();
        let receiver = register_pending(&mut state, "approval-1", "approval-turn", &terminal);
        let mut receiver = Some(receiver);
        match scenario {
            "closed" => drop(receiver.take()),
            "removed" => drop(state.remove_pending_approval("approval-1")),
            "cleared" => state.clear_pending_waiters(),
            _ => {}
        }
        let id = if scenario == "wrong-id" {
            "approval-2"
        } else {
            "approval-1"
        };
        let turn = if scenario == "wrong-turn" {
            "another-turn"
        } else {
            "approval-turn"
        };
        state.mark_pending_exec_approval_cancelled(id, Some(turn));
        assert_eq!(
            terminal.cancelled_at_completion("launch-turn", "parent-call"),
            scenario == "matching",
            "{scenario}"
        );
    }
}

#[test]
fn ordinary_pending_approval_and_channel_drop_do_not_create_exec_cancellation() {
    let terminal = new_terminal();
    let mut state = TurnState::default();
    let (sender, _receiver) = oneshot::channel();
    assert!(
        state
            .insert_pending_approval("parent-call".to_string(), sender)
            .is_none()
    );
    state.mark_pending_exec_approval_cancelled("parent-call", Some("launch-turn"));
    state.clear_pending_waiters();
    assert!(!terminal.cancelled_at_completion("launch-turn", "parent-call"));

    let terminal = new_terminal();
    let mut state = TurnState::default();
    let _receiver = register_pending(&mut state, "approval-1", "approval-turn", &terminal);
    state.clear_pending_waiters();
    assert!(!terminal.cancelled_at_completion("launch-turn", "parent-call"));
}

#[test]
fn reused_parent_call_ids_do_not_share_cancellation() {
    let old_execution = new_terminal();
    let new_execution = new_terminal();
    let mut state = TurnState::default();
    let _old_receiver = register_pending(&mut state, "approval-old", "turn-old", &old_execution);
    let _new_receiver = register_pending(&mut state, "approval-new", "turn-new", &new_execution);
    state.mark_pending_exec_approval_cancelled("approval-old", Some("turn-old"));
    assert!(old_execution.cancelled_at_completion("launch-turn", "parent-call"));
    assert!(!new_execution.cancelled_at_completion("launch-turn", "parent-call"));
}

#[test]
fn later_turn_approval_is_bound_to_its_original_execution_identity() {
    let terminal = new_terminal();
    assert!(
        PendingExecApprovalCancellation::new(
            "approval-turn".to_string(),
            "another-parent",
            Arc::clone(&terminal),
        )
        .is_none()
    );
    let mut state = TurnState::default();
    let _receiver = register_pending(&mut state, "approval-1", "later-turn", &terminal);
    state.mark_pending_exec_approval_cancelled("approval-1", Some("later-turn"));
    assert!(!terminal.cancelled_at_completion("later-turn", "parent-call"));
    assert!(!terminal.cancelled_at_completion("launch-turn", "another-parent"));
    assert!(terminal.cancelled_at_completion("launch-turn", "parent-call"));
}

#[test]
fn completion_first_rejects_late_abort_and_cancel_first_keeps_its_classification() {
    for abort_first in [false, true] {
        let terminal = new_terminal();
        let mut state = TurnState::default();
        let _receiver = register_pending(&mut state, "approval-1", "approval-turn", &terminal);
        if abort_first {
            state.mark_pending_exec_approval_cancelled("approval-1", Some("approval-turn"));
        }
        assert_eq!(
            terminal.cancelled_at_completion("launch-turn", "parent-call"),
            abort_first
        );
        state.mark_pending_exec_approval_cancelled("approval-1", Some("approval-turn"));
        // Re-reading a classification is not an event-delivery gate.
        assert_eq!(
            terminal.cancelled_at_completion("launch-turn", "parent-call"),
            abort_first
        );
    }
}

#[test]
fn omitted_turn_id_still_requires_the_exact_live_approval_id() {
    let terminal = new_terminal();
    let mut state = TurnState::default();
    let _receiver = register_pending(&mut state, "approval-1", "approval-turn", &terminal);
    state.mark_pending_exec_approval_cancelled("approval-1", /*supplied_turn_id*/ None);
    assert!(terminal.cancelled_at_completion("launch-turn", "parent-call"));
}

async fn completion_item(
    exit_code: i32,
    explicit_cancel: bool,
    failure_message: Option<&str>,
) -> CommandExecutionItem {
    let (session, turn, receiver) = make_session_and_context_with_rx().await;
    let terminal = Arc::new(ExecApprovalTerminal::new(
        turn.sub_id.clone(),
        "parent-call".to_string(),
    ));
    let mut state = TurnState::default();
    let _approval_receiver = register_pending(&mut state, "approval-1", "approval-turn", &terminal);
    if explicit_cancel {
        state.mark_pending_exec_approval_cancelled("approval-1", Some("approval-turn"));
    }
    let mut buffer = HeadTailBuffer::default();
    buffer.push_chunk(b"actual output before termination\n");
    let transcript = Arc::new(Mutex::new(buffer));
    let command = vec!["owned-command".to_string(), "argument".to_string()];
    let cwd = codex_utils_path_uri::PathUri::from_host_native_path(
        &std::env::current_dir().expect("test current directory"),
    )
    .expect("absolute test current directory");
    if let Some(message) = failure_message {
        emit_failed_exec_end_for_unified_exec(
            Arc::clone(&session),
            turn,
            "parent-call".to_string(),
            command,
            cwd,
            Some("process-1".to_string()),
            /*plugin_attribution*/ None,
            transcript,
            String::new(),
            message.to_string(),
            Duration::from_millis(17),
            Some(terminal),
        )
        .await;
    } else {
        emit_exec_end_for_unified_exec(
            Arc::clone(&session),
            turn,
            "parent-call".to_string(),
            command,
            cwd,
            Some("process-1".to_string()),
            /*plugin_attribution*/ None,
            transcript,
            "unused fallback".to_string(),
            exit_code,
            Duration::from_millis(17),
            Some(terminal),
        )
        .await;
    }
    let event = receiver
        .try_recv()
        .expect("completion was emitted before return");
    let EventMsg::ItemCompleted(completed) = event.msg else {
        panic!("expected canonical ItemCompleted");
    };
    let TurnItem::CommandExecution(item) = completed.item else {
        panic!("expected canonical command item");
    };
    assert!(
        receiver.try_recv().is_err(),
        "one completion per emitter call"
    );
    item
}

#[tokio::test]
async fn explicit_cancel_changes_only_the_canonical_status_for_real_exit_output() {
    for exit_code in [0, 1] {
        let mut ordinary = completion_item(
            exit_code, /*explicit_cancel*/ false, /*failure_message*/ None,
        )
        .await;
        assert_eq!(
            ordinary.status,
            if exit_code == 0 {
                CommandExecutionStatus::Completed
            } else {
                CommandExecutionStatus::Failed
            }
        );
        assert_eq!(ordinary.exit_code, Some(exit_code));
        let cancelled = completion_item(
            exit_code, /*explicit_cancel*/ true, /*failure_message*/ None,
        )
        .await;
        ordinary.status = CommandExecutionStatus::Declined;
        assert_eq!(cancelled, ordinary);
    }
}

#[tokio::test]
async fn explicit_cancel_preserves_the_existing_failed_completion_payload() {
    let mut ordinary = completion_item(
        /*exit_code*/ 1,
        /*explicit_cancel*/ false,
        Some("original failure"),
    )
    .await;
    assert_eq!(ordinary.status, CommandExecutionStatus::Failed);
    assert_eq!(ordinary.exit_code, Some(-1));
    let cancelled = completion_item(
        /*exit_code*/ 1,
        /*explicit_cancel*/ true,
        Some("original failure"),
    )
    .await;
    ordinary.status = CommandExecutionStatus::Declined;
    assert_eq!(cancelled, ordinary);
}
