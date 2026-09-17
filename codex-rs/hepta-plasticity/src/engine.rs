//! Product-composable plasticity proposal engine.
//!
//! This surface composes the deterministic native generator, authenticated
//! evidence/evaluator boundary, V2 verifier and production-safe durable writer.
//! It still grants no selection, activation, training, installation or release
//! authority.

use codex_hepta_types::Digest32;

use crate::AuthenticatedParameterProposalRequestV1;
use crate::CandidateGeneratorConfigV1;
use crate::DurableProposalAppendReceiptV1;
use crate::DurableProposalRegistryError;
use crate::EvaluatorClaimV1;
use crate::EvidenceClaimV1;
use crate::EvidenceVerifier;
use crate::IndependentEvaluatorVerifier;
use crate::ParameterCandidateRequestV2;
use crate::ParameterLearningSignalV1;
use crate::ParameterProposalRequestV2;
use crate::ProductionProposalRegistry;
use crate::generate_parameter_proposal_v2;
use crate::propose_authenticated_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ComposedParameterProposalRequestV1 {
    /// Candidate list must be empty; candidates are generated natively.
    pub request: ParameterProposalRequestV2,
    pub signals: Vec<ParameterLearningSignalV1>,
    pub generator: CandidateGeneratorConfigV1,
    pub evidence: Vec<EvidenceClaimV1>,
    pub evaluator: EvaluatorClaimV1,
    pub now_ms: u64,
    pub expected_predecessor_frame_digest: Digest32,
}

pub fn generate_authenticate_and_append_v1(
    registry: &mut ProductionProposalRegistry,
    composed: ComposedParameterProposalRequestV1,
    evidence_verifier: &impl EvidenceVerifier,
    evaluator_verifier: &impl IndependentEvaluatorVerifier,
) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
    let proposal = generate_parameter_proposal_v2(
        composed.request,
        composed.signals,
        composed.generator,
    )?;
    let authenticated_request = request_from_generated_proposal(&proposal);
    let authenticated = propose_authenticated_v1(
        AuthenticatedParameterProposalRequestV1 {
            request: authenticated_request,
            evidence: composed.evidence,
            evaluator: composed.evaluator,
            now_ms: composed.now_ms,
        },
        evidence_verifier,
        evaluator_verifier,
    )?;
    if authenticated != proposal {
        return Err(DurableProposalRegistryError::Corrupt);
    }
    registry.append_v2(composed.expected_predecessor_frame_digest, authenticated)
}

fn request_from_generated_proposal(
    proposal: &crate::ParameterProposalV2,
) -> ParameterProposalRequestV2 {
    ParameterProposalRequestV2 {
        proposal_id: proposal.proposal_id.clone(),
        proposer_id: proposal.proposer_id.clone(),
        evaluator_id: proposal.evaluator_id.clone(),
        selected_artifact_digest: proposal.selected_artifact_digest,
        window: proposal.window.clone(),
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        dataset_digest: proposal.dataset_digest,
        update_rule_digest: proposal.update_rule_digest,
        modulator_digest: proposal.modulator_digest,
        modulator_broadcast_digest: proposal.modulator_broadcast_digest,
        eligibility_digest: proposal.eligibility_digest,
        evaluation_digest: proposal.evaluation_digest,
        rollback_predecessor_digest: proposal.rollback_predecessor_digest,
        norm_layers: proposal.norm_profile.layers.clone(),
        candidates: proposal
            .candidates
            .iter()
            .map(|candidate| ParameterCandidateRequestV2 {
                candidate_id: candidate.candidate_id.clone(),
                kind: candidate.kind,
                parameter_deltas: candidate.parameter_deltas.clone(),
            })
            .collect(),
    }
}
