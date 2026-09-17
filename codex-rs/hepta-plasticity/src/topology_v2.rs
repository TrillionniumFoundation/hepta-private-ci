//! Bounded topology proposal construction.
//!
//! A topology proposal contains exactly one typed structural operation for the
//! exact successor generation. It is a candidate only: this module deliberately
//! exposes no graph mutation, writer handoff, activation or self-promotion API.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ProposalStatus;
use crate::ProposalWindowV2;
use crate::TopologyOperation;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalRequestV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_topology_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub module_id: StableId,
    pub operation: TopologyOperation,
    pub predecessor_topology_digest: Digest32,
    pub candidate_topology_digest: Digest32,
    pub compatibility_plan_digest: Digest32,
    pub resource_delta_digest: Digest32,
    pub security_review_digest: Digest32,
    pub lesion_plan_digest: Digest32,
    pub rollback_plan_digest: Digest32,
    pub evaluation_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_topology_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub module_id: StableId,
    pub operation: TopologyOperation,
    pub predecessor_topology_digest: Digest32,
    pub candidate_topology_digest: Digest32,
    pub compatibility_plan_digest: Digest32,
    pub resource_delta_digest: Digest32,
    pub security_review_digest: Digest32,
    pub lesion_plan_digest: Digest32,
    pub rollback_plan_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub proposal_digest: Digest32,
    pub status: ProposalStatus,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyProposalErrorV2 {
    SelfEvaluation,
    GenerationNotExactSuccessor,
    EmptyDigest(&'static str),
    PredecessorMismatch,
    TopologyUnchanged,
    ProposalDigestMismatch,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for TopologyProposalErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TopologyProposalErrorV2 {}

pub fn propose_topology_v2(
    request: TopologyProposalRequestV2,
) -> Result<TopologyProposalV2, TopologyProposalErrorV2> {
    validate_header(&request)?;
    let mut proposal = TopologyProposalV2 {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        selected_topology_artifact_digest: request.selected_topology_artifact_digest,
        window: request.window,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        module_id: request.module_id,
        operation: request.operation,
        predecessor_topology_digest: request.predecessor_topology_digest,
        candidate_topology_digest: request.candidate_topology_digest,
        compatibility_plan_digest: request.compatibility_plan_digest,
        resource_delta_digest: request.resource_delta_digest,
        security_review_digest: request.security_review_digest,
        lesion_plan_digest: request.lesion_plan_digest,
        rollback_plan_digest: request.rollback_plan_digest,
        evaluation_digest: request.evaluation_digest,
        proposal_digest: Digest32::ZERO,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    };
    proposal.proposal_digest = digest_topology_proposal_v2(&proposal)?;
    verify_topology_proposal_v2(&proposal)?;
    Ok(proposal)
}

pub fn verify_topology_proposal_v2(
    proposal: &TopologyProposalV2,
) -> Result<(), TopologyProposalErrorV2> {
    validate_header(&TopologyProposalRequestV2 {
        proposal_id: proposal.proposal_id.clone(),
        proposer_id: proposal.proposer_id.clone(),
        evaluator_id: proposal.evaluator_id.clone(),
        selected_topology_artifact_digest: proposal.selected_topology_artifact_digest,
        window: proposal.window.clone(),
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        module_id: proposal.module_id.clone(),
        operation: proposal.operation,
        predecessor_topology_digest: proposal.predecessor_topology_digest,
        candidate_topology_digest: proposal.candidate_topology_digest,
        compatibility_plan_digest: proposal.compatibility_plan_digest,
        resource_delta_digest: proposal.resource_delta_digest,
        security_review_digest: proposal.security_review_digest,
        lesion_plan_digest: proposal.lesion_plan_digest,
        rollback_plan_digest: proposal.rollback_plan_digest,
        evaluation_digest: proposal.evaluation_digest,
    })?;
    if proposal.authority.grants_any() {
        return Err(TopologyProposalErrorV2::AuthorityGranted);
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_topology_proposal_v2(proposal)?
    {
        return Err(TopologyProposalErrorV2::ProposalDigestMismatch);
    }
    Ok(())
}

fn validate_header(request: &TopologyProposalRequestV2) -> Result<(), TopologyProposalErrorV2> {
    if request.proposer_id == request.evaluator_id {
        return Err(TopologyProposalErrorV2::SelfEvaluation);
    }
    if request.baseline_generation.next() != Ok(request.candidate_generation) {
        return Err(TopologyProposalErrorV2::GenerationNotExactSuccessor);
    }
    for (label, digest) in [
        ("selected topology artifact", request.selected_topology_artifact_digest),
        ("window", request.window.window_digest),
        ("predecessor topology", request.predecessor_topology_digest),
        ("candidate topology", request.candidate_topology_digest),
        ("compatibility plan", request.compatibility_plan_digest),
        ("resource delta", request.resource_delta_digest),
        ("security review", request.security_review_digest),
        ("lesion plan", request.lesion_plan_digest),
        ("rollback plan", request.rollback_plan_digest),
        ("evaluation", request.evaluation_digest),
    ] {
        if digest.is_zero() {
            return Err(TopologyProposalErrorV2::EmptyDigest(label));
        }
    }
    if request.predecessor_topology_digest != request.selected_topology_artifact_digest {
        return Err(TopologyProposalErrorV2::PredecessorMismatch);
    }
    if request.predecessor_topology_digest == request.candidate_topology_digest {
        return Err(TopologyProposalErrorV2::TopologyUnchanged);
    }
    Ok(())
}

fn digest_topology_proposal_v2(
    proposal: &TopologyProposalV2,
) -> Result<Digest32, TopologyProposalErrorV2> {
    let mut bytes = b"hepta.plasticity.topology-proposal.v2".to_vec();
    push_id(&mut bytes, &proposal.proposal_id)?;
    push_id(&mut bytes, &proposal.proposer_id)?;
    push_id(&mut bytes, &proposal.evaluator_id)?;
    bytes.extend_from_slice(proposal.selected_topology_artifact_digest.as_array());
    push_id(&mut bytes, &proposal.window.window_id)?;
    bytes.extend_from_slice(proposal.window.window_digest.as_array());
    bytes.extend_from_slice(&proposal.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_generation.get().to_be_bytes());
    push_id(&mut bytes, &proposal.module_id)?;
    bytes.push(match proposal.operation {
        TopologyOperation::Add => 0,
        TopologyOperation::Remove => 1,
        TopologyOperation::Replace => 2,
    });
    for digest in [
        proposal.predecessor_topology_digest,
        proposal.candidate_topology_digest,
        proposal.compatibility_plan_digest,
        proposal.resource_delta_digest,
        proposal.security_review_digest,
        proposal.lesion_plan_digest,
        proposal.rollback_plan_digest,
        proposal.evaluation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    bytes.push(0);
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), TopologyProposalErrorV2> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| TopologyProposalErrorV2::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}
