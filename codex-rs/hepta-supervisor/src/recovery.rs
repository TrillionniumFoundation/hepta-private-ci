use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistryError;

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

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn restore_release_state(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        slot.release_state_generation = record.release_state.generation;
        slot.active_release = match record.release_state.current.as_ref() {
            Some(release_id) => self.resolve_persisted_release(agent_id, release_id)?,
            None => None,
        };
        slot.previous_release = match record.release_state.previous.as_ref() {
            Some(release_id) => self.resolve_persisted_release(agent_id, release_id)?,
            None => None,
        };
        slot.last_command = slot
            .active_release
            .as_ref()
            .map(|release| release.command().clone());
        Ok(())
    }

    fn resolve_persisted_release(
        &self,
        agent_id: &AgentId,
        release_id: &codex_hepta_fleet::ReleaseId,
    ) -> Result<Option<AgentRelease>, SupervisorError> {
        match self.registry.resolve_release(agent_id, release_id) {
            Ok(release) => AgentRelease::try_from(release).map(Some),
            Err(
                FleetRegistryError::ReleaseRevoked { .. }
                | FleetRegistryError::ReleaseNotAllowed { .. },
            ) => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    pub(crate) fn recover_restart_budget(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let pending = crate::restart_budget::pending_restart(
            record.layout.run_root(),
            self.config.restart_max_attempts,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if let Some(claim) = pending {
            slot.restart_attempt = claim.attempt;
            slot.restart_not_before = Some(deadline(now, claim.backoff)?);
            // An adopted replacement is already satisfying this durable
            // restart. Only a missing runtime needs the replacement queued.
            slot.restart_pending = slot.runtime.is_none();
        }
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
                if lease.release_id.as_str() != "unversioned" {
                    let needs_resolution = slot
                        .active_release
                        .as_ref()
                        .is_none_or(|active| active.release_id() != &lease.release_id);
                    if needs_resolution {
                        let leased =
                            match self.registry.resolve_release(agent_id, &lease.release_id) {
                                Ok(release) => AgentRelease::try_from(release)?,
                                Err(error) => {
                                    // Exact process identity has already been proven by adoption.
                                    // If the active release is no longer currently admitted (or
                                    // its admission state cannot be verified), fail closed by
                                    // fencing and killing the child before returning the fault.
                                    // Keep the runtime handle until exit is observed so recovery
                                    // never leaves a live unmanaged process behind.
                                    let runtime_generation = record.lifecycle.generation;
                                    let _ = process.kill();
                                    slot.runtime = Some(AgentRuntime {
                                        process,
                                        identity: lease.identity.clone(),
                                        spawn_generation: lease.spawn_generation,
                                        release_id: lease.release_id.clone(),
                                        generation: runtime_generation,
                                        phase: RuntimePhase::Killing,
                                        healthy: false,
                                        fenced: true,
                                    });
                                    if is_live_lifecycle(record.lifecycle.lifecycle) {
                                        let failed = self.transition_without_runtime(
                                            agent_id,
                                            slot,
                                            runtime_generation,
                                            AgentLifecycle::Failed,
                                        )?;
                                        if let Some(runtime) = slot.runtime.as_mut() {
                                            runtime.generation = failed;
                                        }
                                    }
                                    return Err(error.into());
                                }
                            };
                        slot.previous_release = slot.active_release.take();
                        slot.last_command = Some(leased.command().clone());
                        slot.active_release = Some(leased);
                    }
                }
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
