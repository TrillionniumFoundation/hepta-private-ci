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
        let Some(pending) = crate::restart_budget::pending_restart_snapshot(
            record.layout.run_root(),
            self.config.restart_max_attempts,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        else {
            slot.restart_pending = false;
            slot.restart_not_before = None;
            return Ok(());
        };
        slot.restart_attempt = pending.claim.attempt;
        slot.restart_not_before = Some(deadline(now, pending.claim.backoff)?);

        // A historical pending record without process lineage is not converted
        // into authority to stop, replace or complete a process. It remains
        // durable for operator Stop/Kill cancellation and cannot silently run.
        let Some(target_release) = pending.state.target_release.as_ref() else {
            slot.restart_pending = false;
            return Ok(());
        };

        let Some(runtime) = slot.runtime.as_ref() else {
            let predecessor_closed = pending.state.predecessor.is_none()
                || pending.state.predecessor_exit_observed_unix_ms.is_some();
            slot.restart_pending = predecessor_closed && pending.state.replacement.is_none();
            return Ok(());
        };

        let is_predecessor =
            pending.state.predecessor.as_ref().is_some_and(|process| {
                process.matches(runtime.spawn_generation, &runtime.identity)
            });
        if is_predecessor {
            if pending.state.predecessor_exit_observed_unix_ms.is_some() {
                return Err(SupervisorError::Invalid(
                    "restart predecessor is live after its durable exit observation".to_string(),
                ));
            }
            slot.restart_pending = true;
            return Ok(());
        }

        if let Some(replacement) = pending.state.replacement.as_ref() {
            if !replacement.matches(runtime.spawn_generation, &runtime.identity)
                || runtime.release_id != *target_release
            {
                return Err(SupervisorError::Invalid(
                    "adopted process differs from the durable restart replacement".to_string(),
                ));
            }
            slot.restart_pending = false;
            return Ok(());
        }

        if pending.state.predecessor_exit_observed_unix_ms.is_none() {
            slot.restart_pending = false;
            return Ok(());
        }
        crate::restart_budget::bind_restart_replacement(
            record.layout.run_root(),
            &runtime.release_id,
            runtime.spawn_generation,
            &runtime.identity,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.restart_pending = false;
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
        control_intent::reconcile_absent(
            record.layout.run_root(),
            agent_id,
            record.lifecycle.lifecycle,
        )
        .map_err(SupervisorError::from)?;
        if control_intent::has_unresolved(record.layout.run_root())
            .map_err(SupervisorError::from)?
        {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} has an unresolved durable termination intent"
            )));
        }
        crate::restart_budget::verify_restart_replacement_admission(
            record.layout.run_root(),
            release.release_id(),
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
        if let Err(error) = write_lease(record.layout.run_root(), &lease) {
            slot.exit_lease_removal = Some(ProcessLeaseRemoval::for_failed_publication(
                record.layout.run_root(),
                &lease,
            ));
            self.contain_failed_launch(agent_id, slot, starting.generation, now);
            // A failed kill or lifecycle CAS never drops the only handle. The
            // original publication error stays the operation's failure result.
            return Err(error);
        }
        if let Err(error) = crate::restart_budget::bind_restart_replacement(
            record.layout.run_root(),
            release.release_id(),
            starting.generation,
            &lease.identity,
        ) {
            self.contain_failed_launch(agent_id, slot, starting.generation, now);
            return Err(SupervisorError::Invalid(error.to_string()));
        }
        slot.last_command = Some(release.command().clone());
        slot.active_release = Some(release);
        Ok(())
    }

    fn contain_failed_launch(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        starting_generation: u64,
        now: Instant,
    ) {
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
            unreachable!("freshly acquired child must remain installed");
        };
        match termination {
            Ok(()) => slot.event(starting_generation, SupervisorEventKind::KillRequested),
            Err(fault) => slot.event(
                starting_generation,
                SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
            ),
        }
        match self.registry.compare_and_transition(
            agent_id,
            starting_generation,
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
                starting_generation,
                SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
            ),
        }
    }

    pub(crate) fn recover_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        slot.matrix.apply_restart_recovery(now);
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
            .map_err(SupervisorError::from)?;
            self.recover_matrix_companion(agent_id, slot, record, now)?;
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
        .map_err(SupervisorError::from)?;
        let restart_control = crate::restart_budget::recover_predecessor_control(
            record.layout.run_root(),
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
        let recovery_control = durable_control.or(restart_control).or(lifecycle_control);
        let mut control_fault = None;
        let mut process_fault = None;
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
                if lease.release_id.as_str() != "unversioned" {
                    let needs_resolution = slot
                        .active_release
                        .as_ref()
                        .is_none_or(|active| active.release_id() != &lease.release_id);
                    if needs_resolution {
                        let resolved = self.registry.resolve_release(agent_id, &lease.release_id);
                        if let Err(error) =
                            self.bind_adopted_release(agent_id, slot, record, resolved, now)
                        {
                            process_fault = Some(error);
                        }
                    }
                }
                if process_fault.is_none() {
                    slot.event(
                        record.lifecycle.generation,
                        SupervisorEventKind::OrphanAdopted,
                    );
                    // Install the exact adopted handle before any fallible control
                    // call. Failed signals retain both ownership and a bounded retry.
                    slot.pending_control = recovery_control;
                    control_fault =
                        pending::apply_to_slot(agent_id, slot, now, self.config.stop_grace).err();
                    if record.lifecycle.lifecycle == AgentLifecycle::Running
                        && let Err(error) = self.persist_release_state(agent_id, slot)
                    {
                        process_fault = Some(error);
                    }
                }
            }
            Adoption::Missing => {
                crate::restart_budget::observe_restart_process_exit(
                    record.layout.run_root(),
                    &lease.release_id,
                    lease.spawn_generation,
                    &lease.identity,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
                control_intent::reconcile_absent(
                    record.layout.run_root(),
                    agent_id,
                    self.record(agent_id)?.lifecycle.lifecycle,
                )
                .map_err(SupervisorError::from)?;
                slot.event(generation, SupervisorEventKind::OrphanMissing);
            }
            Adoption::Rejected => {
                // Rejection proves only that this daemon could not establish the
                // exact process identity. It does not prove process absence and
                // therefore cannot authorize lease deletion, terminal control
                // reconciliation, replacement launch or a signal to the PID.
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
        // A main-process signal, release or identity failure must not skip
        // companion adoption. Each owned process remains independently recoverable.
        self.recover_matrix_companion(agent_id, slot, record, now)?;
        if let Some(error) = control_fault {
            return Err(error);
        }
        if let Some(error) = process_fault {
            return Err(error);
        }
        Ok(())
    }
}
