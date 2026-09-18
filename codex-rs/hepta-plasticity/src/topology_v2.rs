//! Typed, bounded topology proposal construction.
//!
//! This module creates next-generation structural candidates only. It has no API
//! for applying graph mutations, transferring writer authority, activation,
//! selection, promotion or release.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

use crate::{ProposalStatus, ProposalWindowV2};

const MAX_TOPOLOGY_CANDIDATES_V2: usize = 32;
const MAX_TOPOLOGY_CHANGES_V2: usize = MAX_TOPOLOGY_CANDIDATES_V2 - 1;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum TopologyOperationV2 {
    Add,
    Remove,
    Replace,
    Split,
    Merge,
    Rewire,
    Retire,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct TopologyChangeV2 {
    pub module_id: StableId,
    pub operation: TopologyOperationV2,
    /// Absent only for `Add`.
    pub predecessor_digest: Option<Digest32>,
    /// Absent only for `Remove` or `Retire`.
    pub candidate_digest: Option<Digest32>,
    pub migration_digest: Digest32,
    pub rollback_digest: Digest32,
    pub writer_handoff_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TopologyCandidateKindV2 {
    NoChange,
    Update,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyCandidateV2 {
    pub candidate_id: StableId,
    pub kind: TopologyCandidateKindV2,
    /// Initial structural candidates contain exactly one typed operation.
    pub changes: Vec<TopologyChangeV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalRequestV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    /// Role label only. Product composition must derive this from authenticated
    /// evidence before treating the proposal as independently evaluated.
    pub evaluator_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub changes: Vec<TopologyChangeV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_artifact_digest: Digest32,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyProposalErrorV2 {
    SelfEvaluation,
    GenerationNotExactSuccessor,
    EmptyDigest(&'static str),
    RollbackPredecessorMismatch,
    ChangeLimitExceeded,
    DuplicateChange(String),
    InvalidOperationShape(String),
    UnchangedTopology(String),
    CandidateIdentity,
    DigestMismatch,
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
    mut request: TopologyProposalRequestV2,
) -> Result<TopologyProposalV2, TopologyProposalErrorV2> {
    validate_header(&request)?;
    canonicalize_changes(&mut request.changes)?;

    let mut candidates = vec![TopologyCandidateV2 {
        candidate_id: context_no_change_id(request.selected_artifact_digest, &request.window)?,
        kind: TopologyCandidateKindV2::NoChange,
        changes: Vec::new(),
    }];
    for change in request.changes {
        candidates.push(TopologyCandidateV2 {
            candidate_id: content_candidate_id(
                request.selected_artifact_digest,
                &request.window,
                &change,
            )?,
            kind: TopologyCandidateKindV2::Update,
            changes: vec![change],
        });
    }
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));

    let mut proposal = TopologyProposalV2 {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        selected_artifact_digest: request.selected_artifact_digest,
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

pub fn verify_topology_proposal_v2(
    proposal: &TopologyProposalV2,
) -> Result<(), TopologyProposalErrorV2> {
    let request = TopologyProposalRequestV2 {
        proposal_id: proposal.proposal_id.clone(),
        proposer_id: proposal.proposer_id.clone(),
        evaluator_id: proposal.evaluator_id.clone(),
        selected_artifact_digest: proposal.selected_artifact_digest,
        window: proposal.window.clone(),
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        evaluation_digest: proposal.evaluation_digest,
        rollback_predecessor_digest: proposal.rollback_predecessor_digest,
        changes: proposal
            .candidates
            .iter()
            .flat_map(|candidate| candidate.changes.clone())
            .collect(),
    };
    validate_header(&request)?;
    if proposal.authority.grants_any() {
        return Err(TopologyProposalErrorV2::AuthorityGranted);
    }
    if proposal.candidates.is_empty()
        || proposal.candidates.len() > MAX_TOPOLOGY_CANDIDATES_V2
        || proposal
            .candidates
            .windows(2)
            .any(|pair| pair[0].candidate_id >= pair[1].candidate_id)
    {
        return Err(TopologyProposalErrorV2::ChangeLimitExceeded);
    }
    let no_change = proposal
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == TopologyCandidateKindV2::NoChange)
        .collect::<Vec<_>>();
    if no_change.len() != 1
        || !no_change[0].changes.is_empty()
        || no_change[0].candidate_id
            != context_no_change_id(proposal.selected_artifact_digest, &proposal.window)?
    {
        return Err(TopologyProposalErrorV2::InvalidOperationShape(
            "no-change".to_string(),
        ));
    }
    let mut change_identities = BTreeSet::new();
    for candidate in proposal
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
    {
        if candidate.changes.len() != 1
            || candidate.candidate_id
                != content_candidate_id(
                    proposal.selected_artifact_digest,
                    &proposal.window,
                    &candidate.changes[0],
                )?
        {
            return Err(TopologyProposalErrorV2::InvalidOperationShape(
                candidate.candidate_id.to_string(),
            ));
        }
        let change = &candidate.changes[0];
        let identity = (change.module_id.clone(), change.operation);
        if !change_identities.insert(identity) {
            return Err(TopologyProposalErrorV2::DuplicateChange(
                change.module_id.to_string(),
            ));
        }
        validate_change(change)?;
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_topology_proposal_v2(proposal)?
    {
        return Err(TopologyProposalErrorV2::DigestMismatch);
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
    for (name, digest) in [
        ("selected artifact", request.selected_artifact_digest),
        ("window", request.window.window_digest),
        ("evaluation", request.evaluation_digest),
        ("rollback predecessor", request.rollback_predecessor_digest),
    ] {
        if digest.is_zero() {
            return Err(TopologyProposalErrorV2::EmptyDigest(name));
        }
    }
    if request.rollback_predecessor_digest != request.selected_artifact_digest {
        return Err(TopologyProposalErrorV2::RollbackPredecessorMismatch);
    }
    if request.changes.len() > MAX_TOPOLOGY_CHANGES_V2 {
        return Err(TopologyProposalErrorV2::ChangeLimitExceeded);
    }
    Ok(())
}

fn canonicalize_changes(
    changes: &mut Vec<TopologyChangeV2>,
) -> Result<(), TopologyProposalErrorV2> {
    changes.sort();
    let mut identities = BTreeSet::new();
    for change in changes {
        let key = (change.module_id.clone(), change.operation);
        if !identities.insert(key) {
            return Err(TopologyProposalErrorV2::DuplicateChange(
                change.module_id.to_string(),
            ));
        }
        validate_change(change)?;
    }
    Ok(())
}

fn validate_change(change: &TopologyChangeV2) -> Result<(), TopologyProposalErrorV2> {
    for (name, digest) in [
        ("migration", change.migration_digest),
        ("rollback", change.rollback_digest),
        ("writer handoff", change.writer_handoff_digest),
        ("evidence", change.evidence_digest),
    ] {
        if digest.is_zero() {
            return Err(TopologyProposalErrorV2::EmptyDigest(name));
        }
    }
    let shape_ok = match change.operation {
        TopologyOperationV2::Add => {
            change.predecessor_digest.is_none() && change.candidate_digest.is_some()
        }
        TopologyOperationV2::Remove | TopologyOperationV2::Retire => {
            change.predecessor_digest.is_some() && change.candidate_digest.is_none()
        }
        TopologyOperationV2::Replace
        | TopologyOperationV2::Split
        | TopologyOperationV2::Merge
        | TopologyOperationV2::Rewire => {
            change.predecessor_digest.is_some() && change.candidate_digest.is_some()
        }
    };
    if !shape_ok {
        return Err(TopologyProposalErrorV2::InvalidOperationShape(
            change.module_id.to_string(),
        ));
    }
    for digest in [change.predecessor_digest, change.candidate_digest]
        .into_iter()
        .flatten()
    {
        if digest.is_zero() {
            return Err(TopologyProposalErrorV2::EmptyDigest("topology lineage"));
        }
    }
    if change.predecessor_digest.is_some() && change.predecessor_digest == change.candidate_digest {
        return Err(TopologyProposalErrorV2::UnchangedTopology(
            change.module_id.to_string(),
        ));
    }
    Ok(())
}

fn context_no_change_id(
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
) -> Result<StableId, TopologyProposalErrorV2> {
    let mut bytes = b"hepta.plasticity.topology-candidate.no-change.v2\0".to_vec();
    push_candidate_context(&mut bytes, selected_artifact_digest, window)?;
    stable_id(&format!(
        "topology:no-change:{}",
        Digest32::of_bytes(&bytes)
    ))
}

fn content_candidate_id(
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
    change: &TopologyChangeV2,
) -> Result<StableId, TopologyProposalErrorV2> {
    let mut bytes = b"hepta.plasticity.topology-candidate.update.v2\0".to_vec();
    push_candidate_context(&mut bytes, selected_artifact_digest, window)?;
    push_change(&mut bytes, change)?;
    stable_id(&format!("topology:update:{}", Digest32::of_bytes(&bytes)))
}

fn push_candidate_context(
    bytes: &mut Vec<u8>,
    selected_artifact_digest: Digest32,
    window: &ProposalWindowV2,
) -> Result<(), TopologyProposalErrorV2> {
    bytes.extend_from_slice(selected_artifact_digest.as_array());
    push_id(bytes, &window.window_id)?;
    bytes.extend_from_slice(window.window_digest.as_array());
    Ok(())
}

fn digest_topology_proposal_v2(
    proposal: &TopologyProposalV2,
) -> Result<Digest32, TopologyProposalErrorV2> {
    let mut bytes = b"hepta.plasticity.topology-proposal.v2\0".to_vec();
    for id in [
        &proposal.proposal_id,
        &proposal.proposer_id,
        &proposal.evaluator_id,
    ] {
        push_id(&mut bytes, id)?;
    }
    bytes.extend_from_slice(proposal.selected_artifact_digest.as_array());
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
            TopologyCandidateKindV2::Update => 1,
        });
        push_len(&mut bytes, candidate.changes.len())?;
        for change in &candidate.changes {
            push_change(&mut bytes, change)?;
        }
    }
    bytes.push(0); // RequiresIndependentAcceptance
    bytes.push(0); // DENY_ALL authority profile
    Ok(Digest32::of_bytes(&bytes))
}

fn push_change(
    bytes: &mut Vec<u8>,
    change: &TopologyChangeV2,
) -> Result<(), TopologyProposalErrorV2> {
    push_id(bytes, &change.module_id)?;
    bytes.push(match change.operation {
        TopologyOperationV2::Add => 0,
        TopologyOperationV2::Remove => 1,
        TopologyOperationV2::Replace => 2,
        TopologyOperationV2::Split => 3,
        TopologyOperationV2::Merge => 4,
        TopologyOperationV2::Rewire => 5,
        TopologyOperationV2::Retire => 6,
    });
    push_optional_digest(bytes, change.predecessor_digest);
    push_optional_digest(bytes, change.candidate_digest);
    for digest in [
        change.migration_digest,
        change.rollback_digest,
        change.writer_handoff_digest,
        change.evidence_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(())
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn stable_id(value: &str) -> Result<StableId, TopologyProposalErrorV2> {
    StableId::new(value).map_err(|_| TopologyProposalErrorV2::CandidateIdentity)
}
fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), TopologyProposalErrorV2> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| TopologyProposalErrorV2::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}
fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), TopologyProposalErrorV2> {
    let value = u32::try_from(value).map_err(|_| TopologyProposalErrorV2::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("id {value}: {error}"))
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).unwrap_or_else(|error| panic!("generation: {error}"))
    }
    fn request() -> TopologyProposalRequestV2 {
        let artifact = digest(b"artifact");
        TopologyProposalRequestV2 {
            proposal_id: id("topology:proposal:1"),
            proposer_id: id("generator:1"),
            evaluator_id: id("evaluator:1"),
            selected_artifact_digest: artifact,
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: digest(b"window"),
            },
            baseline_generation: generation(10),
            candidate_generation: generation(11),
            evaluation_digest: digest(b"evaluation"),
            rollback_predecessor_digest: artifact,
            changes: vec![TopologyChangeV2 {
                module_id: id("module:adapter"),
                operation: TopologyOperationV2::Replace,
                predecessor_digest: Some(digest(b"old")),
                candidate_digest: Some(digest(b"new")),
                migration_digest: digest(b"migration"),
                rollback_digest: digest(b"rollback"),
                writer_handoff_digest: digest(b"handoff"),
                evidence_digest: digest(b"evidence"),
            }],
        }
    }

    #[test]
    fn topology_v2_is_typed_deterministic_and_authority_free() {
        let first = propose_topology_v2(request()).expect("proposal");
        let second = propose_topology_v2(request()).expect("proposal again");
        assert_eq!(first, second);
        assert_eq!(first.candidates.len(), 2);
        assert!(!first.authority.grants_any());
        verify_topology_proposal_v2(&first).expect("verify");
    }

    #[test]
    fn topology_candidate_identity_changes_with_artifact_or_window() {
        let base = propose_topology_v2(request()).expect("base");
        let base_update = base
            .candidates
            .iter()
            .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
            .expect("base update")
            .candidate_id
            .clone();

        let mut artifact = request();
        let other_artifact = digest(b"other-artifact");
        artifact.selected_artifact_digest = other_artifact;
        artifact.rollback_predecessor_digest = other_artifact;
        let artifact_update = propose_topology_v2(artifact)
            .expect("artifact")
            .candidates
            .into_iter()
            .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
            .expect("artifact update")
            .candidate_id;
        assert_ne!(base_update, artifact_update);

        let mut window = request();
        window.window.window_digest = digest(b"other-window");
        let window_update = propose_topology_v2(window)
            .expect("window")
            .candidates
            .into_iter()
            .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
            .expect("window update")
            .candidate_id;
        assert_ne!(base_update, window_update);
    }

    #[test]
    fn topology_verifier_rejects_duplicate_module_operation_with_drift() {
        let mut proposal = propose_topology_v2(request()).expect("proposal");
        let mut drift = proposal
            .candidates
            .iter()
            .find(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
            .expect("update")
            .changes[0]
            .clone();
        drift.candidate_digest = Some(digest(b"new-drift"));
        drift.evidence_digest = digest(b"evidence-drift");
        proposal.candidates.push(TopologyCandidateV2 {
            candidate_id: content_candidate_id(
                proposal.selected_artifact_digest,
                &proposal.window,
                &drift,
            )
            .expect("candidate id"),
            kind: TopologyCandidateKindV2::Update,
            changes: vec![drift],
        });
        proposal
            .candidates
            .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
        proposal.proposal_digest = digest_topology_proposal_v2(&proposal).expect("digest");
        assert!(matches!(
            verify_topology_proposal_v2(&proposal),
            Err(TopologyProposalErrorV2::DuplicateChange(_))
        ));
    }

    #[test]
    fn topology_v2_rejects_invalid_shape_and_unchanged_lineage() {
        let mut invalid = request();
        invalid.changes[0].candidate_digest = None;
        assert!(matches!(
            propose_topology_v2(invalid),
            Err(TopologyProposalErrorV2::InvalidOperationShape(_))
        ));

        let mut unchanged = request();
        unchanged.changes[0].candidate_digest = unchanged.changes[0].predecessor_digest;
        assert!(matches!(
            propose_topology_v2(unchanged),
            Err(TopologyProposalErrorV2::UnchangedTopology(_))
        ));
    }
}
