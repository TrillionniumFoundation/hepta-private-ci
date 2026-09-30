//! Immutable, bounded observation cache, not an authority or a mutation input.
//! Every mutation still compares its fence to the live owner state under lock.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::RwLock;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::FleetRegistry;

use super::SupervisorEpoch;
use super::SupervisordAgentStatus;
use super::SupervisordHealth;
use super::SupervisordMethod;
use super::SupervisordPayload;
use super::error_payload;
use super::status_from;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::daemon_protocol::MAX_SUPERVISORD_ROSTER;

const MAX_AGE: Duration = Duration::from_secs(2);

struct Observation {
    captured_at: Instant,
    epoch: SupervisorEpoch,
    ready: bool,
    agents: BTreeMap<AgentId, SupervisordAgentStatus>,
}

#[derive(Default)]
pub(super) struct ReadView {
    current: RwLock<Option<Arc<Observation>>>,
}

impl ReadView {
    /// Caller holds the lifecycle owner lock, never the read-view lock, during I/O.
    /// Start the freshness clock before capture so a slow capture cannot look new.
    pub(super) fn publish<D: ProcessDriver>(
        &self,
        registry: &FleetRegistry,
        supervisor: &Supervisor<D>,
        epoch: &SupervisorEpoch,
    ) -> Result<(), SupervisorError> {
        let captured_at = Instant::now();
        let snapshot = registry.load()?;
        if snapshot.agents.len() > usize::from(MAX_SUPERVISORD_ROSTER) {
            return Err(SupervisorError::Invalid(
                "read view exceeds roster limit".to_string(),
            ));
        }
        let mut agents = BTreeMap::new();
        let mut ownership_ready = true;
        for (agent_id, record) in snapshot.agents {
            let runtime = supervisor.snapshot(&agent_id);
            ownership_ready &= crate::recovery::process_ownership_ready(&record, runtime.as_ref())?;
            let status = status_from(epoch, &record, runtime)?;
            agents.insert(agent_id, status);
        }
        let observation = Arc::new(Observation {
            captured_at,
            epoch: epoch.clone(),
            ready: ownership_ready && !supervisor.any_production_recovery_required(),
            agents,
        });
        let mut current = self.current.write().map_err(|_| {
            SupervisorError::Invalid("supervisord read view is unavailable".to_string())
        })?;
        *current = Some(observation);
        Ok(())
    }

    pub(super) fn invalidate(&self) {
        if let Ok(mut current) = self.current.write() {
            *current = None;
        }
        // Poison is also fail-closed: respond() never recovers poisoned contents.
    }

    pub(super) fn respond(
        &self,
        method: &SupervisordMethod,
        now: Instant,
        observed_faults: u64,
    ) -> Option<SupervisordPayload> {
        if !matches!(
            method,
            SupervisordMethod::Health
                | SupervisordMethod::Roster { .. }
                | SupervisordMethod::Snapshot { .. }
        ) {
            return None;
        }
        if let SupervisordMethod::Roster { limit } = method
            && !(1..=MAX_SUPERVISORD_ROSTER).contains(limit)
        {
            return Some(error_payload(
                "invalid_frame",
                "invalid roster limit",
                /*actual*/ None,
            ));
        }
        // Only clone the Arc under the lock; encoding and vector copies happen after it.
        let observation = self.current.read().ok().and_then(|current| current.clone());
        let Some(view) = observation.filter(|view| {
            now.checked_duration_since(view.captured_at)
                .is_some_and(|age| age <= MAX_AGE)
        }) else {
            return Some(unavailable());
        };
        Some(match method {
            SupervisordMethod::Health => SupervisordPayload::Health(SupervisordHealth {
                ready: view.ready,
                supervisor_epoch: view.epoch.clone(),
                process_id: std::process::id(),
                // publish() enforces the smaller, u16 roster bound.
                registered_agents: view.agents.len() as u16,
                observed_faults,
            }),
            SupervisordMethod::Roster { limit } => SupervisordPayload::Roster {
                agents: view
                    .agents
                    .values()
                    .take(usize::from(*limit))
                    .cloned()
                    .collect(),
            },
            SupervisordMethod::Snapshot { agent_id } => match view.agents.get(agent_id) {
                Some(agent) => SupervisordPayload::Agent(agent.clone()),
                None => error_payload(
                    "unknown_agent",
                    "selected Agent is not registered",
                    /*actual*/ None,
                ),
            },
            // All other methods use the live owner path, never this observation.
            SupervisordMethod::ReleaseSelection { .. }
            | SupervisordMethod::ProductionMutationStatus { .. }
            | SupervisordMethod::Start { .. }
            | SupervisordMethod::Drain { .. }
            | SupervisordMethod::Stop { .. }
            | SupervisordMethod::Kill { .. }
            | SupervisordMethod::Restart { .. }
            | SupervisordMethod::Upgrade { .. }
            | SupervisordMethod::Rollback { .. }
            | SupervisordMethod::SignedUpgrade { .. }
            | SupervisordMethod::SignedRollback { .. }
            | SupervisordMethod::ResolveProductionRecovery { .. } => return None,
        })
    }
}

pub(super) fn unavailable() -> SupervisordPayload {
    error_payload(
        "control_state_unavailable",
        "supervisord observation is unavailable or expired; refresh before retry",
        /*actual*/ None,
    )
}

#[cfg(test)]
#[path = "daemon_read_view_tests.rs"]
mod tests;
