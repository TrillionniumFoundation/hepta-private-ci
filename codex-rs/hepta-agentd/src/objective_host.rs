//! Runtime consumption of a durably published intelligence host envelope.
//!
//! Agentd owns only the ephemeral run handle. Objective and RunStart facts
//! remain owned by their producers and the durable learning-ledger journal.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;
use codex_hepta_intelligence::ProductionObjectiveError;
use codex_hepta_intelligence::ProductionObjectiveStartReceiptV1;
use codex_hepta_types::Digest32;

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
            Self::Envelope(error) => {
                write!(formatter, "invalid intelligence host envelope: {error}")
            }
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

/// Consume one already-durable objective publication into Agentd's ephemeral
/// run coordinator.
///
/// The opaque publication receipt can only be produced after the sealed durable
/// journal has accepted the complete admission/objective/RunStart event. Agentd
/// therefore does not expose the raw digest envelope as a public start surface.
/// No durable objective bytes are copied into Agentd; only exact digest bindings
/// survive in the ephemeral run coordinator.
pub fn start_published_intelligence_run_v1(
    coordinator: &mut AgentRunCoordinator,
    now_ms: u64,
    publication: &ProductionObjectiveStartReceiptV1,
    body_digest: Digest32,
) -> Result<RunReceipt, ObjectiveHostError> {
    publication
        .validate()
        .map_err(ObjectiveHostError::Envelope)?;
    start_host_envelope_v1(
        coordinator,
        now_ms,
        publication.host_envelope(),
        body_digest,
    )
}

fn start_host_envelope_v1(
    coordinator: &mut AgentRunCoordinator,
    now_ms: u64,
    envelope: &IntelligenceHostEnvelopeV1,
    body_digest: Digest32,
) -> Result<RunReceipt, ObjectiveHostError> {
    envelope.validate().map_err(ObjectiveHostError::Envelope)?;
    let deadline_micros = envelope
        .deadline_unix_micros()
        .ok_or(ObjectiveHostError::DeadlineMissing)?;
    let deadline_ms = deadline_micros / 1_000;
    let run_start = envelope.run_start();

    coordinator
        .start_run(
            now_ms,
            RunSnapshot {
                run_id: run_start.run_id.to_string(),
                request_digest: envelope.admitted_source_digest().to_string(),
                objective_digest: run_start.objective_digest.to_string(),
                body_digest: body_digest.to_string(),
                artifact_set_digest: run_start.artifact_set_digest.to_string(),
                authority_epoch: run_start.authority_epoch,
                generation: run_start.generation,
                fence_digest: run_start.fence_digest.to_string(),
                deadline_ms,
            },
        )
        .map_err(ObjectiveHostError::Runtime)
}

#[cfg(test)]
#[path = "objective_host_tests.rs"]
mod tests;
