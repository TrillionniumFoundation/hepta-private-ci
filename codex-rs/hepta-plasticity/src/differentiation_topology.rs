//! Exact binding into the existing topology proposal owner. Research comparison
//! evidence never substitutes for that owner's independent acceptance.

use codex_hepta_types::Digest32;

use crate::TopologyChangeV2;
use crate::TopologyOperationV2;
use crate::TopologyProposalRequestV2;
use crate::TopologyProposalV2;
use crate::differentiation_study::DifferentiationStudyReceiptV1;
use crate::differentiation_types::DifferentiationConclusionV1;
use crate::differentiation_types::DifferentiationErrorV1;
use crate::differentiation_types::DifferentiationPlanV1;
use crate::propose_topology_v2;

/// Check the proposed split and the actual child artifact together. This does
/// not authenticate the study or replace writer handoff and owner admission.
pub fn validate_differentiation_topology_binding_v1(
    plan: &DifferentiationPlanV1,
    receipt: &DifferentiationStudyReceiptV1,
    candidate_artifact_digest: Digest32,
    change: &TopologyChangeV2,
) -> Result<(), DifferentiationErrorV1> {
    let request = &plan.request;
    if receipt.plan_digest != plan.plan_digest
        || receipt.candidate_artifact_digest != candidate_artifact_digest
        || receipt.conclusion != DifferentiationConclusionV1::RecommendForOwnerReview
        || change.operation != TopologyOperationV2::Split
        || change.module_id != request.module_id
        || change.predecessor_digest != Some(request.parent.topology_digest)
        || change.candidate_digest != Some(receipt.candidate_topology_digest)
        || change.capability_typing_digest != request.parent.capability_digest
        || change.compatibility_plan_digest != request.compatibility_plan_digest
        || change.migration_digest != request.migration_plan_digest
        || change.rollback_digest != request.rollback_plan_digest
        || change.evidence_digest != receipt.receipt_digest
    {
        return Err(DifferentiationErrorV1::TopologyBinding);
    }
    Ok(())
}

/// The study ID also identifies the proposal and window. The comparison digest
/// is research evidence: the existing proposal still requires independent
/// acceptance and grants no runtime, writer, selection or deployment authority.
pub fn propose_differentiation_topology_v1(
    plan: &DifferentiationPlanV1,
    receipt: &DifferentiationStudyReceiptV1,
    request: TopologyProposalRequestV2,
) -> Result<TopologyProposalV2, DifferentiationErrorV1> {
    let frozen = &plan.request;
    let next_generation = frozen
        .parent
        .generation
        .next()
        .map_err(|_| DifferentiationErrorV1::Arithmetic)?;
    if request.proposal_id != frozen.study_id
        || request.window.window_id != frozen.study_id
        || request.window.window_digest != plan.plan_digest
        || request.selected_artifact_digest != frozen.parent.artifact_digest
        || request.rollback_predecessor_digest != frozen.parent.artifact_digest
        || request.baseline_generation != frozen.parent.generation
        || request.candidate_generation != next_generation
        || request.proposer_id != frozen.actors.generator.principal
        || request.evaluator_id != frozen.actors.evaluator.principal
        || request.evaluation_digest != receipt.receipt_digest
        || request.changes.len() != 1
    {
        return Err(DifferentiationErrorV1::TopologyBinding);
    }
    validate_differentiation_topology_binding_v1(
        plan,
        receipt,
        receipt.candidate_artifact_digest,
        &request.changes[0],
    )?;
    propose_topology_v2(request).map_err(DifferentiationErrorV1::TopologyProposal)
}
