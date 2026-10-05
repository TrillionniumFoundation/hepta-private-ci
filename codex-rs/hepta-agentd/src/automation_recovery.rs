//! Bounded recovery/terminal observation for durable automation occurrences.
//!
//! Recovery never invents a fresh queue identity. Lost replies use the App
//! Server's atomic `thread/queue/reconcile` lookup with `ReconcileOnly`; a
//! terminal occurrence is published only after a persisted turn reports a
//! terminal status and the durable TaskFlow step/run have been reconciled.

use codex_app_server_client::AbortOnDropRemoteAppServerClient;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::RemoteAppServerConnectArgs;
use codex_app_server_client::RemoteAppServerEndpoint;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SortDirection;
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
use codex_hepta_automation::AutomationOccurrenceTerminalState;
use codex_hepta_automation::AutomationOccurrenceWork;
use codex_hepta_automation::AutomationQueueReceipt;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationUncertainDispatchScan;
use codex_hepta_contracts::Sha256Digest;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::future::Future;
use std::time::Duration;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;

const TURN_PAGE_SIZE: u32 = 100;
const MAX_TURN_PAGES: usize = 16;
const RECOVERY_RUN_LEASE_MS: u64 = 30_000;
// Separate connect and read budgets, not a total recovery deadline. Owned
// shutdown may take another two five-second waits; database waits remain outside.
const OBSERVATION_DEADLINE: Duration = Duration::from_secs(5);

pub(crate) type RecoveryClock =
    dyn Fn() -> Result<u64, codex_hepta_automation::AutomationError> + Send + Sync;

#[derive(Debug, Eq, PartialEq)]
pub(crate) enum RecoveryPass {
    Idle,
    Observed,
    Deferred,
    Cancelled,
}

#[derive(Debug)]
enum RecoveryError {
    ObservationDeadline,
    Cancelled,
    Fatal(AgentdError),
}

impl From<AgentdError> for RecoveryError {
    fn from(error: AgentdError) -> Self {
        Self::Fatal(error)
    }
}

impl From<codex_hepta_automation::AutomationError> for RecoveryError {
    fn from(error: codex_hepta_automation::AutomationError) -> Self {
        Self::Fatal(error.into())
    }
}

/// Only read-only network waits enter this helper. Durable reconciliation and
/// admitted dispatch acknowledgements are never cancelled by its deadline.
async fn observe<T>(
    future: impl Future<Output = Result<T, AgentdError>>,
    deadline: Instant,
    cancellation: &CancellationToken,
) -> Result<T, RecoveryError> {
    tokio::select! {
        biased;
        _ = cancellation.cancelled() => Err(RecoveryError::Cancelled),
        result = tokio::time::timeout_at(deadline, future) => {
            result.map_err(|_| RecoveryError::ObservationDeadline)?
                .map_err(RecoveryError::Fatal)
        }
    }
}

enum TurnLookup {
    Found(Turn),
    Continue(String),
    Exhausted,
}

pub(crate) async fn reconcile_one(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    now_ms: u64,
    uncertainty_scan: &mut AutomationUncertainDispatchScan,
    cancellation: &CancellationToken,
    clock: &RecoveryClock,
) -> Result<RecoveryPass, AgentdError> {
    state.refresh_generation()?;
    let result = reconcile_one_inner(
        store,
        state,
        identity,
        now_ms,
        uncertainty_scan,
        cancellation,
        clock,
    )
    .await;
    // A timeout/cancellation must not hide a changed owning generation.
    state.refresh_generation()?;
    match result {
        Ok(false) => Ok(RecoveryPass::Idle),
        Ok(true) => Ok(RecoveryPass::Observed),
        Err(RecoveryError::ObservationDeadline) => Ok(RecoveryPass::Deferred),
        Err(RecoveryError::Cancelled) => Ok(RecoveryPass::Cancelled),
        Err(RecoveryError::Fatal(error)) => Err(error),
    }
}

async fn reconcile_one_inner(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    now_ms: u64,
    uncertainty_scan: &mut AutomationUncertainDispatchScan,
    cancellation: &CancellationToken,
    clock: &RecoveryClock,
) -> Result<bool, RecoveryError> {
    if reconcile_one_unknown_dispatch(
        store,
        state,
        identity,
        uncertainty_scan,
        cancellation,
        clock,
    )
    .await?
    {
        return Ok(true);
    }
    let Some(work) = store.pending_occurrence_work(1).await?.into_iter().next() else {
        return Ok(false);
    };
    reconcile_work(store, state, identity, work, now_ms, cancellation, clock).await?;
    Ok(true)
}

async fn reconcile_one_unknown_dispatch(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    uncertainty_scan: &mut AutomationUncertainDispatchScan,
    cancellation: &CancellationToken,
    clock: &RecoveryClock,
) -> Result<bool, RecoveryError> {
    let Some(uncertain) = store.next_uncertain_dispatch(uncertainty_scan).await? else {
        return Ok(false);
    };
    let task = store
        .task(uncertain.task_id)
        .await?
        .ok_or_else(|| AgentdError::Protocol("uncertain automation task is missing".to_string()))?;
    let input = prompt_input(&task.prompt);
    let expected = input_digest(&input)?;
    let client = connect(state, identity, cancellation).await?;
    let response = reconcile_queue(
        &client,
        &task.thread_id,
        input,
        &uncertain.client_user_message_id,
        &expected,
        cancellation,
    )
    .await;
    let _ = client.shutdown().await;
    state.refresh_generation()?;
    let response = response?;
    let now_ms = clock()?;
    validate_reconcile_identity(&response, &uncertain.client_user_message_id, &expected)?;
    match &response.outcome {
        ThreadQueueReconcileOutcome::Queued {
            queued_submission,
            created,
        } => {
            if *created
                || queued_submission.client_user_message_id != uncertain.client_user_message_id
                || queued_submission.id.is_empty()
                || input_digest(&queued_submission.input)? != expected
            {
                return Err(AgentdError::Protocol(
                    "automation recovery queue receipt mismatched durable intent".to_string(),
                )
                .into());
            }
            store
                .reconcile_uncertain_occurrence_admitted(
                    uncertain.task_id,
                    uncertain.occurrence,
                    &AutomationQueueReceipt {
                        queued_submission_id: queued_submission.id.clone(),
                        client_user_message_id: uncertain.client_user_message_id.clone(),
                    },
                    now_ms,
                )
                .await?;
        }
        ThreadQueueReconcileOutcome::Persisted { turn_id } if !turn_id.is_empty() => {
            let occurrence = store
                .reconcile_uncertain_occurrence_admitted(
                    uncertain.task_id,
                    uncertain.occurrence,
                    &AutomationQueueReceipt {
                        queued_submission_id: format!("persisted:{turn_id}"),
                        client_user_message_id: uncertain.client_user_message_id.clone(),
                    },
                    now_ms,
                )
                .await?;
            store
                .record_occurrence_turn(
                    occurrence.task_id,
                    occurrence.occurrence,
                    &occurrence.client_user_message_id,
                    turn_id,
                    &response.payload_sha256,
                    now_ms,
                )
                .await?;
        }
        ThreadQueueReconcileOutcome::Missing => {
            let proof_digest = observation_digest(&response)?;
            store
                .reconcile_uncertain_occurrence_absent(
                    uncertain.task_id,
                    uncertain.occurrence,
                    &uncertain.client_user_message_id,
                    &proof_digest,
                    now_ms,
                )
                .await?;
        }
        ThreadQueueReconcileOutcome::Cancelled => {
            let occurrence = store
                .reconcile_uncertain_occurrence_admitted(
                    uncertain.task_id,
                    uncertain.occurrence,
                    &AutomationQueueReceipt {
                        queued_submission_id: "cancelled-before-turn".to_string(),
                        client_user_message_id: uncertain.client_user_message_id.clone(),
                    },
                    now_ms,
                )
                .await?;
            let work = pending_exact(store, occurrence.task_id, occurrence.occurrence).await?;
            complete_work(
                store,
                &work,
                AutomationOccurrenceTerminalState::Cancelled,
                observation_digest(&response)?,
                now_ms,
                identity.spawn_generation,
            )
            .await?;
        }
        ThreadQueueReconcileOutcome::Persisted { .. } => {
            return Err(AgentdError::Protocol(
                "automation recovery returned an empty persisted turn id".to_string(),
            )
            .into());
        }
    }
    Ok(true)
}

async fn reconcile_work(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    work: AutomationOccurrenceWork,
    now_ms: u64,
    cancellation: &CancellationToken,
    clock: &RecoveryClock,
) -> Result<(), RecoveryError> {
    store
        .ensure_admitted_taskflow_uncertainty(&work, now_ms)
        .await
        .map_err(taskflow_error)?;
    if let Some(turn_id) = work.occurrence.turn_id.as_deref() {
        let client = connect(state, identity, cancellation).await?;
        let observed = find_turn(
            &client,
            &work.admission.thread_id,
            turn_id,
            work.occurrence.terminal_scan_cursor.as_deref(),
            cancellation,
        )
        .await;
        let _ = client.shutdown().await;
        state.refresh_generation()?;
        let observed = observed?;
        let now_ms = clock()?;
        let turn = match observed {
            TurnLookup::Found(turn) => turn,
            TurnLookup::Continue(next_cursor) => {
                store
                    .record_terminal_scan_cursor(
                        work.occurrence.task_id,
                        work.occurrence.occurrence,
                        turn_id,
                        work.occurrence.terminal_scan_cursor.as_deref(),
                        &next_cursor,
                        now_ms,
                    )
                    .await?;
                return Ok(());
            }
            TurnLookup::Exhausted => {
                let mut bytes = b"hepta.automation.turn-history-exhausted.v1\0".to_vec();
                bytes.extend_from_slice(work.occurrence.occurrence_id.as_bytes());
                bytes.push(0);
                bytes.extend_from_slice(turn_id.as_bytes());
                let digest = Sha256Digest::for_bytes(&bytes);
                store
                    .mark_occurrence_indeterminate(
                        work.occurrence.task_id,
                        work.occurrence.occurrence,
                        &digest,
                        now_ms,
                    )
                    .await?;
                return Ok(());
            }
        };
        match turn.status {
            TurnStatus::InProgress => Ok(()),
            TurnStatus::Completed => {
                complete_work(
                    store,
                    &work,
                    AutomationOccurrenceTerminalState::Succeeded,
                    observation_digest(&turn)?,
                    now_ms,
                    identity.spawn_generation,
                )
                .await
            }
            TurnStatus::Failed => {
                complete_work(
                    store,
                    &work,
                    AutomationOccurrenceTerminalState::Failed,
                    observation_digest(&turn)?,
                    now_ms,
                    identity.spawn_generation,
                )
                .await
            }
            TurnStatus::Interrupted => {
                complete_work(
                    store,
                    &work,
                    AutomationOccurrenceTerminalState::Cancelled,
                    observation_digest(&turn)?,
                    now_ms,
                    identity.spawn_generation,
                )
                .await
            }
        }
    } else {
        reconcile_admitted_without_turn(store, state, identity, &work, cancellation, clock).await
    }
}

async fn reconcile_admitted_without_turn(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    work: &AutomationOccurrenceWork,
    cancellation: &CancellationToken,
    clock: &RecoveryClock,
) -> Result<(), RecoveryError> {
    let input = prompt_input(&work.admission.prompt);
    let expected = input_digest(&input)?;
    let client = connect(state, identity, cancellation).await?;
    let response = reconcile_queue(
        &client,
        &work.admission.thread_id,
        input,
        &work.admission.client_user_message_id,
        &expected,
        cancellation,
    )
    .await;
    let _ = client.shutdown().await;
    state.refresh_generation()?;
    let response = response?;
    let now_ms = clock()?;
    validate_reconcile_identity(&response, &work.admission.client_user_message_id, &expected)?;
    match &response.outcome {
        ThreadQueueReconcileOutcome::Queued {
            queued_submission,
            created,
        } => {
            if *created
                || queued_submission.client_user_message_id != work.admission.client_user_message_id
                || input_digest(&queued_submission.input)? != expected
            {
                return Err(AgentdError::Protocol(
                    "automation queued reconciliation changed identity or payload".to_string(),
                )
                .into());
            }
            Ok(())
        }
        ThreadQueueReconcileOutcome::Persisted { turn_id } if !turn_id.is_empty() => {
            store
                .record_occurrence_turn(
                    work.occurrence.task_id,
                    work.occurrence.occurrence,
                    &work.occurrence.client_user_message_id,
                    turn_id,
                    &response.payload_sha256,
                    now_ms,
                )
                .await?;
            Ok(())
        }
        ThreadQueueReconcileOutcome::Cancelled => {
            complete_work(
                store,
                work,
                AutomationOccurrenceTerminalState::Cancelled,
                observation_digest(&response)?,
                now_ms,
                identity.spawn_generation,
            )
            .await
        }
        ThreadQueueReconcileOutcome::Missing => {
            let digest = observation_digest(&response)?;
            store
                .mark_occurrence_indeterminate(
                    work.occurrence.task_id,
                    work.occurrence.occurrence,
                    &digest,
                    now_ms,
                )
                .await?;
            Ok(())
        }
        ThreadQueueReconcileOutcome::Persisted { .. } => Err(AgentdError::Protocol(
            "automation reconciliation returned an empty persisted turn id".to_string(),
        )
        .into()),
    }
}

async fn complete_work(
    store: &AutomationStore,
    work: &AutomationOccurrenceWork,
    terminal: AutomationOccurrenceTerminalState,
    receipt_digest: Sha256Digest,
    now_ms: u64,
    recovery_generation: u64,
) -> Result<(), RecoveryError> {
    store
        .ensure_admitted_taskflow_uncertainty(work, now_ms)
        .await
        .map_err(taskflow_error)?;
    store
        .reconcile_occurrence_taskflow_terminal_with_recovery(
            work,
            terminal,
            &receipt_digest,
            now_ms,
            recovery_generation,
            RECOVERY_RUN_LEASE_MS,
        )
        .await
        .map_err(taskflow_error)?;
    store
        .complete_occurrence(
            work.occurrence.task_id,
            work.occurrence.occurrence,
            terminal,
            &receipt_digest,
            now_ms,
        )
        .await?;
    Ok(())
}

async fn pending_exact(
    store: &AutomationStore,
    task_id: codex_hepta_automation::AutomationTaskId,
    occurrence: u64,
) -> Result<AutomationOccurrenceWork, AgentdError> {
    store
        .pending_occurrence_work(1024)
        .await?
        .into_iter()
        .find(|work| work.occurrence.task_id == task_id && work.occurrence.occurrence == occurrence)
        .ok_or_else(|| {
            AgentdError::Protocol(
                "automation occurrence is not in the recovery frontier".to_string(),
            )
        })
}

async fn connect(
    state: &AgentdState,
    identity: &AgentdIdentity,
    cancellation: &CancellationToken,
) -> Result<AbortOnDropRemoteAppServerClient, RecoveryError> {
    if !state.automation_admission_ready()? {
        return Err(AgentdError::Protocol(
            "automation recovery requires a ready owning Agent generation".to_string(),
        )
        .into());
    }
    let socket_path =
        AbsolutePathBuf::from_absolute_path(&identity.app_server_socket).map_err(|error| {
            AgentdError::Protocol(format!("automation socket path invalid: {error}"))
        })?;
    // Initialization precedes worker spawn, and ownership is returned without
    // another await. Cancellation drops the pre-worker stream; once returned,
    // this exclusive client is always shut down before a read result is handled.
    let client = observe(
        async {
            RemoteAppServerClient::connect_with_bounded_events(
                RemoteAppServerConnectArgs {
                    endpoint: RemoteAppServerEndpoint::UnixSocket { socket_path },
                    client_name: "hepta-agentd-automation-recovery".to_string(),
                    client_version: env!("CARGO_PKG_VERSION").to_string(),
                    experimental_api: true,
                    mcp_server_openai_form_elicitation: false,
                    opt_out_notification_methods: Vec::new(),
                    channel_capacity: 8,
                },
                16,
            )
            .await
            .map(RemoteAppServerClient::into_abort_on_drop)
            .map_err(|error| {
                AgentdError::Protocol(format!("automation recovery connect failed: {error}"))
            })
        },
        Instant::now() + OBSERVATION_DEADLINE,
        cancellation,
    )
    .await?;
    let expected_home = identity.home_root.to_string_lossy();
    if client.codex_home() != Some(expected_home.as_ref()) {
        let _ = client.shutdown().await;
        return Err(AgentdError::GenerationFenced(
            "automation recovery App Server home differs from owning Agent home".to_string(),
        )
        .into());
    }
    Ok(client)
}

async fn reconcile_queue(
    client: &RemoteAppServerClient,
    thread_id: &str,
    input: Vec<UserInput>,
    client_user_message_id: &str,
    expected_payload_sha256: &str,
    cancellation: &CancellationToken,
) -> Result<ThreadQueueReconcileResponse, RecoveryError> {
    observe(
        async {
            client
                .request_handle()
                .request_typed(ClientRequest::ThreadQueueReconcile {
                    request_id: RequestId::Integer(1),
                    params: ThreadQueueReconcileParams {
                        thread_id: thread_id.to_string(),
                        input,
                        client_user_message_id: client_user_message_id.to_string(),
                        expected_payload_sha256: expected_payload_sha256.to_string(),
                        mode: ThreadQueueReconcileMode::ReconcileOnly,
                    },
                })
                .await
                .map_err(|error| {
                    AgentdError::Protocol(format!("automation queue reconcile failed: {error}"))
                })
        },
        Instant::now() + OBSERVATION_DEADLINE,
        cancellation,
    )
    .await
}

async fn find_turn(
    client: &RemoteAppServerClient,
    thread_id: &str,
    turn_id: &str,
    start_cursor: Option<&str>,
    cancellation: &CancellationToken,
) -> Result<TurnLookup, RecoveryError> {
    let mut cursor = start_cursor.map(str::to_owned);
    // All pages share one read budget. A slow later page keeps the already
    // observed continuation instead of pretending the turn was absent.
    let deadline = Instant::now() + OBSERVATION_DEADLINE;
    for page_index in 0..MAX_TURN_PAGES {
        let observed = observe(
            async {
                client
                    .request_handle()
                    .request_typed(ClientRequest::ThreadTurnsList {
                        request_id: RequestId::Integer(
                            i64::try_from(page_index + 2).unwrap_or(i64::MAX),
                        ),
                        params: ThreadTurnsListParams {
                            thread_id: thread_id.to_string(),
                            cursor: cursor.clone(),
                            limit: Some(TURN_PAGE_SIZE),
                            sort_direction: Some(SortDirection::Desc),
                            items_view: Some(TurnItemsView::NotLoaded),
                        },
                    })
                    .await
                    .map_err(|error| {
                        AgentdError::Protocol(format!(
                            "automation turn observation failed: {error}"
                        ))
                    })
            },
            deadline,
            cancellation,
        )
        .await;
        let response: ThreadTurnsListResponse = match observed {
            Err(RecoveryError::ObservationDeadline) => {
                return deferred_turn_scan(page_index, cursor);
            }
            result => result?,
        };
        if let Some(turn) = response.data.into_iter().find(|turn| turn.id == turn_id) {
            return Ok(TurnLookup::Found(turn));
        }
        let Some(next) = response.next_cursor else {
            return Ok(TurnLookup::Exhausted);
        };
        if cursor.as_deref() == Some(next.as_str()) {
            return Err(AgentdError::Protocol(
                "automation turn observation returned a repeated cursor".to_string(),
            )
            .into());
        }
        cursor = Some(next);
    }
    cursor.map(TurnLookup::Continue).ok_or_else(|| {
        AgentdError::Protocol(
            "automation bounded turn observation ended without a continuation cursor".to_string(),
        )
        .into()
    })
}

fn deferred_turn_scan(
    page_index: usize,
    cursor: Option<String>,
) -> Result<TurnLookup, RecoveryError> {
    if page_index == 0 {
        return Err(RecoveryError::ObservationDeadline);
    }
    cursor.map(TurnLookup::Continue).ok_or_else(|| {
        AgentdError::Protocol("automation recovery lost scan continuation".to_string()).into()
    })
}

fn prompt_input(prompt: &str) -> Vec<UserInput> {
    vec![UserInput::Text {
        text: prompt.to_string(),
        text_elements: Vec::new(),
    }]
}

pub(crate) fn input_digest(input: &[UserInput]) -> Result<String, AgentdError> {
    user_input_payload_sha256(
        &input
            .iter()
            .cloned()
            .map(UserInput::into_core)
            .collect::<Vec<_>>(),
    )
    .map_err(|error| AgentdError::Protocol(format!("automation input digest failed: {error}")))
}

pub(crate) fn validate_reconcile_identity(
    response: &ThreadQueueReconcileResponse,
    client_user_message_id: &str,
    expected_payload_sha256: &str,
) -> Result<(), AgentdError> {
    if response.client_user_message_id != client_user_message_id
        || response.payload_sha256 != expected_payload_sha256
    {
        return Err(AgentdError::Protocol(
            "automation reconciliation identity or payload mismatch".to_string(),
        ));
    }
    Ok(())
}

fn observation_digest(value: &impl serde::Serialize) -> Result<Sha256Digest, AgentdError> {
    Ok(Sha256Digest::for_bytes(&serde_json::to_vec(value)?))
}

fn taskflow_error(error: codex_hepta_automation::TaskFlowError) -> AgentdError {
    AgentdError::Protocol(format!("automation TaskFlow recovery failed: {error}"))
}

#[cfg(test)]
#[path = "automation_observation_policy_tests.rs"]
mod observation_policy_tests;
