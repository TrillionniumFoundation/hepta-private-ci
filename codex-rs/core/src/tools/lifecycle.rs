use std::sync::Arc;

use codex_extension_api::ToolCallOutcome;
use codex_extension_api::ToolCallSource as ExtensionToolCallSource;
use codex_extension_api::ToolFinishInput;
use codex_extension_api::ToolPolicyDecision;
use codex_extension_api::ToolPolicyError;
use codex_extension_api::ToolPolicyInput;
use codex_extension_api::ToolPolicyTerminalInput;
use codex_extension_api::ToolStartInput;
use codex_tools::ToolName;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::sync::Notify;

use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolInvocation;

#[derive(Debug)]
struct ToolDispatchAttemptState {
    id: String,
    host_accepted: AtomicBool,
    policy_active: AtomicBool,
    policy_terminal_phase: Mutex<ToolPolicyTerminalPhase>,
    policy_terminal_changed: Notify,
}

#[derive(Clone, Debug)]
pub(crate) struct ToolDispatchAttemptId(Arc<ToolDispatchAttemptState>);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ToolPolicyTerminalPhase {
    Open,
    CancellationClaimed,
    PreHandlerWriting,
    PreHandlerCommitted,
    PreHandlerUnconfirmed,
    HandlerWriting,
    HandlerCommitted,
    HandlerUnconfirmed,
}

impl ToolDispatchAttemptId {
    pub(crate) fn new() -> Self {
        Self(Arc::new(ToolDispatchAttemptState {
            id: uuid::Uuid::new_v4().to_string(),
            host_accepted: AtomicBool::new(false),
            policy_active: AtomicBool::new(false),
            policy_terminal_phase: Mutex::new(ToolPolicyTerminalPhase::Open),
            policy_terminal_changed: Notify::new(),
        }))
    }

    pub(crate) fn as_str(&self) -> &str {
        self.0.id.as_str()
    }

    pub(crate) fn mark_host_accepted(&self) {
        self.0.host_accepted.store(true, Ordering::Release);
    }

    pub(crate) fn host_accepted(&self) -> bool {
        self.0.host_accepted.load(Ordering::Acquire)
    }

    pub(crate) fn activate_policy(&self) {
        self.0.policy_active.store(true, Ordering::Release);
    }

    pub(crate) fn policy_is_active(&self) -> bool {
        self.0.policy_active.load(Ordering::Acquire)
    }

    pub(crate) fn policy_terminal_phase(&self) -> ToolPolicyTerminalPhase {
        *self
            .0
            .policy_terminal_phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub(crate) fn try_claim_policy_cancellation(&self) -> bool {
        self.transition_policy_terminal(
            ToolPolicyTerminalPhase::Open,
            ToolPolicyTerminalPhase::CancellationClaimed,
        )
    }

    pub(crate) fn try_begin_handler_terminal(&self) -> bool {
        let mut phase = self
            .0
            .policy_terminal_phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !matches!(
            *phase,
            ToolPolicyTerminalPhase::Open | ToolPolicyTerminalPhase::CancellationClaimed
        ) {
            return false;
        }
        *phase = ToolPolicyTerminalPhase::HandlerWriting;
        drop(phase);
        self.0.policy_terminal_changed.notify_waiters();
        true
    }

    pub(crate) fn try_begin_pre_handler_terminal(&self) -> bool {
        self.transition_policy_terminal(
            ToolPolicyTerminalPhase::Open,
            ToolPolicyTerminalPhase::PreHandlerWriting,
        )
    }

    pub(crate) fn mark_pre_handler_terminal_committed(&self) -> bool {
        self.transition_policy_terminal(
            ToolPolicyTerminalPhase::PreHandlerWriting,
            ToolPolicyTerminalPhase::PreHandlerCommitted,
        )
    }

    pub(crate) fn mark_pre_handler_terminal_unconfirmed(&self) -> bool {
        self.transition_policy_terminal(
            ToolPolicyTerminalPhase::PreHandlerWriting,
            ToolPolicyTerminalPhase::PreHandlerUnconfirmed,
        )
    }

    pub(crate) fn try_begin_indeterminate_terminal(&self) -> bool {
        let mut phase = self
            .0
            .policy_terminal_phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !matches!(
            *phase,
            ToolPolicyTerminalPhase::Open | ToolPolicyTerminalPhase::CancellationClaimed
        ) {
            return false;
        }
        *phase = ToolPolicyTerminalPhase::HandlerWriting;
        drop(phase);
        self.0.policy_terminal_changed.notify_waiters();
        true
    }

    pub(crate) fn mark_handler_terminal_committed(&self) -> bool {
        self.transition_policy_terminal(
            ToolPolicyTerminalPhase::HandlerWriting,
            ToolPolicyTerminalPhase::HandlerCommitted,
        )
    }

    pub(crate) fn mark_handler_terminal_unconfirmed(&self) -> bool {
        self.transition_policy_terminal(
            ToolPolicyTerminalPhase::HandlerWriting,
            ToolPolicyTerminalPhase::HandlerUnconfirmed,
        )
    }

    pub(crate) async fn wait_for_policy_terminal_resolution(&self) -> ToolPolicyTerminalPhase {
        loop {
            let changed = self.0.policy_terminal_changed.notified();
            let phase = self.policy_terminal_phase();
            if !matches!(
                phase,
                ToolPolicyTerminalPhase::PreHandlerWriting
                    | ToolPolicyTerminalPhase::HandlerWriting
            ) {
                return phase;
            }
            changed.await;
        }
    }

    fn transition_policy_terminal(
        &self,
        expected: ToolPolicyTerminalPhase,
        next: ToolPolicyTerminalPhase,
    ) -> bool {
        let mut phase = self
            .0
            .policy_terminal_phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if *phase != expected {
            return false;
        }
        *phase = next;
        drop(phase);
        self.0.policy_terminal_changed.notify_waiters();
        true
    }
}

pub(crate) fn has_active_tool_policy(session: &Session) -> bool {
    session
        .services
        .extensions
        .tool_policy_contributors()
        .iter()
        .any(|contributor| contributor.is_active(&session.services.thread_extension_data))
}

pub(crate) async fn notify_tool_start(invocation: &ToolInvocation) {
    let contributors = invocation
        .session
        .services
        .extensions
        .tool_lifecycle_contributors();
    if contributors.is_empty() {
        return;
    }
    let thread_store = &invocation.session.services.thread_extension_data;
    let conversation_history = invocation.session.conversation_history_snapshot().await;

    for contributor in contributors {
        contributor
            .on_tool_start(ToolStartInput {
                session_store: &invocation.session.services.session_extension_data,
                thread_store,
                turn_store: invocation.turn.extension_data.as_ref(),
                turn_id: invocation.turn.sub_id.as_str(),
                call_id: invocation.call_id.as_str(),
                tool_name: &invocation.tool_name,
                payload: &invocation.payload,
                conversation_history: Arc::clone(&conversation_history),
                source: extension_tool_call_source(invocation.source.clone()),
            })
            .await;
    }
}

pub(crate) async fn enforce_tool_admission(
    invocation: &ToolInvocation,
    attempt_id: &ToolDispatchAttemptId,
) -> Result<(), FunctionCallError> {
    evaluate_tool_policy(invocation, attempt_id, ToolPolicyGate::Admission).await
}

pub(crate) async fn enforce_tool_authorization(
    invocation: &ToolInvocation,
    attempt_id: &ToolDispatchAttemptId,
) -> Result<(), FunctionCallError> {
    evaluate_tool_policy(invocation, attempt_id, ToolPolicyGate::Authorization).await
}

pub(crate) async fn notify_tool_finish(
    invocation: &ToolInvocation,
    attempt_id: &ToolDispatchAttemptId,
    outcome: ToolCallOutcome,
) -> Result<(), FunctionCallError> {
    let terminal_result = notify_tool_policy_terminal_parts(
        invocation.session.as_ref(),
        invocation.turn.as_ref(),
        invocation.call_id.as_str(),
        attempt_id,
        &invocation.tool_name,
        invocation.source.clone(),
        outcome,
        attempt_id.host_accepted(),
    )
    .await;
    notify_tool_lifecycle_finish(invocation, outcome).await;
    terminal_result
}

pub(crate) async fn notify_tool_policy_terminal(
    invocation: &ToolInvocation,
    attempt_id: &ToolDispatchAttemptId,
    outcome: ToolCallOutcome,
) -> Result<(), FunctionCallError> {
    notify_tool_policy_terminal_parts(
        invocation.session.as_ref(),
        invocation.turn.as_ref(),
        invocation.call_id.as_str(),
        attempt_id,
        &invocation.tool_name,
        invocation.source.clone(),
        outcome,
        attempt_id.host_accepted(),
    )
    .await
}

pub(crate) async fn notify_tool_lifecycle_finish(
    invocation: &ToolInvocation,
    outcome: ToolCallOutcome,
) {
    notify_tool_lifecycle_finish_parts(
        invocation.session.as_ref(),
        invocation.turn.as_ref(),
        invocation.call_id.as_str(),
        &invocation.tool_name,
        invocation.source.clone(),
        outcome,
    )
    .await;
}

pub(crate) async fn notify_tool_admission_blocked(
    invocation: &ToolInvocation,
    attempt_id: &ToolDispatchAttemptId,
) -> Result<(), FunctionCallError> {
    notify_tool_policy_terminal_parts(
        invocation.session.as_ref(),
        invocation.turn.as_ref(),
        invocation.call_id.as_str(),
        attempt_id,
        &invocation.tool_name,
        invocation.source.clone(),
        ToolCallOutcome::Blocked,
        attempt_id.host_accepted(),
    )
    .await
}

pub(crate) async fn notify_tool_aborted(
    session: &Session,
    turn: &TurnContext,
    call_id: &str,
    attempt_id: &ToolDispatchAttemptId,
    tool_name: &ToolName,
    source: ToolCallSource,
) -> Result<(), FunctionCallError> {
    let terminal_result = notify_tool_policy_terminal_parts(
        session,
        turn,
        call_id,
        attempt_id,
        tool_name,
        source.clone(),
        ToolCallOutcome::Aborted,
        attempt_id.host_accepted(),
    )
    .await;
    notify_tool_lifecycle_finish_parts(
        session,
        turn,
        call_id,
        tool_name,
        source,
        ToolCallOutcome::Aborted,
    )
    .await;
    terminal_result
}

pub(crate) async fn notify_tool_indeterminate(
    session: &Session,
    turn: &TurnContext,
    call_id: &str,
    attempt_id: &ToolDispatchAttemptId,
    tool_name: &ToolName,
    source: ToolCallSource,
    reason_code: &'static str,
) -> Result<(), FunctionCallError> {
    let outcome = ToolCallOutcome::Indeterminate { reason_code };
    let terminal_result = notify_tool_policy_terminal_parts(
        session,
        turn,
        call_id,
        attempt_id,
        tool_name,
        source.clone(),
        outcome,
        attempt_id.host_accepted(),
    )
    .await;
    notify_tool_lifecycle_finish_parts(session, turn, call_id, tool_name, source, outcome).await;
    terminal_result
}

#[expect(
    clippy::too_many_arguments,
    reason = "terminal evidence must carry the complete immutable tool-call binding"
)]
async fn notify_tool_policy_terminal_parts(
    session: &Session,
    turn: &TurnContext,
    call_id: &str,
    attempt_id: &ToolDispatchAttemptId,
    tool_name: &ToolName,
    source: ToolCallSource,
    outcome: ToolCallOutcome,
    host_accepted: bool,
) -> Result<(), FunctionCallError> {
    let mut terminal_error = None;
    for contributor in session.services.extensions.tool_policy_contributors() {
        if !contributor.is_active(&session.services.thread_extension_data) {
            continue;
        }
        if let Err(error) = contributor
            .on_terminal(ToolPolicyTerminalInput {
                session_store: &session.services.session_extension_data,
                thread_store: &session.services.thread_extension_data,
                turn_store: turn.extension_data.as_ref(),
                turn_id: turn.sub_id.as_str(),
                call_id,
                attempt_id: attempt_id.as_str(),
                tool_name,
                source: extension_tool_call_source(source.clone()),
                outcome,
                host_accepted,
            })
            .await
        {
            terminal_error.get_or_insert(error);
        }
    }
    terminal_error.map_or(Ok(()), |error| Err(policy_failure(error, "terminal")))
}

async fn notify_tool_lifecycle_finish_parts(
    session: &Session,
    turn: &TurnContext,
    call_id: &str,
    tool_name: &ToolName,
    source: ToolCallSource,
    outcome: ToolCallOutcome,
) {
    for contributor in session.services.extensions.tool_lifecycle_contributors() {
        contributor
            .on_tool_finish(ToolFinishInput {
                session_store: &session.services.session_extension_data,
                thread_store: &session.services.thread_extension_data,
                turn_store: turn.extension_data.as_ref(),
                turn_id: turn.sub_id.as_str(),
                call_id,
                tool_name,
                source: extension_tool_call_source(source.clone()),
                outcome,
            })
            .await;
    }
}

#[derive(Clone, Copy)]
enum ToolPolicyGate {
    Admission,
    Authorization,
}

async fn evaluate_tool_policy(
    invocation: &ToolInvocation,
    attempt_id: &ToolDispatchAttemptId,
    gate: ToolPolicyGate,
) -> Result<(), FunctionCallError> {
    for contributor in invocation
        .session
        .services
        .extensions
        .tool_policy_contributors()
    {
        if !contributor.is_active(&invocation.session.services.thread_extension_data) {
            continue;
        }
        let input = ToolPolicyInput {
            session_store: &invocation.session.services.session_extension_data,
            thread_store: &invocation.session.services.thread_extension_data,
            turn_store: invocation.turn.extension_data.as_ref(),
            turn_id: invocation.turn.sub_id.as_str(),
            call_id: invocation.call_id.as_str(),
            attempt_id: attempt_id.as_str(),
            tool_name: &invocation.tool_name,
            source: extension_tool_call_source(invocation.source.clone()),
            payload: &invocation.payload,
        };
        let decision = match gate {
            ToolPolicyGate::Admission => contributor.admit(input).await,
            ToolPolicyGate::Authorization => contributor.authorize(input).await,
        }
        .map_err(|error| {
            policy_failure(
                error,
                match gate {
                    ToolPolicyGate::Admission => "admission",
                    ToolPolicyGate::Authorization => "authorization",
                },
            )
        })?;
        if let ToolPolicyDecision::Block {
            reason_code,
            message,
        } = decision
        {
            tracing::warn!(%reason_code, "tool policy blocked execution");
            return Err(FunctionCallError::RespondToModel(message));
        }
    }
    Ok(())
}

fn policy_failure(error: ToolPolicyError, phase: &'static str) -> FunctionCallError {
    tracing::error!(
        phase,
        reason_code = error.reason_code(),
        detail = error.detail(),
        "tool policy failed closed"
    );
    FunctionCallError::Fatal(format!(
        "tool policy failed closed during {phase} ({})",
        error.reason_code()
    ))
}

pub(crate) fn extension_tool_call_source(source: ToolCallSource) -> ExtensionToolCallSource {
    match source {
        ToolCallSource::Direct => ExtensionToolCallSource::Direct,
        ToolCallSource::DirectPlaintextMessage => ExtensionToolCallSource::DirectPlaintextMessage,
        ToolCallSource::CodeMode {
            cell_id,
            runtime_tool_call_id,
        } => ExtensionToolCallSource::CodeMode {
            cell_id,
            runtime_tool_call_id,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::ExtensionToolCallSource;
    use super::ToolCallSource;
    use super::extension_tool_call_source;

    #[test]
    fn plaintext_collaboration_source_is_not_downgraded_to_direct() {
        assert_eq!(
            extension_tool_call_source(ToolCallSource::DirectPlaintextMessage),
            ExtensionToolCallSource::DirectPlaintextMessage,
        );
    }
}
