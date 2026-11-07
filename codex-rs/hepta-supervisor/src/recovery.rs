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
        if self.registry.is_release_intent_reconciliation()
            || slot.intent_publication_fenced
            || slot
                .signed_intent
                .as_ref()
                .is_some_and(super::signed_intent::SignedSupervisorIntent::requires_recovery)
        {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
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
        let (release, release_admission) = self.admit_release_for_process(agent_id, &release)?;
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
        if let Err(error) = crate::signed_intent_policy::revalidate_process_admission(
            release_admission.as_ref(),
            slot.signed_intent.as_ref(),
            &record,
            self.registry.is_release_qualification(),
        ) {
            self.transition_without_runtime(
                agent_id,
                slot,
                starting.generation,
                AgentLifecycle::Failed,
            )?;
            return Err(error);
        }
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
            return Ok(());
        };
        validate_lease(
            &lease,
            agent_id,
            record.lifecycle.generation,
            record.lifecycle.lifecycle,
        )?;
        // Disposition of an Unknown effect retires its already-observed
        // lifecycle generations. A late lease cannot revive that worker even
        // after the disposition itself or a later grant has been recovered.
        let (persisted_intent, intent_fault) =
            match crate::signed_intent::read_intent(record.layout.run_root()) {
                Ok(intent) => (intent, None),
                Err(error) => (None, Some(SupervisorError::Invalid(error.to_string()))),
            };
        // Invalid authorization bytes cannot skip discovery of the independent
        // process identity. Such an adoption is containment only.
        let retired = intent_fault.is_some()
            || persisted_intent.as_ref().is_some_and(|intent| {
                // A new supervisor epoch never resumes a retained PQ admission.
                // Adoption is only for identity containment; the original terminal
                // transaction/CAS witness is reconciled later by the intent owner.
                (intent.pq_authority.is_some()
                    && matches!(
                        intent.status,
                        crate::SignedIntentStatus::Prepared | crate::SignedIntentStatus::Queued
                    ))
                    || intent.unknown_effects.iter().any(|unknown| {
                        lease.spawn_generation <= unknown.decision.expected_lifecycle_generation
                    })
            });
        // Validate timing before adoption yields ownership of a live handle.
        let recovery_deadline = if retired {
            now
        } else {
            match record.lifecycle.lifecycle {
                AgentLifecycle::Starting => deadline(now, self.config.health_timeout)?,
                AgentLifecycle::Draining => deadline(now, self.config.drain_timeout)?,
                AgentLifecycle::Failed => deadline(now, self.config.stop_grace)?,
                AgentLifecycle::Running | AgentLifecycle::Stopped => now,
            }
        };
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
        // A successful admission lock spans the actual adoption. If admission
        // fails, adoption is used only to prove identity before fencing/killing
        // that existing child; it never turns into a permitted running process.
        let needs_current_release = !retired
            && (!self.registry.is_release_qualification()
                || (lease.release_id.as_str() != "unversioned"
                    && slot
                        .active_release
                        .as_ref()
                        .is_none_or(|active| active.release_id() != &lease.release_id)));
        let mut release_admission = needs_current_release.then(|| {
            self.registry
                .admit_release(agent_id, &lease.release_id)
                .map_err(SupervisorError::from)
                .and_then(|admission| {
                    let release = AgentRelease::try_from(admission.release().clone())?;
                    crate::signed_intent_policy::revalidate_process_admission(
                        Some(&admission),
                        persisted_intent.as_ref(),
                        record,
                        self.registry.is_release_qualification(),
                    )?;
                    Ok((release, admission))
                })
        });
        match self
            .driver
            .adopt(&spec)
            .map_err(|error| driver_error(agent_id, error))?
        {
            Adoption::Adopted(mut process) => {
                let _release_admission = if let Some(admission) = release_admission.take() {
                    let (leased, guard) = match admission {
                        Ok(current) => current,
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
                                release_id: lease.release_id,
                                generation: runtime_generation,
                                // Failed termination must remain retryable; it is
                                // not a successfully issued Killing transition.
                                phase: if kill_requested {
                                    RuntimePhase::Killing
                                } else {
                                    RuntimePhase::Stopping { deadline: now }
                                },
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
                            return Err(error);
                        }
                    };
                    if slot
                        .active_release
                        .as_ref()
                        .is_none_or(|active| active.release_id() != leased.release_id())
                    {
                        slot.previous_release = slot.active_release.take();
                    }
                    slot.last_command = Some(leased.command().clone());
                    slot.active_release = Some(leased);
                    Some(guard)
                } else {
                    None
                };
                let mut cleanup_error = if retired { process.kill().err() } else { None };
                let phase = if retired {
                    if cleanup_error.is_some() {
                        RuntimePhase::Stopping { deadline: now }
                    } else {
                        RuntimePhase::Killing
                    }
                } else {
                    match record.lifecycle.lifecycle {
                        AgentLifecycle::Starting => RuntimePhase::AwaitingHealth {
                            deadline: recovery_deadline,
                        },
                        AgentLifecycle::Running => RuntimePhase::Running,
                        AgentLifecycle::Draining => RuntimePhase::Draining {
                            deadline: recovery_deadline,
                        },
                        AgentLifecycle::Failed => {
                            cleanup_error = process.request_stop().err();
                            RuntimePhase::Stopping {
                                deadline: if cleanup_error.is_some() {
                                    now
                                } else {
                                    recovery_deadline
                                },
                            }
                        }
                        AgentLifecycle::Stopped => {
                            cleanup_error = process.kill().err();
                            if cleanup_error.is_some() {
                                RuntimePhase::Stopping { deadline: now }
                            } else {
                                RuntimePhase::Killing
                            }
                        }
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
                    fenced: retired || cleanup_error.is_some(),
                });
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::OrphanAdopted,
                );
                if let Some(error) = cleanup_error {
                    // Adoption proved a real live child. Retain its fenced
                    // handle even when termination failed, so ticks can retry.
                    return Err(driver_error(agent_id, error));
                }
                if !retired && record.lifecycle.lifecycle == AgentLifecycle::Running {
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
                // A rejected identity is not proof of process absence. Keep
                // the lease so ordinary start and Unknown disposal stay fenced.
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
        if let Some(error) = intent_fault {
            return Err(error);
        }
        Ok(())
    }
}
