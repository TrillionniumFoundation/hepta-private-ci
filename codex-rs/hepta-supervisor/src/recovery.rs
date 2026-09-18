use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::AgentRelease;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::SpawnSpec;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::remove_lease;
use crate::lease::validate_lease;
use crate::lease::write_lease;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;
use crate::runtime::is_live_lifecycle;
use crate::restart_budget::clear_restart_budget;
use crate::restart_budget::read_restart_budget;
use crate::restart_budget::unix_millis_now;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn restore_release_state(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        slot.release_state_generation = record.release_state.generation;
        slot.active_release = record
            .release_state
            .current
            .as_ref()
            .map(|release_id| self.registry.resolve_release(agent_id, release_id))
            .transpose()?
            .map(AgentRelease::try_from)
            .transpose()?;
        slot.previous_release = record
            .release_state
            .previous
            .as_ref()
            .map(|release_id| self.registry.resolve_release(agent_id, release_id))
            .transpose()?
            .map(AgentRelease::try_from)
            .transpose()?;
        slot.last_command = slot
            .active_release
            .as_ref()
            .map(|release| release.command().clone());
        Ok(())
    }

    pub(crate) fn restore_restart_budget(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let Some(budget) = read_restart_budget(record.layout.run_root(), agent_id)? else {
            return Ok(());
        };
        let wall_now = unix_millis_now()?;
        let window_ms = u64::try_from(self.config.restart_window.as_millis()).unwrap_or(u64::MAX);
        let elapsed_ms = wall_now.saturating_sub(budget.window_started_unix_ms);
        if elapsed_ms >= window_ms {
            clear_restart_budget(record.layout.run_root())?;
            slot.restart_attempts = 0;
            slot.restart_window_started_at = None;
            slot.restart_not_before = None;
            slot.automatic_restart = false;
            return Ok(());
        }

        slot.restart_attempts = budget.attempts;
        slot.restart_window_started_at = now.checked_sub(Duration::from_millis(elapsed_ms));

        if budget.attempts >= self.config.max_restart_attempts {
            slot.restart_pending = false;
            slot.automatic_restart = false;
            slot.restart_not_before = None;
            slot.event(
                record.lifecycle.generation,
                SupervisorEventKind::RestartBudgetExhausted {
                    attempts: budget.attempts,
                },
            );
            return Ok(());
        }

        // An adopted live process keeps its current generation. The restored
        // attempt counter still fences the next crash inside this window.
        if slot.runtime.is_some() {
            return Ok(());
        }
        if !matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Stopped | AgentLifecycle::Failed
        ) {
            return Ok(());
        }

        let remaining_ms = budget.not_before_unix_ms.saturating_sub(wall_now);
        slot.restart_pending = true;
        slot.automatic_restart = true;
        slot.restart_not_before = Some(
            now.checked_add(Duration::from_millis(remaining_ms))
                .ok_or_else(|| SupervisorError::Invalid("restart deadline overflow".to_string()))?,
        );
        Ok(())
    }

    pub(crate) fn start_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        command: AgentCommand,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.start_release_slot(agent_id, slot, AgentRelease::unversioned(command)?, now)
    }

    pub(crate) fn start_release_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        release: AgentRelease,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let health_deadline = deadline(now, self.config.health_timeout)?;
        if slot.runtime.is_some() {
            return Err(SupervisorError::AlreadyActive(agent_id.clone()));
        }
        let record = self.record(agent_id)?;
        if read_lease(record.layout.run_root())?.is_some() {
            return Err(SupervisorError::UnresolvedLease(agent_id.clone()));
        }
        if !matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Stopped | AgentLifecycle::Failed
        ) {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot start from {:?}",
                record.lifecycle.lifecycle
            )));
        }
        let starting = self.registry.compare_and_transition(
            agent_id,
            record.lifecycle.generation,
            AgentLifecycle::Starting,
        )?;
        slot.event(
            starting.generation,
            SupervisorEventKind::Lifecycle(AgentLifecycle::Starting),
        );
        let spec = SpawnSpec {
            agent_id: agent_id.clone(),
            generation: starting.generation,
            fleet_root: self.registry.layout().fleet_root().as_path().to_path_buf(),
            workspace: record.manifest.workspace.as_path().to_path_buf(),
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            logs_root: record.layout.logs_root().to_path_buf(),
            command: release.command().clone(),
        };
        let mut spawned = match self.driver.spawn(&spec) {
            Ok(spawned) => spawned,
            Err(error) => {
                self.transition_without_runtime(
                    agent_id,
                    slot,
                    starting.generation,
                    AgentLifecycle::Failed,
                )?;
                return Err(driver_error(agent_id, error));
            }
        };
        let lease = ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: agent_id.clone(),
            spawn_generation: starting.generation,
            release_id: release.release_id().clone(),
            identity: spawned.identity.clone(),
        };
        if let Err(error) = write_lease(record.layout.run_root(), &lease) {
            let _ = spawned.process.kill();
            self.transition_without_runtime(
                agent_id,
                slot,
                starting.generation,
                AgentLifecycle::Failed,
            )?;
            return Err(error);
        }
        slot.last_command = Some(release.command().clone());
        slot.active_release = Some(release);
        slot.runtime = Some(AgentRuntime {
            process: spawned.process,
            identity: spawned.identity,
            spawn_generation: starting.generation,
            release_id: lease.release_id,
            generation: starting.generation,
            phase: RuntimePhase::AwaitingHealth {
                deadline: health_deadline,
            },
            healthy: false,
            fenced: false,
        });
        slot.event(starting.generation, SupervisorEventKind::Spawned);
        Ok(())
    }

    pub(crate) fn recover_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let Some(lease) = read_lease(record.layout.run_root())? else {
            if is_live_lifecycle(record.lifecycle.lifecycle) {
                let generation = self.transition_without_runtime(
                    agent_id,
                    slot,
                    record.lifecycle.generation,
                    AgentLifecycle::Failed,
                )?;
                slot.event(generation, SupervisorEventKind::OrphanMissing);
            }
            self.recover_matrix_companion(agent_id, slot, record, now)?;
            return Ok(());
        };
        validate_lease(
            &lease,
            agent_id,
            record.lifecycle.generation,
            record.lifecycle.lifecycle,
        )?;
        if lease.release_id.as_str() != "unversioned" {
            let needs_resolution = slot
                .active_release
                .as_ref()
                .is_none_or(|active| active.release_id() != &lease.release_id);
            if needs_resolution {
                let leased = AgentRelease::try_from(
                    self.registry.resolve_release(agent_id, &lease.release_id)?,
                )?;
                slot.previous_release = slot.active_release.take();
                slot.last_command = Some(leased.command().clone());
                slot.active_release = Some(leased);
            }
        }
        let spec = AdoptSpec {
            agent_id: agent_id.clone(),
            registry_generation: record.lifecycle.generation,
            spawn_generation: lease.spawn_generation,
            workspace: record.manifest.workspace.as_path().to_path_buf(),
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            identity: lease.identity.clone(),
        };
        match self
            .driver
            .adopt(&spec)
            .map_err(|error| driver_error(agent_id, error))?
        {
            Adoption::Adopted(mut process) => {
                let phase = match record.lifecycle.lifecycle {
                    AgentLifecycle::Starting => RuntimePhase::AwaitingHealth {
                        deadline: deadline(now, self.config.health_timeout)?,
                    },
                    AgentLifecycle::Running => RuntimePhase::Running,
                    AgentLifecycle::Draining => RuntimePhase::Draining {
                        deadline: deadline(now, self.config.drain_timeout)?,
                    },
                    AgentLifecycle::Failed => {
                        process
                            .request_stop()
                            .map_err(|error| driver_error(agent_id, error))?;
                        RuntimePhase::Stopping {
                            deadline: deadline(now, self.config.stop_grace)?,
                        }
                    }
                    AgentLifecycle::Stopped => {
                        process
                            .kill()
                            .map_err(|error| driver_error(agent_id, error))?;
                        RuntimePhase::Killing
                    }
                };
                slot.runtime = Some(AgentRuntime {
                    process,
                    identity: lease.identity,
                    spawn_generation: lease.spawn_generation,
                    release_id: lease.release_id,
                    generation: record.lifecycle.generation,
                    phase,
                    healthy: false,
                    fenced: false,
                });
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::OrphanAdopted,
                );
                if record.lifecycle.lifecycle == AgentLifecycle::Running {
                    // A daemon can die after committing the Running lifecycle but before
                    // appending the matching release-state revision. The lease and exact
                    // agentd handshake prove the live release; close that crash window now.
                    self.persist_release_state(agent_id, slot)?;
                }
            }
            Adoption::Missing => {
                remove_lease(record.layout.run_root(), &lease)?;
                let generation = if is_live_lifecycle(record.lifecycle.lifecycle) {
                    self.transition_without_runtime(
                        agent_id,
                        slot,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?
                } else {
                    record.lifecycle.generation
                };
                slot.event(generation, SupervisorEventKind::OrphanMissing);
            }
            Adoption::Rejected => {
                remove_lease(record.layout.run_root(), &lease)?;
                let generation = if is_live_lifecycle(record.lifecycle.lifecycle) {
                    self.transition_without_runtime(
                        agent_id,
                        slot,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?
                } else {
                    record.lifecycle.generation
                };
                slot.event(generation, SupervisorEventKind::OrphanRejected);
            }
        }
        self.recover_matrix_companion(agent_id, slot, record, now)?;
        Ok(())
    }
}
