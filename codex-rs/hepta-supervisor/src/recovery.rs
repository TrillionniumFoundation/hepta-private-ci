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
        let durable = crate::restart_journal::read_main_restart_budget(record.layout.run_root())?;
        if let Some(state) = &durable {
            slot.restart_attempt = state.attempts;
            if let Some(binding) = &state.release_binding {
                if binding.agent_id != *agent_id {
                    return Err(SupervisorError::CorruptLease(
                        "restart witness belongs to another Agent".to_string(),
                    ));
                }
                if state.pending && !state.operator_stopped {
                    if slot
                        .active_release
                        .as_ref()
                        .is_some_and(|release| release.release_id() != &binding.release_id)
                        || record
                            .release_state
                            .current
                            .as_ref()
                            .is_some_and(|release| release != &binding.release_id)
                    {
                        return Err(SupervisorError::CorruptLease(
                            "pending restart release conflicts with the recovered owner"
                                .to_string(),
                        ));
                    }
                    if slot.active_release.is_none() {
                        // The first failed child's lease may already be finalized.
                        // Restore only the original, still-admitted retry identity;
                        // never guess from configuration or publish it as selected.
                        slot.active_release =
                            self.resolve_persisted_release(agent_id, &binding.release_id)?;
                        slot.last_command = slot
                            .active_release
                            .as_ref()
                            .map(|release| release.command().clone());
                        if slot.active_release.is_none() {
                            return Err(SupervisorError::CorruptLease(
                                "pending restart release is no longer admitted".to_string(),
                            ));
                        }
                    }
                }
            }
        }
        let pending = crate::restart_budget::pending_restart(
            record.layout.run_root(),
            self.config.restart_max_attempts,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if let Some(claim) = pending {
            slot.restart_attempt = claim.attempt;
            slot.restart_not_before = Some(deadline(now, claim.backoff)?);
            // Pending means the replacement has not crossed its durable
            // pre-spawn consumption boundary. An adopted process is therefore
            // the predecessor and must finish stopping before replacement.
            slot.restart_pending = slot.runtime.is_none()
                || durable
                    .as_ref()
                    .is_some_and(|state| state.pending_requires_spawn);
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
        if !slot.restart_pending && slot.release_change.is_none() {
            crate::restart_budget::resume_restart(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
        let spawned = match self.driver.spawn(&spec) {
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
        let lease_result = write_lease(record.layout.run_root(), &lease);
        slot.last_command = Some(release.command().clone());
        slot.active_release = Some(release);
        let runtime = slot.runtime.insert(AgentRuntime {
            process: spawned.process,
            identity: spawned.identity,
            spawn_generation: starting.generation,
            release_id: lease.release_id,
            generation: starting.generation,
            phase: RuntimePhase::AwaitingHealth {
                deadline: health_deadline,
            },
            lease_publication_uncertain: lease_result.is_err(),
            healthy: false,
            fenced: false,
        });
        if let Err(error) = lease_result {
            // Retain the exact handle before either the signal or lifecycle
            // write can fail. A failed lease commit must not orphan a live child.
            runtime.fenced = true;
            runtime.phase = RuntimePhase::Stopping { deadline: now };
            if runtime.process.kill().is_ok() {
                runtime.phase = RuntimePhase::Killing;
            }
            self.transition_without_runtime(
                agent_id,
                slot,
                starting.generation,
                AgentLifecycle::Failed,
            )?;
            return Err(error);
        }
        slot.event(starting.generation, SupervisorEventKind::Spawned);
        Ok(())
    }

    pub(crate) fn recover_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<bool, SupervisorError> {
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
            return Ok(false);
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
        let mut confirmed_missing = false;
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
                                    let kill_requested = process.kill().is_ok();
                                    slot.runtime = Some(AgentRuntime {
                                        process,
                                        identity: lease.identity.clone(),
                                        spawn_generation: lease.spawn_generation,
                                        release_id: lease.release_id.clone(),
                                        generation: runtime_generation,
                                        // Failed termination must remain retryable; it is
                                        // not a successfully issued Killing transition.
                                        phase: if kill_requested {
                                            RuntimePhase::Killing
                                        } else {
                                            RuntimePhase::Stopping { deadline: now }
                                        },
                                        lease_publication_uncertain: false,
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
                    AgentLifecycle::Failed => RuntimePhase::Stopping {
                        deadline: deadline(now, self.config.stop_grace)?,
                    },
                    AgentLifecycle::Stopped => RuntimePhase::Stopping { deadline: now },
                };
                let runtime = slot.runtime.insert(AgentRuntime {
                    process,
                    identity: lease.identity,
                    spawn_generation: lease.spawn_generation,
                    release_id: lease.release_id,
                    generation: record.lifecycle.generation,
                    phase,
                    lease_publication_uncertain: false,
                    healthy: false,
                    fenced: false,
                });
                // Retain the exact handle before a fallible signal. A signal
                // error is observable, not permission to discard the child.
                if record.lifecycle.lifecycle == AgentLifecycle::Failed {
                    runtime
                        .process
                        .request_stop()
                        .map_err(|error| driver_error(agent_id, error))?;
                } else if record.lifecycle.lifecycle == AgentLifecycle::Stopped {
                    runtime
                        .process
                        .kill()
                        .map_err(|error| driver_error(agent_id, error))?;
                    runtime.phase = RuntimePhase::Killing;
                }
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
                // The first child may die before readiness publishes a selected
                // release. Recover its exact admitted release from the validated
                // lease, not from current configuration or a guessed command.
                if slot.active_release.is_none()
                    && record.release_state.current.is_none()
                    && record.lifecycle.lifecycle == AgentLifecycle::Starting
                    && lease.release_id.as_str() != "unversioned"
                {
                    slot.active_release =
                        self.resolve_persisted_release(agent_id, &lease.release_id)?;
                    slot.last_command = slot
                        .active_release
                        .as_ref()
                        .map(|release| release.command().clone());
                }
                confirmed_missing = true;
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
        Ok(confirmed_missing)
    }
}
