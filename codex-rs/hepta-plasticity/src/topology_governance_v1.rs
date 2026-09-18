//! Typed writer-handoff validation for topology proposals.
//!
//! A topology proposal remains authority-free. These records prove that every
//! structural candidate carries a concrete migration/writer-handoff design
//! whose digest matches the proposal. They do not execute the handoff.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, Generation, StableId};

use crate::{
    TopologyCandidateKindV2, TopologyChangeV2, TopologyOperationV2, TopologyProposalV2,
    verify_topology_proposal_v2,
};

const MAX_PROTECTED_TOPOLOGY_MODULES: usize = 256;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ProtectedTopologyClassV1 {
    Authority,
    Evaluator,
    Evidence,
    Deletion,
    Privacy,
    Secret,
    Release,
    RuntimeHost,
}

impl ProtectedTopologyClassV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Authority => 0,
            Self::Evaluator => 1,
            Self::Evidence => 2,
            Self::Deletion => 3,
            Self::Privacy => 4,
            Self::Secret => 5,
            Self::Release => 6,
            Self::RuntimeHost => 7,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ProtectedTopologyModuleV1 {
    pub module_id: StableId,
    pub class: ProtectedTopologyClassV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyMutationPolicyV1 {
    pub policy_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub revision: u64,
    pub protected_modules: Vec<ProtectedTopologyModuleV1>,
    pub policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyMutationPolicyErrorV1 {
    EmptyArtifactDigest,
    InvalidRevision,
    ProtectedLimitExceeded,
    DuplicateProtectedModule(String),
    DigestMismatch,
    ArtifactMismatch,
    ProtectedModuleTargeted(String),
    Arithmetic,
}

impl fmt::Display for TopologyMutationPolicyErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for TopologyMutationPolicyErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopologyWriterHandoffV1 {
    pub module_id: StableId,
    pub operation: TopologyOperationV2,
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

/// Construct a canonical protected-surface policy for structural proposals.
pub fn build_topology_mutation_policy_v1(
    policy_id: StableId,
    selected_artifact_digest: Digest32,
    revision: u64,
    mut protected_modules: Vec<ProtectedTopologyModuleV1>,
) -> Result<TopologyMutationPolicyV1, TopologyMutationPolicyErrorV1> {
    canonicalize_topology_policy(
        selected_artifact_digest,
        revision,
        &mut protected_modules,
    )?;
    let mut policy = TopologyMutationPolicyV1 {
        policy_id,
        selected_artifact_digest,
        revision,
        protected_modules,
        policy_digest: Digest32::ZERO,
    };
    policy.policy_digest = digest_topology_policy(&policy)?;
    Ok(policy)
}

pub fn verify_topology_mutation_policy_v1(
    policy: &TopologyMutationPolicyV1,
) -> Result<(), TopologyMutationPolicyErrorV1> {
    let mut protected = policy.protected_modules.clone();
    canonicalize_topology_policy(
        policy.selected_artifact_digest,
        policy.revision,
        &mut protected,
    )?;
    if protected != policy.protected_modules
        || policy.policy_digest.is_zero()
        || policy.policy_digest != digest_topology_policy(policy)?
    {
        return Err(TopologyMutationPolicyErrorV1::DigestMismatch);
    }
    Ok(())
}

pub fn verify_topology_changes_against_policy_v1(
    selected_artifact_digest: Digest32,
    changes: &[TopologyChangeV2],
    policy: &TopologyMutationPolicyV1,
) -> Result<(), TopologyMutationPolicyErrorV1> {
    verify_topology_mutation_policy_v1(policy)?;
    if selected_artifact_digest != policy.selected_artifact_digest {
        return Err(TopologyMutationPolicyErrorV1::ArtifactMismatch);
    }
    let protected = policy
        .protected_modules
        .iter()
        .map(|entry| entry.module_id.clone())
        .collect::<BTreeSet<_>>();
    for change in changes {
        if protected.contains(&change.module_id) {
            return Err(TopologyMutationPolicyErrorV1::ProtectedModuleTargeted(
                change.module_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn canonicalize_topology_policy(
    selected_artifact_digest: Digest32,
    revision: u64,
    protected_modules: &mut Vec<ProtectedTopologyModuleV1>,
) -> Result<(), TopologyMutationPolicyErrorV1> {
    if selected_artifact_digest.is_zero() {
        return Err(TopologyMutationPolicyErrorV1::EmptyArtifactDigest);
    }
    if revision == 0 {
        return Err(TopologyMutationPolicyErrorV1::InvalidRevision);
    }
    if protected_modules.len() > MAX_PROTECTED_TOPOLOGY_MODULES {
        return Err(TopologyMutationPolicyErrorV1::ProtectedLimitExceeded);
    }
    protected_modules.sort();
    let mut module_ids = BTreeSet::new();
    for protected in protected_modules {
        if !module_ids.insert(protected.module_id.clone()) {
            return Err(TopologyMutationPolicyErrorV1::DuplicateProtectedModule(
                protected.module_id.to_string(),
            ));
        }
    }
    Ok(())
}

fn digest_topology_policy(
    policy: &TopologyMutationPolicyV1,
) -> Result<Digest32, TopologyMutationPolicyErrorV1> {
    let mut bytes = b"hepta.plasticity.topology-mutation-policy.v1\0".to_vec();
    push_policy_id(&mut bytes, &policy.policy_id)?;
    bytes.extend_from_slice(policy.selected_artifact_digest.as_array());
    bytes.extend_from_slice(&policy.revision.to_be_bytes());
    let count = u32::try_from(policy.protected_modules.len())
        .map_err(|_| TopologyMutationPolicyErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for protected in &policy.protected_modules {
        push_policy_id(&mut bytes, &protected.module_id)?;
        bytes.push(protected.class.tag());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_policy_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), TopologyMutationPolicyErrorV1> {
    let raw = value.as_str().as_bytes();
    let length =
        u32::try_from(raw.len()).map_err(|_| TopologyMutationPolicyErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
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
        if handoff.module_id != change.module_id || handoff.operation != change.operation {
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
    bytes.push(topology_operation_tag(handoff.operation));
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

fn topology_operation_tag(operation: TopologyOperationV2) -> u8 {
    match operation {
        TopologyOperationV2::Add => 0,
        TopologyOperationV2::Remove => 1,
        TopologyOperationV2::Replace => 2,
        TopologyOperationV2::Split => 3,
        TopologyOperationV2::Merge => 4,
        TopologyOperationV2::Rewire => 5,
        TopologyOperationV2::Retire => 6,
    }
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
            operation: TopologyOperationV2::Replace,
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
            operation: TopologyOperationV2::Replace,
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
            operation: TopologyOperationV2::Rewire,
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

    #[test]
    fn handoff_operation_must_match_candidate_operation() {
        let selected = digest("artifact:operation-mismatch");
        let handoff = bind_topology_writer_handoff_v1(TopologyWriterHandoffV1 {
            module_id: id("module:a"),
            operation: TopologyOperationV2::Replace,
            source_writer_id: id("writer:old"),
            destination_writer_id: id("writer:new"),
            source_domain_digest: digest("domain:old"),
            destination_domain_digest: digest("domain:new"),
            baseline_generation: generation(14),
            candidate_generation: generation(15),
            migration_digest: digest("migration"),
            rollback_digest: digest("rollback"),
            handoff_digest: Digest32::ZERO,
        })
        .expect("handoff");
        let proposal = propose_topology_v2(TopologyProposalRequestV2 {
            proposal_id: id("topology:operation-mismatch"),
            proposer_id: id("generator"),
            evaluator_id: id("evaluator"),
            selected_artifact_digest: selected,
            window: ProposalWindowV2 {
                window_id: id("window:operation-mismatch"),
                window_digest: digest("window:operation-mismatch"),
            },
            baseline_generation: generation(14),
            candidate_generation: generation(15),
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: selected,
            changes: vec![TopologyChangeV2 {
                module_id: id("module:a"),
                operation: TopologyOperationV2::Rewire,
                predecessor_digest: Some(digest("old")),
                candidate_digest: Some(digest("new")),
                migration_digest: handoff.migration_digest,
                rollback_digest: handoff.rollback_digest,
                writer_handoff_digest: handoff.handoff_digest,
                evidence_digest: digest("evidence"),
            }],
        })
        .expect("proposal");
        assert!(matches!(
            verify_topology_writer_handoffs_v1(&proposal, &[handoff]),
            Err(TopologyGovernanceErrorV1::HandoffDigestMismatch(module))
                if module == "module:a"
        ));
    }

    #[test]
    fn topology_policy_rejects_protected_evaluator_surface() {
        let selected = digest("artifact:policy");
        let policy = build_topology_mutation_policy_v1(
            id("topology-policy:1"),
            selected,
            1,
            vec![ProtectedTopologyModuleV1 {
                module_id: id("learning.eval"),
                class: ProtectedTopologyClassV1::Evaluator,
            }],
        )
        .expect("policy");
        let protected_change = TopologyChangeV2 {
            module_id: id("learning.eval"),
            operation: TopologyOperationV2::Rewire,
            predecessor_digest: Some(digest("eval:old")),
            candidate_digest: Some(digest("eval:new")),
            migration_digest: digest("eval:migration"),
            rollback_digest: digest("eval:rollback"),
            writer_handoff_digest: digest("eval:handoff"),
            evidence_digest: digest("eval:evidence"),
        };
        assert!(matches!(
            verify_topology_changes_against_policy_v1(selected, &[protected_change], &policy),
            Err(TopologyMutationPolicyErrorV1::ProtectedModuleTargeted(module))
                if module == "learning.eval"
        ));
    }
}
