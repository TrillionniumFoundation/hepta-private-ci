//! A new companion retry and its eventual command launch each re-admit the
//! release. Rejection preserves existing process owners and charged budgets;
//! observing or cleaning an existing lifetime does not use this admission.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::AgentCommand;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::restart_journal::unix_millis_now;
use crate::restart_policy::RestartSchedule;
use crate::restart_policy::schedule_restart;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;

impl<D: ProcessDriver> Supervisor<D> {
    pub(super) fn admit_matrix_replacement(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
    ) -> Option<AgentCommand> {
        let admitted = slot
            .active_release
            .as_ref()
            .ok_or_else(|| {
                SupervisorError::Invalid(
                    "Matrix replacement requires an active release".to_string(),
                )
            })
            .and_then(|cached| {
                if let Some(runtime) = slot.runtime.as_ref()
                    && matches!(runtime.phase, RuntimePhase::Running)
                {
                    // Serving metadata observed before a driver poll is not a
                    // fresh Fleet owner fence for a subsequent companion effect.
                    // This read does not make admission atomic with later CAS.
                    let record = self.record(agent_id)?;
                    if runtime.fenced
                        || runtime.release_id != *cached.release_id()
                        || record.lifecycle.generation != runtime.generation
                        || record.lifecycle.lifecycle != AgentLifecycle::Running
                    {
                        return Err(SupervisorError::Invalid(
                            "Matrix replacement main owner is no longer current and serving"
                                .to_string(),
                        ));
                    }
                }
                // Nonrunning/ownerless constructor accounting retains its existing
                // contract. Actual launch separately requires a healthy Running main.
                self.refresh_release_for_transition(agent_id, cached)
                    .and_then(|fresh| {
                        if fresh.release_id() != cached.release_id() {
                            return Err(SupervisorError::Invalid(
                                "Matrix replacement release differs from the active bundle"
                                    .to_string(),
                            ));
                        }
                        fresh.matrixd_command().cloned().ok_or_else(|| {
                            SupervisorError::Invalid(
                                "admitted release has no Matrix companion command".to_string(),
                            )
                        })
                    })
            });
        match admitted {
            Ok(command) => Some(command),
            Err(error) => {
                let message =
                    bounded_message(format!("Matrix release admission rejected: {error}"));
                slot.matrix.degraded = true;
                slot.matrix.last_error = Some(message.clone());
                slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
                None
            }
        }
    }

    /// Publish exactly one new retry charge after fresh release admission.
    /// Rejection preserves the uncharged failure marker and all prior claims.
    pub(super) fn schedule_matrix_retry(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
        now: Instant,
    ) {
        if self
            .admit_matrix_replacement(agent_id, slot, generation)
            .is_none()
        {
            return;
        }
        // From this point a clock/publication failure uses the existing
        // exhausted fail-closed state, rather than attempting a second charge.
        slot.matrix.retry_admission = None;
        let wall_now = match unix_millis_now() {
            Ok(wall_now) => wall_now,
            Err(error) => {
                let message = bounded_message(format!(
                    "Matrix restart budget could not read wall clock: {error}"
                ));
                slot.matrix.retry_at = None;
                slot.matrix.restart_exhausted = true;
                slot.matrix.last_error = Some(message.clone());
                slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
                return;
            }
        };
        match schedule_restart(
            &mut slot.matrix.restart_attempt,
            &mut slot.matrix.restart_window_started_at,
            now,
        ) {
            RestartSchedule::Retry { attempt, retry_at } => {
                if attempt == 1 || slot.matrix.restart_window_started_unix_millis.is_none() {
                    slot.matrix.restart_window_started_unix_millis = Some(wall_now);
                }
                slot.matrix.retry_at = Some(retry_at);
                slot.matrix.restart_exhausted = false;
            }
            RestartSchedule::Exhausted { attempts } => {
                slot.matrix.retry_at = None;
                slot.matrix.restart_exhausted = true;
                slot.event(
                    generation,
                    SupervisorEventKind::MatrixRestartBudgetExhausted { attempts },
                );
            }
        }
        if let Err(error) = self.persist_restart_budget(agent_id, slot) {
            let message = bounded_message(format!(
                "Matrix restart budget could not be persisted: {error}"
            ));
            slot.matrix.retry_at = None;
            slot.matrix.restart_exhausted = true;
            slot.matrix.last_error = Some(message.clone());
            slot.event(generation, SupervisorEventKind::MatrixDegraded(message));
        }
    }
}
