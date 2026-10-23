//! Finite Notes readiness and the original run observation/cancellation seam.

use super::control::now_ms;
use super::control::require_run_reconciliation_ready;
use super::control::wire_cancellation_disposition;
use super::control::wire_run_receipt;
use super::*;
#[cfg(target_os = "linux")]
use crate::AgentdMethod;
use crate::AgentdPayload;
#[cfg(target_os = "linux")]
use crate::AgentdResponse;

impl AgentdState {
    pub(crate) fn objective_admission_ready(&self) -> Result<bool, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(runtime.lifecycle == AgentLifecycle::Running
            && (runtime.app_server_ready || runtime.notes_organ_ready)
            && runtime.critical_stores_ready
            && runtime.revocation_ready
            && runtime.required_ports_ready
            && runtime.admission_open
            && !runtime.fenced)
    }

    pub(super) fn run_cancellation_payload(
        &self,
        run_id: String,
        expected_revision: u64,
        reason: String,
    ) -> Result<AgentdPayload, AgentdError> {
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        require_run_reconciliation_ready(runtime.lifecycle, runtime.fenced)?;
        drop(runtime);
        let (disposition, receipt) = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .cancel_run(now_ms()?, &run_id, expected_revision, &reason)
            .map_err(run_error)?;
        Ok(AgentdPayload::RunCancellation(
            crate::AgentRunCancellation {
                disposition: wire_cancellation_disposition(disposition),
                receipt: wire_run_receipt(receipt),
            },
        ))
    }

    pub(super) fn run_status_payload(&self, run_id: String) -> Result<AgentdPayload, AgentdError> {
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        require_run_reconciliation_ready(runtime.lifecycle, runtime.fenced)?;
        drop(runtime);
        let run = self
            .runs
            .lock()
            .map_err(poisoned_state)?
            .run(&run_id)
            .map(wire_run_receipt);
        Ok(AgentdPayload::RunStatus { run })
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn check_notes_organ_authority(&self) -> Result<(), AgentdError> {
        let root = self.notes_organ_root.get().ok_or_else(|| {
            AgentdError::Invalid("Notes Organ has no original Root session".into())
        })?;
        let host = self.production_operations.get().ok_or_else(|| {
            AgentdError::Invalid("Notes Organ has no original production owner".into())
        })?;
        self.notes_objective
            .get()
            .ok_or_else(|| {
                AgentdError::Invalid("Notes Organ has no fixed Notes registration".into())
            })?
            .validate_host(host)?;
        let writer = host.writer();
        if writer.authority() != &root.authority()
            || writer.owner_agent_id() != &self.identity.agent_id
            || writer.checkpoint_fenced()
        {
            return Err(AgentdError::GenerationFenced(
                "Notes Organ original owner is fenced".into(),
            ));
        }
        root.verifier()
            .verify(writer.authority(), &self.identity.agent_id)
            .map_err(AgentdError::GenerationFenced)
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn mark_notes_organ_ready(&self) -> Result<(), AgentdError> {
        self.check_notes_organ_authority()?;
        self.refresh_generation()?;
        let mut runtime = self.runtime.lock().map_err(poisoned_state)?;
        if !runtime.critical_stores_ready || runtime.fenced {
            return Err(AgentdError::GenerationFenced(
                "Notes Organ prerequisites are unavailable".into(),
            ));
        }
        runtime.notes_organ_ready = true;
        runtime.required_ports_ready = true;
        runtime.admission_open = runtime.lifecycle == AgentLifecycle::Running;
        Ok(())
    }

    #[cfg(target_os = "linux")]
    pub(crate) async fn notes_response(
        &self,
        request_id: u64,
        spawn_generation: u64,
        method: AgentdMethod,
    ) -> Result<AgentdResponse, AgentdError> {
        if spawn_generation != self.identity.spawn_generation {
            return Err(AgentdError::GenerationFenced(
                "Notes Organ request belongs to another process generation".into(),
            ));
        }
        self.check_notes_organ_authority()?;
        self.refresh_generation()?;
        let (generation, lifecycle, ready, critical, revocation, ports, admission, fenced) = {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            (
                runtime.current_generation,
                runtime.lifecycle,
                runtime.notes_organ_ready,
                runtime.critical_stores_ready,
                runtime.revocation_ready,
                runtime.required_ports_ready,
                runtime.admission_open,
                runtime.fenced,
            )
        };
        let payload = match method {
            AgentdMethod::Capabilities => AgentdPayload::Capabilities(
                crate::AgentdCapabilitySet::new(vec![
                    crate::AgentdCapability::new(
                        "hepta.organ.notes",
                        /*major*/ 1,
                        /*minor*/ 0,
                    )
                    .map_err(AgentdError::Protocol)?,
                    crate::AgentdCapability::new(
                        "objective.start",
                        /*major*/ 1,
                        /*minor*/ 0,
                    )
                    .map_err(AgentdError::Protocol)?,
                    crate::AgentdCapability::new(
                        "objective.admission.read",
                        /*major*/ 1,
                        /*minor*/ 0,
                    )
                    .map_err(AgentdError::Protocol)?,
                ])
                .map_err(AgentdError::Protocol)?,
            ),
            AgentdMethod::Health => AgentdPayload::Health(crate::HealthSnapshot {
                promotion_ready: matches!(
                    lifecycle,
                    AgentLifecycle::Starting | AgentLifecycle::Running
                ) && ready
                    && critical
                    && revocation
                    && ports
                    && !fenced,
                ready: lifecycle == AgentLifecycle::Running
                    && ready
                    && critical
                    && revocation
                    && ports
                    && admission
                    && !fenced,
                fenced,
                lifecycle,
                process_id: std::process::id(),
                workspace: self.identity.workspace.clone(),
                home_root: self.identity.home_root.clone(),
                run_root: self.identity.run_root.clone(),
            }),
            AgentdMethod::Lifecycle => AgentdPayload::Lifecycle(crate::LifecycleSnapshot {
                lifecycle,
                app_server_ready: false,
                fenced,
            }),
            AgentdMethod::Readiness => AgentdPayload::Readiness(crate::ReadinessSnapshot {
                critical_stores_ready: critical,
                revocation_ready: revocation,
                required_ports_ready: ports,
                admission_open: admission,
            }),
            AgentdMethod::ObjectiveStart { request } => {
                let host = self.objective_runtime.get().ok_or_else(|| {
                    AgentdError::Protocol("Notes Objective owner is unavailable".into())
                })?;
                match host.submit_notes(self, request, generation).await? {
                    crate::objective_runtime::ObjectiveStartResult::Admitted(receipt) => {
                        AgentdPayload::ObjectiveRun(receipt)
                    }
                    crate::objective_runtime::ObjectiveStartResult::Conflict {
                        run_id,
                        conflict_digest,
                    } => AgentdPayload::ObjectiveConflict {
                        run_id,
                        conflict_digest,
                    },
                }
            }
            AgentdMethod::ObjectiveAdmission { query } => {
                let host = self.objective_runtime.get().ok_or_else(|| {
                    AgentdError::Protocol("Notes Objective owner is unavailable".into())
                })?;
                AgentdPayload::ObjectiveAdmission {
                    outcome: host.admission_history(self.identity(), query),
                }
            }
            AgentdMethod::RunCancel {
                run_id,
                expected_revision,
                reason,
            } => self.run_cancellation_payload(run_id, expected_revision, reason)?,
            AgentdMethod::RunStatus { run_id } => self.run_status_payload(run_id)?,
            _ => {
                return Err(AgentdError::Invalid(
                    "method is outside the finite Notes Organ profile".into(),
                ));
            }
        };
        self.check_notes_organ_authority()?;
        Ok(AgentdResponse {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            agent_id: self.identity.agent_id.clone(),
            spawn_generation: self.identity.spawn_generation,
            current_generation: generation,
            payload,
        })
    }
}
