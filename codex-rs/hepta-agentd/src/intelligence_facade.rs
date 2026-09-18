//! Agentd product caller for intelligence.control V3 envelopes.
//!
//! The intelligence facade prepares an authority-free envelope. Agentd admits
//! that exact envelope into its existing run coordinator and only marks dispatch
//! after the Codex execution path has actually accepted the run.

use codex_hepta_intelligence::CompositionErrorV3;
use codex_hepta_intelligence::IntelligenceHostEnvelopeV1;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::ContextAttachment;
use crate::RunReceipt;
use crate::RunSnapshot;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntelligenceFacadeCallerError {
    Envelope(CompositionErrorV3),
    Runtime(AgentRunError),
    Arithmetic,
}

pub struct AgentdIntelligenceCaller<'a> {
    coordinator: &'a mut AgentRunCoordinator,
}

impl<'a> AgentdIntelligenceCaller<'a> {
    pub fn new(coordinator: &'a mut AgentRunCoordinator) -> Self {
        Self { coordinator }
    }

    pub fn admit(
        &mut self,
        now_micros: u64,
        envelope: &IntelligenceHostEnvelopeV1,
    ) -> Result<RunReceipt, IntelligenceFacadeCallerError> {
        envelope
            .validate()
            .map_err(IntelligenceFacadeCallerError::Envelope)?;

        // Never widen an intelligence deadline while adapting micros to the
        // existing millisecond Agentd coordinator.  Floor the deadline and
        // ceil the observation time so the adapter can only fail earlier.
        let deadline_ms = envelope.deadline_micros / 1_000;
        let now_ms = now_micros
            .checked_add(999)
            .ok_or(IntelligenceFacadeCallerError::Arithmetic)?
            / 1_000;

        let started = self
            .coordinator
            .start_run(
                now_ms,
                RunSnapshot {
                    run_id: envelope.run_id.to_string(),
                    request_digest: envelope.request_digest.to_string(),
                    objective_digest: envelope.objective_digest.to_string(),
                    body_digest: envelope.body_digest.to_string(),
                    artifact_set_digest: envelope.artifact_set_digest.to_string(),
                    authority_epoch: envelope.authority_epoch,
                    deadline_ms,
                },
            )
            .map_err(IntelligenceFacadeCallerError::Runtime)?;

        self.coordinator
            .attach_context(
                started.revision,
                ContextAttachment {
                    run_id: envelope.run_id.to_string(),
                    request_digest: envelope.request_digest.to_string(),
                    objective_digest: envelope.objective_digest.to_string(),
                    body_digest: envelope.body_digest.to_string(),
                    artifact_set_digest: envelope.artifact_set_digest.to_string(),
                    context_digest: envelope.context_digest.to_string(),
                    compilation_receipt_digest: envelope.context_receipt_digest.to_string(),
                },
            )
            .map_err(IntelligenceFacadeCallerError::Runtime)
    }

    pub fn mark_dispatched(
        &mut self,
        envelope: &IntelligenceHostEnvelopeV1,
        expected_revision: u64,
    ) -> Result<RunReceipt, IntelligenceFacadeCallerError> {
        envelope
            .validate()
            .map_err(IntelligenceFacadeCallerError::Envelope)?;
        self.coordinator
            .mark_dispatched(envelope.run_id.as_str(), expected_revision)
            .map_err(IntelligenceFacadeCallerError::Runtime)
    }
}

#[cfg(test)]
#[path = "intelligence_facade_tests.rs"]
mod tests;
