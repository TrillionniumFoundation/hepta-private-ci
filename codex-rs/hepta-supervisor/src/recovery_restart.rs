//! Restart admission from an exact observed absence, never a missing file alone.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;

use crate::AdoptSpec;
use crate::Adoption;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::write_lease;
use crate::restart_budget;
use crate::restart_budget::RestartBudgetError;
use crate::restart_lineage;
use crate::restart_lineage::RestartProcessWitness;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;

impl<D: ProcessDriver> Supervisor<D> {
    pub(super) fn recover_unleased_restart_process(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        claim: &restart_budget::RestartClaim,
        now: Instant,
    ) -> Result<Option<RestartProcessWitness>, SupervisorError> {
        let Some(witness) = restart_lineage::process_to_reconcile(
            record.layout.owner_run_root(),
            agent_id,
            claim.window_started_unix_ms,
            claim.attempt,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        else {
            return Ok(None);
        };
        let spec = AdoptSpec {
            agent_id: agent_id.clone(),
            registry_generation: record.lifecycle.generation,
            spawn_generation: witness.spawn_generation,
            workspace: record.manifest.workspace.as_path().to_path_buf(),
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            identity: witness.identity.clone(),
        };
        match self
            .driver
            .adopt(&spec)
            .map_err(|error| driver_error(agent_id, error))?
        {
            Adoption::Missing => {
                restart_lineage::mark_process_absent(
                    record.layout.owner_run_root(),
                    agent_id,
                    &witness,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                return Ok(Some(witness));
            }
            Adoption::Rejected => {
                return Err(SupervisorError::Invalid(
                    "restart witness process absence is unproven".into(),
                ));
            }
            Adoption::Adopted(process) => {
                // Acquire before attempting any durable repair. An absent lease
                // cannot cause the exact live owner to be dropped or served.
                slot.runtime = Some(AgentRuntime {
                    process,
                    identity: witness.identity.clone(),
                    spawn_generation: witness.spawn_generation,
                    release_id: witness.release_id.clone(),
                    generation: record.lifecycle.generation,
                    phase: RuntimePhase::Stopping { deadline: now },
                    healthy: false,
                    fenced: true,
                });
                slot.recovery_blocker =
                    Some("live restart process was found without its exact lease".into());
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::DriverFault(
                        "live restart process was found without its exact lease".into(),
                    ),
                );
                write_lease(
                    record.layout.owner_run_root(),
                    &ProcessLease {
                        schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                        agent_id: agent_id.clone(),
                        spawn_generation: witness.spawn_generation,
                        release_id: witness.release_id,
                        identity: witness.identity,
                    },
                )?;
            }
        }
        Ok(None)
    }

    // This transition is reached only after exact native Missing and
    // admission of the original lease and durable termination evidence.
    pub(super) fn recover_missing_main_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        lease: &ProcessLease,
        admitted: &super::admission::MainRecoveryAdmission,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let witness = RestartProcessWitness::new(
            lease.spawn_generation,
            lease.identity.clone(),
            lease.release_id.clone(),
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let mut claim = crate::restart_budget::pending_restart(
            record.layout.owner_run_root(),
            self.config.restart_max_attempts,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if record.lifecycle.lifecycle == AgentLifecycle::Running
            && admitted.control.is_none()
            && restart_lineage::completed_process_matches(
                record.layout.owner_run_root(),
                agent_id,
                &witness,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            // Close an already durable healthy completion only; this
            // is not a fabricated success for the newly missing task.
            crate::restart_budget::complete_restart(record.layout.owner_run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            claim = None;
        }
        if let Some(claim) = claim {
            restart_lineage::begin_absence_if_unrecorded(
                record.layout.owner_run_root(),
                agent_id,
                claim.window_started_unix_ms,
                claim.attempt,
                &witness,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            restart_lineage::mark_process_absent(
                record.layout.owner_run_root(),
                agent_id,
                &witness,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        } else if record.lifecycle.lifecycle == AgentLifecycle::Running
            && admitted.control.is_none()
        {
            // An exact Missing from the native driver, rather than a
            // deleted lease or a rejected handshake, authorizes this
            // normal already-Running workload restart under its budget.
            self.queue_absent_restart(agent_id, slot, record, witness, now)?;
        }
        Ok(())
    }

    pub(crate) fn queue_absent_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        predecessor: RestartProcessWitness,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let claim = restart_budget::claim_restart(
            record.layout.owner_run_root(),
            self.config.restart_max_attempts,
            self.config.restart_window,
            self.config.restart_backoff_base,
        );
        self.queue_absent_restart_claim(agent_id, slot, record, predecessor, claim, now)
    }

    fn queue_absent_restart_claim(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        predecessor: RestartProcessWitness,
        claim: Result<restart_budget::RestartClaim, RestartBudgetError>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let claim = match claim {
            Ok(claim) => claim,
            Err(RestartBudgetError::Exhausted) => {
                slot.restart_pending = false;
                slot.restart_not_before = None;
                slot.restart_attempt = self.config.restart_max_attempts;
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::AutomaticRestartBudgetExhausted {
                        attempts: self.config.restart_max_attempts,
                    },
                );
                return Ok(());
            }
            Err(error) => return Err(SupervisorError::Invalid(error.to_string())),
        };
        restart_lineage::begin_absent(
            record.layout.owner_run_root(),
            agent_id,
            claim.window_started_unix_ms,
            claim.attempt,
            predecessor,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.restart_attempt = claim.attempt;
        slot.restart_not_before = Some(deadline(now, claim.backoff)?);
        slot.restart_pending = true;
        slot.event(
            record.lifecycle.generation,
            SupervisorEventKind::AutomaticRestartQueued {
                attempt: claim.attempt,
            },
        );
        Ok(())
    }

    pub(crate) fn retry_absent_replacement(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let failed = restart_lineage::exited_restart(record.layout.owner_run_root(), agent_id)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .ok_or_else(|| {
                SupervisorError::Invalid("replacement absence witness is missing".into())
            })?;
        if record.lifecycle.lifecycle == AgentLifecycle::Stopped {
            restart_budget::cancel_restart(record.layout.owner_run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            restart_lineage::cancel(record.layout.owner_run_root(), agent_id)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.restart_pending = false;
            slot.restart_not_before = None;
            return Ok(());
        }
        // An exited replacement has not discharged this chain's health
        // obligation. Atomically charge the next original-window attempt;
        // owner restart and elapsed wall time cannot buy a fresh budget.
        let claim = restart_budget::continue_failed_restart(
            record.layout.owner_run_root(),
            self.config.restart_max_attempts,
            self.config.restart_backoff_base,
            failed.window_started_unix_ms,
            failed.attempt,
        );
        self.queue_absent_restart_claim(agent_id, slot, record, failed.replacement, claim, now)
    }
}
