use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_memory::H7SignedArtifactEnvelope;

use crate::AgentCommand;
use crate::AgentFault;
use crate::AgentRelease;
use crate::AgentSupervisorSnapshot;
use crate::ControlReleaseChange;
use crate::ControlReleaseChangePhase;
use crate::ControlRuntimePhase;
use crate::ManagedProcess;
use crate::MatrixSupervisorSnapshot;
use crate::ProcessDriver;
use crate::SupervisorConfig;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::signed_authority::H7H89ProductionGrant;
use crate::signed_authority::H7H89ProductionGrantVerifier;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::ProductionMutationReceipt;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

/// Lifecycle-only controller with one process handle and bounded buffers per agent.
pub struct Supervisor<D: ProcessDriver> {
    pub(crate) registry: FleetRegistry,
    pub(crate) driver: D,
    pub(crate) config: SupervisorConfig,
    pub(crate) slots: BTreeMap<AgentId, AgentSlot<D::Process>>,
    pub(crate) recovery_blocked: BTreeSet<AgentId>,
}

#[cfg(test)]
#[path = "supervisor_tests.rs"]
mod tests;

#[path = "signed_recovery.rs"]
mod signed_recovery;

impl<D: ProcessDriver> Supervisor<D> {
    pub fn recover(
        registry: FleetRegistry,
        driver: D,
        config: SupervisorConfig,
        now: Instant,
    ) -> Result<(Self, TickReport), SupervisorError> {
        config.validate()?;
        let snapshot = registry.load()?;
        let slots = snapshot
            .agents
            .keys()
            .cloned()
            .map(|agent_id| (agent_id, AgentSlot::new(&config)))
            .collect();
        let mut supervisor = Self {
            registry,
            driver,
            config,
            slots,
            recovery_blocked: BTreeSet::new(),
        };
        let mut report = TickReport::default();
        for (agent_id, record) in snapshot.agents {
            let result = supervisor.with_slot(&agent_id, |supervisor, slot| {
                supervisor.restore_release_state(&agent_id, slot, &record)?;
                // Always inspect the durable signed intent even when process
                // adoption/recovery failed. Otherwise a driver fault could
                // accidentally hide an externally-authorized ambiguous
                // mutation and leave ordinary lifecycle mutations enabled.
                let process_recovery = supervisor.recover_slot(&agent_id, slot, &record, now);
                let signed_recovery = supervisor.recover_signed_intent(&agent_id, slot, &record);
                match (process_recovery, signed_recovery) {
                    (_, Err(error @ SupervisorError::SignedIntentRecoveryRequired(_))) => {
                        Err(error)
                    }
                    (Err(error), _) => Err(error),
                    (_, Err(error)) => Err(error),
                    (Ok(()), Ok(())) => Ok(()),
                }
            });
            if let Err(error) = result {
                if matches!(&error, SupervisorError::SignedIntentRecoveryRequired(_)) {
                    // A plausible interrupted transition enters operator
                    // recovery mode. A journal whose target already became
                    // current but whose recorded source contradicts the
                    // durable release predecessor is not merely ambiguous:
                    // it cannot have been produced by the observed release
                    // lineage, so preserve the historical strict-recovery
                    // behavior and refuse to construct a supervisor.
                    let contradictory_lineage = supervisor
                        .slots
                        .get(&agent_id)
                        .and_then(|slot| slot.signed_intent.as_ref())
                        .is_some_and(|intent| {
                            record
                                .release_state
                                .current
                                .as_ref()
                                .is_some_and(|current| current.as_str() == intent.target_release)
                                && record
                                    .release_state
                                    .previous
                                    .as_ref()
                                    .is_some_and(|previous| {
                                        previous.as_str() != intent.source_release
                                    })
                        });
                    if contradictory_lineage {
                        return Err(error);
                    }
                    supervisor.recovery_blocked.insert(agent_id.clone());
                }
                supervisor.record_fault(&agent_id, &error, &mut report);
            }
        }
        Ok((supervisor, report))
    }

    pub fn snapshot(&self, agent_id: &AgentId) -> Option<AgentSupervisorSnapshot> {
        self.slots
            .get(agent_id)
            .map(|slot| AgentSupervisorSnapshot {
                active: slot.runtime.is_some(),
                healthy: slot
                    .runtime
                    .as_ref()
                    .is_some_and(|runtime| runtime.healthy && !runtime.fenced),
                runtime_generation: slot.runtime.as_ref().map(|runtime| runtime.generation),
                spawn_generation: slot
                    .runtime
                    .as_ref()
                    .map(|runtime| runtime.spawn_generation),
                process_system_id: slot
                    .runtime
                    .as_ref()
                    .map(|runtime| runtime.identity.system_id()),
                active_release: slot
                    .active_release
                    .as_ref()
                    .map(|release| release.identity().to_string()),
                previous_release: slot
                    .previous_release
                    .as_ref()
                    .map(|release| release.identity().to_string()),
                release_change_pending: slot.release_change.is_some(),
                matrix: MatrixSupervisorSnapshot {
                    configured: slot.matrix.configured,
                    active: slot.matrix.runtime.is_some(),
                    healthy: slot
                        .matrix
                        .runtime
                        .as_ref()
                        .is_some_and(|runtime| runtime.healthy && !runtime.fenced),
                    degraded: slot.matrix.degraded,
                    process_system_id: slot
                        .matrix
                        .runtime
                        .as_ref()
                        .map(|runtime| runtime.identity.system_id()),
                    attached_agent_generation: slot
                        .matrix
                        .runtime
                        .as_ref()
                        .map(|runtime| runtime.attached_agent_generation),
                    binding_revision: slot
                        .matrix
                        .runtime
                        .as_ref()
                        .map(|runtime| runtime.binding_revision),
                    restart_attempt: slot.matrix.restart_attempt,
                    last_error: slot.matrix.last_error.clone(),
                },
                events: slot.events.items.iter().cloned().collect(),
                logs: slot.logs.items.iter().cloned().collect(),
                control_revision: slot.control_revision,
                restart_pending: slot.restart_pending,
                release_state_generation: slot.release_state_generation,
                runtime_phase: slot.runtime.as_ref().map(|runtime| match runtime.phase {
                    crate::runtime::RuntimePhase::AwaitingHealth { .. } => {
                        ControlRuntimePhase::AwaitingHealth
                    }
                    crate::runtime::RuntimePhase::Running => ControlRuntimePhase::Running,
                    crate::runtime::RuntimePhase::Draining { .. } => ControlRuntimePhase::Draining,
                    crate::runtime::RuntimePhase::Stopping { .. } => ControlRuntimePhase::Stopping,
                    crate::runtime::RuntimePhase::Killing => ControlRuntimePhase::Killing,
                }),
                runtime_release: slot
                    .runtime
                    .as_ref()
                    .map(|runtime| runtime.release_id.to_string()),
                runtime_incarnation: slot
                    .runtime
                    .as_ref()
                    .map(|runtime| runtime.identity.incarnation().to_string()),
                runtime_fenced: slot.runtime.as_ref().is_some_and(|runtime| runtime.fenced),
                release_change: slot
                    .release_change
                    .as_ref()
                    .map(|change| ControlReleaseChange {
                        origin_release: change.origin.identity().to_string(),
                        target_release: change.target.identity().to_string(),
                        prior_previous_release: change
                            .prior_previous
                            .as_ref()
                            .map(|release| release.identity().to_string()),
                        phase: match change.phase {
                            crate::runtime::ReleaseChangePhase::WaitingForTargetExit => {
                                ControlReleaseChangePhase::WaitingForTargetExit
                            }
                            crate::runtime::ReleaseChangePhase::TargetStarting => {
                                ControlReleaseChangePhase::TargetStarting
                            }
                            crate::runtime::ReleaseChangePhase::AutomaticRollbackStarting => {
                                ControlReleaseChangePhase::AutomaticRollbackStarting
                            }
                        },
                        explicit_rollback: change.explicit_rollback,
                    }),
                has_last_command: slot.last_command.is_some(),
            })
    }

    pub(crate) fn next_control_revision(&self, agent_id: &AgentId) -> Result<u64, SupervisorError> {
        self.slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?
            .control_revision
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("control revision overflow".to_string()))
    }

    pub(crate) fn set_control_revision(
        &mut self,
        agent_id: &AgentId,
        revision: u64,
    ) -> Result<(), SupervisorError> {
        let slot = self
            .slots
            .get_mut(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        if revision != slot.control_revision.saturating_add(1) {
            return Err(SupervisorError::Invalid(
                "control revision must advance exactly once".to_string(),
            ));
        }
        slot.control_revision = revision;
        Ok(())
    }

    #[cfg(unix)]
    pub(crate) fn preflight_drain(&self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let runtime = slot
            .runtime
            .as_ref()
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        if runtime.generation != record.lifecycle.generation {
            return Err(SupervisorError::GenerationFence {
                agent_id: agent_id.clone(),
                runtime: runtime.generation,
                registry: record.lifecycle.generation,
            });
        }
        if !matches!(
            record.lifecycle.lifecycle,
            AgentLifecycle::Running | AgentLifecycle::Draining
        ) {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot drain from {:?}",
                record.lifecycle.lifecycle
            )));
        }
        Ok(())
    }

    #[cfg(unix)]
    pub(crate) fn preflight_start(&self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        if slot.runtime.is_some() {
            return Err(SupervisorError::AlreadyActive(agent_id.clone()));
        }
        if crate::lease::read_lease(record.layout.run_root())?.is_some() {
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
        Ok(())
    }

    #[cfg(unix)]
    pub(crate) fn preflight_stop_or_kill(&self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let runtime = slot
            .runtime
            .as_ref()
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        if runtime.generation != record.lifecycle.generation {
            return Err(SupervisorError::GenerationFence {
                agent_id: agent_id.clone(),
                runtime: runtime.generation,
                registry: record.lifecycle.generation,
            });
        }
        Ok(())
    }

    #[cfg(unix)]
    pub(crate) fn preflight_restart(&self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        if slot.release_change.is_some() || slot.restart_pending {
            return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
        }
        if slot.active_release.is_none() && slot.last_command.is_none() {
            return Err(SupervisorError::NoPreviousCommand(agent_id.clone()));
        }
        match slot.runtime.as_ref() {
            Some(runtime) if runtime.generation != record.lifecycle.generation => {
                Err(SupervisorError::GenerationFence {
                    agent_id: agent_id.clone(),
                    runtime: runtime.generation,
                    registry: record.lifecycle.generation,
                })
            }
            Some(_) => Ok(()),
            None => {
                if crate::lease::read_lease(record.layout.run_root())?.is_some() {
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
                Ok(())
            }
        }
    }

    pub(crate) fn preflight_upgrade(
        &self,
        agent_id: &AgentId,
        target: &AgentRelease,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        if slot.release_change.is_some() || slot.restart_pending {
            return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
        }
        let current = slot.active_release.as_ref().ok_or_else(|| {
            SupervisorError::Invalid(format!(
                "agent {agent_id} has no explicit active release identity"
            ))
        })?;
        if current.identity() == target.identity() || current.command() == target.command() {
            return Err(SupervisorError::TargetReleaseUnchanged(agent_id.clone()));
        }
        if record.lifecycle.lifecycle != AgentLifecycle::Running {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot change release from {:?}",
                record.lifecycle.lifecycle
            )));
        }
        let runtime = slot
            .runtime
            .as_ref()
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        if runtime.generation != record.lifecycle.generation {
            return Err(SupervisorError::GenerationFence {
                agent_id: agent_id.clone(),
                runtime: runtime.generation,
                registry: record.lifecycle.generation,
            });
        }
        Ok(())
    }

    #[cfg(unix)]
    pub(crate) fn preflight_rollback(&self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let target = slot
            .previous_release
            .as_ref()
            .ok_or_else(|| SupervisorError::NoPreviousRelease(agent_id.clone()))?;
        self.preflight_upgrade(agent_id, target)
    }

    pub fn agent_ids(&self) -> Vec<AgentId> {
        self.slots.keys().cloned().collect()
    }

    pub fn start(
        &mut self,
        agent_id: &AgentId,
        command: AgentCommand,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.start_slot(agent_id, slot, command, now)
        })
    }

    pub fn start_release(
        &mut self,
        agent_id: &AgentId,
        release: AgentRelease,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.start_release_slot(agent_id, slot, release, now)
        })
    }

    pub fn drain(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.drain_slot(agent_id, slot, now)
        })
    }

    pub fn stop(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.stop_slot(agent_id, slot, now)
        })
    }

    pub fn kill(&mut self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.kill_slot(agent_id, slot)
        })
    }

    pub fn restart(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.restart_slot(agent_id, slot, now)
        })
    }

    pub fn upgrade(
        &mut self,
        agent_id: &AgentId,
        target: AgentRelease,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.upgrade_slot(
                agent_id, slot, target, now, /*explicit_rollback*/ false,
            )
        })
    }

    pub fn rollback(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            let target = slot
                .previous_release
                .clone()
                .ok_or_else(|| SupervisorError::NoPreviousRelease(agent_id.clone()))?;
            supervisor.upgrade_slot(agent_id, slot, target, now, /*explicit_rollback*/ true)
        })
    }

    /// Admit one externally signed H7/OPE operation into the real lifecycle
    /// supervisor. The H7 envelope remains a qualification artifact; the
    /// independent production grant is the only object that carries
    /// production authority. This method queues the existing drain/start
    /// state machine and records a fsynced intent before touching the child.
    #[expect(
        clippy::too_many_arguments,
        reason = "grant admission keeps verifier, epochs and clocks explicit"
    )]
    pub fn apply_production_grant(
        &mut self,
        agent_id: &AgentId,
        grant: &H7H89ProductionGrant,
        h7_envelope: &H7SignedArtifactEnvelope,
        verifier: &H7H89ProductionGrantVerifier,
        expected_authority_epoch: u64,
        now_unix_seconds: u64,
        now: Instant,
    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        self.ensure_mutations_unfrozen()?;
        self.with_slot(agent_id, |supervisor, slot| {
            let record = supervisor.record(agent_id)?;
            let current = slot.active_release.as_ref().ok_or_else(|| {
                SupervisorError::Invalid(format!(
                    "agent {agent_id} has no explicit active release identity"
                ))
            })?;
            let target_id = ReleaseId::parse(grant.target_release.clone())?;
            let target =
                AgentRelease::try_from(supervisor.registry.resolve_release(agent_id, &target_id)?)?;
            if grant.transition == H7H89ProductionTransition::Rollback {
                let previous = slot
                    .previous_release
                    .as_ref()
                    .ok_or_else(|| SupervisorError::NoPreviousRelease(agent_id.clone()))?;
                if previous.identity() != target.identity() {
                    return Err(SupervisorError::Invalid(format!(
                        "signed rollback target {} is not the recorded previous release {}",
                        target.identity(),
                        previous.identity()
                    )));
                }
            }
            verifier
                .verify(
                    grant,
                    h7_envelope,
                    agent_id,
                    current.identity(),
                    target.identity(),
                    slot.control_revision,
                    record.lifecycle.generation,
                    expected_authority_epoch,
                    now_unix_seconds,
                )
                .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;
            supervisor.preflight_upgrade(agent_id, &target)?;
            if slot
                .signed_intent
                .as_ref()
                .is_some_and(|intent| intent.status.is_unresolved())
            {
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
            let next_control_revision = supervisor.next_control_revision(agent_id)?;
            let intent = SignedSupervisorIntent::new(
                grant.digest().clone(),
                agent_id.to_string(),
                grant.transition,
                current.identity().to_string(),
                target.identity().to_string(),
                slot.control_revision,
                record.lifecycle.generation,
                expected_authority_epoch,
                SignedIntentStatus::Prepared,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &intent)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            // From this line onward a durable external-authority mutation has
            // started. Even if later queueing fails, the intent remains the
            // recovery witness and callers must treat the outcome as unknown.
            slot.signed_intent = Some(intent.clone());
            supervisor.set_control_revision(agent_id, next_control_revision)?;
            let explicit_rollback = grant.transition == H7H89ProductionTransition::Rollback;
            if let Err(error) =
                supervisor.upgrade_slot(agent_id, slot, target, now, explicit_rollback)
            {
                let recovery = intent
                    .with_status(SignedIntentStatus::RecoveryRequired)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                let _ = write_intent(record.layout.run_root(), &recovery);
                slot.signed_intent = Some(recovery);
                return Err(error);
            }
            let queued = intent
                .with_status(SignedIntentStatus::Queued)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &queued)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(queued);
            Ok(ProductionMutationReceipt::queued(
                grant,
                next_control_revision,
            ))
        })
    }

    pub(crate) fn commit_signed_intent_if_target(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let Some(intent) = slot.signed_intent.clone() else {
            return Ok(());
        };
        if !matches!(
            intent.status,
            SignedIntentStatus::Prepared | SignedIntentStatus::Queued
        ) {
            return Ok(());
        }
        let Some(active) = slot.active_release.as_ref() else {
            return Ok(());
        };
        if active.identity() != intent.target_release {
            return Ok(());
        }
        let committed = intent
            .with_status(SignedIntentStatus::Committed)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let record = self.record(agent_id)?;
        write_intent(record.layout.run_root(), &committed)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.signed_intent = Some(committed);
        Ok(())
    }

    fn recover_signed_intent(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let intent = match read_intent(record.layout.run_root()) {
            Ok(intent) => intent,
            Err(_) => {
                // A corrupt/truncated authority journal is itself unresolved
                // authority state. Do not downgrade it to an ordinary I/O or
                // serialization fault that would leave mutations enabled.
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
        };
        let Some(intent) = intent else {
            return Ok(());
        };
        if intent.agent_id != agent_id.to_string() {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        slot.signed_intent = Some(intent.clone());
        if intent.status.is_terminal() {
            return Ok(());
        }
        // A restart has no durable proof that an apparently matching target
        // was produced by this exact signed mutation. In particular, the
        // one-file intent does not carry an independently committed source /
        // target release-state revision, control-revision successor,
        // lifecycle-generation transition, or continuity of the daemon's
        // authority epoch. Treating `Running + target` as Committed would
        // therefore let an unrelated/manual upgrade close an old grant.
        // Every non-terminal intent remains fail-closed until an explicit
        // recovery ceremony binds the durable intent digest and current state.
        //
        // Fence and kill any adopted child before surfacing the recovery
        // requirement; normal ticking may only reap this exact child.
        if let Some(runtime) = slot.runtime.as_mut() {
            let _ = runtime.process.kill();
            runtime.fenced = true;
            runtime.phase = RuntimePhase::Killing;
        }
        Err(SupervisorError::SignedIntentRecoveryRequired(
            agent_id.clone(),
        ))
    }

    pub fn tick(&mut self, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        let agent_ids: Vec<_> = self.slots.keys().cloned().collect();
        for agent_id in agent_ids {
            let result = self.with_slot(&agent_id, |supervisor, slot| {
                supervisor.tick_slot(&agent_id, slot, now)
            });
            if let Err(error) = result {
                self.record_fault(&agent_id, &error, &mut report);
            }
        }
        report
    }

    fn with_slot<R>(
        &mut self,
        agent_id: &AgentId,
        operation: impl FnOnce(&mut Self, &mut AgentSlot<D::Process>) -> Result<R, SupervisorError>,
    ) -> Result<R, SupervisorError> {
        let mut slot = self
            .slots
            .remove(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let result = operation(self, &mut slot);
        self.slots.insert(agent_id.clone(), slot);
        result
    }

    pub(crate) fn transition_without_runtime(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        expected: u64,
        lifecycle: AgentLifecycle,
    ) -> Result<u64, SupervisorError> {
        let next = self
            .registry
            .compare_and_transition(agent_id, expected, lifecycle)?;
        slot.event(next.generation, SupervisorEventKind::Lifecycle(lifecycle));
        Ok(next.generation)
    }

    pub(crate) fn record(&self, agent_id: &AgentId) -> Result<AgentRecord, SupervisorError> {
        self.registry
            .load()?
            .agent(agent_id)
            .cloned()
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))
    }

    fn record_fault(
        &mut self,
        agent_id: &AgentId,
        error: &SupervisorError,
        report: &mut TickReport,
    ) {
        let message = bounded_message(error.to_string());
        if let Some(slot) = self.slots.get_mut(agent_id) {
            let generation = slot
                .runtime
                .as_ref()
                .map(|runtime| runtime.generation)
                .unwrap_or(0);
            slot.event(
                generation,
                SupervisorEventKind::DriverFault(message.clone()),
            );
        }
        report.faults.push(AgentFault {
            agent_id: agent_id.clone(),
            message,
        });
    }
}