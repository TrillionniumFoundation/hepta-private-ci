//! Constructor-only observations of metadata hydration that has no effect.
//! They never supply admission or mutation inputs. Every nonempty observation
//! is settled by another complete Fleet read and fresh witness absence checks.

use std::collections::BTreeMap;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;

use super::recovery_probe::known_absent;
use crate::MAX_SUPERVISORD_ROSTER;
use crate::SupervisorError;
use crate::runtime::AgentSlot;

pub(crate) enum ConstructorHydration<'a> {
    Fresh,
    Observe(&'a mut ConstructorHydrationObservation),
}

impl ConstructorHydration<'_> {
    pub(crate) fn observes_idle<P>(
        self,
        agent_id: &AgentId,
        slot: &AgentSlot<P>,
        record: &AgentRecord,
    ) -> bool {
        match self {
            Self::Fresh => false,
            Self::Observe(observation) => {
                idle_slot(slot) && observation.record_if_idle(agent_id, record)
            }
        }
    }
}

pub(super) fn idle_slot<P>(slot: &AgentSlot<P>) -> bool {
    slot.runtime.is_none()
        && slot.matrix.runtime.is_none()
        && slot.recovery_blocker.is_none()
        && slot.pending_control.is_none()
        && slot.exit_lease_removal.is_none()
        && slot.observed_exit.is_none()
        && slot.matrix.exit_lease_removal.is_none()
        && slot.matrix.observed_exit.is_none()
        && !slot.matrix.configured
        && !slot.matrix.degraded
        && slot.matrix.restart_attempt == 0
        && slot.matrix.restart_window_started_at.is_none()
        && slot.matrix.restart_window_started_unix_millis.is_none()
        && !slot.matrix.restart_after_exit
        && !slot.matrix.restart_exhausted
        && slot.matrix.last_error.is_none()
        && slot.matrix.retry_at.is_none()
        && slot.matrix.recovery_budget.is_none()
        && slot.deferred_agent_action.is_none()
        && !slot.restart_pending
        && slot.failed_restart_spawn.is_none()
        && slot.restart_not_before.is_none()
        && slot.restart_attempt == 0
        && slot.active_release.is_none()
        && slot.previous_release.is_none()
        && slot.last_command.is_none()
        && slot.release_change.is_none()
        && slot.release_transaction.is_none()
        && slot.signed_intent.is_none()
        && slot.release_state_generation == 0
        && slot.control_revision == 0
}

#[derive(Default)]
pub(crate) struct ConstructorHydrationObservation {
    observed: BTreeMap<AgentId, AgentRecord>,
}

impl ConstructorHydrationObservation {
    /// The caller separately proves that the slot has no owned process,
    /// pending work or recovery denial. Keep the first complete Fleet record;
    /// another observation must never overwrite evidence of a change.
    pub(crate) fn record_if_idle(&mut self, agent_id: &AgentId, record: &AgentRecord) -> bool {
        if record.layout.agent_id() != agent_id
            || &record.manifest.agent_id != agent_id
            || &record.lifecycle.agent_id != agent_id
            || &record.release_state.agent_id != agent_id
            || record.lifecycle.lifecycle != AgentLifecycle::Stopped
            || record.lifecycle.generation != 0
            || record.release_state.generation != 0
            || record.release_state.current.is_some()
            || record.release_state.previous.is_some()
            || !witnesses_absent(record)
        {
            return false;
        }
        if let Some(initial) = self.observed.get(agent_id) {
            return initial == record;
        }
        if self.observed.len() >= usize::from(MAX_SUPERVISORD_ROSTER) {
            return false;
        }
        self.observed.insert(agent_id.clone(), record.clone());
        true
    }

    pub(crate) fn agents(&self) -> impl Iterator<Item = &AgentId> {
        self.observed.keys()
    }

    /// A failed global read is returned to the constructor, which must deny
    /// observed slots while retaining every independently acquired owner.
    pub(crate) fn changed_agents(
        &self,
        registry: &FleetRegistry,
    ) -> Result<Vec<AgentId>, SupervisorError> {
        if self.observed.is_empty() {
            return Ok(Vec::new());
        }
        let current = registry.load()?;
        Ok(self
            .observed
            .iter()
            .filter(|&(agent_id, initial)| {
                current.agent(agent_id) != Some(initial) || !witnesses_absent(initial)
            })
            .map(|(agent_id, _initial)| agent_id.clone())
            .collect())
    }
}

fn witnesses_absent(record: &AgentRecord) -> bool {
    let main_absent = known_absent(
        record.layout.run_root(),
        &[
            crate::lease::PROCESS_LEASE_FILE,
            crate::control_intent::CONTROL_INTENT_FILE,
            crate::restart_journal::RESTART_JOURNAL_FILE,
            crate::restart_lineage::RESTART_LINEAGE_FILE,
            crate::release_transaction::RELEASE_TRANSACTION_FILE,
            crate::signed_intent::SIGNED_INTENT_FILE,
            crate::signed_intent::SIGNED_INTENT_RECOVERY_FILE,
        ],
    );
    let matrix = record.layout.matrixd_process_lease();
    let (Some(parent), Some(name)) = (
        matrix.parent(),
        matrix.file_name().and_then(|name| name.to_str()),
    ) else {
        return false;
    };
    main_absent && known_absent(parent, &[name])
}

#[cfg(test)]
#[path = "constructor_hydration_tests.rs"]
mod tests;
