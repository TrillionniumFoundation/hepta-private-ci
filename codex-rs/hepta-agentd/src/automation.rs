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
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTurnQueue;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::automation_recovery;

const AUTOMATION_TICK_INTERVAL: Duration = Duration::from_millis(250);
const AUTOMATION_LEASE_DURATION: Duration = Duration::from_secs(30);
const AUTOMATION_DISPATCH_TIMEOUT: Duration = Duration::from_secs(5);
const AUTOMATION_MAX_CONSECUTIVE_DISPATCH_RETRIES: u8 = 3;
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
        let expected_payload_sha256 = automation_recovery::input_digest(&input)
            .map_err(QueueFailure::BeforeAdmission)?;
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
                queued_submission,
                ..
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
        QueueFailure::BeforeAdmission(AgentdError::Automation(
            error @ (AutomationError::Unavailable | AutomationError::Corrupt),
        )) => error,
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
    if let Err(error) = store
        .recover_stale_generation(identity.spawn_generation)
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
        AUTOMATION_LEASE_DURATION,
        AUTOMATION_DISPATCH_TIMEOUT,
    ) {
        Ok(scheduler) => scheduler,
        Err(error) => return stop_after_automation_error(error, &state, &cancellation).await,
    };
    let mut retry_budget = DispatchRetryBudget::default();
    loop {
        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(AUTOMATION_TICK_INTERVAL) => {}
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
        let now_ms = match unix_time_ms() {
            Ok(now_ms) => now_ms,
            Err(error) => return stop_after_automation_error(error, &state, &cancellation).await,
        };

        // Reconcile one durable historical occurrence before admitting new
        // work. This is bounded to one item/turn-page chain per tick and does
        // not prevent an overlap-allowed scheduler from also making progress.
        if let Err(error) = automation_recovery::reconcile_one(
            scheduler.store(),
            &state,
            &identity,
            now_ms,
        )
        .await
        {
            return stop_after_recovery_error(error, &state);
        }

        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            result = scheduler.tick(now_ms) => {
                match result {
                    Ok(tick) => {
                        if handle_automation_tick(
                            tick,
                            &mut retry_budget,
                            &state,
                            &cancellation,
                        )
                        .await?
                        {
                            return Ok(());
                        }
                    }
                    Err(error) => {
                        return stop_after_automation_error(error, &state, &cancellation).await;
                    }
                }
            }
        }
    }
}

/// Applies the scheduler's fail-stop policy to one tick. A durable unknown
/// dispatch no longer kills the scheduler: the next tick first enters the
/// exact-client-id reconciliation path above. Only repeated proven
/// pre-admission failures exhaust the bounded retry budget.
pub(crate) async fn handle_automation_tick(
    tick: codex_hepta_automation::AutomationTick,
    retry_budget: &mut DispatchRetryBudget,
    state: &AgentdState,
    cancellation: &CancellationToken,
) -> Result<bool, AgentdError> {
    let stop_error = if retry_budget.observe(&tick) {
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
    fn observe(&mut self, tick: &codex_hepta_automation::AutomationTick) -> bool {
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
        self.consecutive_retries >= AUTOMATION_MAX_CONSECUTIVE_DISPATCH_RETRIES
    }
}

async fn stop_after_automation_error(
    error: AutomationError,
    state: &AgentdState,
    cancellation: &CancellationToken,
) -> Result<(), AgentdError> {
    if error == AutomationError::AccessDenied {
        state.mark_fenced();
        return Err(AgentdError::GenerationFenced(
            "automation owner or generation boundary was violated".to_string(),
        ));
    }
    state.mark_automation_unavailable()?;
    wait_for_cancellation(cancellation).await
}

fn stop_after_recovery_error(error: AgentdError, state: &AgentdState) -> Result<(), AgentdError> {
    if matches!(error, AgentdError::GenerationFenced(_)) {
        state.mark_fenced();
    } else {
        state.mark_automation_unavailable()?;
    }
    Err(error)
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
            AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75008").expect("task id");
        let retry = AutomationTick::RetryScheduled {
            task_id,
            occurrence: 1,
        };
        let admitted = AutomationTick::Admitted {
            task_id,
            occurrence: 1,
            queued_submission_id: "queue-1".to_string(),
        };
        let mut budget = DispatchRetryBudget::default();

        assert!(!budget.observe(&retry));
        assert!(!budget.observe(&retry));
        assert!(budget.observe(&retry));

        assert!(!budget.observe(&admitted));
        assert!(!budget.observe(&retry));
        assert!(!budget.observe(&AutomationTick::Idle));
        assert!(!budget.observe(&retry));
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
