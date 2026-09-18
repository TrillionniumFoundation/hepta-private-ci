//! Bounded recovery/terminal observation for durable automation occurrences.
//!
//! Recovery never invents a fresh queue identity. Lost replies use the App
//! Server's atomic `thread/queue/reconcile` lookup with `ReconcileOnly`; a
//! terminal occurrence is published only after a persisted turn reports a
//! terminal status and the durable TaskFlow step/run have been reconciled.

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
use codex_hepta_contracts::Sha256Digest;
use codex_protocol::user_input::user_input_payload_sha256;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;

const TURN_PAGE_SIZE: u32 = 100;
const MAX_TURN_PAGES: usize = 16;
const RECOVERY_RUN_LEASE_MS: u64 = 30_000;

pub(crate) async fn reconcile_one(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    now_ms: u64,
) -> Result<bool, AgentdError> {
    if reconcile_one_unknown_dispatch(store, state, identity, now_ms).await? {
        return Ok(true);
    }
    let Some(work) = store
        .pending_occurrence_work(1)
        .await?
        .into_iter()
        .next()
    else {
        return Ok(false);
    };
    reconcile_work(store, state, identity, work, now_ms).await?;
    Ok(true)
}

async fn reconcile_one_unknown_dispatch(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    now_ms: u64,
) -> Result<bool, AgentdError> {
    let Some(uncertain) = store.uncertain_dispatches(1).await?.into_iter().next() else {
        return Ok(false);
    };
    let task = store
        .task(uncertain.task_id)
        .await?
        .ok_or_else(|| AgentdError::Protocol("uncertain automation task is missing".to_string()))?;
    let input = prompt_input(&task.prompt);
    let expected = input_digest(&input)?;
    let client = connect(state, identity).await?;
    let response = reconcile_queue(
        &client,
        &task.thread_id,
        input,
        &uncertain.client_user_message_id,
        &expected,
    )
    .await;
    let _ = client.shutdown().await;
    let response = response?;
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
                ));
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
            store
                .reconcile_uncertain_occurrence_absent(
                    uncertain.task_id,
                    uncertain.occurrence,
                    &uncertain.client_user_message_id,
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
            ));
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
) -> Result<(), AgentdError> {
    store
        .ensure_admitted_taskflow_uncertainty(&work, now_ms)
        .await
        .map_err(taskflow_error)?;
    if let Some(turn_id) = work.occurrence.turn_id.as_deref() {
        let client = connect(state, identity).await?;
        let observed = find_turn(&client, &work.admission.thread_id, turn_id).await;
        let _ = client.shutdown().await;
        let Some(turn) = observed? else {
            let mut bytes = b"hepta.automation.turn-history-miss.v1\0".to_vec();
            bytes.extend_from_slice(work.occurrence.occurrence_id.as_bytes());
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
        reconcile_admitted_without_turn(store, state, identity, &work, now_ms).await
    }
}

async fn reconcile_admitted_without_turn(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    work: &AutomationOccurrenceWork,
    now_ms: u64,
) -> Result<(), AgentdError> {
    let input = prompt_input(&work.admission.prompt);
    let expected = input_digest(&input)?;
    let client = connect(state, identity).await?;
    let response = reconcile_queue(
        &client,
        &work.admission.thread_id,
        input,
        &work.admission.client_user_message_id,
        &expected,
    )
    .await;
    let _ = client.shutdown().await;
    let response = response?;
    validate_reconcile_identity(
        &response,
        &work.admission.client_user_message_id,
        &expected,
    )?;
    match &response.outcome {
        ThreadQueueReconcileOutcome::Queued {
            queued_submission,
            created,
        } => {
            if *created
                || queued_submission.client_user_message_id
                    != work.admission.client_user_message_id
                || input_digest(&queued_submission.input)? != expected
            {
                return Err(AgentdError::Protocol(
                    "automation queued reconciliation changed identity or payload".to_string(),
                ));
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
        )),
    }
}

async fn complete_work(
    store: &AutomationStore,
    work: &AutomationOccurrenceWork,
    terminal: AutomationOccurrenceTerminalState,
    receipt_digest: Sha256Digest,
    now_ms: u64,
    recovery_generation: u64,
) -> Result<(), AgentdError> {
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
        .find(|work| {
            work.occurrence.task_id == task_id && work.occurrence.occurrence == occurrence
        })
        .ok_or_else(|| {
            AgentdError::Protocol("automation occurrence is not in the recovery frontier".to_string())
        })
}

async fn connect(
    state: &AgentdState,
    identity: &AgentdIdentity,
) -> Result<RemoteAppServerClient, AgentdError> {
    if !state.automation_admission_ready()? {
        return Err(AgentdError::Protocol(
            "automation recovery requires a ready owning Agent generation".to_string(),
        ));
    }
    let socket_path = AbsolutePathBuf::from_absolute_path(&identity.app_server_socket)
        .map_err(|error| AgentdError::Protocol(format!("automation socket path invalid: {error}")))?;
    let client = RemoteAppServerClient::connect_with_bounded_events(
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
    .map_err(|error| AgentdError::Protocol(format!("automation recovery connect failed: {error}")))?;
    let expected_home = identity.home_root.to_string_lossy();
    if client.codex_home() != Some(expected_home.as_ref()) {
        let _ = client.shutdown().await;
        return Err(AgentdError::GenerationFenced(
            "automation recovery App Server home differs from owning Agent home".to_string(),
        ));
    }
    Ok(client)
}

async fn reconcile_queue(
    client: &RemoteAppServerClient,
    thread_id: &str,
    input: Vec<UserInput>,
    client_user_message_id: &str,
    expected_payload_sha256: &str,
) -> Result<ThreadQueueReconcileResponse, AgentdError> {
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
        .map_err(|error| AgentdError::Protocol(format!("automation queue reconcile failed: {error}")))
}

async fn find_turn(
    client: &RemoteAppServerClient,
    thread_id: &str,
    turn_id: &str,
) -> Result<Option<Turn>, AgentdError> {
    let mut cursor = None;
    for page_index in 0..MAX_TURN_PAGES {
        let response: ThreadTurnsListResponse = client
            .request_handle()
            .request_typed(ClientRequest::ThreadTurnsList {
                request_id: RequestId::Integer(
                    i64::try_from(page_index + 2).unwrap_or(i64::MAX),
                ),
                params: ThreadTurnsListParams {
                    thread_id: thread_id.to_string(),
                    cursor,
                    limit: Some(TURN_PAGE_SIZE),
                    sort_direction: Some(SortDirection::Desc),
                    items_view: Some(TurnItemsView::NotLoaded),
                },
            })
            .await
            .map_err(|error| {
                AgentdError::Protocol(format!("automation turn observation failed: {error}"))
            })?;
        if let Some(turn) = response.data.into_iter().find(|turn| turn.id == turn_id) {
            return Ok(Some(turn));
        }
        let Some(next) = response.next_cursor else {
            return Ok(None);
        };
        cursor = Some(next);
    }
    Ok(None)
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
