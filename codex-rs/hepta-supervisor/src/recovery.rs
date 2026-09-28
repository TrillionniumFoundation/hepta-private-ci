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
use crate::control::pending;
use crate::control::pending::PendingControl;
use crate::control_intent;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::ProcessLeaseRemoval;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::lease::remove_lease;
use crate::lease::validate_lease;
use crate::lease::write_lease;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::runtime::deadline;
use crate::runtime::driver_error;
use crate::runtime::is_live_lifecycle;

#[path = "adopted_release.rs"]
mod adopted_release;

#[cfg(test)]
#[path = "recovery_control_tests.rs"]
mod control_tests;

#[cfg(test)]
#[path = "launch_failure_tests.rs"]
mod launch_tests;

#[cfg(test)]
#[path = "recovery_ownership_tests.rs"]
mod ownership_tests;

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
        // Storage/identity/clock faults here are fatal startup faults, not
        // recoverable process faults. Stage Matrix state before adoption.
        self.prepare_matrix_restart_recovery(agent_id, slot, record)
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
        // An unowned or still-terminating companion is not proof of absence.
        // Do not start another main generation over unresolved paired ownership.
        if slot.matrix.runtime.is_some()
            || read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
        {
            return Err(SupervisorError::UnresolvedLease(agent_id.clone()));
        }
        control_intent::reconcile_absent(
            record.layout.run_root(),
            agent_id,
            record.lifecycle.lifecycle,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if control_intent::has_unresolved(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} has an unresolved durable termination intent"
            )));
        }
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
        // Own the acquired child before any fallible publication or cleanup.
        // Selected release metadata changes only after publication succeeds.
        slot.runtime = Some(AgentRuntime {
            process: spawned.process,
            identity: spawned.identity,
            spawn_generation: starting.generation,
            release_id: lease.release_id.clone(),
            generation: starting.generation,
            phase: RuntimePhase::AwaitingHealth {
                deadline: health_deadline,
            },
            healthy: false,
            fenced: false,
        });
        slot.event(starting.generation, SupervisorEventKind::Spawned);
        let publication = write_lease(record.layout.run_root(), &lease);
        let publication_failed = publication.is_err();
        let initialized = slot.runtime.as_ref().and_then(|runtime| {
            runtime.process.initialization_failure().map(str::to_owned)
        });
        let launch = publication.and_then(|()| match initialized {
            Some(error) => Err(driver_error(agent_id, crate::ProcessDriverError::new(error))),
            None => Ok(()),
        });
        if let Err(error) = launch {
            slot.exit_lease_removal = Some(if publication_failed {
                ProcessLeaseRemoval::for_failed_publication(record.layout.run_root(), &lease)
            } else {
                ProcessLeaseRemoval::new(record.layout.run_root(), &lease)
            });
            slot.pending_control = None;
            slot.restart_pending = false;
            slot.restart_not_before = None;
            let termination = if let Some(runtime) = slot.runtime.as_mut() {
                runtime.healthy = false;
                runtime.fenced = true;
                runtime.phase = RuntimePhase::Stopping { deadline: now };
                let result = runtime.process.kill();
                if result.is_ok() {
                    runtime.phase = RuntimePhase::Killing;
                }
                result
            } else {
                unreachable!("freshly acquired child was installed above")
            };
            match termination {
                Ok(()) => slot.event(starting.generation, SupervisorEventKind::KillRequested),
                Err(fault) => slot.event(
                    starting.generation,
                    SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
                ),
            }
            match self.registry.compare_and_transition(
                agent_id,
                starting.generation,
                AgentLifecycle::Failed,
            ) {
                Ok(failed) => {
                    if let Some(runtime) = slot.runtime.as_mut() {
                        runtime.generation = failed.generation;
                    }
                    slot.event(
                        failed.generation,
                        SupervisorEventKind::Lifecycle(AgentLifecycle::Failed),
                    );
                }
                Err(fault) => slot.event(
                    starting.generation,
                    SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
                ),
            }
            // A failed kill or lifecycle CAS never drops the only handle. The
            // original publication error stays the operation's failure result.
            return Err(error);
        }
        slot.last_command = Some(release.command().clone());
        slot.active_release = Some(release);
        Ok(())
    }

    pub(crate) fn recover_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        slot.matrix.apply_restart_recovery(now);
        // Evaluate both owners before returning either error. A main release,
        // control-journal, driver or lifecycle fault cannot skip the companion.
        let main = self.recover_main_slot(agent_id, slot, record, now);
        let companion = self.recover_matrix_companion(agent_id, slot, record, now);
        if let Err(error) = &companion {
            slot.event(
                record.lifecycle.generation,
                SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
            );
        }
        main.and(companion)
    }

    fn recover_main_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let Some(lease) = read_lease(record.layout.run_root())? else {
            let terminal_lifecycle = if is_live_lifecycle(record.lifecycle.lifecycle) {
                let generation = self.transition_without_runtime(
                    agent_id,
                    slot,
                    record.lifecycle.generation,
                    AgentLifecycle::Failed,
                )?;
                slot.event(generation, SupervisorEventKind::OrphanMissing);
                AgentLifecycle::Failed
            } else {
                record.lifecycle.lifecycle
            };
            control_intent::reconcile_absent(
                record.layout.run_root(),
                agent_id,
                terminal_lifecycle,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            return Ok(());
        };
        validate_lease(
            &lease,
            agent_id,
            record.lifecycle.generation,
            record.lifecycle.lifecycle,
        )?;
        let durable_control = control_intent::recover_pending(
            record.layout.run_root(),
            agent_id,
            lease.spawn_generation,
            &lease.identity,
            now,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
        // Compute fallible deadlines before taking ownership of a live child.
        // Registry lifecycle records desired state, not an acknowledged signal.
        let (phase, lifecycle_control) = match record.lifecycle.lifecycle {
            AgentLifecycle::Starting => (
                RuntimePhase::AwaitingHealth {
                    deadline: deadline(now, self.config.health_timeout)?,
                },
                None,
            ),
            AgentLifecycle::Running => (RuntimePhase::Running, None),
            AgentLifecycle::Draining => (
                RuntimePhase::Running,
                Some(PendingControl::Drain {
                    spawn_generation: lease.spawn_generation,
                    deadline: deadline(now, self.config.drain_timeout)?,
                }),
            ),
            AgentLifecycle::Failed => (
                RuntimePhase::AwaitingHealth { deadline: now },
                Some(PendingControl::Stop {
                    spawn_generation: lease.spawn_generation,
                    deadline: deadline(now, self.config.stop_grace)?,
                }),
            ),
            AgentLifecycle::Stopped => (
                RuntimePhase::Stopping { deadline: now },
                Some(PendingControl::Kill {
                    spawn_generation: lease.spawn_generation,
                }),
            ),
        };
        let recovery_control = durable_control.or(lifecycle_control);
        let mut control_fault = None;
        match self
            .driver
            .adopt(&spec)
            .map_err(|error| driver_error(agent_id, error))?
        {
            Adoption::Adopted(process) => {
                // Own the exact child before release lookup or command conversion.
                // Either can fail, even after a successful process handshake.
                slot.runtime = Some(AgentRuntime {
                    process,
                    identity: lease.identity,
                    spawn_generation: lease.spawn_generation,
                    release_id: lease.release_id.clone(),
                    generation: record.lifecycle.generation,
                    phase,
                    healthy: false,
                    fenced: false,
                });
                if let Some(error) = slot.runtime.as_ref().and_then(|runtime| {
                    runtime.process.initialization_failure().map(str::to_owned)
                }) {
                    if let Some(runtime) = slot.runtime.as_mut() {
                        runtime.fenced = true;
                        runtime.healthy = false;
                        runtime.phase = RuntimePhase::Stopping { deadline: now };
                        if runtime.process.kill().is_ok() {
                            runtime.phase = RuntimePhase::Killing;
                            slot.event(record.lifecycle.generation, SupervisorEventKind::KillRequested);
                        }
                    }
                    return Err(driver_error(agent_id, crate::ProcessDriverError::new(error)));
                }
                if lease.release_id.as_str() != "unversioned" {
                    let needs_resolution = slot
                        .active_release
                        .as_ref()
                        .is_none_or(|active| active.release_id() != &lease.release_id);
                    if needs_resolution {
                        let resolved = self.registry.resolve_release(agent_id, &lease.release_id);
                        self.bind_adopted_release(agent_id, slot, record, resolved, now)?;
                    }
                }
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::OrphanAdopted,
                );
                // Install the exact adopted handle before any fallible control
                // call. Failed signals retain both ownership and a bounded retry.
                slot.pending_control = recovery_control;
                control_fault =
                    pending::apply_to_slot(agent_id, slot, now, self.config.stop_grace).err();
                if record.lifecycle.lifecycle == AgentLifecycle::Running {
                    // A daemon can die after committing the Running lifecycle but before
                    // appending the matching release-state revision. The lease and exact
                    // agentd handshake prove the live release; close that crash window now.
                    self.persist_release_state(agent_id, slot)?;
                }
            }
            Adoption::Missing => {
                remove_lease(record.layout.run_root(), &lease)?;
                let terminal_lifecycle = if is_live_lifecycle(record.lifecycle.lifecycle) {
                    self.transition_without_runtime(
                        agent_id,
                        slot,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?;
                    AgentLifecycle::Failed
                } else {
                    record.lifecycle.lifecycle
                };
                control_intent::reconcile_absent(
                    record.layout.run_root(),
                    agent_id,
                    terminal_lifecycle,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.event(record.lifecycle.generation, SupervisorEventKind::OrphanMissing);
            }
            Adoption::Rejected => {
                // Failed identity proof grants neither signal authority nor
                // evidence of absence. Keep the exact lease and any unresolved
                // control intent; Failed is a lifecycle fence, not an exit.
                if is_live_lifecycle(record.lifecycle.lifecycle) {
                    self.transition_without_runtime(
                        agent_id,
                        slot,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?;
                }
                slot.event(record.lifecycle.generation, SupervisorEventKind::OrphanRejected);
            }
        }
        if let Some(error) = control_fault {
            return Err(error);
        }
        Ok(())
    }
}

/// Observational readiness only. Neither an absent handle nor a rejected
/// handshake proves that an on-disk lease no longer represents a live process.
#[cfg(any(unix, test))]
pub(crate) fn process_ownership_ready(
    record: &AgentRecord,
    snapshot: Option<&crate::AgentSupervisorSnapshot>,
) -> Result<bool, SupervisorError> {
    let Some(snapshot) = snapshot else {
        return Ok(false);
    };
    Ok(!snapshot.runtime_fenced
        && (snapshot.active || read_lease(record.layout.run_root())?.is_none())
        && (snapshot.matrix.active
            || read_matrix_lease(record.layout.matrixd_process_lease())?.is_none()))
}
