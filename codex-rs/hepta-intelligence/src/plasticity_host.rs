//! Named Lane-F caller for the learning.plasticity proposal engine.
//!
//! This adapter can persist a proposal candidate but still cannot select,
//! activate, train, install, promote or release it.

use codex_hepta_plasticity::ComposedParameterProposalRequestV1;
use codex_hepta_plasticity::DurableProposalAppendReceiptV1;
use codex_hepta_plasticity::DurableProposalRegistryError;
use codex_hepta_plasticity::EvidenceVerifier;
use codex_hepta_plasticity::IndependentEvaluatorVerifier;
use codex_hepta_plasticity::ProductionProposalRegistry;
use codex_hepta_plasticity::generate_authenticate_and_append_v1;

pub fn run_plasticity_proposal_cycle_v1(
    registry: &mut ProductionProposalRegistry,
    request: ComposedParameterProposalRequestV1,
    evidence_verifier: &impl EvidenceVerifier,
    evaluator_verifier: &impl IndependentEvaluatorVerifier,
) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
    generate_authenticate_and_append_v1(
        registry,
        request,
        evidence_verifier,
        evaluator_verifier,
    )
}
