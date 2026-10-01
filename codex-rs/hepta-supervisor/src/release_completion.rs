//! Retain the observed release outcome until every durable writer acknowledges it.

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::runtime::AgentSlot;
use crate::runtime::ReleaseChangePhase;
use codex_hepta_contracts::AgentId;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn release_became_healthy(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
    ) -> Result<(), SupervisorError> {
        let mut terminal_transaction_phase = None;
        if let Some(change) = slot.release_change.as_mut() {
            match change.phase {
                ReleaseChangePhase::TargetStarting => {
                    change.healthy_generation = Some(generation);
                    slot.previous_release = Some(change.origin.clone());
                    terminal_transaction_phase = Some(if change.explicit_rollback {
                        ReleaseTransactionPhase::RolledBack
                    } else {
                        ReleaseTransactionPhase::Committed
                    });
                }
                ReleaseChangePhase::AutomaticRollbackStarting => {
                    change.healthy_generation = Some(generation);
                    slot.previous_release = change.prior_previous.clone();
                    terminal_transaction_phase = Some(ReleaseTransactionPhase::RolledBack);
                }
                ReleaseChangePhase::WaitingForTargetExit => {}
            }
        }
        // Retain the transition until every outcome writer acknowledges its
        // durability boundary. A healthy Running process retries this path
        // after a failed CAS, journal write, or signed-intent publication.
        self.persist_release_state(agent_id, slot)?;
        if let Some(phase) = terminal_transaction_phase {
            self.advance_release_transaction(agent_id, slot, phase)?;
        }
        self.commit_signed_intent_if_target(agent_id, slot)?;
        if terminal_transaction_phase.is_some()
            && let Some(change) = slot.release_change.take()
        {
            match change.phase {
                ReleaseChangePhase::TargetStarting => {
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
                    slot.event(
                        generation,
                        SupervisorEventKind::AutomaticRollbackCommitted {
                            failed: change.target.identity().to_string(),
                            restored: change.origin.identity().to_string(),
                        },
                    );
                }
                ReleaseChangePhase::WaitingForTargetExit => {
                    slot.release_change = Some(change);
                }
            }
        }
        Ok(())
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
        let mut previous = slot
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
        if slot.release_change.is_none() && actual.current == current {
            // An unavailable/revoked rollback executable hydrates as None.
            // Its durable predecessor identity remains historical evidence;
            // ordinary health observations must not erase that evidence.
            slot.release_state_generation = actual.generation;
            return Ok(());
        }
        if slot.release_change.is_some() {
            let transaction = slot.release_transaction.as_ref().ok_or_else(|| {
                SupervisorError::Invalid("release transition has no prepared journal".to_string())
            })?;
            if slot
                .release_change
                .as_ref()
                .is_some_and(|change| change.phase == ReleaseChangePhase::AutomaticRollbackStarting)
            {
                previous = transaction
                    .rollback_predecessor
                    .as_ref()
                    .map(|value| codex_hepta_fleet::ReleaseId::parse(value.clone()))
                    .transpose()?;
            }
            let source_pair = actual
                .current
                .as_ref()
                .map(codex_hepta_fleet::ReleaseId::as_str)
                == Some(transaction.source_release.as_str())
                && actual
                    .previous
                    .as_ref()
                    .map(codex_hepta_fleet::ReleaseId::as_str)
                    == transaction.rollback_predecessor.as_deref();
            let target_pair = actual
                .current
                .as_ref()
                .map(codex_hepta_fleet::ReleaseId::as_str)
                == Some(transaction.target_release.as_str())
                && actual
                    .previous
                    .as_ref()
                    .map(codex_hepta_fleet::ReleaseId::as_str)
                    == Some(transaction.source_release.as_str());
            let expected = transaction.expected_release_state_generation;
            let source_frontier = source_pair && actual.generation == expected;
            let target_frontier = target_pair && expected.checked_add(1) == Some(actual.generation);
            if !source_frontier && !target_frontier {
                return Err(SupervisorError::Invalid(
                    "release state moved outside the prepared transition frontier".to_string(),
                ));
            }
            // Only exact desired publication is idempotent at the advanced
            // frontier. Never rebase a source restoration over target commit.
            if target_frontier && (actual.current != current || actual.previous != previous) {
                return Err(SupervisorError::Invalid(
                    "release state already committed another transition outcome".to_string(),
                ));
            }
        }
        if actual.current == current && actual.previous == previous {
            slot.release_state_generation = actual.generation;
            return Ok(());
        }
        let expected = slot
            .release_transaction
            .as_ref()
            .filter(|_| slot.release_change.is_some())
            .map(|transaction| transaction.expected_release_state_generation)
            .unwrap_or(slot.release_state_generation);
        let next = self
            .registry
            .compare_and_set_release_state(agent_id, expected, current, previous)?;
        slot.release_state_generation = next.generation;
        Ok(())
    }
}
