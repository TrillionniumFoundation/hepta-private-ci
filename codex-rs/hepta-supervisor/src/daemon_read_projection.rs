//! Reuse derived status only after a fresh, complete capture compares equal.
//! Fleet I/O, metadata scanning and ownership readiness remain outside this
//! cache. In particular, control_revision alone is not a dirty marker.

use std::sync::Arc;

use codex_hepta_fleet::AgentRecord;

use super::SupervisorEpoch;
use super::SupervisordAgentStatus;
use crate::AgentSupervisorSnapshot;
use crate::SupervisorError;
use crate::daemon::status_from;

#[derive(Eq, PartialEq)]
pub(super) struct ProjectionInput {
    epoch: SupervisorEpoch,
    record: AgentRecord,
    runtime: AgentSupervisorSnapshot,
}

impl ProjectionInput {
    pub(super) fn capture(
        epoch: &SupervisorEpoch,
        record: AgentRecord,
        runtime: Option<AgentSupervisorSnapshot>,
        previous: Option<(&Self, &Arc<SupervisordAgentStatus>)>,
    ) -> Result<(Self, Arc<SupervisordAgentStatus>), SupervisorError> {
        let runtime = runtime
            .ok_or_else(|| SupervisorError::UnknownAgent(record.manifest.agent_id.clone()))?;
        let input = Self {
            epoch: epoch.clone(),
            record,
            runtime,
        };
        let status = match previous {
            Some((prior, status)) if prior == &input => Arc::clone(status),
            // Complete record and metadata equality also covers fields that
            // only affect the hidden CAS digest, health and Matrix changes
            // without a revision increment, and external Fleet CAS writes.
            _ => Arc::new(status_from(
                epoch,
                &input.record,
                Some(input.runtime.clone()),
            )?),
        };
        Ok((input, status))
    }
}
