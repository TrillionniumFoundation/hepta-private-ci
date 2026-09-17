//! Bounded topology proposal construction and verification.
//!
//! Topology proposals remain candidate-only: they cannot mutate the current
//! runtime graph, transfer ownership, activate themselves or grant authority.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::Error;
use crate::ProposalStatus;
use crate::ProposalWindowV2;
use crate::TopologyOperation;
use crate::types::MAX_CANDIDATES;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct TopologyDeltaV2 {
    pub module_id: StableId,
    pub operation: TopologyOperation,
    pub predecessor_digest: Digest32,
    pub candidate_digest: Digest32,
    pub migration_digest: Digest32,
    pub rollback_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TopologyCandidateKindV2 {
    NoChange,
    Mutation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyCandidateRequestV2 {
    pub candidate_id: StableId,
    pub kind: TopologyCandidateKindV2,
    /// Structural canary candidates deliberately contain at most one operation.
    pub delta: Option<TopologyDeltaV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalRequestV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_graph_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub candidates: Vec<TopologyCandidateRequestV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyCandidateV2 {
    pub candidate_id: StableId,
    pub kind: TopologyCandidateKindV2,
    pub delta: Option<TopologyDeltaV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_graph_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub candidates: Vec<TopologyCandidateV2>,
    pub proposal_digest: Digest32,
    pub status: ProposalStatus,
    pub authority: AuthorityPosture,
}

pub fn propose_topology_v2(request: TopologyProposalRequestV2) -> Result<TopologyProposalV2, Error> {
    validate_header(&request)?;
    let candidates = build_candidates(request.candidates)?;
    let mut proposal = TopologyProposalV2 {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        selected_graph_digest: request.selected_graph_digest,
        window: request.window,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        evaluation_digest: request.evaluation_digest,
        rollback_predecessor_digest: request.rollback_predecessor_digest,
        candidates,
        proposal_digest: Digest32::ZERO,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    };
    proposal.proposal_digest = digest_topology_proposal_v2(&proposal)?;
    verify_topology_proposal_v2(&proposal)?;
    Ok(proposal)
}

pub fn verify_topology_proposal_v2(proposal: &TopologyProposalV2) -> Result<(), Error> {
    validate_header(&TopologyProposalRequestV2 {
        proposal_id: proposal.proposal_id.clone(),
        proposer_id: proposal.proposer_id.clone(),
        evaluator_id: proposal.evaluator_id.clone(),
        selected_graph_digest: proposal.selected_graph_digest,
        window: proposal.window.clone(),
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        evaluation_digest: proposal.evaluation_digest,
        rollback_predecessor_digest: proposal.rollback_predecessor_digest,
        candidates: proposal
            .candidates
            .iter()
            .map(|candidate| TopologyCandidateRequestV2 {
                candidate_id: candidate.candidate_id.clone(),
                kind: candidate.kind,
                delta: candidate.delta.clone(),
            })
            .collect(),
    })?;
    if proposal.authority.grants_any() {
        return Err(Error::AuthorityGranted);
    }
    let expected = build_candidates(
        proposal
            .candidates
            .iter()
            .map(|candidate| TopologyCandidateRequestV2 {
                candidate_id: candidate.candidate_id.clone(),
                kind: candidate.kind,
                delta: candidate.delta.clone(),
            })
            .collect(),
    )?;
    if expected != proposal.candidates {
        return Err(Error::TopologyProposalMismatch);
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_topology_proposal_v2(proposal)?
    {
        return Err(Error::ProposalDigestMismatch);
    }
    Ok(())
}

fn validate_header(request: &TopologyProposalRequestV2) -> Result<(), Error> {
    if request.proposer_id == request.evaluator_id {
        return Err(Error::SelfEvaluation);
    }
    if request.baseline_generation.next() != Ok(request.candidate_generation) {
        return Err(Error::GenerationNotExactSuccessor);
    }
    for (name, digest) in [
        ("selected graph", request.selected_graph_digest),
        ("window", request.window.window_digest),
        ("evaluation", request.evaluation_digest),
        ("rollback predecessor", request.rollback_predecessor_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if request.rollback_predecessor_digest != request.selected_graph_digest {
        return Err(Error::RollbackPredecessorMismatch);
    }
    Ok(())
}

fn build_candidates(
    mut candidates: Vec<TopologyCandidateRequestV2>,
) -> Result<Vec<TopologyCandidateV2>, Error> {
    if !(1..=MAX_CANDIDATES).contains(&candidates.len()) {
        return Err(Error::CandidateCountOutOfRange);
    }
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    let mut no_change = 0_usize;
    let mut output = Vec::with_capacity(candidates.len());
    for candidate in candidates {
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(Error::DuplicateCandidate(candidate.candidate_id.to_string()));
        }
        match candidate.kind {
            TopologyCandidateKindV2::NoChange => {
                no_change += 1;
                if candidate.delta.is_some() {
                    return Err(Error::TopologyNoChangeHasDelta(candidate.candidate_id.to_string()));
                }
            }
            TopologyCandidateKindV2::Mutation => {
                let Some(delta) = candidate.delta.as_ref() else {
                    return Err(Error::TopologyMutationMissingDelta(
                        candidate.candidate_id.to_string(),
                    ));
                };
                validate_delta(delta)?;
            }
        }
        output.push(TopologyCandidateV2 {
            candidate_id: candidate.candidate_id,
            kind: candidate.kind,
            delta: candidate.delta,
        });
    }
    match no_change {
        0 => Err(Error::MissingNoChangeCandidate),
        1 => Ok(output),
        _ => Err(Error::MultipleNoChangeCandidates),
    }
}

fn validate_delta(delta: &TopologyDeltaV2) -> Result<(), Error> {
    for (name, digest) in [
        ("topology predecessor", delta.predecessor_digest),
        ("topology candidate", delta.candidate_digest),
        ("topology migration", delta.migration_digest),
        ("topology rollback", delta.rollback_digest),
        ("topology evidence", delta.evidence_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if delta.predecessor_digest == delta.candidate_digest {
        return Err(Error::TopologyDigestUnchanged(delta.module_id.to_string()));
    }
    Ok(())
}

fn digest_topology_proposal_v2(proposal: &TopologyProposalV2) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.plasticity.topology-proposal.v2".to_vec();
    push_id(&mut bytes, &proposal.proposal_id)?;
    push_id(&mut bytes, &proposal.proposer_id)?;
    push_id(&mut bytes, &proposal.evaluator_id)?;
    bytes.extend_from_slice(proposal.selected_graph_digest.as_array());
    push_id(&mut bytes, &proposal.window.window_id)?;
    bytes.extend_from_slice(proposal.window.window_digest.as_array());
    bytes.extend_from_slice(&proposal.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(proposal.evaluation_digest.as_array());
    bytes.extend_from_slice(proposal.rollback_predecessor_digest.as_array());
    push_len(&mut bytes, proposal.candidates.len())?;
    for candidate in &proposal.candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.push(match candidate.kind {
            TopologyCandidateKindV2::NoChange => 0,
            TopologyCandidateKindV2::Mutation => 1,
        });
        match &candidate.delta {
            None => bytes.push(0),
            Some(delta) => {
                bytes.push(1);
                push_id(&mut bytes, &delta.module_id)?;
                bytes.push(match delta.operation {
                    TopologyOperation::Add => 0,
                    TopologyOperation::Remove => 1,
                    TopologyOperation::Replace => 2,
                });
                for digest in [
                    delta.predecessor_digest,
                    delta.candidate_digest,
                    delta.migration_digest,
                    delta.rollback_digest,
                    delta.evidence_digest,
                ] {
                    bytes.extend_from_slice(digest.as_array());
                }
            }
        }
    }
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

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), Error> {
    let value = u32::try_from(value).map_err(|_| Error::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}
