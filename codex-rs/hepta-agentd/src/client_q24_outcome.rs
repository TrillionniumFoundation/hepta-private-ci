//! Submit only the original independently signed business observation.
//! A missing or rejected reply never proves that the original append did not
//! occur. Reconcile or retry the exact same evidence; do not renew its signature.

use codex_hepta_agent_protocol::Q24OriginalTaskObservationV1;
use codex_hepta_agent_protocol::Q24OriginalTerminalOutcomeReceiptV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::AgentdClient;
use super::unexpected;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;

impl AgentdClient {
    /// Read the original task data for an independently operated Observer.
    /// The reply is neither a business label nor signing or Dataset authority.
    pub async fn original_q24_task_observation(
        &self,
    ) -> Result<Q24OriginalTaskObservationV1, AgentdError> {
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::Q24OriginalTaskObservation {},
            })
            .await?;
        match response.payload {
            AgentdPayload::Q24OriginalTaskObservation(observed) => Ok(observed),
            payload => unexpected(payload),
        }
    }

    pub async fn submit_original_q24_terminal_outcome(
        &self,
        outcome: &AuthenticatedOutcomeV1,
        signed: &SignedLearningEvidenceV1,
    ) -> Result<Q24OriginalTerminalOutcomeReceiptV1, AgentdError> {
        let request = crate::cell_q24_task_ledger::control::encode(outcome, signed)?;
        let response = self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::Q24OriginalTerminalOutcome {
                    request: Box::new(request),
                },
            })
            .await?;
        match response.payload {
            AgentdPayload::Q24OriginalTerminalOutcome(receipt) => Ok(receipt),
            payload => unexpected(payload),
        }
    }
}
