use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::RwLock;
use tokio::task::JoinError;
use tokio_util::either::Either;
use tokio_util::sync::CancellationToken;
use tokio_util::task::AbortOnDropHandle;
use tracing::Instrument;
use tracing::info;
use tracing::instrument;
use tracing::trace_span;

use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::step_context::StepContext;
use crate::tools::context::AbortedToolOutput;
use crate::tools::context::SharedTurnDiffTracker;
use crate::tools::context::ToolPayload;
use crate::tools::lifecycle::ToolDispatchAttemptId;
use crate::tools::lifecycle::ToolPolicyTerminalPhase;
use crate::tools::lifecycle::has_active_tool_policy;
use crate::tools::lifecycle::notify_tool_aborted;
use crate::tools::lifecycle::notify_tool_indeterminate;
use crate::tools::registry::AnyToolResult;
use crate::tools::registry::ToolArgumentDiffConsumer;
use crate::tools::router::ToolCall;
use crate::tools::router::ToolCallSource;
use codex_protocol::error::CodexErr;
use codex_protocol::models::ResponseInputItem;

const HANDLER_TASK_JOIN_ERROR_REASON_CODE: &str = "handler_task_join_error";
#[cfg(not(test))]
const POLICY_TERMINAL_CANCELLATION_GRACE: Duration = Duration::from_secs(1);
#[cfg(test)]
const POLICY_TERMINAL_CANCELLATION_GRACE: Duration = Duration::from_millis(50);
const POLICY_RESULT_WITHHELD_MESSAGE: &str = "tool dispatch reached a durable terminal before cancellation, but result post-processing did not finish; result withheld; do not retry automatically";
const POLICY_TERMINAL_UNCONFIRMED_MESSAGE: &str =
    "tool policy terminal persistence is unconfirmed; do not retry automatically";

struct ToolCallTimingGuard {
    started_at: Instant,
    execution_started_at: Arc<OnceLock<Instant>>,
    conversation_id: String,
    turn_id: String,
    call_id: String,
    tool_name: codex_tools::ToolName,
}

#[derive(Clone)]
pub(crate) struct ToolCallRuntime {
    session: Arc<Session>,
    // Tool calls may run later, so retain the step whose tool list advertised them.
    step_context: Arc<StepContext>,
    tracker: SharedTurnDiffTracker,
    parallel_execution: Arc<RwLock<()>>,
}

impl ToolCallRuntime {
    pub(crate) fn new(
        session: Arc<Session>,
        step_context: Arc<StepContext>,
        tracker: SharedTurnDiffTracker,
    ) -> Self {
        Self {
            session,
            step_context,
            tracker,
            parallel_execution: Arc::new(RwLock::new(())),
        }
    }

    pub(crate) fn create_diff_consumer(
        &self,
        tool_name: &codex_tools::ToolName,
    ) -> Option<Box<dyn ToolArgumentDiffConsumer>> {
        self.step_context
            .tool_router
            .create_diff_consumer(tool_name)
    }

    #[instrument(level = "trace", skip_all)]
    pub(crate) fn handle_tool_call(
        self,
        call: ToolCall,
        cancellation_token: CancellationToken,
    ) -> impl std::future::Future<Output = Result<ResponseInputItem, CodexErr>> {
        let error_call = call.clone();
        let source = call.direct_source();
        let future = self.handle_tool_call_with_source(call, source, cancellation_token);
        async move {
            match future.await {
                Ok(response) => Ok(response.into_response()),
                Err(FunctionCallError::Fatal(message)) => Err(CodexErr::Fatal(message)),
                Err(other) => Ok(Self::failure_response(error_call, other)),
            }
        }
        .in_current_span()
    }

    #[instrument(level = "trace", skip_all)]
    pub(crate) fn handle_tool_call_with_source(
        self,
        call: ToolCall,
        source: ToolCallSource,
        cancellation_token: CancellationToken,
    ) -> impl std::future::Future<Output = Result<AnyToolResult, FunctionCallError>> {
        if self
            .step_context
            .turn
            .config
            .features
            .enabled(codex_features::Feature::ExecutedToolCallMetadata)
            && let Some(executed_tool_calls) = self.session.services.executed_tool_calls.as_ref()
        {
            executed_tool_calls.record_tool_call(
                &call,
                &source,
                super::effective_tool_mode(&self.step_context.turn),
            );
        }
        let router = &self.step_context.tool_router;
        let supports_parallel = router.tool_supports_parallel(&call);
        let tool_runtime = router.tool_runtime(&call);
        let wait_for_runtime_cancellation = tool_runtime
            .as_ref()
            .is_some_and(|runtime| runtime.waits_for_runtime_cancellation());
        let router = Arc::clone(router);
        let session = Arc::clone(&self.session);
        let step_context = Arc::clone(&self.step_context);
        let turn = Arc::clone(&step_context.turn);
        let tracker = Arc::clone(&self.tracker);
        let lock = Arc::clone(&self.parallel_execution);
        let invocation_cancellation_token = cancellation_token.clone();
        let started = Instant::now();
        let tool_call_timing_guard =
            ToolCallTimingGuard::capture(started, &session.thread_id, &turn.sub_id, &call, &source);
        let execution_started_at = tool_call_timing_guard
            .as_ref()
            .map(|timing| Arc::clone(&timing.execution_started_at));
        let abort_session = Arc::clone(&session);
        let abort_source = source.clone();
        let abort_turn = Arc::clone(&turn);
        let attempt_id = ToolDispatchAttemptId::new();
        if has_active_tool_policy(session.as_ref()) {
            attempt_id.activate_policy();
        }
        let dispatch_attempt_id = attempt_id.clone();
        let terminal_outcome_reached = Arc::new(AtomicBool::new(false));
        let dispatch_terminal_outcome_reached = Arc::clone(&terminal_outcome_reached);
        let dispatch_call = call.clone();

        let dispatch_span = trace_span!(
            "dispatch_tool_call_with_code_mode_result",
            otel.name = %call.tool_name,
            tool_name = %call.tool_name,
            call_id = call.call_id.as_str(),
            aborted = false,
        );
        let abort_dispatch_span = dispatch_span.clone();

        let mut dispatch_handle: AbortOnDropHandle<Result<AnyToolResult, FunctionCallError>> =
            AbortOnDropHandle::new(tokio::spawn(async move {
                if let Some(tool_runtime) = tool_runtime
                    && let Some(readiness) = tool_runtime.wait_until_ready(&session)
                {
                    readiness.await;
                }

                let _guard = if supports_parallel {
                    Either::Left(lock.read().await)
                } else {
                    Either::Right(lock.write().await)
                };
                // Admission through the parallel-execution gate marks the end
                // of dispatch waiting and the start of handler execution.
                if let Some(execution_started_at) = execution_started_at {
                    let _ = execution_started_at.set(Instant::now());
                }

                router
                    .dispatch_tool_call_with_terminal_outcome(
                        session,
                        step_context,
                        invocation_cancellation_token,
                        tracker,
                        dispatch_call,
                        source.clone(),
                        dispatch_attempt_id,
                        dispatch_terminal_outcome_reached,
                    )
                    .instrument(dispatch_span.clone())
                    .await
            }));

        async move {
            let _tool_call_timing_guard = tool_call_timing_guard;
            tokio::select! {
                res = &mut dispatch_handle => match res {
                    Ok(result) => result,
                    Err(err) => {
                        Self::notify_join_error_terminal_if_needed(
                            abort_session.as_ref(),
                            abort_turn.as_ref(),
                            &call,
                            &attempt_id,
                            abort_source.clone(),
                            terminal_outcome_reached.as_ref(),
                            /*terminal_claimed_by_outer*/ false,
                        )
                        .await?;
                        Err(Self::tool_task_join_error(err))
                    }
                },
                _ = cancellation_token.cancelled() => {
                    if attempt_id.policy_is_active() {
                        return Self::handle_active_policy_cancellation(
                            &mut dispatch_handle,
                            wait_for_runtime_cancellation,
                            started,
                            &abort_dispatch_span,
                            abort_session.as_ref(),
                            abort_turn.as_ref(),
                            &call,
                            &attempt_id,
                            abort_source,
                            terminal_outcome_reached.as_ref(),
                        )
                        .await;
                    }
                    if terminal_outcome_reached.load(Ordering::Acquire) || dispatch_handle.is_finished() {
                        match dispatch_handle.await {
                            Ok(result) => result,
                            Err(err) => {
                                Self::notify_join_error_terminal_if_needed(
                                    abort_session.as_ref(),
                                    abort_turn.as_ref(),
                                    &call,
                                    &attempt_id,
                                    abort_source.clone(),
                                    terminal_outcome_reached.as_ref(),
                                    /*terminal_claimed_by_outer*/ false,
                                )
                                .await?;
                                Err(Self::tool_task_join_error(err))
                            }
                        }
                    } else {
                        let secs = started.elapsed().as_secs_f32().max(0.1);
                        abort_dispatch_span.record("aborted", true);
                        if wait_for_runtime_cancellation {
                            if terminal_outcome_reached.swap(true, Ordering::AcqRel) {
                                return match dispatch_handle.await {
                                    Ok(result) => result,
                                    Err(err) => {
                                        Self::notify_join_error_terminal_if_needed(
                                            abort_session.as_ref(),
                                            abort_turn.as_ref(),
                                            &call,
                                            &attempt_id,
                                            abort_source.clone(),
                                            terminal_outcome_reached.as_ref(),
                                            /*terminal_claimed_by_outer*/ false,
                                        )
                                        .await?;
                                        Err(Self::tool_task_join_error(err))
                                    }
                                };
                            }
                            // The abort owns the terminal outcome; await only so
                            // the runtime can finish process teardown.
                            match dispatch_handle.await {
                                Ok(_) => {}
                                Err(err) if err.is_cancelled() => {}
                                Err(err) => {
                                    Self::notify_join_error_terminal_if_needed(
                                        abort_session.as_ref(),
                                        abort_turn.as_ref(),
                                        &call,
                                        &attempt_id,
                                        abort_source.clone(),
                                        terminal_outcome_reached.as_ref(),
                                        /*terminal_claimed_by_outer*/ true,
                                    )
                                    .await?;
                                    return Err(Self::tool_task_join_error(err));
                                }
                            }
                        } else {
                            if terminal_outcome_reached.swap(true, Ordering::AcqRel) {
                                return match dispatch_handle.await {
                                    Ok(result) => result,
                                    Err(err) => {
                                        Self::notify_join_error_terminal_if_needed(
                                            abort_session.as_ref(),
                                            abort_turn.as_ref(),
                                            &call,
                                            &attempt_id,
                                            abort_source.clone(),
                                            terminal_outcome_reached.as_ref(),
                                            /*terminal_claimed_by_outer*/ false,
                                        )
                                        .await?;
                                        Err(Self::tool_task_join_error(err))
                                    }
                                };
                            }
                            dispatch_handle.abort();
                            match dispatch_handle.await {
                                Ok(result) => return result,
                                Err(err) if err.is_cancelled() => {}
                                Err(err) => {
                                    Self::notify_join_error_terminal_if_needed(
                                        abort_session.as_ref(),
                                        abort_turn.as_ref(),
                                        &call,
                                        &attempt_id,
                                        abort_source.clone(),
                                        terminal_outcome_reached.as_ref(),
                                        /*terminal_claimed_by_outer*/ true,
                                    )
                                    .await?;
                                    return Err(Self::tool_task_join_error(err));
                                }
                            }
                        }
                        let response = Self::aborted_response(&call, secs);
                        notify_tool_aborted(
                            abort_session.as_ref(),
                            abort_turn.as_ref(),
                            call.call_id.as_str(),
                            &attempt_id,
                            &call.tool_name,
                            abort_source,
                        )
                        .await?;
                        Ok(response)
                    }
                },
            }
        }
        .in_current_span()
    }
}

impl ToolCallRuntime {
    #[allow(clippy::too_many_arguments)]
    async fn handle_active_policy_cancellation(
        dispatch_handle: &mut AbortOnDropHandle<Result<AnyToolResult, FunctionCallError>>,
        wait_for_runtime_cancellation: bool,
        started: Instant,
        abort_dispatch_span: &tracing::Span,
        session: &Session,
        turn: &crate::session::turn_context::TurnContext,
        call: &ToolCall,
        attempt_id: &ToolDispatchAttemptId,
        source: ToolCallSource,
        legacy_terminal_outcome_reached: &AtomicBool,
    ) -> Result<AnyToolResult, FunctionCallError> {
        if dispatch_handle.is_finished() {
            return match (&mut *dispatch_handle).await {
                Ok(result) => result,
                Err(err) => {
                    Self::notify_join_error_terminal_if_needed(
                        session,
                        turn,
                        call,
                        attempt_id,
                        source,
                        legacy_terminal_outcome_reached,
                        /*terminal_claimed_by_outer*/ false,
                    )
                    .await?;
                    Err(Self::tool_task_join_error(err))
                }
            };
        }

        loop {
            match attempt_id.policy_terminal_phase() {
                ToolPolicyTerminalPhase::Open => {
                    if !attempt_id.try_claim_policy_cancellation() {
                        continue;
                    }
                }
                ToolPolicyTerminalPhase::PreHandlerWriting => {
                    match tokio::time::timeout(
                        POLICY_TERMINAL_CANCELLATION_GRACE,
                        attempt_id.wait_for_policy_terminal_resolution(),
                    )
                    .await
                    {
                        Ok(_) => continue,
                        Err(_) => {
                            if !attempt_id.mark_pre_handler_terminal_unconfirmed() {
                                continue;
                            }
                            dispatch_handle.abort();
                            let _ = (&mut *dispatch_handle).await;
                            return Err(FunctionCallError::Fatal(
                                POLICY_TERMINAL_UNCONFIRMED_MESSAGE.to_string(),
                            ));
                        }
                    }
                }
                ToolPolicyTerminalPhase::HandlerWriting => {
                    match tokio::time::timeout(
                        POLICY_TERMINAL_CANCELLATION_GRACE,
                        attempt_id.wait_for_policy_terminal_resolution(),
                    )
                    .await
                    {
                        Ok(_) => continue,
                        Err(_) => {
                            if !attempt_id.mark_handler_terminal_unconfirmed() {
                                continue;
                            }
                            dispatch_handle.abort();
                            let _ = (&mut *dispatch_handle).await;
                            return Err(FunctionCallError::Fatal(
                                POLICY_TERMINAL_UNCONFIRMED_MESSAGE.to_string(),
                            ));
                        }
                    }
                }
                ToolPolicyTerminalPhase::PreHandlerCommitted
                | ToolPolicyTerminalPhase::HandlerCommitted => {
                    dispatch_handle.abort();
                    match (&mut *dispatch_handle).await {
                        Ok(_) => {}
                        Err(err) if err.is_cancelled() => {}
                        Err(err) => return Err(Self::tool_task_join_error(err)),
                    }
                    return Ok(Self::policy_result_withheld_response(call));
                }
                ToolPolicyTerminalPhase::PreHandlerUnconfirmed
                | ToolPolicyTerminalPhase::HandlerUnconfirmed => {
                    dispatch_handle.abort();
                    let _ = (&mut *dispatch_handle).await;
                    return Err(FunctionCallError::Fatal(
                        POLICY_TERMINAL_UNCONFIRMED_MESSAGE.to_string(),
                    ));
                }
                ToolPolicyTerminalPhase::CancellationClaimed => {
                    let secs = started.elapsed().as_secs_f32().max(0.1);
                    abort_dispatch_span.record("aborted", true);
                    let joined = if wait_for_runtime_cancellation {
                        (&mut *dispatch_handle).await
                    } else {
                        dispatch_handle.abort();
                        (&mut *dispatch_handle).await
                    };
                    match joined {
                        Ok(result) => {
                            if attempt_id.policy_terminal_phase()
                                == ToolPolicyTerminalPhase::CancellationClaimed
                            {
                                notify_tool_aborted(
                                    session,
                                    turn,
                                    call.call_id.as_str(),
                                    attempt_id,
                                    &call.tool_name,
                                    source.clone(),
                                )
                                .await?;
                                return Ok(Self::aborted_response(call, secs));
                            }
                            if matches!(
                                attempt_id.policy_terminal_phase(),
                                ToolPolicyTerminalPhase::PreHandlerCommitted
                                    | ToolPolicyTerminalPhase::HandlerCommitted
                            ) {
                                return Ok(Self::policy_result_withheld_response(call));
                            }
                            if matches!(
                                attempt_id.policy_terminal_phase(),
                                ToolPolicyTerminalPhase::PreHandlerUnconfirmed
                                    | ToolPolicyTerminalPhase::HandlerUnconfirmed
                            ) {
                                return Err(FunctionCallError::Fatal(
                                    POLICY_TERMINAL_UNCONFIRMED_MESSAGE.to_string(),
                                ));
                            }
                            return result;
                        }
                        Err(err) if err.is_cancelled() => {
                            if attempt_id.policy_terminal_phase()
                                == ToolPolicyTerminalPhase::CancellationClaimed
                            {
                                notify_tool_aborted(
                                    session,
                                    turn,
                                    call.call_id.as_str(),
                                    attempt_id,
                                    &call.tool_name,
                                    source.clone(),
                                )
                                .await?;
                                return Ok(Self::aborted_response(call, secs));
                            }
                            continue;
                        }
                        Err(err) => {
                            Self::notify_join_error_terminal_if_needed(
                                session,
                                turn,
                                call,
                                attempt_id,
                                source.clone(),
                                legacy_terminal_outcome_reached,
                                /*terminal_claimed_by_outer*/ true,
                            )
                            .await?;
                            return Err(Self::tool_task_join_error(err));
                        }
                    }
                }
            }
        }
    }

    async fn notify_join_error_terminal_if_needed(
        session: &Session,
        turn: &crate::session::turn_context::TurnContext,
        call: &ToolCall,
        attempt_id: &ToolDispatchAttemptId,
        source: ToolCallSource,
        terminal_outcome_reached: &AtomicBool,
        terminal_claimed_by_outer: bool,
    ) -> Result<(), FunctionCallError> {
        if attempt_id.policy_is_active() {
            match attempt_id.policy_terminal_phase() {
                ToolPolicyTerminalPhase::PreHandlerWriting => {
                    attempt_id.mark_pre_handler_terminal_unconfirmed();
                    return Ok(());
                }
                ToolPolicyTerminalPhase::HandlerWriting => {
                    attempt_id.mark_handler_terminal_unconfirmed();
                    return Ok(());
                }
                ToolPolicyTerminalPhase::PreHandlerCommitted
                | ToolPolicyTerminalPhase::PreHandlerUnconfirmed
                | ToolPolicyTerminalPhase::HandlerCommitted
                | ToolPolicyTerminalPhase::HandlerUnconfirmed => return Ok(()),
                ToolPolicyTerminalPhase::Open | ToolPolicyTerminalPhase::CancellationClaimed => {
                    if !attempt_id.try_begin_indeterminate_terminal() {
                        return Ok(());
                    }
                    let terminal_result = notify_tool_indeterminate(
                        session,
                        turn,
                        call.call_id.as_str(),
                        attempt_id,
                        &call.tool_name,
                        source,
                        HANDLER_TASK_JOIN_ERROR_REASON_CODE,
                    )
                    .await;
                    return match terminal_result {
                        Ok(()) if attempt_id.mark_handler_terminal_committed() => Ok(()),
                        Ok(()) => Err(FunctionCallError::Fatal(
                            POLICY_TERMINAL_UNCONFIRMED_MESSAGE.to_string(),
                        )),
                        Err(err) => {
                            attempt_id.mark_handler_terminal_unconfirmed();
                            Err(err)
                        }
                    };
                }
            }
        }
        if !terminal_claimed_by_outer && terminal_outcome_reached.swap(true, Ordering::AcqRel) {
            return Ok(());
        }
        notify_tool_indeterminate(
            session,
            turn,
            call.call_id.as_str(),
            attempt_id,
            &call.tool_name,
            source,
            HANDLER_TASK_JOIN_ERROR_REASON_CODE,
        )
        .await
    }

    fn tool_task_join_error(err: JoinError) -> FunctionCallError {
        FunctionCallError::Fatal(format!("tool task failed to receive: {err:?}"))
    }

    fn failure_response(call: ToolCall, err: FunctionCallError) -> ResponseInputItem {
        let message = err.to_string();
        match call.payload {
            ToolPayload::ToolSearch { .. } => ResponseInputItem::ToolSearchOutput {
                call_id: call.call_id,
                status: "completed".to_string(),
                execution: "client".to_string(),
                tools: Vec::new(),
            },
            ToolPayload::Custom { .. } => ResponseInputItem::CustomToolCallOutput {
                call_id: call.call_id,
                name: None,
                output: codex_protocol::models::FunctionCallOutputPayload {
                    body: codex_protocol::models::FunctionCallOutputBody::Text(message),
                    success: Some(false),
                },
            },
            _ => ResponseInputItem::FunctionCallOutput {
                call_id: call.call_id,
                output: codex_protocol::models::FunctionCallOutputPayload {
                    body: codex_protocol::models::FunctionCallOutputBody::Text(message),
                    success: Some(false),
                },
            },
        }
    }

    fn aborted_response(call: &ToolCall, secs: f32) -> AnyToolResult {
        AnyToolResult {
            call_id: call.call_id.clone(),
            payload: call.payload.clone(),
            result: Box::new(AbortedToolOutput {
                message: Self::abort_message(call, secs),
            }),
            post_tool_use_payload: None,
        }
    }

    fn policy_result_withheld_response(call: &ToolCall) -> AnyToolResult {
        AnyToolResult {
            call_id: call.call_id.clone(),
            payload: call.payload.clone(),
            result: Box::new(AbortedToolOutput {
                message: POLICY_RESULT_WITHHELD_MESSAGE.to_string(),
            }),
            post_tool_use_payload: None,
        }
    }

    fn abort_message(call: &ToolCall, secs: f32) -> String {
        if call.tool_name.is_default_namespace() && call.tool_name.name == "exec_command" {
            format!("Wall time: {secs:.1} seconds\naborted by user")
        } else {
            format!("aborted by user after {secs:.1}s")
        }
    }
}

impl ToolCallTimingGuard {
    fn capture(
        started_at: Instant,
        conversation_id: &impl std::fmt::Display,
        turn_id: &str,
        call: &ToolCall,
        source: &ToolCallSource,
    ) -> Option<Self> {
        // Code-mode calls are nested within a direct code-mode tool call whose
        // timing already includes them. Suppress nested guards so consumers do
        // not mistake overlapping events for independent tool-call latency.
        if !matches!(
            source,
            ToolCallSource::Direct | ToolCallSource::DirectPlaintextMessage
        ) || !tracing::enabled!(tracing::Level::INFO)
        {
            return None;
        }

        Some(Self {
            started_at,
            execution_started_at: Arc::new(OnceLock::new()),
            conversation_id: conversation_id.to_string(),
            turn_id: turn_id.to_string(),
            call_id: call.call_id.clone(),
            tool_name: call.tool_name.clone(),
        })
    }
}

impl Drop for ToolCallTimingGuard {
    fn drop(&mut self) {
        let completed_at = Instant::now();
        // Snapshot once so a concurrently-starting dispatch cannot make one
        // event internally inconsistent.
        let execution_started_at = self
            .execution_started_at
            .get()
            .copied()
            .filter(|execution_started_at| *execution_started_at <= completed_at);
        let duration_ms = |duration: std::time::Duration| u64::try_from(duration.as_millis()).ok();
        let total_duration_ms = duration_ms(completed_at.duration_since(self.started_at));
        let dispatch_duration_ms = execution_started_at.map_or_else(
            || total_duration_ms,
            |execution_started_at| {
                duration_ms(execution_started_at.duration_since(self.started_at))
            },
        );
        let handler_duration_ms = execution_started_at.map_or(Some(0), |execution_started_at| {
            duration_ms(completed_at.duration_since(execution_started_at))
        });

        macro_rules! log_tool_call {
            ($dispatch_duration_ms:expr, $handler_duration_ms:expr, $total_duration_ms:expr) => {
                info!(
                    event.name = "codex.tool_call",
                    trace_id = %codex_otel::current_span_trace_id().unwrap_or_default(),
                    conversation.id = %self.conversation_id,
                    turn_id = %self.turn_id,
                    tool_name = %self.tool_name,
                    call_id = %self.call_id,
                    tool_source = "direct",
                    execution_started = execution_started_at.is_some(),
                    dispatch_duration_ms = $dispatch_duration_ms,
                    handler_duration_ms = $handler_duration_ms,
                    total_duration_ms = $total_duration_ms,
                    "tool call completed"
                );
            };
        }

        match (dispatch_duration_ms, handler_duration_ms, total_duration_ms) {
            (Some(dispatch_duration_ms), Some(handler_duration_ms), Some(total_duration_ms)) => {
                log_tool_call!(dispatch_duration_ms, handler_duration_ms, total_duration_ms);
            }
            _ => {
                log_tool_call!(
                    tracing::field::Empty,
                    tracing::field::Empty,
                    tracing::field::Empty
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    use crate::session::step_context::StepContext;
    use crate::tools::context::FunctionToolOutput;
    use crate::tools::context::ToolInvocation;
    use crate::tools::registry::CoreToolRuntime;
    use crate::tools::registry::ToolExecutor;
    use crate::tools::registry::ToolRegistry;
    use crate::tools::router::ToolRouter;
    use crate::turn_diff_tracker::TurnDiffTracker;
    use codex_extension_api::ToolCallOutcome;
    use codex_protocol::models::FunctionCallOutputBody;
    use codex_protocol::models::FunctionCallOutputPayload;
    use pretty_assertions::assert_eq;
    use tokio::sync::Notify;
    use tokio::sync::oneshot;
    use tracing_test::internal::MockWriter;

    #[test]
    fn tool_call_timing_guard_ignores_code_mode_source() {
        let subscriber = tracing_subscriber::fmt()
            .with_max_level(tracing::Level::INFO)
            .finish();
        tracing::subscriber::with_default(subscriber, || {
            let call = ToolCall {
                tool_name: codex_tools::ToolName::plain("test_tool"),
                call_id: "call-1".to_string(),
                payload: ToolPayload::Function {
                    arguments: "{}".to_string(),
                },
                encrypted_function_args: None,
            };
            let direct_guard = ToolCallTimingGuard::capture(
                Instant::now(),
                &"conversation-id",
                "turn-id",
                &call,
                &ToolCallSource::Direct,
            );
            assert!(
                direct_guard.is_some(),
                "direct tool calls should create a timing guard"
            );
            drop(direct_guard);

            let code_mode_guard = ToolCallTimingGuard::capture(
                Instant::now(),
                &"conversation-id",
                "turn-id",
                &call,
                &ToolCallSource::CodeMode {
                    cell_id: "cell-1".to_string(),
                    runtime_tool_call_id: "runtime-call-1".to_string(),
                },
            );
            assert!(
                code_mode_guard.is_none(),
                "nested code-mode calls should not create overlapping timing events"
            );
        });
    }

    #[tokio::test]
    async fn cancellation_before_dispatch_admission_logs_dispatch_only_timing() -> anyhow::Result<()>
    {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_policy_contributor(Arc::new(PolicyAttemptRecorder {
            records: Arc::clone(&policy_records),
        }));
        session.services.extensions = Arc::new(builder.build());
        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("test_tool");
        let handler = Arc::new(ImmediateHandler {
            tool_name: tool_name.clone(),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let execution_gate = Arc::clone(&runtime.parallel_execution);
        let execution_gate_guard = execution_gate
            .try_write_owned()
            .expect("execution gate should be available before dispatch starts");
        let (release_execution_gate_tx, release_execution_gate_rx) = std::sync::mpsc::channel();
        let execution_gate_task = tokio::task::spawn_blocking(move || {
            let _execution_gate_guard = execution_gate_guard;
            release_execution_gate_rx
                .recv()
                .expect("test should release the execution gate");
        });

        let buffer: &'static std::sync::Mutex<Vec<u8>> =
            Box::leak(Box::new(std::sync::Mutex::new(Vec::new())));
        let subscriber = tracing_subscriber::fmt()
            .with_ansi(false)
            .with_max_level(tracing::Level::INFO)
            .with_writer(MockWriter::new(buffer))
            .finish();
        let _subscriber_guard = tracing::subscriber::set_default(subscriber);

        let cancellation_token = CancellationToken::new();
        let call = ToolCall {
            tool_name,
            call_id: "call-1".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };
        let response_task =
            tokio::spawn(runtime.handle_tool_call(call, cancellation_token.clone()));
        cancellation_token.cancel();
        tokio::time::timeout(Duration::from_secs(1), response_task)
            .await
            .expect("timed out waiting for cancelled tool response")
            .expect("cancelled tool response task should join")
            .expect("cancelled tool call should produce a response");

        let logs = String::from_utf8(
            buffer
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone(),
        )?;
        let timing_events = logs
            .lines()
            .filter(|line| line.contains("event.name=\"codex.tool_call\""))
            .collect::<Vec<_>>();
        assert_eq!(
            timing_events.len(),
            1,
            "cancelled tool call should emit exactly one timing event; logs:\n{logs}"
        );
        let timing_event = timing_events[0];
        assert!(
            timing_event.contains("execution_started=false"),
            "tool cancelled before admission should not report execution started: {timing_event}"
        );
        assert!(
            timing_event.contains("handler_duration_ms=0"),
            "tool cancelled before admission should report zero handler duration: {timing_event}"
        );
        let duration_field = |name: &str| {
            timing_event.split_whitespace().find_map(|field| {
                field
                    .strip_prefix(&format!("{name}="))
                    .and_then(|value| value.parse::<u64>().ok())
            })
        };
        let dispatch_duration_ms = duration_field("dispatch_duration_ms")
            .expect("timing event should include dispatch_duration_ms");
        let total_duration_ms = duration_field("total_duration_ms")
            .expect("timing event should include total_duration_ms");
        assert_eq!(
            dispatch_duration_ms, total_duration_ms,
            "tool cancelled before admission should attribute all elapsed time to dispatch: {timing_event}"
        );
        let policy_records = policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .drain(..)
            .collect::<Vec<_>>();
        assert_eq!(policy_records.len(), 1);
        assert_eq!(policy_records[0].call_id, "call-1");
        assert!(!policy_records[0].attempt_id.is_empty());
        assert_eq!(
            policy_records[0].phase,
            PolicyAttemptPhase::Terminal {
                outcome: ToolCallOutcome::Aborted,
                host_accepted: false,
            },
            "cancellation before admission must not claim host acceptance",
        );
        release_execution_gate_tx
            .send(())
            .expect("execution gate task should remain available");
        execution_gate_task
            .await
            .expect("execution gate task should join");

        Ok(())
    }

    struct ImmediateHandler {
        tool_name: codex_tools::ToolName,
    }

    impl ToolExecutor<ToolInvocation> for ImmediateHandler {
        fn tool_name(&self) -> codex_tools::ToolName {
            self.tool_name.clone()
        }

        fn spec(&self) -> codex_tools::ToolSpec {
            codex_tools::ToolSpec::Function(codex_tools::ResponsesApiTool {
                name: self.tool_name.name.clone(),
                description: "Immediate test tool.".to_string(),
                strict: false,
                defer_loading: None,
                parameters: codex_tools::JsonSchema::default(),
                output_schema: None,
            })
        }

        fn handle(&self, _invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
            Box::pin(async {
                Ok(
                    Box::new(FunctionToolOutput::from_text("ok".to_string(), Some(true)))
                        as Box<dyn crate::tools::context::ToolOutput>,
                )
            })
        }
    }

    impl CoreToolRuntime for ImmediateHandler {}

    struct PanickingHandler {
        tool_name: codex_tools::ToolName,
    }

    impl ToolExecutor<ToolInvocation> for PanickingHandler {
        fn tool_name(&self) -> codex_tools::ToolName {
            self.tool_name.clone()
        }

        fn spec(&self) -> codex_tools::ToolSpec {
            codex_tools::ToolSpec::Function(codex_tools::ResponsesApiTool {
                name: self.tool_name.name.clone(),
                description: "Panicking test tool.".to_string(),
                strict: false,
                defer_loading: None,
                parameters: codex_tools::JsonSchema::default(),
                output_schema: None,
            })
        }

        fn handle(&self, _invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
            Box::pin(async { panic!("intentional handler panic") })
        }
    }

    impl CoreToolRuntime for PanickingHandler {}

    struct CancellationPanicHandler {
        tool_name: codex_tools::ToolName,
        started: std::sync::Mutex<Option<oneshot::Sender<()>>>,
    }

    impl ToolExecutor<ToolInvocation> for CancellationPanicHandler {
        fn tool_name(&self) -> codex_tools::ToolName {
            self.tool_name.clone()
        }

        fn spec(&self) -> codex_tools::ToolSpec {
            codex_tools::ToolSpec::Function(codex_tools::ResponsesApiTool {
                name: self.tool_name.name.clone(),
                description: "Cancellation panic test tool.".to_string(),
                strict: false,
                defer_loading: None,
                parameters: codex_tools::JsonSchema::default(),
                output_schema: None,
            })
        }

        fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
            Box::pin(async move {
                let started = self
                    .started
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .take();
                if let Some(started) = started {
                    let _ = started.send(());
                }
                invocation.cancellation_token.cancelled().await;
                panic!("intentional cancellation cleanup panic")
            })
        }
    }

    impl CoreToolRuntime for CancellationPanicHandler {
        fn waits_for_runtime_cancellation(&self) -> bool {
            true
        }
    }

    struct CancellationCleanupHandler {
        tool_name: codex_tools::ToolName,
        started: std::sync::Mutex<Option<oneshot::Sender<()>>>,
        cleanup_started: std::sync::Mutex<Option<oneshot::Sender<()>>>,
        allow_cleanup: Arc<Notify>,
    }

    impl ToolExecutor<ToolInvocation> for CancellationCleanupHandler {
        fn tool_name(&self) -> codex_tools::ToolName {
            self.tool_name.clone()
        }

        fn spec(&self) -> codex_tools::ToolSpec {
            codex_tools::ToolSpec::Function(codex_tools::ResponsesApiTool {
                name: self.tool_name.name.clone(),
                description: "Cancellation cleanup test tool.".to_string(),
                strict: false,
                defer_loading: None,
                parameters: codex_tools::JsonSchema::default(),
                output_schema: None,
            })
        }

        fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
            Box::pin(self.handle_call(invocation))
        }
    }

    impl CancellationCleanupHandler {
        async fn handle_call(
            &self,
            invocation: ToolInvocation,
        ) -> Result<Box<dyn crate::tools::context::ToolOutput>, FunctionCallError> {
            let started = self
                .started
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take();
            if let Some(started) = started {
                let _ = started.send(());
            }
            invocation.cancellation_token.cancelled().await;
            let cleanup_started = self
                .cleanup_started
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take();
            if let Some(cleanup_started) = cleanup_started {
                let _ = cleanup_started.send(());
            }
            self.allow_cleanup.notified().await;
            Ok(Box::new(FunctionToolOutput::from_text(
                "cleanup complete".to_string(),
                Some(false),
            )) as Box<dyn crate::tools::context::ToolOutput>)
        }
    }

    impl CoreToolRuntime for CancellationCleanupHandler {
        fn waits_for_runtime_cancellation(&self) -> bool {
            true
        }
    }

    struct FinishRecorder {
        records: Arc<std::sync::Mutex<Vec<ToolCallOutcome>>>,
    }

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    enum PolicyAttemptPhase {
        Admission,
        Authorization,
        Terminal {
            outcome: ToolCallOutcome,
            host_accepted: bool,
        },
    }

    #[derive(Debug, Eq, PartialEq)]
    struct PolicyAttemptRecord {
        attempt_id: String,
        call_id: String,
        phase: PolicyAttemptPhase,
    }

    struct PolicyAttemptRecorder {
        records: Arc<std::sync::Mutex<Vec<PolicyAttemptRecord>>>,
    }

    impl codex_extension_api::ToolPolicyContributor for PolicyAttemptRecorder {
        fn admit<'a>(
            &'a self,
            input: codex_extension_api::ToolPolicyInput<'a>,
        ) -> codex_extension_api::ToolPolicyFuture<'a, codex_extension_api::ToolPolicyDecision>
        {
            let records = Arc::clone(&self.records);
            let record = PolicyAttemptRecord {
                attempt_id: input.attempt_id.to_string(),
                call_id: input.call_id.to_string(),
                phase: PolicyAttemptPhase::Admission,
            };
            Box::pin(async move {
                records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(record);
                Ok(codex_extension_api::ToolPolicyDecision::Allow)
            })
        }

        fn authorize<'a>(
            &'a self,
            input: codex_extension_api::ToolPolicyInput<'a>,
        ) -> codex_extension_api::ToolPolicyFuture<'a, codex_extension_api::ToolPolicyDecision>
        {
            let records = Arc::clone(&self.records);
            let record = PolicyAttemptRecord {
                attempt_id: input.attempt_id.to_string(),
                call_id: input.call_id.to_string(),
                phase: PolicyAttemptPhase::Authorization,
            };
            Box::pin(async move {
                records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(record);
                Ok(codex_extension_api::ToolPolicyDecision::Allow)
            })
        }

        fn on_terminal<'a>(
            &'a self,
            input: codex_extension_api::ToolPolicyTerminalInput<'a>,
        ) -> codex_extension_api::ToolPolicyFuture<'a, ()> {
            let records = Arc::clone(&self.records);
            let record = PolicyAttemptRecord {
                attempt_id: input.attempt_id.to_string(),
                call_id: input.call_id.to_string(),
                phase: PolicyAttemptPhase::Terminal {
                    outcome: input.outcome,
                    host_accepted: input.host_accepted,
                },
            };
            Box::pin(async move {
                records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(record);
                Ok(())
            })
        }
    }

    struct BlockingTerminalPolicy {
        terminal_started: std::sync::Mutex<Option<oneshot::Sender<()>>>,
        allow_terminal: Arc<Notify>,
        terminal_calls: Arc<std::sync::atomic::AtomicUsize>,
    }

    impl codex_extension_api::ToolPolicyContributor for BlockingTerminalPolicy {
        fn on_terminal<'a>(
            &'a self,
            _input: codex_extension_api::ToolPolicyTerminalInput<'a>,
        ) -> codex_extension_api::ToolPolicyFuture<'a, ()> {
            let terminal_started = self
                .terminal_started
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take();
            let allow_terminal = Arc::clone(&self.allow_terminal);
            let terminal_calls = Arc::clone(&self.terminal_calls);
            Box::pin(async move {
                terminal_calls.fetch_add(1, Ordering::AcqRel);
                if let Some(terminal_started) = terminal_started {
                    let _ = terminal_started.send(());
                }
                allow_terminal.notified().await;
                Ok(())
            })
        }
    }

    impl codex_extension_api::ToolLifecycleContributor for FinishRecorder {
        fn on_tool_finish<'a>(
            &'a self,
            input: codex_extension_api::ToolFinishInput<'a>,
        ) -> codex_extension_api::ToolLifecycleFuture<'a> {
            let records = Arc::clone(&self.records);
            let outcome = input.outcome;
            Box::pin(async move {
                records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(outcome);
            })
        }
    }

    struct BlockingFinishContributor {
        records: Arc<std::sync::Mutex<Vec<ToolCallOutcome>>>,
        finish_started: std::sync::Mutex<Option<oneshot::Sender<()>>>,
        allow_finish: Arc<Notify>,
    }

    impl codex_extension_api::ToolLifecycleContributor for BlockingFinishContributor {
        fn on_tool_finish<'a>(
            &'a self,
            input: codex_extension_api::ToolFinishInput<'a>,
        ) -> codex_extension_api::ToolLifecycleFuture<'a> {
            let records = Arc::clone(&self.records);
            let allow_finish = Arc::clone(&self.allow_finish);
            let finish_started = self
                .finish_started
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take();
            let outcome = input.outcome;
            Box::pin(async move {
                if let Some(finish_started) = finish_started {
                    let _ = finish_started.send(());
                }
                allow_finish.notified().await;
                records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(outcome);
            })
        }
    }

    struct PanickingFinishContributor;

    impl codex_extension_api::ToolLifecycleContributor for PanickingFinishContributor {
        fn on_tool_finish<'a>(
            &'a self,
            _input: codex_extension_api::ToolFinishInput<'a>,
        ) -> codex_extension_api::ToolLifecycleFuture<'a> {
            Box::pin(async { panic!("intentional lifecycle finish panic") })
        }
    }

    #[tokio::test]
    async fn handler_task_panic_emits_one_indeterminate_terminal() -> anyhow::Result<()> {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let lifecycle_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_policy_contributor(Arc::new(PolicyAttemptRecorder {
            records: Arc::clone(&policy_records),
        }));
        builder.tool_lifecycle_contributor(Arc::new(FinishRecorder {
            records: Arc::clone(&lifecycle_records),
        }));
        session.services.extensions = Arc::new(builder.build());

        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("panic_tool");
        let handler = Arc::new(PanickingHandler {
            tool_name: tool_name.clone(),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let call = ToolCall {
            tool_name,
            call_id: "call-panic".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };

        let result = runtime
            .handle_tool_call(call, CancellationToken::new())
            .await;
        assert!(
            result.is_err(),
            "panicked handler should return a fatal error"
        );

        let policy_records = policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(policy_records.len(), 3);
        let attempt_id = policy_records[0].attempt_id.as_str();
        assert!(
            policy_records
                .iter()
                .all(|record| record.attempt_id == attempt_id)
        );
        assert_eq!(
            policy_records
                .iter()
                .map(|record| record.phase)
                .collect::<Vec<_>>(),
            [
                PolicyAttemptPhase::Admission,
                PolicyAttemptPhase::Authorization,
                PolicyAttemptPhase::Terminal {
                    outcome: ToolCallOutcome::Indeterminate {
                        reason_code: HANDLER_TASK_JOIN_ERROR_REASON_CODE,
                    },
                    host_accepted: true,
                },
            ],
        );
        assert_eq!(
            *lifecycle_records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner),
            [ToolCallOutcome::Indeterminate {
                reason_code: HANDLER_TASK_JOIN_ERROR_REASON_CODE,
            }],
        );

        Ok(())
    }

    #[tokio::test]
    async fn cancellation_owner_records_indeterminate_when_handler_task_panics()
    -> anyhow::Result<()> {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let lifecycle_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_policy_contributor(Arc::new(PolicyAttemptRecorder {
            records: Arc::clone(&policy_records),
        }));
        builder.tool_lifecycle_contributor(Arc::new(FinishRecorder {
            records: Arc::clone(&lifecycle_records),
        }));
        session.services.extensions = Arc::new(builder.build());

        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("cancellation_panic_tool");
        let (started_tx, started_rx) = oneshot::channel();
        let handler = Arc::new(CancellationPanicHandler {
            tool_name: tool_name.clone(),
            started: std::sync::Mutex::new(Some(started_tx)),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let cancellation_token = CancellationToken::new();
        let call = ToolCall {
            tool_name,
            call_id: "call-cancellation-panic".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };
        let response_task =
            tokio::spawn(runtime.handle_tool_call(call, cancellation_token.clone()));
        started_rx.await.expect("handler should start");
        cancellation_token.cancel();
        let result = tokio::time::timeout(Duration::from_secs(1), response_task)
            .await
            .expect("timed out waiting for panicked handler response")
            .expect("outer tool call task should join");
        assert!(
            result.is_err(),
            "panicked cancellation cleanup should return a fatal error"
        );

        let policy_records = policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(policy_records.len(), 3);
        let attempt_id = policy_records[0].attempt_id.as_str();
        assert!(
            policy_records
                .iter()
                .all(|record| record.attempt_id == attempt_id)
        );
        assert_eq!(
            policy_records
                .iter()
                .map(|record| record.phase)
                .collect::<Vec<_>>(),
            [
                PolicyAttemptPhase::Admission,
                PolicyAttemptPhase::Authorization,
                PolicyAttemptPhase::Terminal {
                    outcome: ToolCallOutcome::Indeterminate {
                        reason_code: HANDLER_TASK_JOIN_ERROR_REASON_CODE,
                    },
                    host_accepted: true,
                },
            ],
        );
        assert_eq!(
            *lifecycle_records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner),
            [ToolCallOutcome::Indeterminate {
                reason_code: HANDLER_TASK_JOIN_ERROR_REASON_CODE,
            }],
        );

        Ok(())
    }

    #[tokio::test]
    async fn panic_after_handler_terminal_does_not_emit_a_second_terminal() -> anyhow::Result<()> {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_policy_contributor(Arc::new(PolicyAttemptRecorder {
            records: Arc::clone(&policy_records),
        }));
        builder.tool_lifecycle_contributor(Arc::new(PanickingFinishContributor));
        session.services.extensions = Arc::new(builder.build());

        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("test_tool");
        let handler = Arc::new(ImmediateHandler {
            tool_name: tool_name.clone(),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let call = ToolCall {
            tool_name,
            call_id: "call-finish-panic".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };

        let result = runtime
            .handle_tool_call(call, CancellationToken::new())
            .await;
        assert!(
            result.is_err(),
            "panicked lifecycle finish should return a fatal error"
        );

        let policy_records = policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert_eq!(policy_records.len(), 3);
        assert_eq!(
            policy_records
                .iter()
                .map(|record| record.phase)
                .collect::<Vec<_>>(),
            [
                PolicyAttemptPhase::Admission,
                PolicyAttemptPhase::Authorization,
                PolicyAttemptPhase::Terminal {
                    outcome: ToolCallOutcome::Completed { success: true },
                    host_accepted: true,
                },
            ],
        );

        Ok(())
    }

    #[tokio::test]
    async fn cancellation_after_handler_finishes_preserves_completed_lifecycle()
    -> anyhow::Result<()> {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let (finish_started_tx, finish_started_rx) = oneshot::channel();
        let allow_finish = Arc::new(Notify::new());
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_lifecycle_contributor(Arc::new(BlockingFinishContributor {
            records: Arc::clone(&records),
            finish_started: std::sync::Mutex::new(Some(finish_started_tx)),
            allow_finish: Arc::clone(&allow_finish),
        }));
        session.services.extensions = Arc::new(builder.build());

        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("test_tool");
        let handler = Arc::new(ImmediateHandler {
            tool_name: tool_name.clone(),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let cancellation_token = CancellationToken::new();
        let call = ToolCall {
            tool_name,
            call_id: "call-1".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };

        let response_task =
            tokio::spawn(runtime.handle_tool_call(call, cancellation_token.clone()));
        tokio::time::timeout(Duration::from_secs(1), finish_started_rx)
            .await
            .expect("timed out waiting for lifecycle notification to start")
            .expect("lifecycle notification should start");
        cancellation_token.cancel();
        tokio::time::sleep(Duration::from_millis(10)).await;
        allow_finish.notify_waiters();

        let response = tokio::time::timeout(Duration::from_secs(1), response_task)
            .await
            .expect("timed out waiting for tool response")
            .expect("tool response task should join")?;
        let expected_response = ResponseInputItem::FunctionCallOutput {
            call_id: "call-1".to_string(),
            output: FunctionCallOutputPayload {
                body: FunctionCallOutputBody::Text("ok".to_string()),
                success: Some(true),
            },
        };
        assert_eq!(expected_response, response);

        let actual = records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .drain(..)
            .collect::<Vec<_>>();
        assert_eq!(vec![ToolCallOutcome::Completed { success: true }], actual);

        Ok(())
    }

    #[tokio::test]
    async fn active_policy_committed_terminal_does_not_wait_for_lifecycle_tail()
    -> anyhow::Result<()> {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let lifecycle_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let (finish_started_tx, finish_started_rx) = oneshot::channel();
        let allow_finish = Arc::new(Notify::new());
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_policy_contributor(Arc::new(PolicyAttemptRecorder {
            records: Arc::clone(&policy_records),
        }));
        builder.tool_lifecycle_contributor(Arc::new(BlockingFinishContributor {
            records: Arc::clone(&lifecycle_records),
            finish_started: std::sync::Mutex::new(Some(finish_started_tx)),
            allow_finish: Arc::clone(&allow_finish),
        }));
        session.services.extensions = Arc::new(builder.build());

        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("test_tool");
        let handler = Arc::new(ImmediateHandler {
            tool_name: tool_name.clone(),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let cancellation_token = CancellationToken::new();
        let call = ToolCall {
            tool_name,
            call_id: "call-policy-tail".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };

        let response_task =
            tokio::spawn(runtime.handle_tool_call(call, cancellation_token.clone()));
        finish_started_rx
            .await
            .expect("lifecycle tail should start after policy terminal commit");
        cancellation_token.cancel();
        let response = tokio::time::timeout(Duration::from_millis(500), response_task)
            .await
            .expect("committed policy terminal must not wait for lifecycle tail")
            .expect("tool response task should join")?;
        let ResponseInputItem::FunctionCallOutput { output, .. } = response else {
            anyhow::bail!("cancelled tool should return function output");
        };
        let FunctionCallOutputBody::Text(text) = output.body else {
            anyhow::bail!("cancelled tool output should be text");
        };
        assert_eq!(text, POLICY_RESULT_WITHHELD_MESSAGE);
        assert!(
            lifecycle_records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .is_empty(),
            "aborted lifecycle tail must not fabricate an Aborted observation",
        );
        assert!(matches!(
            policy_records
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .as_slice(),
            [
                PolicyAttemptRecord {
                    phase: PolicyAttemptPhase::Admission,
                    ..
                },
                PolicyAttemptRecord {
                    phase: PolicyAttemptPhase::Authorization,
                    ..
                },
                PolicyAttemptRecord {
                    phase: PolicyAttemptPhase::Terminal {
                        outcome: ToolCallOutcome::Completed { success: true },
                        host_accepted: true,
                    },
                    ..
                },
            ]
        ));
        allow_finish.notify_waiters();
        Ok(())
    }

    #[tokio::test]
    async fn active_policy_terminal_write_timeout_is_fatal_and_not_aborted() -> anyhow::Result<()> {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let (terminal_started_tx, terminal_started_rx) = oneshot::channel();
        let allow_terminal = Arc::new(Notify::new());
        let terminal_calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_policy_contributor(Arc::new(BlockingTerminalPolicy {
            terminal_started: std::sync::Mutex::new(Some(terminal_started_tx)),
            allow_terminal: Arc::clone(&allow_terminal),
            terminal_calls: Arc::clone(&terminal_calls),
        }));
        session.services.extensions = Arc::new(builder.build());

        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("test_tool");
        let handler = Arc::new(ImmediateHandler {
            tool_name: tool_name.clone(),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let cancellation_token = CancellationToken::new();
        let call = ToolCall {
            tool_name,
            call_id: "call-policy-writing".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };

        let response_task =
            tokio::spawn(runtime.handle_tool_call(call, cancellation_token.clone()));
        terminal_started_rx
            .await
            .expect("policy terminal write should start");
        cancellation_token.cancel();
        let result = tokio::time::timeout(Duration::from_millis(500), response_task)
            .await
            .expect("terminal write cancellation grace must be bounded")
            .expect("tool response task should join");
        let error = result.expect_err("unconfirmed terminal must fail the turn");
        assert!(
            error
                .to_string()
                .contains(POLICY_TERMINAL_UNCONFIRMED_MESSAGE)
        );
        assert_eq!(terminal_calls.load(Ordering::Acquire), 1);
        allow_terminal.notify_waiters();
        Ok(())
    }

    #[tokio::test]
    async fn cancellation_after_runtime_cleanup_commits_completed_and_withholds_result()
    -> anyhow::Result<()> {
        let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
        let records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let policy_records = Arc::new(std::sync::Mutex::new(Vec::new()));
        let mut builder =
            codex_extension_api::ExtensionRegistryBuilder::<crate::config::Config>::new();
        builder.tool_policy_contributor(Arc::new(PolicyAttemptRecorder {
            records: Arc::clone(&policy_records),
        }));
        builder.tool_lifecycle_contributor(Arc::new(FinishRecorder {
            records: Arc::clone(&records),
        }));
        session.services.extensions = Arc::new(builder.build());

        let session = Arc::new(session);
        let turn_context = Arc::new(turn_context);
        let tool_name = codex_tools::ToolName::plain("cleanup_tool");
        let (started_tx, started_rx) = oneshot::channel();
        let (cleanup_started_tx, cleanup_started_rx) = oneshot::channel();
        let allow_cleanup = Arc::new(Notify::new());
        let handler = Arc::new(CancellationCleanupHandler {
            tool_name: tool_name.clone(),
            started: std::sync::Mutex::new(Some(started_tx)),
            cleanup_started: std::sync::Mutex::new(Some(cleanup_started_tx)),
            allow_cleanup: Arc::clone(&allow_cleanup),
        }) as Arc<dyn CoreToolRuntime>;
        let step_context = StepContext::for_test(Arc::clone(&turn_context));
        let router = Arc::new(ToolRouter::from_parts(
            ToolRegistry::from_tools([handler]),
            Vec::new(),
        ));
        let step_context = step_context.with_tool_router_for_test(router);
        let tracker = Arc::new(tokio::sync::Mutex::new(TurnDiffTracker::new()));
        let runtime = ToolCallRuntime::new(session, step_context, tracker);
        let cancellation_token = CancellationToken::new();
        let call = ToolCall {
            tool_name,
            call_id: "call-1".to_string(),
            payload: ToolPayload::Function {
                arguments: "{}".to_string(),
            },
            encrypted_function_args: None,
        };

        let response_task =
            tokio::spawn(runtime.handle_tool_call(call, cancellation_token.clone()));
        started_rx.await.expect("handler should start");
        cancellation_token.cancel();
        cleanup_started_rx
            .await
            .expect("handler should start cleanup");
        tokio::time::sleep(Duration::from_millis(10)).await;
        allow_cleanup.notify_one();

        let response = tokio::time::timeout(Duration::from_secs(1), response_task)
            .await
            .expect("timed out waiting for tool response")
            .expect("tool response task should join")?;
        let ResponseInputItem::FunctionCallOutput { output, .. } = response else {
            anyhow::bail!("cancelled tool should return function output");
        };
        let FunctionCallOutputBody::Text(text) = output.body else {
            anyhow::bail!("cancelled tool output should be text");
        };
        assert_eq!(text, POLICY_RESULT_WITHHELD_MESSAGE);

        let actual = records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .drain(..)
            .collect::<Vec<_>>();
        assert_eq!(vec![ToolCallOutcome::Completed { success: false }], actual);

        let policy_records = policy_records
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .drain(..)
            .collect::<Vec<_>>();
        assert_eq!(policy_records.len(), 3);
        assert!(
            policy_records
                .iter()
                .all(|record| record.call_id == "call-1")
        );
        let attempt_id = policy_records[0].attempt_id.as_str();
        assert!(
            !attempt_id.is_empty(),
            "attempt ID must be opaque and non-empty"
        );
        assert!(
            policy_records
                .iter()
                .all(|record| record.attempt_id == attempt_id),
            "cancellation terminal must retain the dispatch attempt ID",
        );
        assert_eq!(
            policy_records
                .iter()
                .map(|record| record.phase)
                .collect::<Vec<_>>(),
            [
                PolicyAttemptPhase::Admission,
                PolicyAttemptPhase::Authorization,
                PolicyAttemptPhase::Terminal {
                    outcome: ToolCallOutcome::Completed { success: false },
                    host_accepted: true,
                },
            ],
        );

        Ok(())
    }
}
