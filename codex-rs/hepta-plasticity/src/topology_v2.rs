//! Deterministic, authority-free topology proposal construction.
//!
//! Topology V2 is a next-snapshot structural proposal only. It binds the typed
//! graph candidate, compatibility/resource/security/lesion/rollback plans and
//! exact predecessor generation. It exposes no API for applying graph changes,
//! selecting a candidate, promoting, or releasing it.

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

use crate::{Error, ProposalStatus, TopologyOperation};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalRequestV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    /// Structural inequality only. Governed callers must authenticate evaluator identity.
    pub evaluator_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub predecessor_topology_digest: Digest32,
    pub operation: TopologyOperation,
    pub typed_nodes_edges_digest: Digest32,
    pub candidate_topology_digest: Digest32,
    pub compatibility_plan_digest: Digest32,
    pub resource_delta_digest: Digest32,
    pub security_review_digest: Digest32,
    pub lesion_plan_digest: Digest32,
    pub rollback_plan_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub predecessor_topology_digest: Digest32,
    pub operation: TopologyOperation,
    pub typed_nodes_edges_digest: Digest32,
    pub candidate_topology_digest: Digest32,
    pub compatibility_plan_digest: Digest32,
    pub resource_delta_digest: Digest32,
    pub security_review_digest: Digest32,
    pub lesion_plan_digest: Digest32,
    pub rollback_plan_digest: Digest32,
    pub evidence_digest: Digest32,
    pub proposal_digest: Digest32,
    pub status: ProposalStatus,
    pub authority: AuthorityPosture,
}

pub fn propose_topology_v2(request: TopologyProposalRequestV2) -> Result<TopologyProposalV2, Error> {
    validate_topology_header(&request)?;
    let mut proposal = TopologyProposalV2 {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        predecessor_topology_digest: request.predecessor_topology_digest,
        operation: request.operation,
        typed_nodes_edges_digest: request.typed_nodes_edges_digest,
        candidate_topology_digest: request.candidate_topology_digest,
        compatibility_plan_digest: request.compatibility_plan_digest,
        resource_delta_digest: request.resource_delta_digest,
        security_review_digest: request.security_review_digest,
        lesion_plan_digest: request.lesion_plan_digest,
        rollback_plan_digest: request.rollback_plan_digest,
        evidence_digest: request.evidence_digest,
        proposal_digest: Digest32::ZERO,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    };
    proposal.proposal_digest = digest_topology_proposal_v2(&proposal)?;
    verify_topology_proposal_v2(&proposal)?;
    Ok(proposal)
}

pub fn verify_topology_proposal_v2(proposal: &TopologyProposalV2) -> Result<(), Error> {
    validate_topology_header(&TopologyProposalRequestV2 {
        proposal_id: proposal.proposal_id.clone(),
        proposer_id: proposal.proposer_id.clone(),
        evaluator_id: proposal.evaluator_id.clone(),
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        predecessor_topology_digest: proposal.predecessor_topology_digest,
        operation: proposal.operation,
        typed_nodes_edges_digest: proposal.typed_nodes_edges_digest,
        candidate_topology_digest: proposal.candidate_topology_digest,
        compatibility_plan_digest: proposal.compatibility_plan_digest,
        resource_delta_digest: proposal.resource_delta_digest,
        security_review_digest: proposal.security_review_digest,
        lesion_plan_digest: proposal.lesion_plan_digest,
        rollback_plan_digest: proposal.rollback_plan_digest,
        evidence_digest: proposal.evidence_digest,
    })?;
    if proposal.authority.grants_any() {
        return Err(Error::AuthorityGranted);
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_topology_proposal_v2(proposal)?
    {
        return Err(Error::ProposalDigestMismatch);
    }
    Ok(())
}

fn validate_topology_header(request: &TopologyProposalRequestV2) -> Result<(), Error> {
    if request.proposer_id == request.evaluator_id {
        return Err(Error::SelfEvaluation);
    }
    if request.baseline_generation.next() != Ok(request.candidate_generation) {
        return Err(Error::GenerationNotExactSuccessor);
    }
    for (label, digest) in [
        ("predecessor topology", request.predecessor_topology_digest),
        ("typed nodes and edges", request.typed_nodes_edges_digest),
        ("candidate topology", request.candidate_topology_digest),
        ("compatibility plan", request.compatibility_plan_digest),
        ("resource delta", request.resource_delta_digest),
        ("security review", request.security_review_digest),
        ("lesion plan", request.lesion_plan_digest),
        ("rollback plan", request.rollback_plan_digest),
        ("topology evidence", request.evidence_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(label));
        }
    }
    if request.predecessor_topology_digest == request.candidate_topology_digest {
        return Err(Error::TopologyDigestUnchanged(request.proposal_id.to_string()));
    }
    Ok(())
}

fn digest_topology_proposal_v2(proposal: &TopologyProposalV2) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.plasticity.topology-proposal.v2".to_vec();
    push_id(&mut bytes, &proposal.proposal_id)?;
    push_id(&mut bytes, &proposal.proposer_id)?;
    push_id(&mut bytes, &proposal.evaluator_id)?;
    bytes.extend_from_slice(&proposal.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(proposal.predecessor_topology_digest.as_array());
    bytes.push(match proposal.operation {
        TopologyOperation::Add => 0,
        TopologyOperation::Remove => 1,
        TopologyOperation::Replace => 2,
    });
    for digest in [
        proposal.typed_nodes_edges_digest,
        proposal.candidate_topology_digest,
        proposal.compatibility_plan_digest,
        proposal.resource_delta_digest,
        proposal.security_review_digest,
        proposal.lesion_plan_digest,
        proposal.rollback_plan_digest,
        proposal.evidence_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    bytes.push(0);
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), Error> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| Error::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("valid generation")
    }

    fn request() -> TopologyProposalRequestV2 {
        TopologyProposalRequestV2 {
            proposal_id: id("topology:proposal:1"),
            proposer_id: id("learning.plasticity"),
            evaluator_id: id("learning.eval"),
            baseline_generation: generation(4),
            candidate_generation: generation(5),
            predecessor_topology_digest: digest("topology:4"),
            operation: TopologyOperation::Replace,
            typed_nodes_edges_digest: digest("typed-graph"),
            candidate_topology_digest: digest("topology:5"),
            compatibility_plan_digest: digest("compatibility"),
            resource_delta_digest: digest("resources"),
            security_review_digest: digest("security"),
            lesion_plan_digest: digest("lesion"),
            rollback_plan_digest: digest("rollback"),
            evidence_digest: digest("evidence"),
        }
    }

    #[test]
    fn topology_v2_is_next_generation_and_authority_free() {
        let proposal = propose_topology_v2(request()).expect("valid proposal");
        assert!(!proposal.authority.grants_any());
        verify_topology_proposal_v2(&proposal).expect("proposal verifies");
    }

    #[test]
    fn topology_v2_rejects_same_topology_digest() {
        let mut request = request();
        request.candidate_topology_digest = request.predecessor_topology_digest;
        assert!(matches!(
            propose_topology_v2(request),
            Err(Error::TopologyDigestUnchanged(_))
        ));
    }
}
