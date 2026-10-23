//! Settle historical automation from the original App Server's read-only owner.
//! Draining never uses queue reconciliation that can reserve or wake a turn.

use super::*;
use codex_app_server::AppServerDrainHandle;
use codex_app_server::QueueHistoricalObservation;
use codex_app_server::QueueHistoricalOutcome;
use codex_app_server::QueueHistoricalTerminal;
use codex_hepta_automation::AutomationOccurrenceState;

pub(super) async fn reconcile_one(
    store: &AutomationStore,
    state: &AgentdState,
    identity: &AgentdIdentity,
    observer: &AppServerDrainHandle,
) -> Result<bool, AgentdError> {
    // An unknown dispatch without affirmative durable evidence remains
    // quarantined. It must not starve an admitted occurrence's settlement.
    if let Some(uncertain) = store.uncertain_dispatches(1).await?.into_iter().next() {
        let task = store.task(uncertain.task_id).await?.ok_or_else(|| {
            AgentdError::Protocol("uncertain automation task is missing".to_string())
        })?;
        let observed = observe(
            state,
            identity,
            observer,
            &task.thread_id,
            &task.prompt,
            &uncertain.client_user_message_id,
        )
        .await?;
        let receipt_id = match &observed.outcome {
            QueueHistoricalOutcome::Persisted { turn_id, .. } => {
                Some(format!("persisted:{turn_id}"))
            }
            QueueHistoricalOutcome::Cancelled => Some("cancelled-before-turn".to_string()),
            QueueHistoricalOutcome::Pending {
                queued_submission_id,
            } => queued_submission_id.clone(),
            QueueHistoricalOutcome::Missing | QueueHistoricalOutcome::Unknown => None,
        };
        if let Some(queued_submission_id) = receipt_id {
            let now_ms = crate::automation::unix_time_ms()?;
            let occurrence = store
                .reconcile_uncertain_occurrence_admitted(
                    uncertain.task_id,
                    uncertain.occurrence,
                    &AutomationQueueReceipt {
                        queued_submission_id,
                        client_user_message_id: uncertain.client_user_message_id,
                    },
                    now_ms,
                )
                .await?;
            let work = AutomationOccurrenceWork {
                admission: AutomationAdmission {
                    agent_id: task.owner_agent_id,
                    task_id: occurrence.task_id,
                    occurrence: occurrence.occurrence,
                    scheduled_for_ms: occurrence.scheduled_for_ms,
                    thread_id: task.thread_id,
                    prompt: task.prompt,
                    client_user_message_id: occurrence.client_user_message_id.clone(),
                },
                occurrence,
            };
            settle(store, &work, observed, now_ms).await?;
            return Ok(true);
        }
    }
    let Some(work) = store
        .pending_drain_occurrence_work(1)
        .await?
        .into_iter()
        .next()
    else {
        return Ok(false);
    };
    let observed = observe(
        state,
        identity,
        observer,
        &work.admission.thread_id,
        &work.admission.prompt,
        &work.admission.client_user_message_id,
    )
    .await?;
    settle(store, &work, observed, crate::automation::unix_time_ms()?).await?;
    Ok(true)
}

async fn observe(
    state: &AgentdState,
    identity: &AgentdIdentity,
    observer: &AppServerDrainHandle,
    thread_id: &str,
    prompt: &str,
    client_id: &str,
) -> Result<QueueHistoricalObservation, AgentdError> {
    validate_observation_generation(state)?;
    let expected = input_digest(&prompt_input(prompt))?;
    let response = tokio::time::timeout(
        RECOVERY_REQUEST_TIMEOUT,
        observer.observe_exact_submission(&identity.home_root, thread_id, client_id, &expected),
    )
    .await
    .map_err(|_| AgentdError::Protocol("automation historical observation timed out".to_string()))?
    .map_err(|error| {
        AgentdError::Protocol(format!("automation historical observation failed: {error}"))
    })?;
    validate_observation_generation(state)?;
    if response.client_user_message_id != client_id || response.payload_sha256 != expected {
        return Err(AgentdError::Protocol(
            "historical automation observation changed identity or payload".to_string(),
        ));
    }
    Ok(response)
}

async fn settle(
    store: &AutomationStore,
    work: &AutomationOccurrenceWork,
    observed: QueueHistoricalObservation,
    now_ms: u64,
) -> Result<(), AgentdError> {
    let outcome = match &observed.outcome {
        QueueHistoricalOutcome::Pending {
            queued_submission_id,
        } => serde_json::json!({ "pending": queued_submission_id }),
        QueueHistoricalOutcome::Persisted { turn_id, terminal } => {
            serde_json::json!({ "turnId": turn_id, "terminal": terminal.map(|status| match status { QueueHistoricalTerminal::Completed => "completed", QueueHistoricalTerminal::Failed => "failed", QueueHistoricalTerminal::Interrupted => "interrupted" }) })
        }
        QueueHistoricalOutcome::Missing => serde_json::json!("missing"),
        QueueHistoricalOutcome::Unknown => serde_json::json!("unknown"),
        QueueHistoricalOutcome::Cancelled => serde_json::json!("cancelled"),
    };
    let receipt = observation_digest(
        &serde_json::json!({ "domain": "hepta.automation.drained-owner-observation.v1", "threadId": work.admission.thread_id, "clientId": observed.client_user_message_id, "payloadSha256": observed.payload_sha256, "outcome": outcome }),
    )?;
    store
        .ensure_admitted_taskflow_uncertainty(work, now_ms)
        .await
        .map_err(taskflow_error)?;
    let terminal = match observed.outcome {
        QueueHistoricalOutcome::Persisted { turn_id, terminal } => {
            if turn_id.is_empty()
                || work
                    .occurrence
                    .turn_id
                    .as_deref()
                    .is_some_and(|expected| expected != turn_id)
            {
                return Err(AgentdError::Protocol(
                    "historical automation observation changed persisted turn identity".to_string(),
                ));
            }
            // Indeterminate is recoverable by exact terminal evidence. The
            // existing owner only records a fresh turn on an Admitted row.
            if work.occurrence.state == AutomationOccurrenceState::Admitted {
                store
                    .record_occurrence_turn(
                        work.occurrence.task_id,
                        work.occurrence.occurrence,
                        &work.occurrence.client_user_message_id,
                        &turn_id,
                        &observed.payload_sha256,
                        now_ms,
                    )
                    .await?;
            }
            terminal.map(|status| match status {
                QueueHistoricalTerminal::Completed => AutomationOccurrenceTerminalState::Succeeded,
                QueueHistoricalTerminal::Failed => AutomationOccurrenceTerminalState::Failed,
                QueueHistoricalTerminal::Interrupted => {
                    AutomationOccurrenceTerminalState::Cancelled
                }
            })
        }
        QueueHistoricalOutcome::Cancelled if work.occurrence.turn_id.is_none() => {
            Some(AutomationOccurrenceTerminalState::Cancelled)
        }
        QueueHistoricalOutcome::Cancelled => None,
        QueueHistoricalOutcome::Pending {
            queued_submission_id,
        } => {
            if let Some(id) = queued_submission_id
                && work.occurrence.queued_submission_id.as_deref() != Some(id.as_str())
            {
                return Err(AgentdError::Protocol(
                    "historical automation observation changed queue identity".to_string(),
                ));
            }
            None
        }
        QueueHistoricalOutcome::Missing | QueueHistoricalOutcome::Unknown => None,
    };
    if let Some(terminal) = terminal {
        let canonical_receipt = store
            .reconcile_occurrence_taskflow_historical_terminal(
                work,
                terminal,
                &receipt,
                now_ms,
                RECOVERY_RUN_LEASE_MS,
            )
            .await
            .map_err(taskflow_error)?;
        store
            .complete_occurrence(
                work.occurrence.task_id,
                work.occurrence.occurrence,
                terminal,
                &canonical_receipt,
                now_ms,
            )
            .await?;
        Ok(())
    } else {
        store
            .mark_occurrence_indeterminate(
                work.occurrence.task_id,
                work.occurrence.occurrence,
                &receipt,
                now_ms,
            )
            .await?;
        Ok(())
    }
}

#[cfg(all(test, unix))]
#[path = "automation_drain_recovery_tests.rs"]
mod tests;
