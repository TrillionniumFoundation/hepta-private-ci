use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SortDirection;
use codex_app_server_protocol::ThreadQueueAddParams;
use codex_app_server_protocol::ThreadQueueAddResponse;
use codex_app_server_protocol::ThreadQueueReconcileMode;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::ThreadQueueReconcileParams;
use codex_app_server_protocol::ThreadQueueReconcileResponse;
use codex_app_server_protocol::ThreadTurnsListParams;
use codex_app_server_protocol::ThreadTurnsListResponse;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_automation::AutomationAdmission;
use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationFuture;
use codex_hepta_automation::AutomationOccurrenceTerminal;
use codex_hepta_automation::AutomationProviderObservationKind;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationScheduler;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationSubmittedOccurrence;
use codex_hepta_automation::AutomationTurnQueue;
use codex_hepta_contracts::Sha256Digest;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;

const AUTOMATION_TICK_INTERVAL: Duration = Duration::from_millis(250);
const AUTOMATION_LEASE_DURATION: Duration = Duration::from_secs(30);
const AUTOMATION_DISPATCH_TIMEOUT: Duration = Duration::from_secs(5);
const AUTOMATION_MAX_CONSECUTIVE_DISPATCH_RETRIES: u8 = 3;
const APP_SERVER_COMMAND_CAPACITY: usize = 8;
const APP_SERVER_EVENT_CAPACITY: usize = 16;
const AUTOMATION_OBSERVER_TURN_PAGE: u32 = 128;
const AUTOMATION_OBSERVER_MAX_TURN_PAGES: usize = 8;

pub(crate) struct AgentdAutomationQueue {
    state: Arc<AgentdState>,
    identity: AgentdIdentity,
}

#[derive(Debug)]
enum QueueFailure {
    /// The request has not crossed the App Server admission seam.  These
    /// failures may be retried with the existing bounded dispatch budget.
    BeforeAdmission(AgentdError),
    /// The request may have crossed the seam, but no reliable terminal receipt
    /// was returned.  Retrying would be a blind duplicate, so the occurrence
    /// must be durably quarantined instead.
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
        let request = automation_queue_request(&admission);
        let response: ThreadQueueAddResponse = client
            .request_handle()
            .request_typed(request)
            .await
            .map_err(|_| QueueFailure::OutcomeUnknown)?;
        let _ = client.shutdown().await;
        // The response proves only what the App Server returned.  Any state
        // transition observed after the request is still an uncertain local
        // outcome: preserve the occurrence for explicit reconciliation rather
        // than handing it to a retry path.
        self.state
            .refresh_generation()
            .map_err(|_| QueueFailure::OutcomeUnknown)?;
        if !self
            .state
            .automation_is_available()
            .map_err(|_| QueueFailure::OutcomeUnknown)?
        {
            return Err(QueueFailure::OutcomeUnknown);
        }
        if !self
            .state
            .automation_admission_ready()
            .map_err(|_| QueueFailure::OutcomeUnknown)?
        {
            return Err(QueueFailure::OutcomeUnknown);
        }
        if response.queued_submission.client_user_message_id != admission.client_user_message_id
            || response.queued_submission.id.is_empty()
        {
            return Err(QueueFailure::OutcomeUnknown);
        }
        Ok(AutomationQueueReceipt {
            queued_submission_id: response.queued_submission.id,
            client_user_message_id: response.queued_submission.client_user_message_id,
        })
    }

    async fn connect_observer(&self) -> Result<RemoteAppServerClient, AutomationError> {
        if !self
            .state
            .automation_is_available()
            .map_err(|_| AutomationError::Unavailable)?
            || !self
                .state
                .automation_admission_ready()
                .map_err(|_| AutomationError::AccessDenied)?
        {
            return Err(AutomationError::Unavailable);
        }
        let socket_path = AbsolutePathBuf::from_absolute_path(&self.identity.app_server_socket)
            .map_err(|_| AutomationError::Unavailable)?;
        let client = RemoteAppServerClient::connect_with_bounded_events(
            RemoteAppServerConnectArgs {
                endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                client_name: "hepta-agentd-automation-observer".to_string(),
                client_version: env!("CARGO_PKG_VERSION").to_string(),
                experimental_api: true,
                mcp_server_openai_form_elicitation: false,
                opt_out_notification_methods: Vec::new(),
                channel_capacity: APP_SERVER_COMMAND_CAPACITY,
            },
            APP_SERVER_EVENT_CAPACITY,
        )
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let expected_home = self.identity.home_root.to_string_lossy();
        if client.codex_home() != Some(expected_home.as_ref()) {
            let _ = client.shutdown().await;
            return Err(AutomationError::AccessDenied);
        }
        Ok(client)
    }

    fn verify_observer_generation(&self) -> Result<(), AutomationError> {
        self.state
            .refresh_generation()
            .map_err(|_| AutomationError::AccessDenied)?;
        if !self
            .state
            .automation_is_available()
            .map_err(|_| AutomationError::Unavailable)?
            || !self
                .state
                .automation_admission_ready()
                .map_err(|_| AutomationError::AccessDenied)?
        {
            return Err(AutomationError::AccessDenied);
        }
        Ok(())
    }

    async fn reconcile_one_submitted(
        &self,
        store: &AutomationStore,
        now_ms: u64,
    ) -> Result<(), AutomationError> {
        let Some(occurrence) = store.submitted_occurrences(1).await?.into_iter().next() else {
            return Ok(());
        };
        let client = self.connect_observer().await?;
        let evidence = observe_provider_occurrence(&client, &occurrence).await;
        let _ = client.shutdown().await;
        let evidence = evidence?;
        self.verify_observer_generation()?;

        match evidence {
            ProviderEvidence::Queued => Ok(()),
            ProviderEvidence::TurnPersisted { turn_id, terminal } => {
                store
                    .record_provider_turn(
                        occurrence.admission.task_id,
                        occurrence.admission.occurrence,
                        &turn_id,
                        now_ms,
                    )
                    .await?;
                if let Some((terminal, receipt_digest)) = terminal {
                    store
                        .reconcile_submitted_terminal(
                            &occurrence,
                            terminal,
                            &receipt_digest,
                            now_ms,
                        )
                        .await?;
                }
                Ok(())
            }
            ProviderEvidence::Terminal {
                terminal,
                receipt_digest,
            } => {
                store
                    .reconcile_submitted_terminal(
                        &occurrence,
                        terminal,
                        &receipt_digest,
                        now_ms,
                    )
                    .await
            }
            ProviderEvidence::Missing { receipt_digest } => {
                store
                    .record_provider_reconciliation_observation(
                        occurrence.admission.task_id,
                        occurrence.admission.occurrence,
                        AutomationProviderObservationKind::ReconciledMissing,
                        &receipt_digest,
                        now_ms,
                    )
                    .await?;
                Err(AutomationError::DispatchUnknown)
            }
            ProviderEvidence::BoundedHistoryMiss => Ok(()),
        }
    }
}

#[derive(Debug)]
enum ProviderEvidence {
    Queued,
    TurnPersisted {
        turn_id: String,
        terminal: Option<(AutomationOccurrenceTerminal, Sha256Digest)>,
    },
    Terminal {
        terminal: AutomationOccurrenceTerminal,
        receipt_digest: Sha256Digest,
    },
    Missing {
        receipt_digest: Sha256Digest,
    },
    BoundedHistoryMiss,
}

async fn observe_provider_occurrence(
    client: &RemoteAppServerClient,
    occurrence: &AutomationSubmittedOccurrence,
) -> Result<ProviderEvidence, AutomationError> {
    if let Some(turn_id) = occurrence.provider_turn_id.as_deref() {
        return observe_turn(client, &occurrence.admission.thread_id, turn_id).await;
    }

    let input = automation_input(&occurrence.admission);
    let expected_payload_sha256 = automation_input_digest(&input)?;
    let response: ThreadQueueReconcileResponse = client
        .request_handle()
        .request_typed(ClientRequest::ThreadQueueReconcile {
            request_id: RequestId::Integer(2),
            params: ThreadQueueReconcileParams {
                thread_id: occurrence.admission.thread_id.clone(),
                input: input.clone(),
                client_user_message_id: occurrence.admission.client_user_message_id.clone(),
                expected_payload_sha256: expected_payload_sha256.clone(),
                mode: ThreadQueueReconcileMode::ReconcileOnly,
            },
        })
        .await
        .map_err(|_| AutomationError::Unavailable)?;
    if response.client_user_message_id != occurrence.admission.client_user_message_id
        || response.payload_sha256 != expected_payload_sha256
    {
        return Err(AutomationError::Corrupt);
    }

    match response.outcome {
        ThreadQueueReconcileOutcome::Queued {
            queued_submission,
            created,
        } => {
            if created
                || queued_submission.client_user_message_id
                    != occurrence.admission.client_user_message_id
                || queued_submission.id != occurrence.queued_submission_id
                || automation_input_digest(&queued_submission.input)? != expected_payload_sha256
            {
                return Err(AutomationError::Corrupt);
            }
            Ok(ProviderEvidence::Queued)
        }
        ThreadQueueReconcileOutcome::Persisted { turn_id } => {
            if turn_id.is_empty() {
                return Err(AutomationError::Corrupt);
            }
            let terminal = match observe_turn(client, &occurrence.admission.thread_id, &turn_id).await?
            {
                ProviderEvidence::Terminal {
                    terminal,
                    receipt_digest,
                } => Some((terminal, receipt_digest)),
                ProviderEvidence::BoundedHistoryMiss | ProviderEvidence::Queued => None,
                ProviderEvidence::Missing { receipt_digest } => {
                    return Ok(ProviderEvidence::Missing { receipt_digest });
                }
                ProviderEvidence::TurnPersisted { .. } => return Err(AutomationError::Corrupt),
            };
            Ok(ProviderEvidence::TurnPersisted { turn_id, terminal })
        }
        ThreadQueueReconcileOutcome::Cancelled => {
            let receipt_digest = digest_json(&response)?;
            Ok(ProviderEvidence::Terminal {
                terminal: AutomationOccurrenceTerminal::Cancelled,
                receipt_digest,
            })
        }
        ThreadQueueReconcileOutcome::Missing => Ok(ProviderEvidence::Missing {
            receipt_digest: digest_json(&response)?,
        }),
    }
}

async fn observe_turn(
    client: &RemoteAppServerClient,
    thread_id: &str,
    turn_id: &str,
) -> Result<ProviderEvidence, AutomationError> {
    let mut cursor = None;
    for _ in 0..AUTOMATION_OBSERVER_MAX_TURN_PAGES {
        let response: ThreadTurnsListResponse = client
            .request_handle()
            .request_typed(ClientRequest::ThreadTurnsList {
                request_id: RequestId::Integer(3),
                params: ThreadTurnsListParams {
                    thread_id: thread_id.to_string(),
                    cursor,
                    limit: Some(AUTOMATION_OBSERVER_TURN_PAGE),
                    sort_direction: Some(SortDirection::Desc),
                    items_view: Some(TurnItemsView::NotLoaded),
                },
            })
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        if let Some(turn) = response.data.into_iter().find(|turn| turn.id == turn_id) {
            return turn_evidence(&turn);
        }
        let Some(next_cursor) = response.next_cursor else {
            return Ok(ProviderEvidence::Missing {
                receipt_digest: Sha256Digest::for_bytes(
                    format!(
                        "hepta.automation.turn-missing.v1\\0{thread_id}\\0{turn_id}"
                    )
                    .as_bytes(),
                ),
            });
        };
        cursor = Some(next_cursor);
    }
    Ok(ProviderEvidence::BoundedHistoryMiss)
}

fn turn_evidence(turn: &Turn) -> Result<ProviderEvidence, AutomationError> {
    let terminal = match turn.status {
        TurnStatus::Completed => Some(AutomationOccurrenceTerminal::Succeeded),
        TurnStatus::Failed => Some(AutomationOccurrenceTerminal::Failed),
        TurnStatus::Interrupted => Some(AutomationOccurrenceTerminal::Cancelled),
        TurnStatus::InProgress => None,
    };
    Ok(match terminal {
        Some(terminal) => ProviderEvidence::Terminal {
            terminal,
            receipt_digest: digest_json(turn)?,
        },
        None => ProviderEvidence::Queued,
    })
}

fn digest_json(value: &impl serde::Serialize) -> Result<Sha256Digest, AutomationError> {
    let bytes = serde_json::to_vec(value).map_err(|_| AutomationError::Corrupt)?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn automation_input(admission: &AutomationAdmission) -> Vec<UserInput> {
    vec![UserInput::Text {
        text: admission.prompt.clone(),
        text_elements: Vec::new(),
    }]
}

fn automation_input_digest(input: &[UserInput]) -> Result<String, AutomationError> {
    user_input_payload_sha256(
        &input
            .iter()
            .cloned()
            .map(UserInput::into_core)
            .collect::<Vec<_>>(),
    )
    .map_err(|_| AutomationError::Corrupt)
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
        Arc::clone(&queue),
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
        if let Err(error) = queue
            .reconcile_one_submitted(scheduler.store(), now_ms)
            .await
        {
            return stop_after_automation_error(error, &state, &cancellation).await;
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

/// Applies the scheduler's fail-stop policy to one tick.  A `true` result
/// means the caller should terminate its scheduler task after cancellation
/// has been observed; the Agent itself remains alive for normal turns.
pub(crate) async fn handle_automation_tick(
    tick: codex_hepta_automation::AutomationTick,
    retry_budget: &mut DispatchRetryBudget,
    state: &AgentdState,
    cancellation: &CancellationToken,
) -> Result<bool, AgentdError> {
    let stop_error = match tick {
        codex_hepta_automation::AutomationTick::DispatchUncertain { .. } => {
            Some(AutomationError::DispatchUnknown)
        }
        tick if retry_budget.observe(&tick) => Some(AutomationError::Dispatch),
        _ => None,
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
    /// Returns true once a bounded run of dispatch retries is exhausted.
    /// Any idle or successful submission proves the queue is making progress
    /// and resets the consecutive-failure counter.
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

async fn wait_for_cancellation(cancellation: &CancellationToken) -> Result<(), AgentdError> {
    cancellation.cancelled().await;
    Ok(())
}

fn automation_queue_request(admission: &AutomationAdmission) -> ClientRequest {
    ClientRequest::ThreadQueueAdd {
        request_id: RequestId::Integer(1),
        params: ThreadQueueAddParams {
            thread_id: admission.thread_id.clone(),
            input: automation_input(admission),
            client_user_message_id: admission.client_user_message_id.clone(),
        },
    }
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
    fn automation_has_only_normal_app_server_queue_admission() {
        let admission = AutomationAdmission {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id"),
            task_id: AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75007")
                .expect("task id"),
            occurrence: 3,
            occurrence_id: codex_hepta_automation::AutomationOccurrenceId::derive(
                AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75007")
                    .expect("task id"),
                1,
                44,
            )
            .expect("occurrence id"),
            schedule_revision: 1,
            scheduled_for_ms: 44,
            thread_id: "019153a4-3088-7e03-a56a-9b1964f75ddd".to_string(),
            prompt: "run through governance".to_string(),
            client_user_message_id: "hepta.automation.test".to_string(),
        };
        let ClientRequest::ThreadQueueAdd { params, .. } = automation_queue_request(&admission)
        else {
            panic!("automation must only enter via thread/queue/add");
        };
        assert_eq!(params.thread_id, admission.thread_id);
        assert_eq!(
            params.client_user_message_id,
            admission.client_user_message_id
        );
        assert_eq!(
            params.input,
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
        let submitted = AutomationTick::Submitted {
            task_id,
            occurrence: 1,
            queued_submission_id: "queue-1".to_string(),
        };
        let mut budget = DispatchRetryBudget::default();

        assert!(!budget.observe(&retry));
        assert!(!budget.observe(&retry));
        assert!(budget.observe(&retry));

        assert!(!budget.observe(&submitted));
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
