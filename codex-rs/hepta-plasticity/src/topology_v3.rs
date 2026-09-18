//! Governed, deterministic topology proposal V3.
//!
//! This writer produces next-generation structural candidates only. It never
//! mutates the running graph, installs code, selects itself, promotes a release
//! or grants authority. Independent selection and runtime canary admission stay
//! in their owning control planes.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ProposalStatus;

pub const MAX_TOPOLOGY_CHANGES_V3: usize = 64;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum TopologyOperationV3 {
    Add,
    Replace,
    Rewire,
    Retire,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyChangeV3 {
    pub module_id: StableId,
    pub operation: TopologyOperationV3,
    pub predecessor_binding_digest: Option<Digest32>,
    pub candidate_binding_digest: Option<Digest32>,
    pub dependency_set_digest: Digest32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalRequestV3 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    /// Identity inequality is a structural check, not proof of independence.
    pub evaluator_id: StableId,
    pub predecessor_generation: Generation,
    pub candidate_generation: Generation,
    pub predecessor_topology_digest: Digest32,
    pub candidate_topology_digest: Digest32,
    /// Mandatory no-change candidate for independent evaluation.
    pub no_change_baseline_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub changes: Vec<TopologyChangeV3>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyProposalV3 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub predecessor_generation: Generation,
    pub candidate_generation: Generation,
    pub predecessor_topology_digest: Digest32,
    pub candidate_topology_digest: Digest32,
    pub no_change_baseline_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub changes: Vec<TopologyChangeV3>,
    pub proposal_digest: Digest32,
    pub status: ProposalStatus,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyProposalErrorV3 {
    SelfEvaluation,
    GenerationNotExactSuccessor,
    EmptyDigest(&'static str),
    SameTopology,
    NoChangeBaselineMismatch,
    RollbackPredecessorMismatch,
    ChangeCount,
    DuplicateModule(String),
    NonCanonicalOrder,
    InvalidOperationBinding(String),
    ProposalDigestMismatch,
    AuthorityGranted,
    Arithmetic,
}

impl std::fmt::Display for TopologyProposalErrorV3 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for TopologyProposalErrorV3 {}

pub fn propose_topology_v3(
    mut request: TopologyProposalRequestV3,
) -> Result<TopologyProposalV3, TopologyProposalErrorV3> {
    validate_header(
        &request.proposer_id,
        &request.evaluator_id,
        request.predecessor_generation,
        request.candidate_generation,
        request.predecessor_topology_digest,
        request.candidate_topology_digest,
        request.no_change_baseline_digest,
        request.evaluation_digest,
        request.rollback_predecessor_digest,
    )?;
    canonicalize_changes(&mut request.changes)?;
    let mut proposal = TopologyProposalV3 {
        proposal_id: request.proposal_id,
        proposer_id: request.proposer_id,
        evaluator_id: request.evaluator_id,
        predecessor_generation: request.predecessor_generation,
        candidate_generation: request.candidate_generation,
        predecessor_topology_digest: request.predecessor_topology_digest,
        candidate_topology_digest: request.candidate_topology_digest,
        no_change_baseline_digest: request.no_change_baseline_digest,
        evaluation_digest: request.evaluation_digest,
        rollback_predecessor_digest: request.rollback_predecessor_digest,
        changes: request.changes,
        proposal_digest: Digest32::ZERO,
        status: ProposalStatus::RequiresIndependentAcceptance,
        authority: AuthorityPosture::DENY_ALL,
    };
    proposal.proposal_digest = digest_topology_proposal_v3(&proposal)?;
    verify_topology_proposal_v3(&proposal)?;
    Ok(proposal)
}

pub fn verify_topology_proposal_v3(
    proposal: &TopologyProposalV3,
) -> Result<(), TopologyProposalErrorV3> {
    validate_header(
        &proposal.proposer_id,
        &proposal.evaluator_id,
        proposal.predecessor_generation,
        proposal.candidate_generation,
        proposal.predecessor_topology_digest,
        proposal.candidate_topology_digest,
        proposal.no_change_baseline_digest,
        proposal.evaluation_digest,
        proposal.rollback_predecessor_digest,
    )?;
    if proposal.authority.grants_any() {
        return Err(TopologyProposalErrorV3::AuthorityGranted);
    }
    let mut canonical = proposal.changes.clone();
    canonicalize_changes(&mut canonical)?;
    if canonical != proposal.changes {
        return Err(TopologyProposalErrorV3::NonCanonicalOrder);
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_topology_proposal_v3(proposal)?
    {
        return Err(TopologyProposalErrorV3::ProposalDigestMismatch);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn validate_header(
    proposer_id: &StableId,
    evaluator_id: &StableId,
    predecessor_generation: Generation,
    candidate_generation: Generation,
    predecessor_topology_digest: Digest32,
    candidate_topology_digest: Digest32,
    no_change_baseline_digest: Digest32,
    evaluation_digest: Digest32,
    rollback_predecessor_digest: Digest32,
) -> Result<(), TopologyProposalErrorV3> {
    if proposer_id == evaluator_id {
        return Err(TopologyProposalErrorV3::SelfEvaluation);
    }
    if predecessor_generation.next() != Ok(candidate_generation) {
        return Err(TopologyProposalErrorV3::GenerationNotExactSuccessor);
    }
    for (name, digest) in [
        ("predecessor topology", predecessor_topology_digest),
        ("candidate topology", candidate_topology_digest),
        ("no-change baseline", no_change_baseline_digest),
        ("evaluation", evaluation_digest),
        ("rollback predecessor", rollback_predecessor_digest),
    ] {
        if digest.is_zero() {
            return Err(TopologyProposalErrorV3::EmptyDigest(name));
        }
    }
    if predecessor_topology_digest == candidate_topology_digest {
        return Err(TopologyProposalErrorV3::SameTopology);
    }
    if no_change_baseline_digest != predecessor_topology_digest {
        return Err(TopologyProposalErrorV3::NoChangeBaselineMismatch);
    }
    if rollback_predecessor_digest != predecessor_topology_digest {
        return Err(TopologyProposalErrorV3::RollbackPredecessorMismatch);
    }
    Ok(())
}

fn canonicalize_changes(
    changes: &mut Vec<TopologyChangeV3>,
) -> Result<(), TopologyProposalErrorV3> {
    if !(1..=MAX_TOPOLOGY_CHANGES_V3).contains(&changes.len()) {
        return Err(TopologyProposalErrorV3::ChangeCount);
    }
    changes.sort_by(|left, right| left.module_id.cmp(&right.module_id));
    let mut seen = BTreeSet::new();
    for change in changes.iter() {
        if !seen.insert(change.module_id.clone()) {
            return Err(TopologyProposalErrorV3::DuplicateModule(
                change.module_id.to_string(),
            ));
        }
        for (name, digest) in [
            ("dependency set", change.dependency_set_digest),
            ("change evidence", change.evidence_digest),
        ] {
            if digest.is_zero() {
                return Err(TopologyProposalErrorV3::EmptyDigest(name));
            }
        }
        let valid = match change.operation {
            TopologyOperationV3::Add => {
                change.predecessor_binding_digest.is_none()
                    && change
                        .candidate_binding_digest
                        .is_some_and(|digest| !digest.is_zero())
            }
            TopologyOperationV3::Replace => {
                matches!(
                    (change.predecessor_binding_digest, change.candidate_binding_digest),
                    (Some(predecessor), Some(candidate))
                        if !predecessor.is_zero()
                            && !candidate.is_zero()
                            && predecessor != candidate
                )
            }
            TopologyOperationV3::Rewire => {
                matches!(
                    (change.predecessor_binding_digest, change.candidate_binding_digest),
                    (Some(predecessor), Some(candidate))
                        if !predecessor.is_zero() && !candidate.is_zero()
                )
            }
            TopologyOperationV3::Retire => {
                change
                    .predecessor_binding_digest
                    .is_some_and(|digest| !digest.is_zero())
                    && change.candidate_binding_digest.is_none()
            }
        };
        if !valid {
            return Err(TopologyProposalErrorV3::InvalidOperationBinding(
                change.module_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn digest_topology_proposal_v3(
    proposal: &TopologyProposalV3,
) -> Result<Digest32, TopologyProposalErrorV3> {
    let mut bytes = b"hepta.plasticity.topology-proposal.v3".to_vec();
    push_id(&mut bytes, &proposal.proposal_id)?;
    push_id(&mut bytes, &proposal.proposer_id)?;
    push_id(&mut bytes, &proposal.evaluator_id)?;
    bytes.extend_from_slice(&proposal.predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_generation.get().to_be_bytes());
    for digest in [
        proposal.predecessor_topology_digest,
        proposal.candidate_topology_digest,
        proposal.no_change_baseline_digest,
        proposal.evaluation_digest,
        proposal.rollback_predecessor_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, proposal.changes.len())?;
    for change in &proposal.changes {
        push_id(&mut bytes, &change.module_id)?;
        bytes.push(match change.operation {
            TopologyOperationV3::Add => 0,
            TopologyOperationV3::Replace => 1,
            TopologyOperationV3::Rewire => 2,
            TopologyOperationV3::Retire => 3,
        });
        push_optional_digest(&mut bytes, change.predecessor_binding_digest);
        push_optional_digest(&mut bytes, change.candidate_binding_digest);
        bytes.extend_from_slice(change.dependency_set_digest.as_array());
        bytes.extend_from_slice(change.evidence_digest.as_array());
    }
    bytes.push(match proposal.status {
        ProposalStatus::RequiresIndependentAcceptance => 0,
    });
    bytes.push(0);
    Ok(Digest32::of_bytes(&bytes))
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), TopologyProposalErrorV3> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| TopologyProposalErrorV3::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), TopologyProposalErrorV3> {
    bytes.extend_from_slice(
        &u32::try_from(value)
            .map_err(|_| TopologyProposalErrorV3::Arithmetic)?
            .to_be_bytes(),
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn request() -> TopologyProposalRequestV3 {
        TopologyProposalRequestV3 {
            proposal_id: id("topology.proposal.8"),
            proposer_id: id("generator"),
            evaluator_id: id("evaluator"),
            predecessor_generation: Generation::new(7).expect("generation"),
            candidate_generation: Generation::new(8).expect("generation"),
            predecessor_topology_digest: digest("topology-7"),
            candidate_topology_digest: digest("topology-8"),
            no_change_baseline_digest: digest("topology-7"),
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: digest("topology-7"),
            changes: vec![
                TopologyChangeV3 {
                    module_id: id("prompt.optimizer"),
                    operation: TopologyOperationV3::Replace,
                    predecessor_binding_digest: Some(digest("prompt-old")),
                    candidate_binding_digest: Some(digest("prompt-new")),
                    dependency_set_digest: digest("deps-prompt"),
                    evidence_digest: digest("evidence-prompt"),
                },
                TopologyChangeV3 {
                    module_id: id("future.adapter"),
                    operation: TopologyOperationV3::Add,
                    predecessor_binding_digest: None,
                    candidate_binding_digest: Some(digest("adapter-new")),
                    dependency_set_digest: digest("deps-adapter"),
                    evidence_digest: digest("evidence-adapter"),
                },
            ],
        }
    }

    #[test]
    fn proposal_is_canonical_deny_all_and_exact_successor() {
        let proposal = propose_topology_v3(request()).expect("proposal");
        verify_topology_proposal_v3(&proposal).expect("verify");
        assert_eq!(proposal.changes[0].module_id.as_str(), "future.adapter");
        assert_eq!(proposal.changes[1].module_id.as_str(), "prompt.optimizer");
        assert!(!proposal.authority.grants_any());
    }

    #[test]
    fn no_change_and_rollback_are_bound_to_predecessor() {
        let mut value = request();
        value.no_change_baseline_digest = digest("other");
        assert_eq!(
            propose_topology_v3(value).unwrap_err(),
            TopologyProposalErrorV3::NoChangeBaselineMismatch
        );
        let mut value = request();
        value.rollback_predecessor_digest = digest("other");
        assert_eq!(
            propose_topology_v3(value).unwrap_err(),
            TopologyProposalErrorV3::RollbackPredecessorMismatch
        );
    }

    #[test]
    fn operation_shapes_fail_closed() {
        let mut value = request();
        value.changes[0].candidate_binding_digest = value.changes[0].predecessor_binding_digest;
        assert!(matches!(
            propose_topology_v3(value),
            Err(TopologyProposalErrorV3::InvalidOperationBinding(_))
        ));
    }
}
