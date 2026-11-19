//! Offline Cell split candidates.
//!
//! A split is a hypothesis about a future generation, not a runtime mutation.
//! This module deliberately keeps the candidate small and digest-bound: the
//! caller supplies independent evidence, a bounded state/optimizer mapping and
//! the compatibility/security reviews.  The returned value carries no
//! capability and cannot activate a child Cell.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ProposalStatus;

const Q24: i64 = 1 << 24;
const MAX_SPLIT_SLOTS: usize = 128;
const MAX_SPLIT_CHILDREN: usize = 2;

/// A source state slot copied or projected into one of the two children.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct CellSplitStateMappingV1 {
    pub source_slot: u32,
    pub child_a_slot: Option<u32>,
    pub child_b_slot: Option<u32>,
    pub state_digest: Digest32,
    pub optimizer_state_digest: Option<Digest32>,
}

/// Evidence required before a split candidate can be proposed offline.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitEvidenceV1 {
    pub residual_digest: Digest32,
    pub conflict_digest: Digest32,
    pub split_trigger_digest: Digest32,
    pub baseline_utility_q24: i64,
    pub child_a_utility_q24: i64,
    pub child_b_utility_q24: i64,
    pub retained_task_utility_q24: i64,
    pub resource_delta_q24: i64,
    pub independent_evaluation_digest: Digest32,
}

/// Inputs to the deterministic, proposal-only split generator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitCandidateRequestV1 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub cell_id: StableId,
    pub child_a_id: StableId,
    pub child_b_id: StableId,
    pub parent_artifact_digest: Digest32,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub window_digest: Digest32,
    pub evidence: CellSplitEvidenceV1,
    pub state_mapping: Vec<CellSplitStateMappingV1>,
    pub capability_typing_digest: Digest32,
    pub compatibility_plan_digest: Digest32,
    pub migration_digest: Digest32,
    pub rollback_digest: Digest32,
    pub writer_handoff_digest: Digest32,
    pub resource_review_digest: Digest32,
    pub security_review_digest: Digest32,
}

/// An offline split candidate.  `authority` is permanently deny-all and the
/// status requires an independent evaluator; runtime activation lives in the
/// separate governed topology/runtime owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitCandidateV1 {
    pub candidate_id: StableId,
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub cell_id: StableId,
    pub child_a_id: StableId,
    pub child_b_id: StableId,
    pub parent_artifact_digest: Digest32,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub window_digest: Digest32,
    pub evidence: CellSplitEvidenceV1,
    pub state_mapping: Vec<CellSplitStateMappingV1>,
    pub capability_typing_digest: Digest32,
    pub compatibility_plan_digest: Digest32,
    pub migration_digest: Digest32,
    pub rollback_digest: Digest32,
    pub writer_handoff_digest: Digest32,
    pub resource_review_digest: Digest32,
    pub security_review_digest: Digest32,
    pub proposal_digest: Digest32,
    pub status: ProposalStatus,
    pub authority: AuthorityPosture,
}

impl CellSplitCandidateV1 {
    /// Project the offline candidate into the existing topology proposal
    /// envelope. This only copies digests; it does not apply the split.
    #[must_use]
    pub fn topology_change_v2(&self) -> crate::TopologyChangeV2 {
        crate::TopologyChangeV2 {
            module_id: self.cell_id.clone(),
            operation: crate::TopologyOperationV2::Split,
            predecessor_digest: Some(self.parent_artifact_digest),
            candidate_digest: Some(self.proposal_digest),
            capability_typing_digest: self.capability_typing_digest,
            compatibility_plan_digest: self.compatibility_plan_digest,
            lesion_ablation_digest: self.evidence.conflict_digest,
            resource_review_digest: self.resource_review_digest,
            security_review_digest: self.security_review_digest,
            migration_digest: self.migration_digest,
            rollback_digest: self.rollback_digest,
            writer_handoff_digest: self.writer_handoff_digest,
            evidence_digest: self.evidence.independent_evaluation_digest,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitCandidateErrorV1 {
    SelfEvaluation,
    GenerationNotExactSuccessor,
    EmptyDigest(&'static str),
    EmptyCell,
    ChildIdentity,
    MappingLimit,
    MappingDuplicate(u32),
    MappingTargetCollision(u32),
    InvalidMapping(u32),
    InvalidEvidence(&'static str),
    Arithmetic,
    CandidateIdentity,
    DigestMismatch,
    InvalidStatus,
    AuthorityGranted,
}

impl fmt::Display for CellSplitCandidateErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitCandidateErrorV1 {}

/// Build one deterministic split candidate. No topology or runtime state is
/// mutated; callers may persist this record for later independent evaluation.
pub fn propose_cell_split_candidate_v1(
    mut request: CellSplitCandidateRequestV1,
) -> Result<CellSplitCandidateV1, CellSplitCandidateErrorV1> {
    validate_request(&request)?;
    request.state_mapping.sort();
    validate_mapping(&request.state_mapping)?;
    let candidate_id = candidate_id(&request)?;
    let mut candidate = CellSplitCandidateV1 {
        candidate_id,
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        cell_id: request.cell_id,
        child_a_id: request.child_a_id,
        child_b_id: request.child_b_id,
        parent_artifact_digest: request.parent_artifact_digest,
        baseline_generation: request.baseline_generation,
        candidate_generation: request.candidate_generation,
        window_digest: request.window_digest,
        evidence: request.evidence,
        state_mapping: request.state_mapping,
        capability_typing_digest: request.capability_typing_digest,
        compatibility_plan_digest: request.compatibility_plan_digest,
        migration_digest: request.migration_digest,
        rollback_digest: request.rollback_digest,
        writer_handoff_digest: request.writer_handoff_digest,
        resource_review_digest: request.resource_review_digest,
        security_review_digest: request.security_review_digest,
        proposal_digest: Digest32::ZERO,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    };
    candidate.proposal_digest = digest_candidate(&candidate)?;
    verify_cell_split_candidate_v1(&candidate)?;
    Ok(candidate)
}

pub fn verify_cell_split_candidate_v1(
    candidate: &CellSplitCandidateV1,
) -> Result<(), CellSplitCandidateErrorV1> {
    if candidate.status != ProposalStatus::RequiresIndependentAcceptance {
        return Err(CellSplitCandidateErrorV1::InvalidStatus);
    }
    if candidate.authority.grants_any() {
        return Err(CellSplitCandidateErrorV1::AuthorityGranted);
    }
    let request = CellSplitCandidateRequestV1 {
        proposal_id: candidate.proposal_id.clone(),
        proposer_id: candidate.proposer_id.clone(),
        evaluator_id: candidate.evaluator_id.clone(),
        cell_id: candidate.cell_id.clone(),
        child_a_id: candidate.child_a_id.clone(),
        child_b_id: candidate.child_b_id.clone(),
        parent_artifact_digest: candidate.parent_artifact_digest,
        baseline_generation: candidate.baseline_generation,
        candidate_generation: candidate.candidate_generation,
        window_digest: candidate.window_digest,
        evidence: candidate.evidence.clone(),
        state_mapping: candidate.state_mapping.clone(),
        capability_typing_digest: candidate.capability_typing_digest,
        compatibility_plan_digest: candidate.compatibility_plan_digest,
        migration_digest: candidate.migration_digest,
        rollback_digest: candidate.rollback_digest,
        writer_handoff_digest: candidate.writer_handoff_digest,
        resource_review_digest: candidate.resource_review_digest,
        security_review_digest: candidate.security_review_digest,
    };
    // Header validation is independent of activation.  The original proposer
    // and evaluator identities remain bound so a candidate cannot silently
    // replace the independent-evaluation relationship during verification.
    validate_request(&request)?;
    validate_mapping(&candidate.state_mapping)?;
    if candidate.candidate_id != candidate_id_from_fields(candidate)?
        || candidate.proposal_digest.is_zero()
        || candidate.proposal_digest != digest_candidate(candidate)?
    {
        return Err(CellSplitCandidateErrorV1::DigestMismatch);
    }
    Ok(())
}

fn validate_request(
    request: &CellSplitCandidateRequestV1,
) -> Result<(), CellSplitCandidateErrorV1> {
    if request.proposer_id == request.evaluator_id {
        return Err(CellSplitCandidateErrorV1::SelfEvaluation);
    }
    validate_request_without_roles(request)
}

fn validate_request_without_roles(
    request: &CellSplitCandidateRequestV1,
) -> Result<(), CellSplitCandidateErrorV1> {
    if request.cell_id.as_str().is_empty() {
        return Err(CellSplitCandidateErrorV1::EmptyCell);
    }
    if request.child_a_id == request.child_b_id
        || request.child_a_id == request.cell_id
        || request.child_b_id == request.cell_id
    {
        return Err(CellSplitCandidateErrorV1::ChildIdentity);
    }
    if request.baseline_generation.next() != Ok(request.candidate_generation) {
        return Err(CellSplitCandidateErrorV1::GenerationNotExactSuccessor);
    }
    for (name, digest) in [
        ("parent artifact", request.parent_artifact_digest),
        ("window", request.window_digest),
        ("capability typing", request.capability_typing_digest),
        ("compatibility plan", request.compatibility_plan_digest),
        ("migration", request.migration_digest),
        ("rollback", request.rollback_digest),
        ("writer handoff", request.writer_handoff_digest),
        ("resource review", request.resource_review_digest),
        ("security review", request.security_review_digest),
    ] {
        if digest.is_zero() {
            return Err(CellSplitCandidateErrorV1::EmptyDigest(name));
        }
    }
    validate_evidence(&request.evidence)?;
    Ok(())
}

fn validate_evidence(
    evidence: &CellSplitEvidenceV1,
) -> Result<(), CellSplitCandidateErrorV1> {
    for (name, digest) in [
        ("residual", evidence.residual_digest),
        ("conflict", evidence.conflict_digest),
        ("split trigger", evidence.split_trigger_digest),
        ("independent evaluation", evidence.independent_evaluation_digest),
    ] {
        if digest.is_zero() {
            return Err(CellSplitCandidateErrorV1::EmptyDigest(name));
        }
    }
    for (name, value) in [
        ("baseline utility", evidence.baseline_utility_q24),
        ("child a utility", evidence.child_a_utility_q24),
        ("child b utility", evidence.child_b_utility_q24),
        ("retained utility", evidence.retained_task_utility_q24),
        ("resource delta", evidence.resource_delta_q24),
    ] {
        if !(-8 * Q24..=8 * Q24).contains(&value) {
            return Err(CellSplitCandidateErrorV1::InvalidEvidence(name));
        }
    }
    if evidence.child_a_utility_q24 < evidence.baseline_utility_q24
        && evidence.child_b_utility_q24 < evidence.baseline_utility_q24
    {
        return Err(CellSplitCandidateErrorV1::InvalidEvidence(
            "both children regress baseline",
        ));
    }
    if evidence.retained_task_utility_q24 < -Q24 {
        return Err(CellSplitCandidateErrorV1::InvalidEvidence("retention floor"));
    }
    Ok(())
}

fn validate_mapping(
    mapping: &[CellSplitStateMappingV1],
) -> Result<(), CellSplitCandidateErrorV1> {
    if mapping.is_empty() || mapping.len() > MAX_SPLIT_SLOTS {
        return Err(CellSplitCandidateErrorV1::MappingLimit);
    }
    let mut seen_sources = std::collections::BTreeSet::new();
    let mut seen_targets = std::collections::BTreeSet::new();
    for row in mapping {
        if row.state_digest.is_zero()
            || row.optimizer_state_digest.is_some_and(Digest32::is_zero)
            || (row.child_a_slot.is_none() && row.child_b_slot.is_none())
        {
            return Err(CellSplitCandidateErrorV1::InvalidMapping(row.source_slot));
        }
        if !seen_sources.insert(row.source_slot) {
            return Err(CellSplitCandidateErrorV1::MappingDuplicate(row.source_slot));
        }
        for (child, target) in [(0_u8, row.child_a_slot), (1_u8, row.child_b_slot)] {
            if let Some(target) = target {
                if !seen_targets.insert((child, target)) {
                    return Err(CellSplitCandidateErrorV1::MappingTargetCollision(target));
                }
            }
        }
        if [row.child_a_slot, row.child_b_slot]
            .into_iter()
            .flatten()
            .count()
            > MAX_SPLIT_CHILDREN
        {
            return Err(CellSplitCandidateErrorV1::InvalidMapping(row.source_slot));
        }
    }
    Ok(())
}

fn candidate_id(
    request: &CellSplitCandidateRequestV1,
) -> Result<StableId, CellSplitCandidateErrorV1> {
    let digest = Digest32::of_parts(&[
        b"hepta.plasticity.cell-split-candidate-id.v1\0",
        request.parent_artifact_digest.as_array(),
        request.evidence.split_trigger_digest.as_array(),
        request.migration_digest.as_array(),
        request.rollback_digest.as_array(),
        request.cell_id.as_str().as_bytes(),
        b"\0",
        request.child_a_id.as_str().as_bytes(),
        b"\0",
        request.child_b_id.as_str().as_bytes(),
    ]);
    StableId::new(format!("candidate:split:{digest}"))
        .map_err(|_| CellSplitCandidateErrorV1::CandidateIdentity)
}

fn candidate_id_from_fields(
    candidate: &CellSplitCandidateV1,
) -> Result<StableId, CellSplitCandidateErrorV1> {
    let digest = Digest32::of_parts(&[
        b"hepta.plasticity.cell-split-candidate-id.v1\0",
        candidate.parent_artifact_digest.as_array(),
        candidate.evidence.split_trigger_digest.as_array(),
        candidate.migration_digest.as_array(),
        candidate.rollback_digest.as_array(),
        candidate.cell_id.as_str().as_bytes(),
        b"\0",
        candidate.child_a_id.as_str().as_bytes(),
        b"\0",
        candidate.child_b_id.as_str().as_bytes(),
    ]);
    StableId::new(format!("candidate:split:{digest}"))
        .map_err(|_| CellSplitCandidateErrorV1::CandidateIdentity)
}

fn digest_candidate(
    candidate: &CellSplitCandidateV1,
) -> Result<Digest32, CellSplitCandidateErrorV1> {
    let mut bytes = b"hepta.plasticity.cell-split-candidate.v1\0".to_vec();
    for id in [
        &candidate.candidate_id,
        &candidate.proposal_id,
        &candidate.proposer_id,
        &candidate.evaluator_id,
        &candidate.cell_id,
        &candidate.child_a_id,
        &candidate.child_b_id,
    ] {
        let raw = id.as_str().as_bytes();
        let length = u32::try_from(raw.len()).map_err(|_| CellSplitCandidateErrorV1::Arithmetic)?;
        bytes.extend_from_slice(&length.to_be_bytes());
        bytes.extend_from_slice(raw);
    }
    for digest in [
        candidate.parent_artifact_digest,
        candidate.window_digest,
        candidate.capability_typing_digest,
        candidate.compatibility_plan_digest,
        candidate.migration_digest,
        candidate.rollback_digest,
        candidate.writer_handoff_digest,
        candidate.resource_review_digest,
        candidate.security_review_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&candidate.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&candidate.candidate_generation.get().to_be_bytes());
    let e = &candidate.evidence;
    for digest in [
        e.residual_digest,
        e.conflict_digest,
        e.split_trigger_digest,
        e.independent_evaluation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        e.baseline_utility_q24,
        e.child_a_utility_q24,
        e.child_b_utility_q24,
        e.retained_task_utility_q24,
        e.resource_delta_q24,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    for row in &candidate.state_mapping {
        bytes.extend_from_slice(&row.source_slot.to_be_bytes());
        for target in [row.child_a_slot, row.child_b_slot] {
            match target {
                Some(value) => {
                    bytes.push(1);
                    bytes.extend_from_slice(&value.to_be_bytes());
                }
                None => bytes.push(0),
            }
        }
        bytes.extend_from_slice(row.state_digest.as_array());
        bytes.extend_from_slice(
            row.optimizer_state_digest
                .unwrap_or(Digest32::ZERO)
                .as_array(),
        );
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[cfg(test)]
#[path = "cell_split_tests.rs"]
mod tests;
