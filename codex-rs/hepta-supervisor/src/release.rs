use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::AgentRelease;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::runtime::AgentSlot;
use crate::runtime::ReleaseChange;
use crate::runtime::ReleaseChangePhase;
use crate::signed_intent::SignedIntentStatus;
use crate::release_selection::read_release_selection;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn upgrade_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        target: AgentRelease,
        now: Instant,
        explicit_rollback: bool,
    ) -> Result<(), SupervisorError> {
        if slot.release_change.is_some() || slot.restart_pending {
            return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
        }
        let current = slot.active_release.clone().ok_or_else(|| {
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
        let lifecycle = self.record(agent_id)?.lifecycle;
        if lifecycle.lifecycle != AgentLifecycle::Running {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot change release from {:?}",
                lifecycle.lifecycle
            )));
        }
        let prior_previous = slot.previous_release.clone();
        slot.release_change = Some(ReleaseChange {
            origin: current.clone(),
            target: target.clone(),
            prior_previous,
            phase: ReleaseChangePhase::WaitingForTargetExit,
            explicit_rollback,
        });
        if let Err(error) = self.drain_slot(agent_id, slot, now) {
            slot.release_change = None;
            return Err(error);
        }
        let generation = slot
            .runtime
            .as_ref()
            .map(|runtime| runtime.generation)
            .unwrap_or(lifecycle.generation);
        let kind = if explicit_rollback {
            SupervisorEventKind::ExplicitRollbackQueued {
                previous: current.identity().to_string(),
                target: target.identity().to_string(),
            }
        } else {
            SupervisorEventKind::UpgradeQueued {
                previous: current.identity().to_string(),
                target: target.identity().to_string(),
            }
        };
        slot.event(generation, kind);
        Ok(())
    }

    pub(crate) fn release_became_healthy(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
    ) -> Result<(), SupervisorError> {
        let mut automatic_rollback_committed = false;
        if let Some(change) = slot.release_change.take() {
            match change.phase {
                ReleaseChangePhase::TargetStarting => {
                    slot.previous_release = Some(change.origin.clone());
                    let kind = if change.explicit_rollback {
                        SupervisorEventKind::ExplicitRollbackCommitted {
                            previous: change.origin.identity().to_string(),
                            target: change.target.identity().to_string(),
                        }
                    } else {
                        SupervisorEventKind::UpgradeCommitted {
                            previous: change.origin.identity().to_string(),
                            target: change.target.identity().to_string(),
                        }
                    };
                    slot.event(generation, kind);
                }
                ReleaseChangePhase::AutomaticRollbackStarting => {
                    slot.previous_release = change.prior_previous;
                    slot.event(
                        generation,
                        SupervisorEventKind::AutomaticRollbackCommitted {
                            failed: change.target.identity().to_string(),
                            restored: change.origin.identity().to_string(),
                        },
                    );
                    automatic_rollback_committed = true;
                }
                ReleaseChangePhase::WaitingForTargetExit => {
                    slot.release_change = Some(change);
                }
            }
        }
        self.persist_release_state(agent_id, slot)?;
        if automatic_rollback_committed {
            self.mark_signed_intent_rolled_back(agent_id, slot)
        } else {
            self.commit_signed_intent_if_target(agent_id, slot)
        }
    }

    pub(crate) fn persist_release_state(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let current = slot
            .active_release
            .as_ref()
            .map(|release| release.release_id().clone());
        let previous = slot
            .previous_release
            .as_ref()
            .map(|release| release.release_id().clone());
        if current
            .as_ref()
            .is_some_and(|release| release.as_str() == "unversioned")
        {
            return Ok(());
        }
        let actual = self.record(agent_id)?.release_state;
        slot.release_state_generation = actual.generation;
        if actual.current == current && actual.previous == previous {
            return Ok(());
        }
        let next = self.registry.compare_and_set_release_state(
            agent_id,
            actual.generation,
            current,
            previous,
        )?;
        slot.release_state_generation = next.generation;
        Ok(())
    }

    pub(crate) fn continue_release_change_after_exit(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<bool, SupervisorError> {
        let Some(mut change) = slot.release_change.take() else {
            return Ok(false);
        };
        match change.phase {
            ReleaseChangePhase::WaitingForTargetExit => {
                let target = change.target.clone();
                change.phase = ReleaseChangePhase::TargetStarting;
                slot.release_change = Some(change);
                slot.active_release = None;
                match self.start_release_slot(agent_id, slot, target, now) {
                    Ok(()) => Ok(true),
                    Err(_) => self.start_automatic_rollback(agent_id, slot, now),
                }
            }
            ReleaseChangePhase::TargetStarting => {
                slot.release_change = Some(change);
                self.start_automatic_rollback(agent_id, slot, now)
            }
            ReleaseChangePhase::AutomaticRollbackStarting => {
                let generation = self.record(agent_id)?.lifecycle.generation;
                slot.active_release = None;
                slot.event(
                    generation,
                    SupervisorEventKind::AutomaticRollbackFailed {
                        failed: change.target.identity().to_string(),
                        rollback: change.origin.identity().to_string(),
                    },
                );
                self.mark_signed_intent_recovery_required(agent_id, slot)?;
                Ok(true)
            }
        }
    }

    fn start_automatic_rollback(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<bool, SupervisorError> {
        let Some(mut change) = slot.release_change.take() else {
            return Ok(false);
        };
        let generation = self.record(agent_id)?.lifecycle.generation;
        slot.event(
            generation,
            SupervisorEventKind::AutomaticRollbackQueued {
                failed: change.target.identity().to_string(),
                target: change.origin.identity().to_string(),
            },
        );
        // Never restart the cached predecessor directly. Re-resolve the
        // current per-Agent allowance and immutable catalog bytes first.
        let rollback = match self
            .registry
            .resolve_release(agent_id, change.origin.release_id())
            .map_err(SupervisorError::from)
            .and_then(AgentRelease::try_from)
        {
            Ok(rollback) => rollback,
            Err(error) => {
                self.mark_signed_intent_recovery_required(agent_id, slot)?;
                return Err(error);
            }
        };

        // A signed production transition additionally binds the predecessor
        // bytes to its durable selection record. Catalog/allowance drift after
        // admission therefore quarantines rollback instead of silently
        // executing a differently installed predecessor.
        if slot.signed_intent.as_ref().is_some_and(|intent| {
            matches!(
                intent.status,
                SignedIntentStatus::Prepared | SignedIntentStatus::Queued
            )
        }) {
            let record = self.record(agent_id)?;
            let selection = read_release_selection(record.layout.run_root())?
                .ok_or_else(|| SupervisorError::SignedIntentRecoveryRequired(agent_id.clone()))?;
            if selection.source_release != rollback.identity() {
                self.mark_signed_intent_recovery_required(agent_id, slot)?;
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
            let provenance = self
                .registry
                .release_provenance(agent_id, rollback.release_id())?;
            let binding = &selection.binding;
            let bytes_match = provenance.manifest_sha256
                == binding.source_manifest_sha256.as_str()
                && provenance.agentd_sha256 == binding.source_agentd_sha256.as_str()
                && provenance.matrixd_sha256.as_deref()
                    == binding
                        .source_matrixd_sha256
                        .as_ref()
                        .map(|digest| digest.as_str());
            if !bytes_match {
                self.mark_signed_intent_recovery_required(agent_id, slot)?;
                return Err(SupervisorError::SignedIntentRecoveryRequired(
                    agent_id.clone(),
                ));
            }
        }

        change.phase = ReleaseChangePhase::AutomaticRollbackStarting;
        slot.release_change = Some(change);
        slot.active_release = None;
        if let Err(error) = self.start_release_slot(agent_id, slot, rollback, now) {
            let failed_generation = self.record(agent_id)?.lifecycle.generation;
            if let Some(change) = slot.release_change.take() {
                slot.event(
                    failed_generation,
                    SupervisorEventKind::AutomaticRollbackFailed {
                        failed: change.target.identity().to_string(),
                        rollback: change.origin.identity().to_string(),
                    },
                );
            }
            self.mark_signed_intent_recovery_required(agent_id, slot)?;
            return Err(error);
        }
        Ok(true)
    }
}
