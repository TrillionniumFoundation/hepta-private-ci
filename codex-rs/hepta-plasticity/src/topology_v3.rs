//! Deterministic authority-free topology proposal V3.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::RuntimeTopologyDeltaV1;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::StableId;

use crate::types::*;

pub fn propose_topology_v3(
    request: TopologyProposalRequestV3,
) -> Result<TopologyProposalV3, Error> {
    validate_header(&request)?;
    let candidates = build_candidates(request.candidates)?;
    let mut proposal = TopologyProposalV3 {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        selected_topology_digest: request.selected_topology_digest,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        evaluation_digest: request.evaluation_digest,
        rollback_predecessor_digest: request.rollback_predecessor_digest,
        candidates,
        proposal_digest: Digest32::ZERO,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    };
    proposal.proposal_digest = digest_topology_proposal_v3(&proposal)?;
    verify_topology_proposal_v3(&proposal)?;
    Ok(proposal)
}

/// Convert one already-verified proposal candidate into the neutral runtime
/// admission contract. This grants no selection or promotion authority.
pub fn runtime_topology_candidate_v1(
    proposal: &TopologyProposalV3,
    candidate_id: &StableId,
) -> Result<RuntimeTopologyCandidateV1, Error> {
    verify_topology_proposal_v3(proposal)?;
    let selected = proposal
        .candidates
        .iter()
        .find(|candidate| &candidate.candidate_id == candidate_id)
        .ok_or_else(|| Error::UnknownTopologyCandidate(candidate_id.to_string()))?;
    let deltas = selected
        .topology_deltas
        .iter()
        .map(|delta| RuntimeTopologyDeltaV1 {
            module_id: delta.module_id.clone(),
            operation: match delta.operation {
                TopologyOperationV3::Add => RuntimeTopologyOperationV1::Add,
                TopologyOperationV3::Replace => RuntimeTopologyOperationV1::Replace,
                TopologyOperationV3::Retire => RuntimeTopologyOperationV1::Retire,
                TopologyOperationV3::Rewire => RuntimeTopologyOperationV1::Rewire,
                TopologyOperationV3::Split => RuntimeTopologyOperationV1::Split,
                TopologyOperationV3::Merge => RuntimeTopologyOperationV1::Merge,
            },
            related_module_ids: delta.related_module_ids.clone(),
            predecessor_digest: delta.predecessor_digest,
            candidate_digest: delta.candidate_digest,
            evidence_digest: delta.evidence_digest,
        })
        .collect::<Vec<_>>();
    let candidate = RuntimeTopologyCandidateV1 {
        proposal_digest: proposal.proposal_digest,
        candidate_id: selected.candidate_id.clone(),
        candidate_digest: selected.candidate_digest,
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        selected_topology_digest: proposal.selected_topology_digest,
        evaluation_digest: proposal.evaluation_digest,
        rollback_predecessor_digest: proposal.rollback_predecessor_digest,
        changed: matches!(selected.kind, TopologyCandidateKindV3::Change),
        deltas,
    };
    candidate
        .validate()
        .map_err(|_| Error::RuntimeTopologyContract)?;
    Ok(candidate)
}

pub fn verify_topology_proposal_v3(proposal: &TopologyProposalV3) -> Result<(), Error> {
    let request = TopologyProposalRequestV3 {
        proposal_id: proposal.proposal_id.clone(),
        proposer_id: proposal.proposer_id.clone(),
        evaluator_id: proposal.evaluator_id.clone(),
        selected_topology_digest: proposal.selected_topology_digest,
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        evaluation_digest: proposal.evaluation_digest,
        rollback_predecessor_digest: proposal.rollback_predecessor_digest,
        candidates: proposal
            .candidates
            .iter()
            .map(|candidate| TopologyCandidateRequestV3 {
                candidate_id: candidate.candidate_id.clone(),
                kind: candidate.kind,
                topology_deltas: candidate.topology_deltas.clone(),
            })
            .collect(),
    };
    validate_header(&request)?;
    if proposal.authority.grants_any() {
        return Err(Error::AuthorityGranted);
    }
    let expected = build_candidates(request.candidates)?;
    if expected != proposal.candidates {
        return Err(Error::ProposalDigestMismatch);
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_topology_proposal_v3(proposal)?
    {
        return Err(Error::ProposalDigestMismatch);
    }
    Ok(())
}

fn validate_header(request: &TopologyProposalRequestV3) -> Result<(), Error> {
    if request.proposer_id == request.evaluator_id {
        return Err(Error::SelfEvaluation);
    }
    if request.baseline_generation.next() != Ok(request.candidate_generation) {
        return Err(Error::GenerationNotExactSuccessor);
    }
    for (name, digest) in [
        ("selected topology", request.selected_topology_digest),
        ("evaluation", request.evaluation_digest),
        ("rollback predecessor", request.rollback_predecessor_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if request.rollback_predecessor_digest != request.selected_topology_digest {
        return Err(Error::RollbackPredecessorMismatch);
    }
    Ok(())
}

fn build_candidates(
    mut requests: Vec<TopologyCandidateRequestV3>,
) -> Result<Vec<TopologyCandidateV3>, Error> {
    if !(1..=MAX_CANDIDATES).contains(&requests.len()) {
        return Err(Error::CandidateCountOutOfRange);
    }
    requests.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut candidate_ids = BTreeSet::new();
    let mut no_change_count = 0_usize;
    let mut total_deltas = 0_usize;
    let mut candidates = Vec::with_capacity(requests.len());
    for mut request in requests {
        if !candidate_ids.insert(request.candidate_id.clone()) {
            return Err(Error::DuplicateCandidate(request.candidate_id.to_string()));
        }
        total_deltas = total_deltas
            .checked_add(request.topology_deltas.len())
            .filter(|count| *count <= MAX_TOPOLOGY_DELTAS)
            .ok_or(Error::TopologyLimitExceeded)?;
        match request.kind {
            TopologyCandidateKindV3::NoChange => {
                no_change_count += 1;
                if !request.topology_deltas.is_empty() {
                    return Err(Error::NoChangeHasTopologyDeltas(
                        request.candidate_id.to_string(),
                    ));
                }
            }
            TopologyCandidateKindV3::Change if request.topology_deltas.is_empty() => {
                return Err(Error::TopologyChangeHasNoDeltas(
                    request.candidate_id.to_string(),
                ));
            }
            TopologyCandidateKindV3::Change => {}
        }
        request.topology_deltas.sort_by(|left, right| {
            left.module_id
                .cmp(&right.module_id)
                .then_with(|| left.operation.cmp(&right.operation))
        });
        validate_deltas(&request.topology_deltas)?;
        let candidate_digest = digest_topology_candidate(
            &request.candidate_id,
            request.kind,
            &request.topology_deltas,
        )?;
        candidates.push(TopologyCandidateV3 {
            candidate_id: request.candidate_id,
            kind: request.kind,
            topology_deltas: request.topology_deltas,
            candidate_digest,
        });
    }
    match no_change_count {
        0 => Err(Error::MissingNoChangeCandidate),
        1 => Ok(candidates),
        _ => Err(Error::MultipleNoChangeCandidates),
    }
}

fn validate_deltas(deltas: &[TopologyDeltaV3]) -> Result<(), Error> {
    let mut modules = BTreeSet::new();
    for delta in deltas {
        if !modules.insert(delta.module_id.clone()) {
            return Err(Error::DuplicateTopology(delta.module_id.to_string()));
        }
        if delta.evidence_digest.is_zero() {
            return Err(Error::EmptyDigest("topology evidence"));
        }
        let related = delta.related_module_ids.iter().collect::<BTreeSet<_>>();
        if related.len() != delta.related_module_ids.len() || related.contains(&delta.module_id) {
            return Err(Error::DuplicateTopology(delta.module_id.to_string()));
        }
        match delta.operation {
            TopologyOperationV3::Add => {
                if !delta.related_module_ids.is_empty()
                    || !delta.predecessor_digest.is_zero()
                    || delta.candidate_digest.is_zero()
                {
                    return Err(Error::TopologyDigestUnchanged(delta.module_id.to_string()));
                }
            }
            TopologyOperationV3::Retire => {
                if !delta.related_module_ids.is_empty()
                    || delta.predecessor_digest.is_zero()
                    || !delta.candidate_digest.is_zero()
                {
                    return Err(Error::TopologyDigestUnchanged(delta.module_id.to_string()));
                }
            }
            TopologyOperationV3::Replace | TopologyOperationV3::Rewire => {
                if !delta.related_module_ids.is_empty()
                    || delta.predecessor_digest.is_zero()
                    || delta.candidate_digest.is_zero()
                    || delta.predecessor_digest == delta.candidate_digest
                {
                    return Err(Error::TopologyDigestUnchanged(delta.module_id.to_string()));
                }
            }
            TopologyOperationV3::Split | TopologyOperationV3::Merge => {
                if delta.related_module_ids.is_empty()
                    || delta.predecessor_digest.is_zero()
                    || delta.candidate_digest.is_zero()
                    || delta.predecessor_digest == delta.candidate_digest
                {
                    return Err(Error::TopologyDigestUnchanged(delta.module_id.to_string()));
                }
            }
        }
    }
    Ok(())
}

fn digest_topology_candidate(
    candidate_id: &codex_hepta_types::StableId,
    kind: TopologyCandidateKindV3,
    deltas: &[TopologyDeltaV3],
) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.plasticity.topology-candidate.v3".to_vec();
    push_id(&mut bytes, candidate_id)?;
    bytes.push(match kind {
        TopologyCandidateKindV3::NoChange => 0,
        TopologyCandidateKindV3::Change => 1,
    });
    push_len(&mut bytes, deltas.len())?;
    for delta in deltas {
        push_id(&mut bytes, &delta.module_id)?;
        bytes.push(match delta.operation {
            TopologyOperationV3::Add => 0,
            TopologyOperationV3::Replace => 1,
            TopologyOperationV3::Retire => 2,
            TopologyOperationV3::Rewire => 3,
            TopologyOperationV3::Split => 4,
            TopologyOperationV3::Merge => 5,
        });
        push_len(&mut bytes, delta.related_module_ids.len())?;
        for related in &delta.related_module_ids {
            push_id(&mut bytes, related)?;
        }
        bytes.extend_from_slice(delta.predecessor_digest.as_array());
        bytes.extend_from_slice(delta.candidate_digest.as_array());
        bytes.extend_from_slice(delta.evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_topology_proposal_v3(proposal: &TopologyProposalV3) -> Result<Digest32, Error> {
    let mut bytes = b"hepta.plasticity.topology-proposal.v3".to_vec();
    bytes.extend_from_slice(&TOPOLOGY_V3.to_be_bytes());
    push_id(&mut bytes, &proposal.proposal_id)?;
    push_id(&mut bytes, &proposal.proposer_id)?;
    push_id(&mut bytes, &proposal.evaluator_id)?;
    bytes.extend_from_slice(proposal.selected_topology_digest.as_array());
    bytes.extend_from_slice(&proposal.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(proposal.evaluation_digest.as_array());
    bytes.extend_from_slice(proposal.rollback_predecessor_digest.as_array());
    push_len(&mut bytes, proposal.candidates.len())?;
    for candidate in &proposal.candidates {
        bytes.extend_from_slice(candidate.candidate_digest.as_array());
    }
    bytes.push(0);
    bytes.push(0);
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &codex_hepta_types::StableId) -> Result<(), Error> {
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
