//! Preserve authenticated policy evidence across the final Agentd admission.
//!
//! This is a result envelope on the existing canonical path, not an admission
//! authority or a second runner. V1 remains the compatibility runner result.

use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_intuition::ProductionDispositionV1;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIntelligenceAdmittedOutcomeV1;
use crate::AgentdIntuitionDecisionReceiptV2;
use crate::AgentdIntuitionServiceErrorV1;
use crate::RunPhase;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CanonicalIntuitionAdmissionV2 {
    outcome: AgentdIntelligenceAdmittedOutcomeV1,
    policy_receipt: Option<AgentdIntuitionDecisionReceiptV2>,
    binding_digest: Option<Digest32>,
}

impl CanonicalIntuitionAdmissionV2 {
    pub(crate) fn disposition(&self) -> &'static str {
        match &self.outcome {
            AgentdIntelligenceAdmittedOutcomeV1::Ready { .. } => "canonical_ready",
            AgentdIntelligenceAdmittedOutcomeV1::Abstained => "canonical_abstained",
            AgentdIntelligenceAdmittedOutcomeV1::SlowPath => "canonical_slow_path",
        }
    }

    pub(crate) fn policy_receipt(&self) -> Option<&AgentdIntuitionDecisionReceiptV2> {
        self.policy_receipt.as_ref()
    }

    pub(crate) fn binding_digest(&self) -> Option<Digest32> {
        self.binding_digest
    }
}

/// Convert every post-policy failure without losing its acknowledged receipt.
/// The caller must enforce the process profile before invoking the pipeline;
/// absence of a policy receipt represents explicit development compatibility.
pub(crate) fn finish_canonical_admission(
    admission: Result<AgentdIntelligenceAdmittedOutcomeV1, AgentdError>,
    policy_receipt: Option<AgentdIntuitionDecisionReceiptV2>,
) -> Result<CanonicalIntuitionAdmissionV2, AgentdError> {
    let Some(receipt) = policy_receipt else {
        return admission.map(|outcome| CanonicalIntuitionAdmissionV2 {
            outcome,
            policy_receipt: None,
            binding_digest: None,
        });
    };
    let bound = admission.and_then(|outcome| {
        bind_admitted_outcome(&outcome, &receipt).map(|digest| (outcome, digest))
    });
    match bound {
        Ok((outcome, digest)) => Ok(CanonicalIntuitionAdmissionV2 {
            outcome,
            policy_receipt: Some(receipt),
            binding_digest: Some(digest),
        }),
        Err(source) => Err(AgentdIntuitionServiceErrorV1::AdmissionFailedAfterPolicy {
            receipt,
            source: Box::new(source),
        }
        .into()),
    }
}

fn mismatch() -> AgentdError {
    AgentdError::Protocol("agentd.intuition.service.admitted_binding_mismatch".to_string())
}

fn bind_admitted_outcome(
    outcome: &AgentdIntelligenceAdmittedOutcomeV1,
    receipt: &AgentdIntuitionDecisionReceiptV2,
) -> Result<Digest32, AgentdError> {
    if receipt.service_receipt_digest.is_zero()
        || receipt.host_binding_digest.is_zero()
        || receipt.decision.authentication_digest.is_zero()
        || receipt.decision.decision.authority.grants_any()
    {
        return Err(mismatch());
    }
    let identity = (
        "hepta.agentd.intuition-admitted.v2",
        receipt.service_receipt_digest.to_string(),
        receipt.host_binding_digest.to_string(),
        receipt.decision.authentication_digest.to_string(),
    );
    let bytes = match (outcome, &receipt.decision.decision.disposition) {
        (
            AgentdIntelligenceAdmittedOutcomeV1::Ready {
                prepared,
                run_receipt,
            },
            ProductionDispositionV1::Selected(selected),
        ) => {
            let AdvisoryDecisionV1::Selected {
                candidate_id,
                propensity,
            } = &prepared.envelope.decision.decision
            else {
                return Err(mismatch());
            };
            let rows = &receipt.decision.decision.propensities;
            if candidate_id != selected
                || propensity.raw() == 0
                || rows.iter().filter(|row| &row.candidate_id == selected).count() != 1
                || !rows.iter().any(|row| {
                    &row.candidate_id == selected && row.probability == *propensity
                })
                || receipt.learning.is_none()
                || receipt.production_record_id.is_none()
            {
                return Err(mismatch());
            }
            let snapshot = prepared.run_snapshot();
            let attachment = prepared.context_attachment();
            if run_receipt.run_id != snapshot.run_id
                || run_receipt.phase != RunPhase::ContextAttached
                || run_receipt.authority_epoch != snapshot.authority_epoch
                || run_receipt.generation != snapshot.generation
                || run_receipt.fence_digest != snapshot.fence_digest
                || run_receipt.deadline_ms != snapshot.deadline_ms
                || run_receipt.context_digest.as_ref() != Some(&attachment.context_digest)
                || run_receipt.compilation_receipt_digest.as_ref()
                    != Some(&attachment.compilation_receipt_digest)
                || run_receipt.terminal_observed
                || run_receipt.cancel_reason.is_some()
                || run_receipt.cancel_ack_deadline_ms.is_some()
            {
                return Err(mismatch());
            }
            // The phase is fixed above. Bind the complete immutable snapshot,
            // context attachment, proposal and observed final revision instead
            // of hashing Debug output or only the selected candidate name.
            serde_json::to_vec(&(
                identity,
                "ready",
                prepared.dispatch_proposal_digest.to_string(),
                snapshot,
                attachment,
                run_receipt.revision,
                run_receipt.idempotent,
            ))?
        }
        (
            AgentdIntelligenceAdmittedOutcomeV1::Abstained,
            ProductionDispositionV1::Abstained(_),
        ) => {
            if receipt.learning.is_some() || receipt.production_record_id.is_some() {
                return Err(mismatch());
            }
            serde_json::to_vec(&(identity, "abstained"))?
        }
        (
            AgentdIntelligenceAdmittedOutcomeV1::SlowPath,
            ProductionDispositionV1::SlowPath(_),
        ) => {
            if receipt.learning.is_some() || receipt.production_record_id.is_some() {
                return Err(mismatch());
            }
            serde_json::to_vec(&(identity, "slow_path"))?
        }
        _ => return Err(mismatch()),
    };
    Ok(Digest32::of_bytes(&bytes))
}

#[cfg(test)]
#[path = "intuition_policy_admission_tests.rs"]
mod tests;
