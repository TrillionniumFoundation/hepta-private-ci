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
use crate::release_selection::ReleaseSelectionRecord;
use crate::release_selection::ReleaseSelectionSnapshot;
use crate::release_selection::ReleaseSelectionStatus;
use crate::release_selection::read_release_selection;
use crate::release_selection::write_release_selection;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::signed_authority::H7H89ProductionGrant;
use crate::signed_authority::H7H89ProductionGrantVerifier;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::ProductionMutationReceipt;
use crate::signed_authority::ProductionRecoveryDecision;
use crate::signed_authority::ProductionRecoveryOutcome;
use crate::signed_authority::ReleaseSelectionBinding;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::write_intent;

/// Lifecycle-only controller with one process handle and bounded buffers per agent.
pub struct Supervisor<D: ProcessDriver> {
    pub(crate) registry: FleetRegistry,
    pub(crate) driver: D,
    pub(crate) config: SupervisorConfig,
    /// Host-pinned revocation frontier for production release selection.
    /// None keeps ordinary lifecycle-only embeddings unchanged.
    pub(crate) production_revocation_frontier: Option<u64>,
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
            production_revocation_frontier: None,
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

    pub fn set_production_revocation_frontier(
        &mut self,
        revocation_frontier: u64,
    ) -> Result<(), SupervisorError> {
        if revocation_frontier == 0 {
            return Err(SupervisorError::Invalid(
                "production revocation frontier must be non-zero".to_string(),
            ));
        }
        self.production_revocation_frontier = Some(revocation_frontier);
        Ok(())
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
                runtime_lease_persisted: slot
                    .runtime
                    .as_ref()
                    .is_none_or(|runtime| runtime.lease_persisted),
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
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        self.preflight_upgrade_slot(agent_id, slot, target)
    }

    fn preflight_upgrade_slot(
        &self,
        agent_id: &AgentId,
        slot: &AgentSlot<D::Process>,
        target: &AgentRelease,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        Self::ensure_signed_intent_resolved(agent_id, slot)?;
        if slot.release_change.is_some() || slot.restart_pending {
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
        self.ensure_unsigned_release_transition_allowed()?;
        self.with_slot(agent_id, |supervisor, slot| {
            Self::ensure_signed_intent_resolved(agent_id, slot)?;
            supervisor.upgrade_slot(
                agent_id, slot, target, now, /*explicit_rollback*/ false,
            )
        })
    }

    pub fn rollback(&mut self, agent_id: &AgentId, now: Instant) -> Result<(), SupervisorError> {
        self.ensure_unsigned_release_transition_allowed()?;
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

    fn ensure_unsigned_release_transition_allowed(&self) -> Result<(), SupervisorError> {
        if self.production_revocation_frontier.is_some() {
            return Err(SupervisorError::ProductionAuthority(
                "production mode release changes require an independently signed production grant"
                    .to_string(),
            ));
        }
        Ok(())
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
        expected_revocation_frontier: u64,
        now_unix_seconds: u64,
        now: Instant,
    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            if let Some(configured_frontier) = supervisor.production_revocation_frontier
                && configured_frontier != expected_revocation_frontier
            {
                return Err(SupervisorError::ProductionAuthority(format!(
                    "production revocation frontier mismatch: configured {configured_frontier}, requested {expected_revocation_frontier}"
                )));
            }
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
                grant.release_selection.compatibility_receipt_sha256.clone(),
                expected_revocation_frontier,
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
                    expected_revocation_frontier,
                    now_unix_seconds,
                )
                .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;
            supervisor.preflight_upgrade_slot(agent_id, slot, &target)?;
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
            let next_control_revision = Self::next_control_revision_for_slot(slot)?;
            // The release-selection journal is the authoritative transaction
            // record and carries enough fields to reconstruct a missing
            // execution intent. Persist it first so no crash cut can leave an
            // intent that has no recoverable selection/binding record.
            let selection = ReleaseSelectionRecord::prepared(
                grant,
                next_control_revision,
                record.lifecycle.generation,
            )?;
            write_release_selection(record.layout.run_root(), &selection)?;
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
            if let Err(error) = write_intent(record.layout.run_root(), &intent) {
                if let Ok(selection_recovery) =
                    selection.with_status(ReleaseSelectionStatus::RecoveryRequired)
                {
                    let _ =
                        write_release_selection(record.layout.run_root(), &selection_recovery);
                }
                return Err(SupervisorError::Invalid(error.to_string()));
            }
            Self::set_control_revision_for_slot(slot, next_control_revision)?;
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
        let selection = read_release_selection(record.layout.run_root())?
            .ok_or_else(|| SupervisorError::SignedIntentRecoveryRequired(agent_id.clone()))?;
        if selection.grant_sha256 != committed.grant_sha256 {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        // Terminalize the authoritative release-selection record before the
        // intent. If the second write is interrupted, startup still sees an
        // unresolved intent and deterministically rewrites both records to
        // RecoveryRequired. The reverse order can strand a terminal intent
        // beside a queued selection with no admissible recovery ceremony.
        let selection = selection.with_status(ReleaseSelectionStatus::Committed)?;
        write_release_selection(record.layout.run_root(), &selection)?;
        write_intent(record.layout.run_root(), &committed)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
        let selection = read_release_selection(record.layout.run_root())?
            .ok_or_else(|| SupervisorError::SignedIntentRecoveryRequired(agent_id.clone()))?;
        if selection.grant_sha256 != rolled_back.grant_sha256 {
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        }
        // Use the same recoverable terminalization order as the committed
        // path and explicit recovery ceremony: selection first, intent last.
        let selection = selection.with_status(ReleaseSelectionStatus::RolledBack)?;
        write_release_selection(record.layout.run_root(), &selection)?;
        write_intent(record.layout.run_root(), &rolled_back)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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

    pub fn release_selection_snapshot(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<ReleaseSelectionSnapshot>, SupervisorError> {
        let record = self.record(agent_id)?;
        Ok(read_release_selection(record.layout.run_root())?.map(|selection| selection.snapshot()))
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
        expected_revocation_frontier: u64,
        now_unix_seconds: u64,
    ) -> Result<ProductionMutationReceipt, SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            if let Some(configured_frontier) = supervisor.production_revocation_frontier
                && configured_frontier != expected_revocation_frontier
            {
                return Err(SupervisorError::ProductionAuthority(format!(
                    "production recovery revocation frontier mismatch: configured {configured_frontier}, requested {expected_revocation_frontier}"
                )));
            }
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
                    expected_revocation_frontier,
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
            let terminal_selection = selection.with_recovery_status(
                terminal_selection_status,
                decision.digest().clone(),
            )?;
            write_release_selection(record.layout.run_root(), &terminal_selection)?;
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

    fn intent_from_release_selection(
        selection: &ReleaseSelectionRecord,
        status: SignedIntentStatus,
    ) -> Result<SignedSupervisorIntent, SupervisorError> {
        let expected_control_revision = selection.control_revision.checked_sub(1).ok_or_else(|| {
            SupervisorError::Invalid(
                "release selection control revision has no predecessor".to_string(),
            )
        })?;
        SignedSupervisorIntent::new(
            selection.grant_sha256.clone(),
            selection.agent_id.clone(),
            selection.transition,
            selection.source_release.clone(),
            selection.target_release.clone(),
            expected_control_revision,
            selection.lifecycle_generation,
            selection.authority_epoch,
            status,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))
    }

    fn quarantine_unresolved_selection(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        selection: &ReleaseSelectionRecord,
    ) -> Result<(), SupervisorError> {
        let recovery_selection =
            selection.with_status(ReleaseSelectionStatus::RecoveryRequired)?;
        // The authoritative selection goes first. A crash before the intent
        // write remains reconstructible from this complete record.
        write_release_selection(
            self.record(agent_id)?.layout.run_root(),
            &recovery_selection,
        )?;
        let recovery_intent =
            Self::intent_from_release_selection(&recovery_selection, SignedIntentStatus::RecoveryRequired)?;
        write_intent(
            self.record(agent_id)?.layout.run_root(),
            &recovery_intent,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.signed_intent = Some(recovery_intent);

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
            let _ = runtime.process.kill();
            runtime.fenced = true;
            runtime.phase = RuntimePhase::Killing;
        }
        Err(SupervisorError::SignedIntentRecoveryRequired(
            agent_id.clone(),
        ))
    }

    fn recover_signed_intent(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let intent = read_intent(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let Some(selection) = read_release_selection(record.layout.run_root())? else {
            // New production admissions always persist the authoritative
            // release-selection record first. An intent without its selection
            // is legacy/corrupt state: preserve the old fail-closed behavior
            // and mark the surviving witness RecoveryRequired, but do not
            // invent compatibility/provenance fields for a fake selection.
            let Some(intent) = intent else {
                return Ok(());
            };
            if intent.agent_id != agent_id.to_string() {
                return Err(SupervisorError::Invalid(
                    "signed supervisor intent agent binding mismatch".to_string(),
                ));
            }
            let recovery = intent
                .with_status(SignedIntentStatus::RecoveryRequired)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            write_intent(record.layout.run_root(), &recovery)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(recovery);
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
                let _ = runtime.process.kill();
                runtime.fenced = true;
                runtime.phase = RuntimePhase::Killing;
            }
            return Err(SupervisorError::SignedIntentRecoveryRequired(
                agent_id.clone(),
            ));
        };
        selection.validate()?;
        if selection.agent_id != agent_id.to_string() {
            return Err(SupervisorError::Invalid(
                "release selection Agent binding mismatch".to_string(),
            ));
        }
        slot.control_revision = selection.control_revision;

        // A terminal authoritative selection can repair a missing/stale
        // intent only when the independently durable Fleet release state and
        // immutable bytes prove the same terminal outcome. Journal status
        // alone never manufactures a committed physical release.
        if selection.status.terminal() {
            let (terminal_intent_status, expected_release, manifest, agentd, matrixd) =
                match selection.status {
                    ReleaseSelectionStatus::Committed => (
                        SignedIntentStatus::Committed,
                        selection.target_release.as_str(),
                        selection.binding.target_manifest_sha256.as_str(),
                        selection.binding.target_agentd_sha256.as_str(),
                        selection
                            .binding
                            .target_matrixd_sha256
                            .as_ref()
                            .map(|digest| digest.as_str()),
                    ),
                    ReleaseSelectionStatus::RolledBack => (
                        SignedIntentStatus::RolledBack,
                        selection.source_release.as_str(),
                        selection.binding.source_manifest_sha256.as_str(),
                        selection.binding.source_agentd_sha256.as_str(),
                        selection
                            .binding
                            .source_matrixd_sha256
                            .as_ref()
                            .map(|digest| digest.as_str()),
                    ),
                    _ => unreachable!(),
                };
            let current = self.record(agent_id)?.release_state.current;
            let durable_release_matches = current
                .as_ref()
                .is_some_and(|release| release.as_str() == expected_release);
            let bytes_match = if durable_release_matches {
                let release_id = ReleaseId::parse(expected_release.to_string())?;
                let provenance = self.registry.release_provenance(agent_id, &release_id)?;
                provenance.manifest_sha256 == manifest
                    && provenance.agentd_sha256 == agentd
                    && provenance.matrixd_sha256.as_deref() == matrixd
            } else {
                false
            };
            if !durable_release_matches || !bytes_match {
                return self.quarantine_unresolved_selection(agent_id, slot, &selection);
            }

            let expected =
                Self::intent_from_release_selection(&selection, terminal_intent_status)?;
            let needs_repair = intent.as_ref().is_none_or(|actual| {
                actual.agent_id != expected.agent_id
                    || actual.grant_sha256 != expected.grant_sha256
                    || actual.transition != expected.transition
                    || actual.source_release != expected.source_release
                    || actual.target_release != expected.target_release
                    || actual.expected_control_revision != expected.expected_control_revision
                    || actual.expected_lifecycle_generation
                        != expected.expected_lifecycle_generation
                    || actual.authority_epoch != expected.authority_epoch
                    || actual.status != terminal_intent_status
            });
            if needs_repair {
                write_intent(record.layout.run_root(), &expected)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            }
            slot.signed_intent = Some(expected);
            return Ok(());
        }

        // Prepared plus an unchanged Running lifecycle is a provably
        // pre-dispatch crash cut: selection was durable, but drain had not
        // linearized. Close it as RolledBack without killing the healthy
        // predecessor. Every later durable lifecycle state remains unknown and
        // requires the independently signed recovery ceremony.
        let lifecycle = self.record(agent_id)?.lifecycle;
        if selection.status == ReleaseSelectionStatus::Prepared
            && lifecycle.lifecycle == AgentLifecycle::Running
            && lifecycle.generation == selection.lifecycle_generation
        {
            let rolled_back = selection.with_status(ReleaseSelectionStatus::RolledBack)?;
            write_release_selection(record.layout.run_root(), &rolled_back)?;
            let rolled_back_intent =
                Self::intent_from_release_selection(&rolled_back, SignedIntentStatus::RolledBack)?;
            write_intent(record.layout.run_root(), &rolled_back_intent)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            slot.signed_intent = Some(rolled_back_intent);
            return Ok(());
        }

        // Any queued/recovery-required state, or Prepared after the lifecycle
        // generation moved, crossed a boundary whose outcome cannot be
        // inferred from process liveness. Normalize both witnesses to the same
        // recoverable state and quarantine the exact process generation.
        self.quarantine_unresolved_selection(agent_id, slot, &selection)
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
        compatibility_receipt_sha256: Sha256Digest,
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
            compatibility_receipt_sha256,
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
