//! Typed governance for topology proposals and writer handoff plans.
//!
//! TopologyProposalV2 keeps a compact digest boundary. This module makes the
//! writer-handoff digest meaningful by requiring one typed, validated plan for
//! every structural update before a proposal can enter the governed registry.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, StableId};

use crate::{
    TopologyCandidateKindV2, TopologyOperationV2, TopologyProposalV2,
    verify_topology_proposal_v2,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WriterHandoffPlanV1 {
    pub module_id: StableId,
    pub from_owner: StableId,
    pub to_owner: StableId,
    pub predecessor_writer_fence: u64,
    pub successor_writer_fence: u64,
    pub source_store_digest: Digest32,
    pub migration_digest: Digest32,
    pub rollback_digest: Digest32,
    pub acknowledgement_contract_digest: Digest32,
    pub plan_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GovernedTopologyProposalV1 {
    pub proposal: TopologyProposalV2,
    pub handoffs: Vec<WriterHandoffPlanV1>,
    pub handoff_set_digest: Digest32,
    pub source_authentication_digest: Digest32,
    pub evaluation_authentication_digest: Digest32,
    pub admission_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TopologyGovernanceErrorV1 {
    Proposal(crate::TopologyProposalErrorV2),
    EmptyDigest(&'static str),
    OwnerCollision(String),
    InvalidFence(String),
    DigestMismatch(String),
    MissingHandoff(String),
    UnexpectedHandoff(String),
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

pub fn build_writer_handoff_plan_v1(
    module_id: StableId,
    from_owner: StableId,
    to_owner: StableId,
    predecessor_writer_fence: u64,
    successor_writer_fence: u64,
    source_store_digest: Digest32,
    migration_digest: Digest32,
    rollback_digest: Digest32,
    acknowledgement_contract_digest: Digest32,
) -> Result<WriterHandoffPlanV1, TopologyGovernanceErrorV1> {
    let mut plan = WriterHandoffPlanV1 {
        module_id,
        from_owner,
        to_owner,
        predecessor_writer_fence,
        successor_writer_fence,
        source_store_digest,
        migration_digest,
        rollback_digest,
        acknowledgement_contract_digest,
        plan_digest: Digest32::ZERO,
    };
    validate_writer_handoff_plan_v1(&plan, None)?;
    plan.plan_digest = digest_handoff(&plan)?;
    Ok(plan)
}

pub fn validate_writer_handoff_plan_v1(
    plan: &WriterHandoffPlanV1,
    expected_digest: Option<Digest32>,
) -> Result<(), TopologyGovernanceErrorV1> {
    if plan.from_owner == plan.to_owner {
        return Err(TopologyGovernanceErrorV1::OwnerCollision(
            plan.module_id.to_string(),
        ));
    }
    if plan.predecessor_writer_fence == 0
        || plan.successor_writer_fence <= plan.predecessor_writer_fence
    {
        return Err(TopologyGovernanceErrorV1::InvalidFence(
            plan.module_id.to_string(),
        ));
    }
    for (name, digest) in [
        ("source store", plan.source_store_digest),
        ("migration", plan.migration_digest),
        ("rollback", plan.rollback_digest),
        ("acknowledgement contract", plan.acknowledgement_contract_digest),
    ] {
        if digest.is_zero() {
            return Err(TopologyGovernanceErrorV1::EmptyDigest(name));
        }
    }
    if let Some(expected) = expected_digest
        && (plan.plan_digest.is_zero()
            || plan.plan_digest != expected
            || digest_handoff(plan)? != expected)
    {
        return Err(TopologyGovernanceErrorV1::DigestMismatch(
            plan.module_id.to_string(),
        ));
    }
    Ok(())
}

pub fn admit_governed_topology_v1(
    proposal: TopologyProposalV2,
    mut handoffs: Vec<WriterHandoffPlanV1>,
    source_authentication_digest: Digest32,
    evaluation_authentication_digest: Digest32,
) -> Result<GovernedTopologyProposalV1, TopologyGovernanceErrorV1> {
    verify_topology_proposal_v2(&proposal)?;
    if source_authentication_digest.is_zero() {
        return Err(TopologyGovernanceErrorV1::EmptyDigest(
            "source authentication",
        ));
    }
    if evaluation_authentication_digest.is_zero() {
        return Err(TopologyGovernanceErrorV1::EmptyDigest(
            "evaluation authentication",
        ));
    }

    handoffs.sort_by(|left, right| left.module_id.cmp(&right.module_id));
    let mut by_module = BTreeMap::new();
    for handoff in &handoffs {
        if by_module
            .insert(handoff.module_id.clone(), handoff)
            .is_some()
        {
            return Err(TopologyGovernanceErrorV1::UnexpectedHandoff(
                handoff.module_id.to_string(),
            ));
        }
    }

    for candidate in proposal
        .candidates
        .iter()
        .filter(|candidate| candidate.kind == TopologyCandidateKindV2::Update)
    {
        let change = candidate
            .changes
            .first()
            .ok_or_else(|| TopologyGovernanceErrorV1::MissingHandoff(
                candidate.candidate_id.to_string(),
            ))?;
        let handoff = by_module
            .remove(&change.module_id)
            .ok_or_else(|| TopologyGovernanceErrorV1::MissingHandoff(
                change.module_id.to_string(),
            ))?;
        validate_writer_handoff_plan_v1(handoff, Some(change.writer_handoff_digest))?;
        if handoff.migration_digest != change.migration_digest
            || handoff.rollback_digest != change.rollback_digest
        {
            return Err(TopologyGovernanceErrorV1::DigestMismatch(
                change.module_id.to_string(),
            ));
        }
        match change.operation {
            TopologyOperationV2::Add
            | TopologyOperationV2::Remove
            | TopologyOperationV2::Replace
            | TopologyOperationV2::Split
            | TopologyOperationV2::Merge
            | TopologyOperationV2::Rewire
            | TopologyOperationV2::Retire => {}
        }
    }
    if let Some((module_id, _)) = by_module.into_iter().next() {
        return Err(TopologyGovernanceErrorV1::UnexpectedHandoff(
            module_id.to_string(),
        ));
    }

    let handoff_set_digest = digest_handoff_set(&handoffs)?;
    let mut bytes = b"hepta.plasticity.topology-admission.v1\0".to_vec();
    for digest in [
        proposal.proposal_digest,
        handoff_set_digest,
        source_authentication_digest,
        evaluation_authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let admission_digest = Digest32::of_bytes(&bytes);
    Ok(GovernedTopologyProposalV1 {
        proposal,
        handoffs,
        handoff_set_digest,
        source_authentication_digest,
        evaluation_authentication_digest,
        admission_digest,
    })
}

fn digest_handoff(plan: &WriterHandoffPlanV1) -> Result<Digest32, TopologyGovernanceErrorV1> {
    let mut bytes = b"hepta.plasticity.writer-handoff.v1\0".to_vec();
    push_id(&mut bytes, &plan.module_id)?;
    push_id(&mut bytes, &plan.from_owner)?;
    push_id(&mut bytes, &plan.to_owner)?;
    bytes.extend_from_slice(&plan.predecessor_writer_fence.to_be_bytes());
    bytes.extend_from_slice(&plan.successor_writer_fence.to_be_bytes());
    for digest in [
        plan.source_store_digest,
        plan.migration_digest,
        plan.rollback_digest,
        plan.acknowledgement_contract_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_handoff_set(
    handoffs: &[WriterHandoffPlanV1],
) -> Result<Digest32, TopologyGovernanceErrorV1> {
    let mut bytes = b"hepta.plasticity.writer-handoff-set.v1\0".to_vec();
    push_len(&mut bytes, handoffs.len())?;
    for handoff in handoffs {
        bytes.extend_from_slice(handoff.plan_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), TopologyGovernanceErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| TopologyGovernanceErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
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
    use codex_hepta_types::Generation;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    fn governed() -> GovernedTopologyProposalV1 {
        let handoff = build_writer_handoff_plan_v1(
            id("module:adapter"),
            id("owner:old"),
            id("owner:new"),
            7,
            8,
            digest(b"source-store"),
            digest(b"migration"),
            digest(b"rollback"),
            digest(b"ack-contract"),
        )
        .expect("handoff");
        let artifact = digest(b"artifact");
        let proposal = propose_topology_v2(TopologyProposalRequestV2 {
            proposal_id: id("topology:governed:1"),
            proposer_id: id("generator:1"),
            evaluator_id: id("evaluator:1"),
            selected_artifact_digest: artifact,
            window: ProposalWindowV2 {
                window_id: id("window:1"),
                window_digest: digest(b"window"),
            },
            baseline_generation: generation(1),
            candidate_generation: generation(2),
            evaluation_digest: digest(b"evaluation"),
            rollback_predecessor_digest: artifact,
            changes: vec![TopologyChangeV2 {
                module_id: id("module:adapter"),
                operation: TopologyOperationV2::Replace,
                predecessor_digest: Some(digest(b"old")),
                candidate_digest: Some(digest(b"new")),
                migration_digest: handoff.migration_digest,
                rollback_digest: handoff.rollback_digest,
                writer_handoff_digest: handoff.plan_digest,
                evidence_digest: digest(b"evidence"),
            }],
        })
        .expect("proposal");
        admit_governed_topology_v1(
            proposal,
            vec![handoff],
            digest(b"source-auth"),
            digest(b"evaluation-auth"),
        )
        .expect("governed")
    }

    #[test]
    fn governed_topology_binds_exact_writer_handoff() {
        let value = governed();
        assert!(!value.admission_digest.is_zero());
        assert_eq!(value.handoffs.len(), 1);
    }

    #[test]
    fn writer_handoff_requires_distinct_owner_and_advancing_fence() {
        assert!(matches!(
            build_writer_handoff_plan_v1(
                id("module:adapter"),
                id("owner:same"),
                id("owner:same"),
                7,
                8,
                digest(b"source-store"),
                digest(b"migration"),
                digest(b"rollback"),
                digest(b"ack-contract"),
            ),
            Err(TopologyGovernanceErrorV1::OwnerCollision(_))
        ));
        assert!(matches!(
            build_writer_handoff_plan_v1(
                id("module:adapter"),
                id("owner:old"),
                id("owner:new"),
                8,
                8,
                digest(b"source-store"),
                digest(b"migration"),
                digest(b"rollback"),
                digest(b"ack-contract"),
            ),
            Err(TopologyGovernanceErrorV1::InvalidFence(_))
        ));
    }
}
