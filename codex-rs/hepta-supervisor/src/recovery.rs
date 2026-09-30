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
use crate::control_intent;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::ProcessLeaseRemoval;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::lease::remove_lease;
use crate::lease::write_lease;
use crate::restart_lineage;
use crate::restart_lineage::RestartProcessWitness;
use crate::restart_lineage::RestartRecoveryRole;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::runtime::deadline;
use crate::runtime::driver_error;
use crate::runtime::is_live_lifecycle;

#[path = "adopted_release.rs"]
mod adopted_release;

#[path = "recovery_admission.rs"]
mod admission;

#[cfg(test)]
#[path = "recovery_admission_tests.rs"]
mod admission_tests;

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

        // Process ownership has priority over semantic hydration. A live main
        // or Matrix lease may represent a process that must be adopted and
        // contained even when catalog, restart-journal, or release-state reads
        // fail. Defer all fallible release/companion hydration until recover_slot
        // has attempted independent owner acquisition.
        if read_lease(record.layout.run_root())?.is_some()
            || read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
        {
            return Ok(());
        }
        self.hydrate_release_state(agent_id, slot, record)
    }

    fn hydrate_release_state(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        // A lease-bound adopted release may already be the healthy target of
        // an unfinished transition while the committed release state still
        // names its source. Preserve that exact admitted selection; only the
        // transition owner may publish its new current/previous pair.
        let active_release = if slot.runtime.is_some() {
            slot.active_release.clone()
        } else {
            match record.release_state.current.as_ref() {
                Some(release_id) => self.resolve_persisted_release(agent_id, release_id)?,
                None => None,
            }
        };
        let previous_release = match record.release_state.previous.as_ref() {
            Some(release_id) => self.resolve_persisted_release(agent_id, release_id)?,
            None => None,
        };
        slot.release_state_generation = record.release_state.generation;
        slot.active_release = active_release;
        slot.previous_release = previous_release;
        slot.last_command = slot
            .active_release
            .as_ref()
            .map(|release| release.command().clone());
        self.prepare_matrix_restart_recovery(agent_id, slot, record)
    }

    pub(crate) fn resolve_persisted_release(
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
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        if control_intent::cancel_restart_if_unresolved(record.layout.run_root(), agent_id)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            let lineage = restart_lineage::cancel(record.layout.run_root(), agent_id)
                .map_err(|error| SupervisorError::Invalid(error.to_string()));
            slot.restart_pending = false;
            slot.restart_not_before = None;
            return lineage;
        }
        let pending = crate::restart_budget::pending_restart(
            record.layout.run_root(),
            self.config.restart_max_attempts,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let Some(claim) = pending else {
            restart_lineage::cancel_if_budget_absent(record.layout.run_root(), agent_id)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.restart_pending = false;
            slot.restart_not_before = None;
            return Ok(());
        };

        slot.restart_attempt = claim.attempt;
        let current = slot
            .runtime
            .as_ref()
            .map(|runtime| {
                RestartProcessWitness::new(
                    runtime.spawn_generation,
                    runtime.identity.clone(),
                    runtime.release_id.clone(),
                )
            })
            .transpose()
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let lease_present = read_lease(record.layout.run_root())?.is_some();
        let role = restart_lineage::reconcile_pending(
            record.layout.run_root(),
            agent_id,
            claim.window_started_unix_ms,
            claim.attempt,
            current.as_ref(),
            lease_present,
        );
        let role = match role {
            Ok(role) => role,
            Err(error) => {
                // Keep the daemon alive to retain any exact adopted handle, but
                // make that handle non-serving and retry termination. The
                // unresolved lineage remains durable and blocks replacement.
                admission::reject_owned(agent_id, slot, now);
                slot.restart_pending = false;
                slot.restart_not_before = None;
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
                );
                return Err(SupervisorError::Invalid(error.to_string()));
            }
        };
        match role {
            RestartRecoveryRole::PredecessorOwned => {
                slot.restart_pending = true;
                slot.restart_not_before = Some(deadline(now, claim.backoff)?);
                // A crash may occur after publishing the budget and lineage,
                // before the original Drain/Stop was staged. The exact owned
                // predecessor must resume that control; health alone cannot
                // turn it into a replacement or leave it serving indefinitely.
                if slot.pending_control.is_none()
                    && slot.runtime.as_ref().is_some_and(|runtime| {
                        !runtime.fenced
                            && matches!(
                                runtime.phase,
                                RuntimePhase::AwaitingHealth { .. } | RuntimePhase::Running
                            )
                    })
                {
                    let control = if matches!(
                        record.lifecycle.lifecycle,
                        AgentLifecycle::Running | AgentLifecycle::Draining
                    ) {
                        self.drain_slot(agent_id, slot, now)
                    } else {
                        self.stop_runtime_slot(agent_id, slot, now)
                    };
                    if let Err(error) = control {
                        // A retryable signal retains its staged control and
                        // exact process. Do not abort recovery and drop the
                        // owner solely because that signal was unacknowledged.
                        slot.event(
                            record.lifecycle.generation,
                            SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
                        );
                    }
                }
            }
            RestartRecoveryRole::ReplacementPending => {
                slot.restart_pending = true;
                slot.restart_not_before = Some(deadline(now, claim.backoff)?);
            }
            RestartRecoveryRole::ReplacementStarted => {
                // The exact replacement is already owned. Wait for its health
                // transition; do not queue a second process and do not complete
                // the budget merely because a process exists.
                slot.restart_pending = false;
                slot.restart_not_before = None;
            }
            RestartRecoveryRole::Completed => {
                crate::restart_budget::complete_restart(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.restart_pending = false;
                slot.restart_not_before = None;
            }
            RestartRecoveryRole::Cancelled => {
                crate::restart_budget::cancel_restart(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.restart_pending = false;
                slot.restart_not_before = None;
            }
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
        if slot.has_recovery_denial() {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} requires durable recovery before starting a process"
            )));
        }
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
        let initialized = slot
            .runtime
            .as_ref()
            .and_then(|runtime| runtime.process.initialization_failure().map(str::to_owned));
        let launch = publication
            .and_then(|()| match initialized {
                Some(error) => Err(driver_error(
                    agent_id,
                    crate::ProcessDriverError::new(error),
                )),
                None => Ok(()),
            })
            .and_then(|()| {
                let Some(claim) = crate::restart_budget::pending_restart(
                    record.layout.run_root(),
                    self.config.restart_max_attempts,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                else {
                    return Ok(());
                };
                let runtime = slot.runtime.as_ref().ok_or_else(|| {
                    SupervisorError::Invalid("restart replacement owner is absent".to_string())
                })?;
                let replacement = RestartProcessWitness::new(
                    runtime.spawn_generation,
                    runtime.identity.clone(),
                    runtime.release_id.clone(),
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                restart_lineage::bind_replacement(
                    record.layout.run_root(),
                    agent_id,
                    claim.window_started_unix_ms,
                    claim.attempt,
                    replacement,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))
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
            let _ = restart_lineage::cancel(record.layout.run_root(), agent_id);
            let _ = crate::restart_budget::cancel_restart(record.layout.run_root());
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
        // Acquire the main owner first. Then attempt semantic hydration, but do
        // not propagate its failure before the independent Matrix acquisition.
        let main = self.recover_main_slot(agent_id, slot, record, now);
        if let Err(error) = &main {
            if !Self::recovery_control_fault_is_retryable(slot, error) {
                slot.recovery_blocker = Some(bounded_message(error.to_string()));
            }
        }
        let hydration = if slot.recovery_blocker.is_some() {
            Ok(())
        } else {
            self.record(agent_id)
                .and_then(|fresh| self.hydrate_release_state(agent_id, slot, &fresh))
        };
        if let Err(error) = &hydration {
            slot.recovery_blocker = Some(bounded_message(error.to_string()));
        }
        let companion = self.recover_matrix_companion(agent_id, slot, record, now);
        if let Err(error) = &companion {
            slot.recovery_blocker = Some(bounded_message(error.to_string()));
            slot.event(
                record.lifecycle.generation,
                SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
            );
        }
        if let Err(error) = &hydration {
            self.reject_hydration_after_ownership(agent_id, slot, now, error);
        } else {
            slot.matrix.apply_restart_recovery(now);
        }
        main.and(companion).and(hydration)
    }

    fn reject_hydration_after_ownership(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
        error: &SupervisorError,
    ) {
        if slot.runtime.as_ref().is_some_and(|runtime| !runtime.fenced) {
            admission::reject_owned(agent_id, slot, now);
        }
        if slot
            .matrix
            .runtime
            .as_ref()
            .is_some_and(|runtime| !runtime.fenced)
            && let Err(signal) = self.kill_matrix_now(agent_id, slot)
        {
            slot.event(
                0,
                SupervisorEventKind::DriverFault(bounded_message(signal.to_string())),
            );
        }
        slot.event(
            0,
            SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
        );
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
        // Assess the existing durable evidence without propagating a semantic
        // failure before independent process acquisition. No failed admission
        // can grant a signal: only Adoption::Adopted supplies that authority.
        let admission = admission::assess(agent_id, record, &lease, &self.config, now);
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
        let mut control_fault = None;
        match self
            .driver
            .adopt(&spec)
            .map_err(|error| driver_error(agent_id, error))?
        {
            Adoption::Adopted(process) => {
                // Retain first, even when the journal, lifecycle relationship,
                // deadline or post-acquisition driver setup was rejected.
                slot.runtime = Some(AgentRuntime {
                    process,
                    identity: lease.identity,
                    spawn_generation: lease.spawn_generation,
                    release_id: lease.release_id.clone(),
                    generation: record.lifecycle.generation,
                    phase: RuntimePhase::Stopping { deadline: now },
                    healthy: false,
                    fenced: true,
                });
                if slot.recovery_blocker.is_some() {
                    admission::reject_owned(agent_id, slot, now);
                    return Ok(());
                }
                let admitted = admission.and_then(|admitted| {
                    match slot.runtime.as_ref().and_then(|runtime| {
                        runtime.process.initialization_failure().map(str::to_owned)
                    }) {
                        Some(error) => Err(driver_error(
                            agent_id,
                            crate::ProcessDriverError::new(error),
                        )),
                        None => Ok(admitted),
                    }
                });
                let admitted = match admitted {
                    Ok(admitted) => admitted,
                    Err(error) => {
                        admission::reject_owned(agent_id, slot, now);
                        return Err(error);
                    }
                };
                if let Some(runtime) = slot.runtime.as_mut() {
                    runtime.phase = admitted.phase;
                    runtime.fenced = false;
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
                slot.pending_control = admitted.control;
                control_fault =
                    pending::apply_to_slot(agent_id, slot, now, self.config.stop_grace).err();
                // Metadata publication follows full transaction/intent
                // recovery and a fresh healthy tick, never bare adoption.
            }
            Adoption::Missing => {
                // An absent process does not make malformed control evidence
                // valid. Retain rejected evidence for explicit reconciliation.
                admission?;
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
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::OrphanMissing,
                );
            }
            Adoption::Rejected => {
                admission?;
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
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::OrphanRejected,
                );
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
