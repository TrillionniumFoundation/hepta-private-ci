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
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::signed_authority::H7H89ProductionGrant;
use crate::signed_authority::H7H89ProductionGrantVerifier;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::ProductionMutationReceipt;
use crate::signed_authority::ProductionRecoveryDecision;
use crate::signed_authority::ProductionRecoveryOutcome;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;
use crate::release_selection::ReleaseSelectionRecord;
use crate::release_selection::ReleaseSelectionStatus;
use crate::release_selection::read_release_selection;
use crate::release_selection::write_release_selection;

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
                supervisor.restore_release_state(&agent_id, slot, &record)?;
                supervisor.recover_slot(&agent_id, slot, &record, now)?;
                supervisor.restore_restart_budget(&agent_id, slot, &record, now)?;
                supervisor.recover_signed_intent(&agent_id, slot, &record)
            });
            if let Err(error) = result {
                // An unresolved signed mutation quarantines only its owning
                // Agent. The daemon still starts so the read-only status and
                // independently signed recovery ceremony remain reachable.
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
                automatic_restart: slot.automatic_restart,
                restart_attempts: slot.restart_attempts,
                restart_not_before_pending: slot.restart_not_before.is_some(),
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
        Self::ensure_signed_intent_resolved(agent_id, slot)?;
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
        Self::ensure_signed_intent_resolved(agent_id, slot)?;
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
        Self::ensure_signed_intent_resolved(agent_id, slot)?;
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
        let previous = slot
            .previous_release
            .as_ref()
            .ok_or_else(|| SupervisorError::NoPreviousRelease(agent_id.clone()))?;
        let target = AgentRelease::try_from(
            self.registry
                .resolve_release(agent_id, previous.release_id())?,
        )?;
        self.preflight_upgrade(agent_id, &target)
    }

    pub fn agent_ids(&self) -> Vec<AgentId> {
        self.slots.keys().cloned().collect()
    }

    fn ensure_signed_intent_resolved(
        agent_id: &AgentId,
        slot: &AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        if slot.signed_intent.as_ref().is_some_and(|intent| {
            !matches!(
                intent.status,
                SignedIntentStatus::Committed | SignedIntentStatus::RolledBack
            )
        }) {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        Ok(())
    }

    pub fn start(
        &mut self,
        agent_id: &AgentId,
        command: AgentCommand,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            Self::ensure_signed_intent_resolved(agent_id, slot)?;
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
            Self::ensure_signed_intent_resolved(agent_id, slot)?;
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
            Self::ensure_signed_intent_resolved(agent_id, slot)?;
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
            Self::ensure_signed_intent_resolved(agent_id, slot)?;
            supervisor.upgrade_slot(
                agent_id, slot, target, now, /*explicit_rollback*/ false,
            )
        })
    }

    pub fn rollback(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            Self::ensure_signed_intent_resolved(agent_id, slot)?;
            let previous = slot
                .previous_release
                .as_ref()
                .ok_or_else(|| SupervisorError::NoPreviousRelease(agent_id.clone()))?;
            // Re-resolve the predecessor on every rollback. This re-checks the
            // current per-Agent allowance and immutable release bytes instead
            // of trusting a cached AgentRelease captured before a revocation
            // or catalog integrity change.
            let target = AgentRelease::try_from(
                supervisor
                    .registry
                    .resolve_release(agent_id, previous.release_id())?,
            )?;
            supervisor.upgrade_slot(agent_id, slot, target, now, /*explicit_rollback*/ true)
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
            let release_selection = supervisor.release_selection_binding(
                agent_id,
                current,
                &target,
                expected_authority_epoch,
            )?;
            verifier
                .verify(
                    grant,
                    h7_envelope,
                    agent_id,
                    current.identity(),
                    target.identity(),
                    &release_selection,
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
                .is_some_and(|intent| {
                    !matches!(
                        intent.status,
                        SignedIntentStatus::Committed | SignedIntentStatus::RolledBack
                    )
                })
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
            let selection = ReleaseSelectionRecord::prepared(
                grant,
                next_control_revision,
                record.lifecycle.generation,
            )?;
            if let Err(error) = write_release_selection(record.layout.run_root(), &selection) {
                let recovery = intent
                    .with_status(SignedIntentStatus::RecoveryRequired)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                let _ = write_intent(record.layout.run_root(), &recovery);
                if let Ok(selection_recovery) =
                    selection.with_status(ReleaseSelectionStatus::RecoveryRequired)
                {
                    let _ =
                        write_release_selection(record.layout.run_root(), &selection_recovery);
                }
                slot.signed_intent = Some(recovery);
                return Err(error);
            }
            supervisor.set_control_revision(agent_id, next_control_revision)?;
            slot.signed_intent = Some(intent.clone());
            let explicit_rollback = grant.transition == H7H89ProductionTransition::Rollback;
            if let Err(error) =
                supervisor.upgrade_slot(agent_id, slot, target, now, explicit_rollback)
            {
                let recovery = intent
                    .with_status(SignedIntentStatus::RecoveryRequired)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                let _ = write_intent(record.layout.run_root(), &recovery);
                if let Ok(selection_recovery) =
                    selection.with_status(ReleaseSelectionStatus::RecoveryRequired)
                {
                    let _ =
                        write_release_selection(record.layout.run_root(), &selection_recovery);
                }
                slot.signed_intent = Some(recovery);
                return Err(error);
            }
            let queued = intent
                .with_status(SignedIntentStatus::Queued)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &queued)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            let selection = selection.with_status(ReleaseSelectionStatus::Queued)?;
            write_release_selection(record.layout.run_root(), &selection)?;
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
        let selection = read_release_selection(record.layout.run_root())?
            .ok_or_else(|| {
                SupervisorError::SignedIntentRecoveryRequired(agent_id.clone())
            })?;
        if selection.grant_sha256 != committed.grant_sha256 {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        let selection = selection.with_status(ReleaseSelectionStatus::Committed)?;
        write_release_selection(record.layout.run_root(), &selection)?;
        slot.signed_intent = Some(committed);
        Ok(())
    }

    pub(crate) fn mark_signed_intent_rolled_back(
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
        let record = self.record(agent_id)?;
        let rolled_back = intent
            .with_status(SignedIntentStatus::RolledBack)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        write_intent(record.layout.run_root(), &rolled_back)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let selection = read_release_selection(record.layout.run_root())?
            .ok_or_else(|| {
                SupervisorError::SignedIntentRecoveryRequired(agent_id.clone())
            })?;
        if selection.grant_sha256 != rolled_back.grant_sha256 {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        let selection = selection.with_status(ReleaseSelectionStatus::RolledBack)?;
        write_release_selection(record.layout.run_root(), &selection)?;
        slot.signed_intent = Some(rolled_back);
        Ok(())
    }

    pub(crate) fn mark_signed_intent_recovery_required(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let Some(intent) = slot.signed_intent.clone() else {
            return Ok(());
        };
        if matches!(
            intent.status,
            SignedIntentStatus::Committed | SignedIntentStatus::RolledBack
        ) {
            return Ok(());
        }
        let record = self.record(agent_id)?;
        let recovery = intent
            .with_status(SignedIntentStatus::RecoveryRequired)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        write_intent(record.layout.run_root(), &recovery)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if let Some(selection) = read_release_selection(record.layout.run_root())? {
            if selection.grant_sha256 != recovery.grant_sha256 {
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
            let selection = selection.with_status(ReleaseSelectionStatus::RecoveryRequired)?;
            write_release_selection(record.layout.run_root(), &selection)?;
        }
        slot.signed_intent = Some(recovery);
        Ok(())
    }

    pub fn production_mutation_receipt(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<ProductionMutationReceipt>, SupervisorError> {
        let record = self.record(agent_id)?;
        let Some(intent) = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        else {
            return Ok(None);
        };
        let status = match intent.status {
            SignedIntentStatus::Prepared | SignedIntentStatus::Queued => {
                crate::ProductionMutationStatus::Queued
            }
            SignedIntentStatus::Committed => crate::ProductionMutationStatus::Committed,
            SignedIntentStatus::RolledBack => crate::ProductionMutationStatus::RolledBack,
            SignedIntentStatus::RecoveryRequired => {
                crate::ProductionMutationStatus::RecoveryRequired
            }
        };
        let control_revision = intent
            .expected_control_revision
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("control revision overflow".to_string()))?;
        Ok(Some(ProductionMutationReceipt {
            grant_sha256: intent.grant_sha256,
            agent_id: intent.agent_id,
            transition: intent.transition,
            source_release: intent.source_release,
            target_release: intent.target_release,
            control_revision,
            status,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: true,
        }))
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
            let selection = read_release_selection(record.layout.run_root())?
                .ok_or_else(|| SupervisorError::SignedIntentRecoveryRequired(agent_id.clone()))?;
            if selection.grant_sha256 != intent.grant_sha256 {
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

            let observed_release = record
                .release_state
                .current
                .as_ref()
                .ok_or_else(|| SupervisorError::Invalid(
                    "production recovery has no observed release state".to_string(),
                ))?;
            let expected_release = match decision.outcome {
                ProductionRecoveryOutcome::Committed => &intent.target_release,
                ProductionRecoveryOutcome::RolledBack => &intent.source_release,
            };
            if observed_release.as_str() != expected_release {
                return Err(SupervisorError::Invalid(format!(
                    "recovery outcome expects release {expected_release} but current release is {observed_release}"
                )));
            }
            let provenance = supervisor
                .registry
                .release_provenance(agent_id, observed_release)?;
            let parse = |value: String, label: &str| {
                Sha256Digest::parse(value)
                    .map_err(|_| SupervisorError::Invalid(format!("{label} digest is malformed")))
            };
            let observed_manifest = parse(
                provenance.manifest_sha256,
                "recovery observed release manifest",
            )?;
            let observed_agentd =
                parse(provenance.agentd_sha256, "recovery observed agentd")?;
            let observed_matrixd = provenance
                .matrixd_sha256
                .map(|value| parse(value, "recovery observed matrixd"))
                .transpose()?;

            verifier
                .verify_recovery(
                    decision,
                    agent_id,
                    &intent.grant_sha256,
                    &intent.intent_sha256,
                    observed_release.as_str(),
                    &observed_manifest,
                    &observed_agentd,
                    observed_matrixd.as_ref(),
                    slot.control_revision,
                    record.lifecycle.generation,
                    expected_authority_epoch,
                    now_unix_seconds,
                )
                .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;

            let terminal_selection_status = match decision.outcome {
                ProductionRecoveryOutcome::Committed => ReleaseSelectionStatus::Committed,
                ProductionRecoveryOutcome::RolledBack => ReleaseSelectionStatus::RolledBack,
            };
            let terminal_intent_status = match decision.outcome {
                ProductionRecoveryOutcome::Committed => SignedIntentStatus::Committed,
                ProductionRecoveryOutcome::RolledBack => SignedIntentStatus::RolledBack,
            };

            // Publish the selection terminal state before the intent. If the
            // second write is interrupted, startup will reset the selection
            // to RecoveryRequired from the still-unresolved intent instead of
            // guessing a committed outcome.
            let terminal_selection = selection.with_status(terminal_selection_status)?;
            write_release_selection(record.layout.run_root(), &terminal_selection)?;
            let terminal_intent = intent
                .with_status(terminal_intent_status)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &terminal_intent)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(terminal_intent.clone());
            let next_control_revision = supervisor.next_control_revision(agent_id)?;
            supervisor.set_control_revision(agent_id, next_control_revision)?;

            Ok(ProductionMutationReceipt {
                grant_sha256: terminal_intent.grant_sha256,
                agent_id: terminal_intent.agent_id,
                transition: terminal_intent.transition,
                source_release: terminal_intent.source_release,
                target_release: terminal_intent.target_release,
                control_revision: terminal_selection.control_revision,
                status: match decision.outcome {
                    ProductionRecoveryOutcome::Committed => {
                        crate::ProductionMutationStatus::Committed
                    }
                    ProductionRecoveryOutcome::RolledBack => {
                        crate::ProductionMutationStatus::RolledBack
                    }
                },
                production_authority: true,
                external_effects: true,
                operator_acceptance: true,
                promotion: true,
            })
        })
    }

    fn recover_signed_intent(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let intent = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let selection = read_release_selection(record.layout.run_root())?;
        let Some(intent) = intent else {
            if selection.is_some() {
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
            return Ok(());
        };
        if intent.agent_id != agent_id.to_string() {
            return Err(SupervisorError::Invalid(
                "signed supervisor intent agent binding mismatch".to_string(),
            ));
        }
        slot.signed_intent = Some(intent.clone());
        if matches!(
            intent.status,
            SignedIntentStatus::Committed | SignedIntentStatus::RolledBack
        ) {
            let Some(selection) = selection else {
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            };
            let expected_status = match intent.status {
                SignedIntentStatus::Committed => ReleaseSelectionStatus::Committed,
                SignedIntentStatus::RolledBack => ReleaseSelectionStatus::RolledBack,
                _ => unreachable!(),
            };
            if selection.grant_sha256 != intent.grant_sha256
                || selection.status != expected_status
            {
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
            return Ok(());
        }
        // A restart has no durable proof that an apparently matching target
        // was produced by this exact signed mutation.  In particular, the
        // one-file intent does not carry an independently committed source /
        // target release-state revision, control-revision successor,
        // lifecycle-generation transition, or continuity of the daemon's
        // authority epoch.  Treating `Running + target` as Committed would
        // therefore let an unrelated/manual upgrade close an old grant.
        // Every non-terminal intent must remain fail-closed until an explicit
        // recovery ceremony supplies those witnesses.
        //
        // Fence and kill any adopted child before surfacing the recovery
        // requirement; normal ticking must not continue an ambiguous
        // external transition.
        self.mark_signed_intent_recovery_required(agent_id, slot)?;
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

    pub(crate) fn release_selection_binding(
        &self,
        agent_id: &AgentId,
        source: &AgentRelease,
        target: &AgentRelease,
        revocation_frontier: u64,
    ) -> Result<ReleaseSelectionBinding, SupervisorError> {
        let source = self
            .registry
            .release_provenance(agent_id, source.release_id())?;
        let target = self
            .registry
            .release_provenance(agent_id, target.release_id())?;
        let parse = |value: String, label: &str| {
            Sha256Digest::parse(value)
                .map_err(|_| SupervisorError::Invalid(format!("{label} digest is malformed")))
        };
        ReleaseSelectionBinding::new(
            parse(source.manifest_sha256, "source release manifest")?,
            parse(source.agentd_sha256, "source agentd")?,
            source
                .matrixd_sha256
                .map(|value| parse(value, "source matrixd"))
                .transpose()?,
            parse(target.manifest_sha256, "target release manifest")?,
            parse(target.agentd_sha256, "target agentd")?,
            target
                .matrixd_sha256
                .map(|value| parse(value, "target matrixd"))
                .transpose()?,
            revocation_frontier,
        )
        .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))
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
