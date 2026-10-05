//! One fresh registry observation for a single lifecycle maintenance pass.
//! It supplies generation observations and known layout paths only. Control
//! admission and every durable transition retain their fresh reads and CAS.
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetSnapshot;

use super::Supervisor;
use crate::ProcessDriver;
use crate::SupervisorError;

pub(super) enum TickRegistryObservation {
    Pending,
    Captured(FleetSnapshot),
    Unavailable,
}

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn record_for_tick(
        &mut self,
        agent_id: &AgentId,
    ) -> Result<AgentRecord, SupervisorError> {
        if matches!(&self.tick_records, Some(TickRegistryObservation::Pending)) {
            // Capture lazily, after the existing fenced/observed-exit cleanup
            // branches. A full registry read must not precede emergency signals.
            self.tick_records = Some(match self.registry.load() {
                Ok(snapshot) => TickRegistryObservation::Captured(snapshot),
                Err(_) => TickRegistryObservation::Unavailable,
            });
        }
        match &self.tick_records {
            Some(TickRegistryObservation::Captured(snapshot)) => snapshot
                .agent(agent_id)
                .cloned()
                .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone())),
            // Keep the original exact storage error and containment path when
            // capture failed; outside tick there is no observation to reuse.
            _ => self.record(agent_id),
        }
    }
}
