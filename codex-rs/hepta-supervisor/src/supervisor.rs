use std::collections::BTreeMap;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
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
use crate::release_transaction::DurableReleaseTransaction;
use crate::release_transaction::ReleaseTransactionKind;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::signed_authority::H7H89ProductionGrant;
use crate::signed_authority::H7H89ProductionGrantVerifier;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::ProductionMutationReceipt;
use crate::signed_authority::ProductionMutationState;
use crate::signed_authority::ProductionRecoveryDecision;
use crate::signed_authority::ProductionRecoveryOutcome;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

/// Lifecycle-only controller with one process handle and bounded buffers per agent.
pub struct Supervisor<D: ProcessDriver> {
    pub(crate) registry: FleetRegistry,
    pub(crate) driver: D,
    pub(crate) config: SupervisorConfig,
    slots: BTreeMap<AgentId, AgentSlot<D::Process>>,
}

#[cfg(test)]
#[path = "supervisor_tests.rs"]
mod tests;

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
        };
        let mut report = TickReport::default();
        for (agent_id, record) in snapshot.agents {
            let result = supervisor.with_slot(&agent_id, |supervisor, slot| {
                // Durable control state is safety-critical and must always be
                // hydrated even when exact process adoption/revalidation
                // reports a per-Agent fault. Otherwise an adoption error could
                // hide a recovery-required signed intent or restart/release
                // fence and incorrectly make the daemon appear ready.
                supervisor.restore_release_state(&agent_id, slot, &record)?;
                let (confirmed_missing, process_fault) =
                    match supervisor.recover_slot(&agent_id, slot, &record, now) {
                        Ok(missing) => (missing, None),
                        Err(error) => (false, Some(error)),
                    };
                supervisor.recover_restart_budget(&agent_id, slot, now)?;
                supervisor.restore_matrix_restart_budget(&agent_id, slot, &record, now)?;
                if crate::restart_budget::operator_stopped(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                {
                    // Check the durable stop before a recovered transaction
                    // can resume or launch its replacement.
                    supervisor.quarantine_release_for_stop(&agent_id, slot)?;
                } else {
                    supervisor.recover_release_transaction(&agent_id, slot, now)?;
                }
                supervisor.recover_signed_intent(&agent_id, slot, &record)?;
                let stopped = crate::restart_budget::operator_stopped(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                let quarantined = slot.signed_intent.as_ref().is_some_and(|intent| {
                    !matches!(
                        intent.status,
                        SignedIntentStatus::Committed
                            | SignedIntentStatus::RolledBack
                            | SignedIntentStatus::Aborted
                    )
                }) || slot
                    .release_transaction
                    .as_ref()
                    .is_some_and(|transaction| !transaction.phase.terminal());
                if quarantined {
                    slot.restart_pending = false;
                }
                if !quarantined && slot.release_change.is_none() {
                    if stopped {
                        slot.restart_pending = false;
                        slot.restart_not_before = None;
                        if slot.runtime.as_ref().is_some_and(|runtime| {
                            matches!(
                                runtime.phase,
                                crate::runtime::RuntimePhase::Running
                                    | crate::runtime::RuntimePhase::AwaitingHealth { .. }
                            )
                        }) {
                            supervisor.stop_slot_preserving_restart(&agent_id, slot, now)?;
                        }
                    } else if slot.restart_pending
                        && slot.runtime.as_ref().is_some_and(|runtime| {
                            matches!(
                                runtime.phase,
                                crate::runtime::RuntimePhase::Running
                                    | crate::runtime::RuntimePhase::AwaitingHealth { .. }
                            )
                        })
                    {
                        supervisor.stop_slot_preserving_restart(&agent_id, slot, now)?;
                    } else if confirmed_missing
                        && slot.runtime.is_none()
                        && !slot.restart_pending
                        && slot.active_release.is_some()
                        && matches!(
                            record.lifecycle.lifecycle,
                            AgentLifecycle::Starting | AgentLifecycle::Running
                        )
                    {
                        let restart_fault =
                            supervisor.queue_automatic_restart_before_exit(&agent_id, slot, now);
                        return Ok(process_fault.or(restart_fault));
                    }
                }
                Ok(process_fault)
            });
            match result {
                Ok(Some(error)) => supervisor.record_fault(&agent_id, &error, &mut report),
                Ok(None) => {}
                // Corrupt/unreadable durable restart, release or signed-intent
                // state is not an ordinary process fault. Starting without
                // those fences could widen mutation authority, so fail closed.
                Err(error) => return Err(error),
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
                restart_attempt: slot.restart_attempt,
                release_state_generation: slot.release_state_generation,
                runtime_phase: slot.runtime.as_ref().map(|runtime| match runtime.phase {
                    crate::runtime::RuntimePhase::AwaitingHealth { .. } => {
                        ControlRuntimePhase::AwaitingHealth
                    }
                    crate::runtime::RuntimePhase::Running => ControlRuntimePhase::Running,
                    crate::runtime::RuntimePhase::Unhealthy { .. } => {
                        ControlRuntimePhase::Unhealthy
                    }
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

    fn next_control_revision_for_slot(
        slot: &AgentSlot<D::Process>,
    ) -> Result<u64, SupervisorError> {
        slot.control_revision
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("control revision overflow".to_string()))
    }

    fn set_control_revision_for_slot(
        slot: &mut AgentSlot<D::Process>,
        revision: u64,
    ) -> Result<(), SupervisorError> {
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
        let available = crate::restart_budget::restart_available(
            record.layout.run_root(),
            self.config.restart_max_attempts,
            self.config.restart_window,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if !available {
            return Err(SupervisorError::RestartBudgetExhausted(agent_id.clone()));
        }
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
        // Resolve again before consuming the caller's control revision so a
        // revoked/withdrawn predecessor remains a clean pre-dispatch rejection.
        let target = self.refresh_release_for_transition(agent_id, target)?;
        let record = self.record(agent_id)?;
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        Self::preflight_upgrade_slot(agent_id, slot, &record, &target)
    }

    fn preflight_upgrade_slot(
        agent_id: &AgentId,
        slot: &AgentSlot<D::Process>,
        record: &AgentRecord,
        target: &AgentRelease,
    ) -> Result<(), SupervisorError> {
        if slot.release_change.is_some()
            || slot.restart_pending
            || slot
                .release_transaction
                .as_ref()
                .is_some_and(|transaction| !transaction.phase.terminal())
        {
            return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
        }
        let current = slot.active_release.as_ref().ok_or_else(|| {
            SupervisorError::Invalid(format!(
                "agent {agent_id} has no explicit active release identity"
            ))
        })?;
        if current.identity() == target.identity()
            || (current.command() == target.command()
                && current.matrixd_command() == target.matrixd_command())
        {
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
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.start_release_slot(agent_id, slot, release, now)
        })
    }

    pub fn drain(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.drain_slot(agent_id, slot, now)
        })
    }

    pub fn stop(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.stop_slot(agent_id, slot, now)
        })
    }

    pub fn kill(&mut self, agent_id: &AgentId) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.kill_slot(agent_id, slot)
        })
    }

    pub fn restart(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
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
        self.with_slot(agent_id, |supervisor, slot| {
            supervisor.upgrade_slot(
                agent_id, slot, target, now, /*explicit_rollback*/ false,
                /*authority*/ None,
            )
        })
    }

    pub fn rollback(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            let target = slot
                .previous_release
                .clone()
                .ok_or_else(|| SupervisorError::NoPreviousRelease(agent_id.clone()))?;
            supervisor.upgrade_slot(
                agent_id, slot, target, now, /*explicit_rollback*/ true,
                /*authority*/ None,
            )
        })
    }

    /// Admit one externally signed H7/OPE operation into the real lifecycle
    /// supervisor.  The H7 envelope remains a qualification artifact; the
    /// independent production grant is the only object that carries
    /// production authority.  This method queues the existing drain/start
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
            // `with_slot` temporarily removes this Agent from `self.slots`.
            // Validate the borrowed owner state directly so a valid signed
            // mutation cannot fail with `UnknownAgent` before its effect boundary.
            let target = supervisor.refresh_release_for_transition(agent_id, &target)?;
            Self::preflight_upgrade_slot(agent_id, slot, &record, &target)?;
            if slot.signed_intent.as_ref().is_some_and(|intent| {
                !matches!(
                    intent.status,
                    SignedIntentStatus::Committed
                        | SignedIntentStatus::RolledBack
                        | SignedIntentStatus::Aborted
                )
            }) {
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
            let next_control_revision = Self::next_control_revision_for_slot(slot)?;
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
            if write_intent(record.layout.run_root(), &intent).is_err() {
                return Err(
                    supervisor.fence_failed_signed_publication(agent_id, slot, &intent, now)
                );
            }
            Self::set_control_revision_for_slot(slot, next_control_revision)?;
            slot.signed_intent = Some(intent.clone());
            let explicit_rollback = grant.transition == H7H89ProductionTransition::Rollback;
            if supervisor
                .upgrade_slot(
                    agent_id,
                    slot,
                    target,
                    now,
                    explicit_rollback,
                    Some((grant.digest().clone(), expected_authority_epoch)),
                )
                .is_err()
            {
                return Err(
                    supervisor.fence_failed_signed_publication(agent_id, slot, &intent, now)
                );
            }
            let queued = intent
                .with_status(SignedIntentStatus::Queued)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            if write_intent(record.layout.run_root(), &queued).is_err() {
                return Err(
                    supervisor.fence_failed_signed_publication(agent_id, slot, &intent, now)
                );
            }
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
        let terminal_status = if active.identity() == intent.target_release {
            match intent.transition {
                H7H89ProductionTransition::Upgrade => SignedIntentStatus::Committed,
                H7H89ProductionTransition::Rollback => SignedIntentStatus::RolledBack,
            }
        } else if intent.transition == H7H89ProductionTransition::Upgrade
            && slot
                .release_transaction
                .as_ref()
                .is_some_and(|transaction| {
                    transaction.kind == ReleaseTransactionKind::Upgrade
                        && transaction.phase == ReleaseTransactionPhase::RolledBack
                        && active.identity() == intent.source_release
                })
        {
            // A signed upgrade whose target failed may complete through the
            // supervisor's automatic rollback to its source release.
            SignedIntentStatus::RolledBack
        } else {
            return Ok(());
        };
        let terminal = intent
            .with_status(terminal_status)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let record = self.record(agent_id)?;
        write_intent(record.layout.run_root(), &terminal)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.signed_intent = Some(terminal);
        Ok(())
    }

    fn recover_signed_intent(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let intent = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let Some(intent) = intent else {
            return Ok(());
        };
        if intent.agent_id != agent_id.to_string() {
            return Err(SupervisorError::Invalid(
                "signed supervisor intent agent binding mismatch".to_string(),
            ));
        }
        slot.control_revision =
            slot.control_revision
                .max(
                    intent
                        .expected_control_revision
                        .checked_add(1)
                        .ok_or_else(|| {
                            SupervisorError::Invalid("signed control revision overflow".to_string())
                        })?,
                );
        slot.signed_intent = Some(intent.clone());
        if matches!(
            intent.status,
            SignedIntentStatus::Committed
                | SignedIntentStatus::RolledBack
                | SignedIntentStatus::Aborted
        ) {
            return Ok(());
        }

        // A terminal release transaction is the durable owner witness that the
        // exact signed transition crossed its lifecycle boundary. This closes
        // the crash cut between terminal transaction publication and the
        // matching signed-intent update. Matching release state is required so
        // a detached or unrelated terminal journal cannot close the intent.
        if let Some(transaction) = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            let kind_matches = matches!(
                (intent.transition, transaction.kind),
                (
                    H7H89ProductionTransition::Upgrade,
                    ReleaseTransactionKind::Upgrade
                ) | (
                    H7H89ProductionTransition::Rollback,
                    ReleaseTransactionKind::ExplicitRollback
                )
            );
            let terminal_status = if kind_matches
                && transaction.grant_sha256.as_ref() == Some(&intent.grant_sha256)
                && transaction.source_release == intent.source_release
                && transaction.target_release == intent.target_release
            {
                let current = record
                    .release_state
                    .current
                    .as_ref()
                    .map(codex_hepta_fleet::ReleaseId::as_str);
                let previous = record
                    .release_state
                    .previous
                    .as_ref()
                    .map(codex_hepta_fleet::ReleaseId::as_str);
                match (intent.transition, transaction.phase) {
                    (H7H89ProductionTransition::Upgrade, ReleaseTransactionPhase::Committed)
                        if current == Some(intent.target_release.as_str())
                            && previous == Some(intent.source_release.as_str()) =>
                    {
                        Some(SignedIntentStatus::Committed)
                    }
                    (H7H89ProductionTransition::Upgrade, ReleaseTransactionPhase::RolledBack)
                        if current == Some(intent.source_release.as_str()) =>
                    {
                        Some(SignedIntentStatus::RolledBack)
                    }
                    (H7H89ProductionTransition::Rollback, ReleaseTransactionPhase::RolledBack)
                        if current == Some(intent.target_release.as_str())
                            && previous == Some(intent.source_release.as_str()) =>
                    {
                        Some(SignedIntentStatus::RolledBack)
                    }
                    _ => None,
                }
            } else {
                None
            };
            if let Some(status) = terminal_status {
                let terminal = intent
                    .with_status(status)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                write_intent(record.layout.run_root(), &terminal)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.signed_intent = Some(terminal);
                return Ok(());
            }
        }

        // Keep the daemon reachable for the status/recovery ceremony while
        // quarantining this Agent generation. Ordinary mutation admission is
        // blocked until the signed intent reaches a terminal state.
        let recovery = if intent.status == SignedIntentStatus::RecoveryRequired {
            intent
        } else {
            intent
                .with_status(SignedIntentStatus::RecoveryRequired)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        };
        if slot
            .signed_intent
            .as_ref()
            .is_none_or(|current| current != &recovery)
        {
            write_intent(record.layout.run_root(), &recovery)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }
        slot.signed_intent = Some(recovery.clone());

        let lifecycle = self.record(agent_id)?.lifecycle;
        if matches!(
            lifecycle.lifecycle,
            AgentLifecycle::Starting | AgentLifecycle::Running | AgentLifecycle::Draining
        ) {
            self.transition_without_runtime(
                agent_id,
                slot,
                lifecycle.generation,
                AgentLifecycle::Failed,
            )?;
        }
        if let Some(runtime) = slot.runtime.as_mut() {
            // Process adoption may already have fenced and successfully requested
            // termination. Hydrating the signed-intent fence is not a second kill.
            let already_requested =
                runtime.fenced && matches!(runtime.phase, RuntimePhase::Killing);
            runtime.fenced = true;
            if !already_requested {
                runtime
                    .process
                    .kill()
                    .map_err(|error| crate::runtime::driver_error(agent_id, error))?;
                runtime.phase = RuntimePhase::Killing;
            }
        }
        self.kill_matrix_now(agent_id, slot)?;
        let directive = crate::signed_intent::read_recovery_directive(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if directive.is_some_and(|directive| directive.intent_sha256 == recovery.intent_sha256)
            && slot.runtime.is_none()
            && slot.matrix.runtime.is_none()
        {
            // Abort never certifies success or starts a replacement. Persist
            // suppression before terminalizing either durable owner witness.
            crate::restart_budget::suppress_restart(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            if let Some(transaction) = slot.release_transaction.as_ref() {
                if transaction.grant_sha256.as_ref() != Some(&recovery.grant_sha256) {
                    return Err(SupervisorError::SignedIntentRecoveryRequired(
                        agent_id.clone(),
                    ));
                }
                let aborted = transaction
                    .with_phase(ReleaseTransactionPhase::Aborted)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                write_release_transaction(record.layout.run_root(), &aborted)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.release_transaction = Some(aborted);
            }
            let aborted = recovery
                .with_status(SignedIntentStatus::Aborted)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &aborted)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(aborted);
            slot.restart_pending = false;
            slot.restart_not_before = None;
            slot.release_change = None;
        }
        Ok(())
    }

    pub fn production_recovery_required(
        &self,
        agent_id: &AgentId,
    ) -> Result<bool, SupervisorError> {
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        Ok(slot
            .signed_intent
            .as_ref()
            .is_some_and(|intent| intent.status == SignedIntentStatus::RecoveryRequired))
    }

    pub fn any_production_recovery_required(&self) -> bool {
        self.slots.values().any(|slot| {
            slot.signed_intent
                .as_ref()
                .is_some_and(|intent| intent.status == SignedIntentStatus::RecoveryRequired)
        })
    }

    pub fn release_selection_snapshot(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<DurableReleaseTransaction>, SupervisorError> {
        let record = self.record(agent_id)?;
        read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))
    }

    pub fn production_mutation_state(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<ProductionMutationState>, SupervisorError> {
        let record = self.record(agent_id)?;
        let Some(intent) = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        else {
            return Ok(None);
        };
        let transaction = read_release_transaction(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .filter(|transaction| {
                transaction.grant_sha256.as_ref() == Some(&intent.grant_sha256)
                    && transaction.agent_id == intent.agent_id
                    && transaction.source_release == intent.source_release
                    && transaction.target_release == intent.target_release
            })
            .map(|transaction| transaction.transaction_sha256);
        crate::signed_history::state(intent, transaction)
            .map(Some)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))
    }

    pub fn production_mutation_lookup(
        &self,
        agent_id: &AgentId,
        grant_sha256: &Sha256Digest,
    ) -> Result<Option<ProductionMutationState>, SupervisorError> {
        if let Some(state) = self.production_mutation_state(agent_id)?
            && &state.receipt.grant_sha256 == grant_sha256
        {
            return Ok(Some(state));
        }
        let record = self.record(agent_id)?;
        crate::signed_history::lookup(record.layout.run_root(), agent_id.as_str(), grant_sha256)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))
    }

    pub fn resolve_production_recovery(
        &mut self,
        agent_id: &AgentId,
        decision: &ProductionRecoveryDecision,
        verifier: &H7H89ProductionGrantVerifier,
        expected_authority_epoch: u64,
        now_unix_seconds: u64,
    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            let record = supervisor.record(agent_id)?;
            let intent = read_intent(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .ok_or_else(|| SupervisorError::SignedIntentRecoveryRequired(agent_id.clone()))?;
            if intent.status != SignedIntentStatus::RecoveryRequired {
                return Err(SupervisorError::Invalid(
                    "production recovery requires a recovery_required signed intent".to_string(),
                ));
            }
            let transaction = read_release_transaction(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .ok_or_else(|| SupervisorError::SignedIntentRecoveryRequired(agent_id.clone()))?;
            if transaction.phase != ReleaseTransactionPhase::RecoveryRequired
                || transaction.grant_sha256.as_ref() != Some(&intent.grant_sha256)
            {
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
            if slot.runtime.as_ref().is_some_and(|runtime| !runtime.fenced) {
                return Err(SupervisorError::Invalid(
                    "production recovery requires the ambiguous process to be fenced or absent"
                        .to_string(),
                ));
            }

            let expected_release = match (intent.transition, decision.outcome) {
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::Committed,
                ) => intent.target_release.as_str(),
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::RolledBack,
                ) => intent.source_release.as_str(),
                (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::RolledBack,
                ) => intent.target_release.as_str(),
                (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::Committed,
                ) => {
                    return Err(SupervisorError::Invalid(
                        "a rollback transition cannot recover as a committed upgrade".to_string(),
                    ));
                }
            };
            let expected_release_id = ReleaseId::parse(expected_release.to_string())?;
            if record.release_state.current.as_ref() != Some(&expected_release_id) {
                return Err(SupervisorError::Invalid(format!(
                    "recovery outcome expects release {expected_release} but durable current release differs"
                )));
            }
            let binding = supervisor
                .registry
                .resolve_release_binding(agent_id, &expected_release_id)?;
            let expected_wire = match (intent.transition, decision.outcome) {
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::Committed,
                )
                | (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::RolledBack,
                ) => transaction.target_binding.as_ref(),
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::RolledBack,
                ) => transaction.source_binding.as_ref(),
                (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::Committed,
                ) => None,
            }
            .ok_or_else(|| {
                SupervisorError::Invalid(
                    "production recovery requires a registered release binding".to_string(),
                )
            })?;
            if expected_wire.release_id != binding.release_id.to_string()
                || expected_wire.manifest_sha256.as_str() != binding.manifest_sha256.as_str()
                || expected_wire.agentd_program_sha256.as_str()
                    != binding.agentd_program_sha256.as_str()
                || expected_wire.matrixd_program_sha256.as_deref()
                    != binding.matrixd_program_sha256.as_deref()
                || expected_wire.admission_frontier_sha256.as_str()
                    != binding.admission_frontier_sha256.as_str()
            {
                return Err(SupervisorError::ProductionAuthority(
                    "release binding changed since the production transition was admitted"
                        .to_string(),
                ));
            }
            let parse = |value: String, label: &str| {
                Sha256Digest::parse(value)
                    .map_err(|_| SupervisorError::Invalid(format!("{label} digest is malformed")))
            };
            let manifest = parse(binding.manifest_sha256, "recovery observed manifest")?;
            let agentd = parse(binding.agentd_program_sha256, "recovery observed agentd")?;
            let matrixd = binding
                .matrixd_program_sha256
                .map(|value| parse(value, "recovery observed matrixd"))
                .transpose()?;

            verifier
                .verify_recovery(
                    decision,
                    agent_id,
                    &intent.grant_sha256,
                    &intent.intent_sha256,
                    &transaction.transaction_sha256,
                    expected_release,
                    &manifest,
                    &agentd,
                    matrixd.as_ref(),
                    record.lifecycle.generation,
                    expected_authority_epoch,
                    now_unix_seconds,
                )
                .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;

            let terminal_phase = match (intent.transition, decision.outcome) {
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::Committed,
                ) => ReleaseTransactionPhase::Committed,
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::RolledBack,
                )
                | (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::RolledBack,
                ) => ReleaseTransactionPhase::RolledBack,
                (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::Committed,
                ) => {
                    return Err(SupervisorError::Invalid(
                        "a rollback transition cannot recover as a committed upgrade".to_string(),
                    ));
                }
            };
            let terminal_intent_status = match (intent.transition, decision.outcome) {
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::Committed,
                ) => SignedIntentStatus::Committed,
                (
                    H7H89ProductionTransition::Upgrade,
                    ProductionRecoveryOutcome::RolledBack,
                )
                | (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::RolledBack,
                ) => SignedIntentStatus::RolledBack,
                (
                    H7H89ProductionTransition::Rollback,
                    ProductionRecoveryOutcome::Committed,
                ) => unreachable!("invalid rollback recovery outcome rejected above"),
            };
            let terminal_transaction = transaction
                .with_recovery_resolution(terminal_phase, decision.digest().clone())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_release_transaction(record.layout.run_root(), &terminal_transaction)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.release_transaction = Some(terminal_transaction);
            let terminal_intent = intent
                .with_status(terminal_intent_status)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &terminal_intent)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(terminal_intent.clone());

            let next_control_revision = Self::next_control_revision_for_slot(slot)?;
            Self::set_control_revision_for_slot(slot, next_control_revision)?;
            Ok(ProductionMutationReceipt {
                grant_sha256: terminal_intent.grant_sha256,
                agent_id: terminal_intent.agent_id,
                transition: terminal_intent.transition,
                source_release: terminal_intent.source_release,
                target_release: terminal_intent.target_release,
                control_revision: next_control_revision,
                status: match (terminal_intent.transition, decision.outcome) {
                    (
                        H7H89ProductionTransition::Upgrade,
                        ProductionRecoveryOutcome::Committed,
                    ) => crate::ProductionMutationStatus::Committed,
                    (
                        H7H89ProductionTransition::Upgrade,
                        ProductionRecoveryOutcome::RolledBack,
                    )
                    | (
                        H7H89ProductionTransition::Rollback,
                        ProductionRecoveryOutcome::RolledBack,
                    ) => crate::ProductionMutationStatus::RolledBack,
                    (
                        H7H89ProductionTransition::Rollback,
                        ProductionRecoveryOutcome::Committed,
                    ) => unreachable!("invalid rollback recovery outcome rejected above"),
                },
                production_authority: true,
                external_effects: true,
                operator_acceptance: true,
                promotion: true,
            })
        })
    }

    pub fn tick(&mut self, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        for agent_id in self.agent_ids() {
            report.faults.extend(self.tick_agent(&agent_id, now).faults);
        }
        report
    }

    pub(crate) fn tick_agent(&mut self, agent_id: &AgentId, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        let result = self.with_slot(agent_id, |supervisor, slot| {
            supervisor.tick_slot(agent_id, slot, now)
        });
        if let Err(error) = result {
            self.record_fault(agent_id, &error, &mut report);
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
        // Exact owner lookup preserves path and generation validation without
        // parsing and cloning every other Agent for one child observation.
        Ok(self.registry.load_agent(agent_id)?)
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
