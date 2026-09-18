//! Runtime consumption of a durably published intelligence host envelope.
//!
//! Agentd owns only the ephemeral run handle. Objective and RunStart facts
//! remain owned by their producers and the durable learning-ledger journal.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_intelligence::ProductionObjectiveError;
use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::RunReceipt;
use crate::RunSnapshot;

#[derive(Debug)]
pub enum ObjectiveHostError {
    Envelope(ProductionObjectiveError),
    DeadlineMissing,
    Runtime(AgentRunError),
}

impl fmt::Display for ObjectiveHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Envelope(error) => write!(formatter, "invalid intelligence host envelope: {error}"),
            Self::DeadlineMissing => {
                formatter.write_str("production objective run requires an admitted deadline")
            }
            Self::Runtime(error) => write!(formatter, "agent run admission failed: {error:?}"),
        }
    }
}

impl StdError for ObjectiveHostError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Envelope(error) => Some(error),
            Self::DeadlineMissing | Self::Runtime(_) => None,
        }
    }
}

/// Consume one already-durable, deny-all objective envelope into Agentd's
/// ephemeral run coordinator.
///
/// No durable objective bytes are copied into Agentd. The runtime stores only
/// exact digest references and requires context attachment before dispatch.
pub fn start_intelligence_run_v1(
    coordinator: &mut AgentRunCoordinator,
    now_ms: u64,
    envelope: &IntelligenceHostEnvelopeV1,
) -> Result<RunReceipt, ObjectiveHostError> {
    envelope.validate().map_err(ObjectiveHostError::Envelope)?;
    let deadline_micros = envelope
        .deadline_unix_micros
        .ok_or(ObjectiveHostError::DeadlineMissing)?;
    let deadline_ms = deadline_micros / 1_000;

    coordinator
        .start_run(
            now_ms,
            RunSnapshot {
                run_id: envelope.run_start.run_id.to_string(),
                request_digest: envelope.admitted_source_digest.to_string(),
                objective_digest: envelope.run_start.objective_digest.to_string(),
                body_digest: envelope.runtime_body_digest.to_string(),
                artifact_set_digest: envelope.run_start.artifact_set_digest.to_string(),
                authority_epoch: envelope.run_start.authority_epoch,
                deadline_ms,
            },
        )
        .map_err(ObjectiveHostError::Runtime)
}
