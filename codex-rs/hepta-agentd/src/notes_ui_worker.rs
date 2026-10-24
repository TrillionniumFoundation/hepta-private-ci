//! One async finite adapter under the original required runtime task. A view
//! is disposable; every retained status comes from the original sender owner.

use super::*;
use crate::AgentCancellationDisposition;
use crate::AgentRunPhase;
use crate::AgentRunReceipt;
use crate::AgentdNotesObservationRetention;
use crate::AgentdNotesSubmissionState;
use crate::notes_ui_queue::NotesUiQueue;
use crate::notes_ui_wire::*;
use super::NotesUiCallPhase as CallPhase;

impl AgentdNotesLiteralAdapter {
    pub(super) async fn run_ui(&mut self, queue: &NotesUiQueue) -> Result<(), AgentdError> {
        loop {
            let Some(entry) = queue.take(Instant::now()).map_err(|_| invalid("Notes UI queue failed"))? else {
                queue.wake.notified().await;
                continue;
            };
            self.check_available()?;
            let mut view = queue.current(&entry.command).map_err(|_| invalid("Notes UI view missing"))?;
            let submitting = matches!(entry.command, ObjectiveCommand::Submit { .. });
            let cancelling = matches!(entry.command, ObjectiveCommand::Cancel { .. });
            let mut phase = CallPhase::ReadOnly;
            let outcome = tokio::time::timeout_at(entry.end.into(), self.handle_ui(entry.command, entry.end, &mut view, &mut phase)).await;
            if !matches!(outcome, Ok(Ok(()))) {
                // A cancelled started checkpoint/effect retains the original
                // fence. An old positive observation is never erased by timeout.
                let issue = if submitting && !view.publication_retained {
                    match phase {
                        CallPhase::ReadOnly => {
                            if !view.request_retained { view.stage = ObjectiveStage::Unavailable; }
                            ObjectiveHostIssue::Unavailable
                        }
                        CallPhase::Preparing => {
                            view.stage = ObjectiveStage::SubmitUnknown;
                            ObjectiveHostIssue::PersistenceUnknown
                        }
                        CallPhase::Sending => {
                            view.stage = ObjectiveStage::SubmitUnknown;
                            ObjectiveHostIssue::TransportUnknown
                        }
                    }
                } else { ObjectiveHostIssue::TransportUnknown };
                if cancelling { view.cancellation = ObjectiveCancellation::Unknown; }
                view.issue = Some(issue);
            }
            self.check_available()?;
            queue.update(view).map_err(|_| invalid("Notes UI view update failed"))?;
        }
    }

    async fn handle_ui(&mut self, command: ObjectiveCommand, end: Instant, view: &mut ObjectiveObservation, phase: &mut CallPhase) -> Result<(), AgentdError> {
        if Instant::now() >= end { return Err(invalid("Notes UI action deadline elapsed before start")); }
        view.issue = None;
        view.observed_unix_ms = ObjectiveObservation::new(None, ObjectiveStage::Unavailable).observed_unix_ms;
        match command {
            ObjectiveCommand::Availability {} => {
                self.require_objective_ready().await?;
                let retained = self.retained_intents().await?;
                let navigation = ObjectiveRetainedIntents { client_intent_ids: retained.client_intent_ids, complete: retained.complete };
                navigation.validate().map_err(|_| invalid("original Notes navigation projection refused"))?;
                view.stage = ObjectiveStage::Ready;
                view.retained_intents = Some(navigation);
            }
            ObjectiveCommand::Submit { intent } => {
                if intent.text.trim().is_empty() || intent.text.len() > 4096 {
                    view.issue = Some(ObjectiveHostIssue::InvalidIntent);
                    return Ok(());
                }
                let preparation_end = end.min(Instant::now() + self.deadline);
                let prepared = tokio::time::timeout_at(preparation_end.into(), self.prepare_until(
                    &intent.client_intent_id, &intent.text, preparation_end, phase,
                )).await.map_err(|_| invalid("Notes UI preparation deadline elapsed"))??;
                match prepared {
                    AgentdNotesPreparedObjective::Retained(_) => {
                        *view = self.retained_view(&intent.client_intent_id).await?;
                    }
                    prepared @ AgentdNotesPreparedObjective::Ready { .. } => {
                        // Preparation already obtained the original request ACK.
                        view.request_retained = true;
                        view.stage = ObjectiveStage::Retained;
                        let remaining = end.checked_duration_since(Instant::now())
                            .filter(|remaining| !remaining.is_zero()).ok_or_else(|| invalid("Notes UI submission deadline elapsed"))?;
                        *phase = CallPhase::Sending;
                        let observed = prepared.submit_once(remaining).await?;
                        let acknowledged = observed.retention == AgentdNotesObservationRetention::Acknowledged;
                        view.stage = match observed.state {
                            AgentdNotesSubmissionState::NotSent { .. } => ObjectiveStage::NotSent,
                            AgentdNotesSubmissionState::SubmitUnknown { .. } => ObjectiveStage::SubmitUnknown,
                            AgentdNotesSubmissionState::RefusedBeforePublication { .. } => ObjectiveStage::Refused,
                            AgentdNotesSubmissionState::Admitted { receipt, .. } => {
                                view.publication_retained = acknowledged;
                                if matches!(receipt.disposition.as_str(), "explicit_abstain" | "canonical_abstained") { ObjectiveStage::Abstained }
                                else { ObjectiveStage::Admitted }
                            }
                            AgentdNotesSubmissionState::Conflict { .. } => {
                                view.publication_retained = acknowledged;
                                ObjectiveStage::Conflict
                            }
                        };
                        if !acknowledged {
                            view.stage = ObjectiveStage::SubmitUnknown;
                            view.issue = Some(ObjectiveHostIssue::PersistenceUnknown);
                        }
                    }
                }
                self.refresh_ui_run(&intent.client_intent_id, view).await?;
            }
            ObjectiveCommand::Status { client_intent_id } => {
                *view = self.retained_view(&client_intent_id).await?;
                self.refresh_ui_run(&client_intent_id, view).await?;
            }
            ObjectiveCommand::Cancel { client_intent_id } => {
                *view = self.retained_view(&client_intent_id).await?;
                // A conflicting request must never cancel somebody else's run.
                // Lost admission evidence is reconciled before requesting cancel.
                if !view.publication_retained || view.stage != ObjectiveStage::Admitted {
                    view.cancellation = ObjectiveCancellation::Unknown;
                    view.issue = Some(ObjectiveHostIssue::OwnerRefused);
                    return Ok(());
                }
                view.cancellation = ObjectiveCancellation::Unknown;
                let cancelled = self.cancel(&client_intent_id).await?;
                view.cancellation = match cancelled.disposition {
                    AgentCancellationDisposition::CancelledBeforeDispatch => ObjectiveCancellation::CancelledBeforeDispatch,
                    AgentCancellationDisposition::CancellingAfterDispatch => ObjectiveCancellation::CancellingAfterDispatch,
                    AgentCancellationDisposition::AlreadyTerminal => ObjectiveCancellation::AlreadyTerminal,
                };
                view.run = Some(run_view(cancelled.receipt));
            }
        }
        Ok(())
    }

    async fn refresh_ui_run(&mut self, client_intent_id: &str, view: &mut ObjectiveObservation) -> Result<(), AgentdError> {
        if view.publication_retained && view.stage == ObjectiveStage::Admitted {
            view.run = self.observe_run(client_intent_id).await?.map(run_view);
        }
        Ok(())
    }
}

fn run_view(receipt: AgentRunReceipt) -> ObjectiveRunObservation {
    ObjectiveRunObservation {
        revision: receipt.revision, terminal_observed: receipt.terminal_observed,
        phase: match receipt.phase {
            AgentRunPhase::Admitted => ObjectiveRunPhase::Admitted,
            AgentRunPhase::ContextAttached => ObjectiveRunPhase::ContextAttached,
            AgentRunPhase::Dispatched => ObjectiveRunPhase::Dispatched,
            AgentRunPhase::Cancelling => ObjectiveRunPhase::Cancelling,
            AgentRunPhase::Cancelled => ObjectiveRunPhase::Cancelled,
            AgentRunPhase::Succeeded => ObjectiveRunPhase::Succeeded,
            AgentRunPhase::Failed => ObjectiveRunPhase::Failed,
            AgentRunPhase::Indeterminate => ObjectiveRunPhase::Indeterminate,
        },
    }
}
