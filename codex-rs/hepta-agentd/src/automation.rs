use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::UserInput;
use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationBatchStopReason;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFailureDisposition;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationRuntimePolicyV1;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_automation::classify_automation_error;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::automation_recovery;

const AUTOMATION_TICK_INTERVAL: Duration = Duration::from_millis(250);
const APP_SERVER_COMMAND_CAPACITY: usize = 8;
const APP_SERVER_EVENT_CAPACITY: usize = 16;

pub(crate) struct AgentdAutomationQueue {
    state: Arc<AgentdState>,
    identity: AgentdIdentity,
}

#[derive(Debug)]
enum QueueFailure {
    /// The request has not crossed the App Server admission seam. These
    /// failures may be retried with the existing bounded dispatch budget.
    BeforeAdmission(AgentdError),
    /// The request may have crossed the seam, but no reliable identity-bound
    /// receipt was returned. Recovery must use the same stable client id.
    OutcomeUnknown,
}

impl AgentdAutomationQueue {
    pub(crate) fn new(state: Arc<AgentdState>, identity: AgentdIdentity) -> Self {
        Self { state, identity }
    }

    async fn enqueue_inner(
        &self,
        admission: AutomationAdmission,
    ) -> Result<AutomationQueueReceipt, QueueFailure> {
        if admission.agent_id != self.identity.agent_id {
            return Err(QueueFailure::BeforeAdmission(
                AgentdError::GenerationFenced(
                    "automation admission does not belong to the owning Agent".to_string(),
                ),
            ));
        }
        if !self
            .state
            .automation_is_available()
            .map_err(QueueFailure::BeforeAdmission)?
        {
            return Err(QueueFailure::BeforeAdmission(
                AutomationError::Unavailable.into(),
            ));
        }
        if !self
            .state
            .automation_admission_ready()
            .map_err(QueueFailure::BeforeAdmission)?
        {
            return Err(QueueFailure::BeforeAdmission(AgentdError::Protocol(
                "automation admission is unavailable until this Agent generation is ready"
                    .to_string(),
            )));
        }
        let socket_path = AbsolutePathBuf::from_absolute_path(&self.identity.app_server_socket)
            .map_err(|error| QueueFailure::BeforeAdmission(error.into()))?;
        let client = RemoteAppServerClient::connect_with_bounded_events(
            RemoteAppServerConnectArgs {
                endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                client_name: "hepta-agentd-automation".to_string(),
                client_version: env!("CARGO_PKG_VERSION").to_string(),
                experimental_api: true,
                mcp_server_openai_form_elicitation: false,
                opt_out_notification_methods: Vec::new(),
                channel_capacity: APP_SERVER_COMMAND_CAPACITY,
            },
            APP_SERVER_EVENT_CAPACITY,
        )
        .await
        .map_err(|error| QueueFailure::BeforeAdmission(error.into()))?;
        let expected_home = self.identity.home_root.to_string_lossy();
        if client.codex_home() != Some(expected_home.as_ref()) {
            let _ = client.shutdown().await;
            return Err(QueueFailure::BeforeAdmission(
                AgentdError::GenerationFenced(
                    "automation App Server home differs from the owning Agent home".to_string(),
                ),
            ));
        }
        let input = automation_input(&admission);
        let expected_payload_sha256 =
            automation_recovery::input_digest(&input).map_err(QueueFailure::BeforeAdmission)?;
        let response: ThreadQueueReconcileResponse = client
            .request_handle()
            .request_typed(ClientRequest::ThreadQueueReconcile {
                request_id: RequestId::Integer(1),
                params: ThreadQueueReconcileParams {
                    thread_id: admission.thread_id.clone(),
                    input,
                    client_user_message_id: admission.client_user_message_id.clone(),
                    expected_payload_sha256: expected_payload_sha256.clone(),
                    mode: ThreadQueueReconcileMode::AllowIfAbsent,
                },
            })
            .await
            .map_err(|_| QueueFailure::OutcomeUnknown)?;
        let _ = client.shutdown().await;

        // A transport-success response is still not enough by itself: retain
        // the exact owner generation and payload/client identity before the
        // durable occurrence is allowed to record Core admission.
        self.state
            .refresh_generation()
            .map_err(|_| QueueFailure::OutcomeUnknown)?;
        if !self
            .state
            .automation_is_available()
            .map_err(|_| QueueFailure::OutcomeUnknown)?
            || !self
                .state
                .automation_admission_ready()
                .map_err(|_| QueueFailure::OutcomeUnknown)?
        {
            return Err(QueueFailure::OutcomeUnknown);
        }
        automation_recovery::validate_reconcile_identity(
            &response,
            &admission.client_user_message_id,
            &expected_payload_sha256,
        )
        .map_err(|_| QueueFailure::OutcomeUnknown)?;
        let queued_submission_id = match response.outcome {
            ThreadQueueReconcileOutcome::Queued {
                queued_submission, ..
            } => {
                if queued_submission.client_user_message_id != admission.client_user_message_id
                    || queued_submission.id.is_empty()
                    || automation_recovery::input_digest(&queued_submission.input)
                        .map_err(|_| QueueFailure::OutcomeUnknown)?
                        != expected_payload_sha256
                {
                    return Err(QueueFailure::OutcomeUnknown);
                }
                queued_submission.id
            }
            ThreadQueueReconcileOutcome::Persisted { turn_id } if !turn_id.is_empty() => {
                format!("persisted:{turn_id}")
            }
            ThreadQueueReconcileOutcome::Cancelled => "cancelled-before-turn".to_string(),
            ThreadQueueReconcileOutcome::Missing
            | ThreadQueueReconcileOutcome::Persisted { .. } => {
                return Err(QueueFailure::OutcomeUnknown);
            }
        };
        Ok(AutomationQueueReceipt {
            queued_submission_id,
            client_user_message_id: admission.client_user_message_id,
        })
    }
}

fn queue_failure_to_automation_error(failure: QueueFailure) -> AutomationError {
    match failure {
        QueueFailure::BeforeAdmission(AgentdError::GenerationFenced(_)) => {
            AutomationError::AccessDenied
        }
        QueueFailure::BeforeAdmission(AgentdError::Automation(error)) => error,
        QueueFailure::BeforeAdmission(_) => AutomationError::Dispatch,
        QueueFailure::OutcomeUnknown => AutomationError::DispatchUnknown,
    }
}

impl AutomationTurnQueue for AgentdAutomationQueue {
    fn enqueue(
        &self,
        admission: AutomationAdmission,
    ) -> AutomationFuture<'_, AutomationQueueReceipt> {
        Box::pin(async move {
            match self.enqueue_inner(admission).await {
                Ok(receipt) => Ok(receipt),
                Err(error) => Err(queue_failure_to_automation_error(error)),
            }
        })
    }
}

pub(crate) async fn run_automation_scheduler(
    store: AutomationStore,
    state: Arc<AgentdState>,
    identity: AgentdIdentity,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    let policy = AutomationRuntimePolicyV1::default();
    if let Err(error) = policy.validate() {
        return stop_after_automation_error(error, &state, &cancellation).await;
    }
    let recovery_now_ms = match unix_time_ms() {
        Ok(now_ms) => now_ms,
        Err(error) => return stop_after_automation_error(error, &state, &cancellation).await,
    };
    if let Err(error) = store
        .recover_stale_generation(identity.spawn_generation, recovery_now_ms)
        .await
    {
        return stop_after_automation_error(error, &state, &cancellation).await;
    }
    let queue = Arc::new(AgentdAutomationQueue::new(
        Arc::clone(&state),
        identity.clone(),
    ));
    let scheduler = match AutomationScheduler::new(
        store,
        queue,
        identity.spawn_generation,
        Duration::from_millis(policy.slo.lease_expiry_ms),
        Duration::from_millis(policy.slo.dispatch_timeout_ms),
    ) {
        Ok(scheduler) => scheduler,
        Err(error) => return stop_after_automation_error(error, &state, &cancellation).await,
    };
    run_scheduler_loop(
        scheduler,
        state,
        cancellation,
        AUTOMATION_TICK_INTERVAL,
        policy,
    )
    .await
}

/// Cancellation stops new cycles, never an admitted tick's acknowledgement.
/// Recovery and admission use separate bounded budgets. Every admission still
/// commits its own stable intent before crossing the App Server seam.
async fn run_scheduler_loop<Q: AutomationTurnQueue>(
    scheduler: AutomationScheduler<Q>,
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
    tick_interval: Duration,
    policy: AutomationRuntimePolicyV1,
) -> Result<(), AgentdError> {
    let mut retry_budget = DispatchRetryBudget::default();
    let mut scheduler_transient_budget = TransientErrorBudget::default();
    let mut recovery_transient_budget = TransientErrorBudget::default();
    loop {
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(tick_interval) => {}
        }
        if !state.automation_is_available()? {
            return wait_for_cancellation(&cancellation).await;
        }
        let ready = match state.automation_admission_ready() {
            Ok(ready) => ready,
            Err(error @ AgentdError::GenerationFenced(_)) => {
                state.mark_fenced();
                return Err(error);
            }
            Err(error) => return Err(error),
        };
        if !ready {
            continue;
        }

        // Historical reconciliation snapshots a bounded set of distinct rows.
        // A failed batch never permits new admission in the same cycle, so
        // transport loss cannot grow an unresolved backlog. Identity, ledger
        // and fencing violations still fail closed.
        let recovery_now_ms = match unix_time_ms() {
            Ok(now_ms) => now_ms,
            Err(error) => {
                return stop_after_automation_error(error, &state, &cancellation).await;
            }
        };
        match automation_recovery::reconcile_batch(
            scheduler.store(),
            &state,
            state.identity(),
            recovery_now_ms,
            usize::from(policy.recovery_budget_per_cycle),
        )
        .await
        {
            Ok(_) => recovery_transient_budget.reset(),
            Err(error) => match classify_recovery_error(&error) {
                AutomationFailureDisposition::Fence | AutomationFailureDisposition::FailStop => {
                    return stop_after_recovery_error(error, &state, &cancellation).await;
                }
                AutomationFailureDisposition::Reconcile
                | AutomationFailureDisposition::Retry
                | AutomationFailureDisposition::Isolate => {
                    let consecutive = recovery_transient_budget.observe();
                    if consecutive >= policy.max_consecutive_pre_admission_failures {
                        return stop_after_recovery_error(error, &state, &cancellation).await;
                    }
                    let delay = Duration::from_millis(policy.retry_delay_ms(consecutive));
                    tokio::select! {
                        _ = cancellation.cancelled() => return Ok(()),
                        _ = tokio::time::sleep(delay) => {}
                    }
                    continue;
                }
            },
        }

        if cancellation.is_cancelled() {
            return Ok(());
        }
        // The batch is sequential and bounded. A fresh host clock is sampled
        // for each durable occurrence so a slow provider cannot reuse stale
        // lease timestamps across the entire cycle.
        match scheduler
            .tick_batch_cancellable(&policy, unix_time_ms, || cancellation.is_cancelled())
            .await
        {
            Ok(report) => {
                scheduler_transient_budget.reset();
                let retry_deferred = report.stop_reason == AutomationBatchStopReason::RetryDeferred;
                for tick in report.ticks {
                    if handle_automation_tick_with_limit(
                        tick,
                        &mut retry_budget,
                        policy.max_consecutive_pre_admission_failures,
                        &state,
                        &cancellation,
                    )
                    .await?
                    {
                        return Ok(());
                    }
                }
                if retry_deferred {
                    let delay = Duration::from_millis(
                        policy.retry_delay_ms(retry_budget.consecutive_retries),
                    );
                    tokio::select! {
                        _ = cancellation.cancelled() => return Ok(()),
                        _ = tokio::time::sleep(delay) => {}
                    }
                }
            }
            Err(error) => match classify_automation_error(&error) {
                AutomationFailureDisposition::Fence | AutomationFailureDisposition::FailStop => {
                    return stop_after_automation_error(error, &state, &cancellation).await;
                }
                AutomationFailureDisposition::Reconcile => {
                    scheduler_transient_budget.reset();
                }
                AutomationFailureDisposition::Retry | AutomationFailureDisposition::Isolate => {
                    let consecutive = scheduler_transient_budget.observe();
                    if consecutive >= policy.max_consecutive_pre_admission_failures {
                        return stop_after_automation_error(error, &state, &cancellation).await;
                    }
                    let delay = Duration::from_millis(policy.retry_delay_ms(consecutive));
                    tokio::select! {
                        _ = cancellation.cancelled() => return Ok(()),
                        _ = tokio::time::sleep(delay) => {}
                    }
                }
            },
        }
    }
}

pub(crate) fn classify_recovery_error(error: &AgentdError) -> AutomationFailureDisposition {
    match error {
        AgentdError::GenerationFenced(_) => AutomationFailureDisposition::Fence,
        AgentdError::Automation(error) => classify_automation_error(error),
        AgentdError::Io(_) | AgentdError::Overloaded { .. } => AutomationFailureDisposition::Retry,
        AgentdError::Protocol(message) if transient_recovery_protocol_error(message) => {
            AutomationFailureDisposition::Retry
        }
        _ => AutomationFailureDisposition::FailStop,
    }
}

fn transient_recovery_protocol_error(message: &str) -> bool {
    [
        "automation recovery requires a ready owning Agent generation",
        "automation recovery connect failed:",
        "automation queue reconcile failed:",
        "automation turn observation failed:",
    ]
    .iter()
    .any(|prefix| message.starts_with(*prefix))
}

/// Applies the scheduler's fail-stop policy to one tick. A durable unknown
/// dispatch no longer kills the scheduler: the next cycle first enters the
/// exact-client-id reconciliation path above. Only repeated proven
/// pre-admission failures exhaust the bounded retry budget.
pub(crate) async fn handle_automation_tick(
    tick: codex_hepta_automation::AutomationTick,
    retry_budget: &mut DispatchRetryBudget,
    state: &AgentdState,
    cancellation: &CancellationToken,
) -> Result<bool, AgentdError> {
    handle_automation_tick_with_limit(
        tick,
        retry_budget,
        AutomationRuntimePolicyV1::default().max_consecutive_pre_admission_failures,
        state,
        cancellation,
    )
    .await
}

async fn handle_automation_tick_with_limit(
    tick: codex_hepta_automation::AutomationTick,
    retry_budget: &mut DispatchRetryBudget,
    max_consecutive_retries: u8,
    state: &AgentdState,
    cancellation: &CancellationToken,
) -> Result<bool, AgentdError> {
    let stop_error = if retry_budget.observe(&tick, max_consecutive_retries) {
        Some(AutomationError::Dispatch)
    } else {
        None
    };
    let Some(error) = stop_error else {
        return Ok(false);
    };
    stop_after_automation_error(error, state, cancellation).await?;
    Ok(true)
}

#[derive(Default)]
pub(crate) struct DispatchRetryBudget {
    consecutive_retries: u8,
}

impl DispatchRetryBudget {
    fn observe(
        &mut self,
        tick: &codex_hepta_automation::AutomationTick,
        max_consecutive_retries: u8,
    ) -> bool {
        match tick {
            codex_hepta_automation::AutomationTick::RetryScheduled { .. } => {
                self.consecutive_retries = self.consecutive_retries.saturating_add(1);
            }
            codex_hepta_automation::AutomationTick::Idle
            | codex_hepta_automation::AutomationTick::Submitted { .. }
            | codex_hepta_automation::AutomationTick::DispatchUncertain { .. } => {
                self.consecutive_retries = 0;
            }
        }
        self.consecutive_retries >= max_consecutive_retries
    }
}

#[derive(Default)]
struct TransientErrorBudget {
    consecutive_failures: u8,
}

impl TransientErrorBudget {
    fn observe(&mut self) -> u8 {
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
        self.consecutive_failures
    }

    fn reset(&mut self) {
        self.consecutive_failures = 0;
    }
}

async fn stop_after_automation_error(
    error: AutomationError,
    state: &AgentdState,
    cancellation: &CancellationToken,
) -> Result<(), AgentdError> {
    if matches!(
        error,
        AutomationError::AccessDenied | AutomationError::TimerFenced
    ) {
        state.mark_fenced();
        return Err(AgentdError::GenerationFenced(
            "automation owner, timer epoch or generation boundary was violated".to_string(),
        ));
    }
    state.mark_automation_unavailable()?;
    wait_for_cancellation(cancellation).await
}

async fn stop_after_recovery_error(
    error: AgentdError,
    state: &AgentdState,
    cancellation: &CancellationToken,
) -> Result<(), AgentdError> {
    if classify_recovery_error(&error) == AutomationFailureDisposition::Fence {
        state.mark_fenced();
        if matches!(&error, AgentdError::GenerationFenced(_)) {
            return Err(error);
        }
        return Err(AgentdError::GenerationFenced(
            "automation recovery owner, timer epoch or generation boundary was violated"
                .to_string(),
        ));
    }
    state.mark_automation_unavailable()?;
    wait_for_cancellation(cancellation).await
}

async fn wait_for_cancellation(cancellation: &CancellationToken) -> Result<(), AgentdError> {
    cancellation.cancelled().await;
    Ok(())
}

fn automation_input(admission: &AutomationAdmission) -> Vec<UserInput> {
    vec![UserInput::Text {
        text: admission.prompt.clone(),
        text_elements: Vec::new(),
    }]
}

fn unix_time_ms() -> Result<u64, AutomationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AutomationError::Unavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| AutomationError::Unavailable)
}

#[cfg(test)]
mod tests {
    use codex_hepta_automation::AutomationTaskId;
    use codex_hepta_automation::AutomationTick;
    use codex_hepta_contracts::AgentId;

    use super::*;

    #[test]
    fn automation_reconcile_payload_uses_stable_client_identity() {
        let admission = AutomationAdmission {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id"),
            task_id: AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75007")
                .expect("task id"),
            occurrence: 3,
            scheduled_for_ms: 44,
            thread_id: "019153a4-3088-7e03-a56a-9b1964f75ddd".to_string(),
            prompt: "run through governance".to_string(),
            client_user_message_id: "hepta.automation.test".to_string(),
        };
        let input = automation_input(&admission);
        let digest = automation_recovery::input_digest(&input).expect("input digest");
        assert!(!digest.is_empty());
        assert_eq!(
            input,
            vec![UserInput::Text {
                text: admission.prompt,
                text_elements: Vec::new(),
            }]
        );
    }

    #[test]
    fn dispatch_retry_budget_is_bounded_and_progress_resets_it() {
        let task_id =
            AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75008").expect("agent id");
        let retry = AutomationTick::RetryScheduled {
            task_id,
            occurrence: 1,
        };
        let admitted = AutomationTick::Submitted {
            task_id,
            occurrence: 1,
            queued_submission_id: "queue-1".to_string(),
        };
        let mut budget = DispatchRetryBudget::default();

        assert!(!budget.observe(&retry, 3));
        assert!(!budget.observe(&retry, 3));
        assert!(budget.observe(&retry, 3));

        assert!(!budget.observe(&admitted, 3));
        assert!(!budget.observe(&retry, 3));
        assert!(!budget.observe(&AutomationTick::Idle, 3));
        assert!(!budget.observe(&retry, 3));
    }

    #[test]
    fn transient_error_budget_resets_after_progress() {
        let mut budget = TransientErrorBudget::default();
        assert_eq!(budget.observe(), 1);
        assert_eq!(budget.observe(), 2);
        budget.reset();
        assert_eq!(budget.observe(), 1);
    }

    #[test]
    fn recovery_error_classification_retries_transport_but_fails_closed_on_drift() {
        for message in [
            "automation recovery requires a ready owning Agent generation",
            "automation recovery connect failed: unavailable",
            "automation queue reconcile failed: closed",
            "automation turn observation failed: timeout",
        ] {
            assert_eq!(
                classify_recovery_error(&AgentdError::Protocol(message.to_string())),
                AutomationFailureDisposition::Retry
            );
        }
        assert_eq!(
            classify_recovery_error(&AgentdError::Automation(AutomationError::DispatchUnknown)),
            AutomationFailureDisposition::Reconcile
        );
        assert_eq!(
            classify_recovery_error(&AgentdError::GenerationFenced(
                "stale generation".to_string()
            )),
            AutomationFailureDisposition::Fence
        );
        assert_eq!(
            classify_recovery_error(&AgentdError::Automation(AutomationError::AccessDenied)),
            AutomationFailureDisposition::Fence
        );
        assert_eq!(
            classify_recovery_error(&AgentdError::Automation(AutomationError::TimerFenced)),
            AutomationFailureDisposition::Fence
        );
        assert_eq!(
            classify_recovery_error(&AgentdError::Protocol(
                "automation reconciliation identity or payload mismatch".to_string()
            )),
            AutomationFailureDisposition::FailStop
        );
    }

    #[test]
    fn queue_failures_after_admission_seam_are_never_dispatch_retries() {
        assert_eq!(
            queue_failure_to_automation_error(QueueFailure::BeforeAdmission(
                AgentdError::Protocol("socket unavailable".to_string()),
            )),
            AutomationError::Dispatch
        );
        assert_eq!(
            queue_failure_to_automation_error(QueueFailure::OutcomeUnknown),
            AutomationError::DispatchUnknown
        );
        assert_eq!(
            queue_failure_to_automation_error(QueueFailure::BeforeAdmission(
                AgentdError::GenerationFenced("stale generation".to_string()),
            )),
            AutomationError::AccessDenied
        );
    }
}

#[path = "automation_service.rs"]
mod service;
pub(crate) use service::spawn_automation_service;

#[cfg(test)]
#[path = "automation_service_tests.rs"]
mod service_tests;
