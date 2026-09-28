//! Final Agentd admission binds the authenticated policy to the actual run/context.
//! This receipt is observational and grants no execution or effect authority.

use codex_hepta_agent_protocol::ObjectiveIntuitionAdmissionV1;
use codex_hepta_intuition::ProductionDispositionV1;
use codex_hepta_types::Digest32;
use crate::AgentdError;
use crate::AgentdIntuitionDecisionReceiptV2;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::RunPhase;
use crate::RunReceipt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntuitionAdmittedReceiptV1 {
    policy: AgentdIntuitionDecisionReceiptV2,
    admission_digest: Digest32,
}

impl AgentdIntuitionAdmittedReceiptV1 {
    pub(crate) fn bind_ready(
        policy: AgentdIntuitionDecisionReceiptV2,
        prepared: &PreparedAgentdIntelligenceRunV1,
        run: &RunReceipt,
    ) -> Result<Self, AgentdError> {
        let snapshot = prepared.run_snapshot();
        let context = prepared.context_attachment();
        if !matches!(policy.decision.decision.disposition, ProductionDispositionV1::Selected(_))
            || policy.learning.is_none() || policy.production_record_id.is_none()
            || run.phase != RunPhase::ContextAttached || run.run_id != snapshot.run_id
            || run.authority_epoch != snapshot.authority_epoch || run.generation != snapshot.generation
            || run.fence_digest != snapshot.fence_digest || run.deadline_ms != snapshot.deadline_ms
            || run.context_digest.as_deref() != Some(context.context_digest.as_str())
            || run.compilation_receipt_digest.as_deref() != Some(context.compilation_receipt_digest.as_str())
            || run.cancel_reason.is_some() || run.terminal_observed
        {
            return Err(AgentdError::Protocol("agentd.intuition.admission.binding_mismatch".to_string()));
        }
        let bytes = serde_json::to_vec(&(
            "hepta.agentd.intuition-admission.v1", policy.service_receipt_digest.to_string(),
            prepared.envelope.envelope_digest.to_string(), prepared.dispatch_proposal_digest.to_string(),
            snapshot, context, run.revision,
        ))?;
        Ok(Self { policy, admission_digest: Digest32::of_bytes(&bytes) })
    }

    pub(crate) fn bind_terminal(
        policy: AgentdIntuitionDecisionReceiptV2,
        run_id: &str,
        run_snapshot_digest: Digest32,
    ) -> Result<Self, AgentdError> {
        if matches!(policy.decision.decision.disposition, ProductionDispositionV1::Selected(_))
            || policy.learning.is_some() || policy.production_record_id.is_some()
            || run_id.is_empty() || run_snapshot_digest.is_zero()
        {
            return Err(AgentdError::Protocol("agentd.intuition.admission.terminal_mismatch".to_string()));
        }
        let bytes = serde_json::to_vec(&(
            "hepta.agentd.intuition-terminal-admission.v1", run_id,
            run_snapshot_digest.to_string(), policy.service_receipt_digest.to_string(),
        ))?;
        Ok(Self { policy, admission_digest: Digest32::of_bytes(&bytes) })
    }

    #[must_use]
    pub fn policy(&self) -> &AgentdIntuitionDecisionReceiptV2 { &self.policy }
    #[must_use]
    pub const fn admission_digest(&self) -> Digest32 { self.admission_digest }
    #[must_use]
    pub fn wire_receipt(&self) -> ObjectiveIntuitionAdmissionV1 {
        ObjectiveIntuitionAdmissionV1 {
            schema_version: 1,
            admission_digest: self.admission_digest.to_string(),
            service_receipt_digest: self.policy.service_receipt_digest.to_string(),
            authentication_digest: self.policy.decision.authentication_digest.to_string(),
            production_record_id: self.policy.production_record_id.as_ref().map(ToString::to_string),
            ledger_event_digest: self.policy.learning.as_ref().map(|value| value.event_digest.to_string()),
            ledger_chain_digest: self.policy.learning.as_ref().map(|value| value.chain_digest.to_string()),
            ledger_sequence: self.policy.learning.as_ref().map(|value| value.sequence.get()),
        }
    }
}
