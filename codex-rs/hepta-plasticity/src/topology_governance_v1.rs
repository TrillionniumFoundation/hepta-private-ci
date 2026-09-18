//! Typed writer-handoff validation for topology proposals.
//!
//! A topology proposal remains authority-free. These records prove that every
//! structural candidate carries a concrete migration/writer-handoff design
//! whose digest matches the proposal. They do not execute the handoff.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, Generation, StableId};

use crate::{TopologyCandidateKindV2, TopologyProposalV2, verify_topology_proposal_v2};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyWriterHandoffV1 {
    pub module_id: StableId,
    pub source_writer_id: StableId,
    pub destination_writer_id: StableId,
    pub source_domain_digest: Digest32,
    pub destination_domain_digest: Digest32,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub migration_digest: Digest32,
    pub rollback_digest: Digest32,
    pub handoff_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyGovernanceErrorV1 {
    Proposal(crate::TopologyProposalErrorV2),
    EmptyDigest(&'static str),
    SameWriter(String),
    GenerationMismatch(String),
    DuplicateHandoff(String),
    MissingHandoff(String),
    UnexpectedHandoff(String),
    HandoffDigestMismatch(String),
    MigrationMismatch(String),
    RollbackMismatch(String),
    Arithmetic,
}

impl fmt::Display for TopologyGovernanceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TopologyGovernanceErrorV1 {}
impl From<crate::TopologyProposalErrorV2> for TopologyGovernanceErrorV1 {
    fn from(value: crate::TopologyProposalErrorV2) -> Self {
        Self::Proposal(value)
    }
}

/// Construct the canonical handoff digest. The caller must then place this exact
/// digest in the corresponding `TopologyChangeV2::writer_handoff_digest`.
pub fn bind_topology_writer_handoff_v1(
    mut handoff: TopologyWriterHandoffV1,
) -> Result<TopologyWriterHandoffV1, TopologyGovernanceErrorV1> {
    validate_handoff_shape(&handoff)?;
    handoff.handoff_digest = digest_handoff(&handoff)?;
    Ok(handoff)
}

pub fn verify_topology_writer_handoff_v1(
    handoff: &TopologyWriterHandoffV1,
) -> Result<(), TopologyGovernanceErrorV1> {
    validate_handoff_shape(handoff)?;
    if handoff.handoff_digest.is_zero() || handoff.handoff_digest != digest_handoff(handoff)? {
        return Err(TopologyGovernanceErrorV1::HandoffDigestMismatch(
            handoff.module_id.to_string(),
        ));
    }
    Ok(())
}

/// Validate one exact handoff for every update candidate in the proposal.
pub fn verify_topology_writer_handoffs_v1(
    proposal: &TopologyProposalV2,
    handoffs: &[TopologyWriterHandoffV1],
) -> Result<Digest32, TopologyGovernanceErrorV1> {
    verify_topology_proposal_v2(proposal)?;
    for handoff in handoffs {
        verify_topology_writer_handoff_v1(handoff)?;
    }
    for (index, handoff) in handoffs.iter().enumerate() {
        if handoffs[..index]
            .iter()
            .any(|existing| existing.handoff_digest == handoff.handoff_digest)
        {
            return Err(TopologyGovernanceErrorV1::DuplicateHandoff(
                handoff.module_id.to_string(),
            ));
        }
    }

    let mut used = vec![false; handoffs.len()];
    let mut bound = Vec::new();
    for candidate in proposal
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
    {
        let change = &candidate.changes[0];
        let matches = handoffs
            .iter()
            .enumerate()
            .filter(|(_, handoff)| handoff.handoff_digest == change.writer_handoff_digest)
            .collect::<Vec<_>>();
        let [(index, handoff)] = matches.as_slice() else {
            return Err(TopologyGovernanceErrorV1::MissingHandoff(
                change.module_id.to_string(),
            ));
        };
        if used[*index] {
            return Err(TopologyGovernanceErrorV1::DuplicateHandoff(
                change.module_id.to_string(),
            ));
        }
        used[*index] = true;
        if handoff.module_id != change.module_id {
            return Err(TopologyGovernanceErrorV1::HandoffDigestMismatch(
                change.module_id.to_string(),
            ));
        }
        if handoff.baseline_generation != proposal.baseline_generation
            || handoff.candidate_generation != proposal.candidate_generation
        {
            return Err(TopologyGovernanceErrorV1::GenerationMismatch(
                change.module_id.to_string(),
            ));
        }
        if handoff.migration_digest != change.migration_digest {
            return Err(TopologyGovernanceErrorV1::MigrationMismatch(
                change.module_id.to_string(),
            ));
        }
        if handoff.rollback_digest != change.rollback_digest {
            return Err(TopologyGovernanceErrorV1::RollbackMismatch(
                change.module_id.to_string(),
            ));
        }
        bound.push(handoff.handoff_digest);
    }
    if let Some((_, unexpected)) = handoffs
        .iter()
        .enumerate()
        .find(|(index, _)| !used[*index])
    {
        return Err(TopologyGovernanceErrorV1::UnexpectedHandoff(
            unexpected.module_id.to_string(),
        ));
    }
    let mut bytes = b"hepta.plasticity.topology-handoff-set.v1\0".to_vec();
    push_len(&mut bytes, bound.len())?;
    for digest in bound {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_handoff_shape(
    handoff: &TopologyWriterHandoffV1,
) -> Result<(), TopologyGovernanceErrorV1> {
    if handoff.source_writer_id == handoff.destination_writer_id {
        return Err(TopologyGovernanceErrorV1::SameWriter(
            handoff.module_id.to_string(),
        ));
    }
    if handoff.baseline_generation.next() != Ok(handoff.candidate_generation) {
        return Err(TopologyGovernanceErrorV1::GenerationMismatch(
            handoff.module_id.to_string(),
        ));
    }
    for (label, digest) in [
        ("source domain", handoff.source_domain_digest),
        ("destination domain", handoff.destination_domain_digest),
        ("migration", handoff.migration_digest),
        ("rollback", handoff.rollback_digest),
    ] {
        if digest.is_zero() {
            return Err(TopologyGovernanceErrorV1::EmptyDigest(label));
        }
    }
    Ok(())
}

fn digest_handoff(
    handoff: &TopologyWriterHandoffV1,
) -> Result<Digest32, TopologyGovernanceErrorV1> {
    let mut bytes = b"hepta.plasticity.topology-writer-handoff.v1\0".to_vec();
    push_id(&mut bytes, &handoff.module_id)?;
    push_id(&mut bytes, &handoff.source_writer_id)?;
    push_id(&mut bytes, &handoff.destination_writer_id)?;
    bytes.extend_from_slice(handoff.source_domain_digest.as_array());
    bytes.extend_from_slice(handoff.destination_domain_digest.as_array());
    bytes.extend_from_slice(&handoff.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&handoff.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(handoff.migration_digest.as_array());
    bytes.extend_from_slice(handoff.rollback_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), TopologyGovernanceErrorV1> {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len())?;
    bytes.extend_from_slice(raw);
    Ok(())
}
fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), TopologyGovernanceErrorV1> {
    let value = u32::try_from(value).map_err(|_| TopologyGovernanceErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        ProposalWindowV2, TopologyChangeV2, TopologyOperationV2, TopologyProposalRequestV2,
        propose_topology_v2,
    };

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    #[test]
    fn typed_handoff_binds_structural_candidate_without_applying_it() {
        let handoff = bind_topology_writer_handoff_v1(TopologyWriterHandoffV1 {
            module_id: id("module:a"),
            source_writer_id: id("writer:old"),
            destination_writer_id: id("writer:new"),
            source_domain_digest: digest("domain:old"),
            destination_domain_digest: digest("domain:new"),
            baseline_generation: generation(4),
            candidate_generation: generation(5),
            migration_digest: digest("migration"),
            rollback_digest: digest("rollback"),
            handoff_digest: Digest32::ZERO,
        })
        .expect("handoff");
        let selected = digest("artifact");
        let proposal = propose_topology_v2(TopologyProposalRequestV2 {
            proposal_id: id("topology:proposal"),
            proposer_id: id("generator"),
            evaluator_id: id("evaluator"),
            selected_artifact_digest: selected,
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: digest("window"),
            },
            baseline_generation: generation(4),
            candidate_generation: generation(5),
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: selected,
            changes: vec![TopologyChangeV2 {
                module_id: id("module:a"),
                operation: TopologyOperationV2::Replace,
                predecessor_digest: Some(digest("old")),
                candidate_digest: Some(digest("new")),
                migration_digest: handoff.migration_digest,
                rollback_digest: handoff.rollback_digest,
                writer_handoff_digest: handoff.handoff_digest,
                evidence_digest: digest("evidence"),
            }],
        })
        .expect("proposal");
        let set_digest = verify_topology_writer_handoffs_v1(&proposal, &[handoff])
            .expect("typed handoff set");
        assert!(!set_digest.is_zero());
        assert!(!proposal.authority.grants_any());
    }

    #[test]
    fn handoffs_are_matched_per_candidate_not_only_per_module() {
        let selected = digest("artifact:alternatives");
        let first = bind_topology_writer_handoff_v1(TopologyWriterHandoffV1 {
            module_id: id("module:a"),
            source_writer_id: id("writer:old"),
            destination_writer_id: id("writer:new"),
            source_domain_digest: digest("domain:old"),
            destination_domain_digest: digest("domain:new"),
            baseline_generation: generation(8),
            candidate_generation: generation(9),
            migration_digest: digest("migration:replace"),
            rollback_digest: digest("rollback:replace"),
            handoff_digest: Digest32::ZERO,
        })
        .expect("first handoff");
        let second = bind_topology_writer_handoff_v1(TopologyWriterHandoffV1 {
            module_id: id("module:a"),
            source_writer_id: id("writer:old"),
            destination_writer_id: id("writer:new"),
            source_domain_digest: digest("domain:old"),
            destination_domain_digest: digest("domain:new"),
            baseline_generation: generation(8),
            candidate_generation: generation(9),
            migration_digest: digest("migration:rewire"),
            rollback_digest: digest("rollback:rewire"),
            handoff_digest: Digest32::ZERO,
        })
        .expect("second handoff");
        let proposal = propose_topology_v2(TopologyProposalRequestV2 {
            proposal_id: id("topology:alternatives"),
            proposer_id: id("generator"),
            evaluator_id: id("evaluator"),
            selected_artifact_digest: selected,
            window: ProposalWindowV2 {
                window_id: id("window:alternatives"),
                window_digest: digest("window:alternatives"),
            },
            baseline_generation: generation(8),
            candidate_generation: generation(9),
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: selected,
            changes: vec![
                TopologyChangeV2 {
                    module_id: id("module:a"),
                    operation: TopologyOperationV2::Replace,
                    predecessor_digest: Some(digest("old")),
                    candidate_digest: Some(digest("replace")),
                    migration_digest: first.migration_digest,
                    rollback_digest: first.rollback_digest,
                    writer_handoff_digest: first.handoff_digest,
                    evidence_digest: digest("evidence:replace"),
                },
                TopologyChangeV2 {
                    module_id: id("module:a"),
                    operation: TopologyOperationV2::Rewire,
                    predecessor_digest: Some(digest("old")),
                    candidate_digest: Some(digest("rewire")),
                    migration_digest: second.migration_digest,
                    rollback_digest: second.rollback_digest,
                    writer_handoff_digest: second.handoff_digest,
                    evidence_digest: digest("evidence:rewire"),
                },
            ],
        })
        .expect("alternative proposal");

        let set_digest =
            verify_topology_writer_handoffs_v1(&proposal, &[first, second]).expect("handoffs");
        assert!(!set_digest.is_zero());
    }
}
