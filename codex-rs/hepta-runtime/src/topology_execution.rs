//! Accepted topology execution at the existing live runtime owner.
//!
//! learning.plasticity remains proposal-only. This boundary requires an
//! independently issued, single-use kernel.authority token and an already
//! admitted successor CNS host. The runtime revalidates proposal/handoff,
//! current/successor generations and actual graph identities immediately before
//! the existing generation replacement call.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_control_plane::CnsHierarchyError;
use codex_hepta_control_plane::CnsOrganHostV1;
use codex_hepta_control_plane::CnsRouteV1;
use codex_hepta_control_plane::OrganStateMigrationV1;
use codex_hepta_plasticity::GovernedTopologyProposalV1;
use codex_hepta_plasticity::TopologyCandidateKindV2;
use codex_hepta_plasticity::TopologyGovernanceErrorV1;
use codex_hepta_plasticity::WriterHandoffPlanV1;
use codex_hepta_plasticity::admit_governed_topology_v1;
use codex_hepta_plasticity::validate_writer_handoff_plan_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const TOPOLOGY_DESTINATION: &str = "runtime.hepta-live-shell.topology";
const TOPOLOGY_RECOVERY_DESTINATION: &str = "runtime.hepta-live-shell.topology-recovery";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTopologySnapshotV1 {
    pub route: CnsRouteV1,
}

impl RuntimeTopologySnapshotV1 {
    pub fn cns_id(&self) -> &StableId {
        &self.route.cns
    }

    pub fn generation(&self) -> Generation {
        self.route.generation
    }

    pub fn hierarchy_digest(&self) -> Digest32 {
        self.route.hierarchy_digest
    }
}

#[derive(Debug)]
pub struct RuntimeTopologySuccessorV1 {
    pub(crate) host: CnsOrganHostV1,
    pub(crate) route: CnsRouteV1,
}

impl RuntimeTopologySuccessorV1 {
    pub fn new(
        host: CnsOrganHostV1,
        route: CnsRouteV1,
    ) -> Result<Self, RuntimeTopologyExecutionError> {
        if host.generation() != route.generation {
            return Err(RuntimeTopologyExecutionError::Binding);
        }
        let expected = host
            .route(&route.source.system, &route.source.organ, route.output_port)
            .map_err(RuntimeTopologyExecutionError::Runtime)?;
        if expected != route {
            return Err(RuntimeTopologyExecutionError::Binding);
        }
        Ok(Self { host, route })
    }

    pub fn snapshot(&self) -> RuntimeTopologySnapshotV1 {
        RuntimeTopologySnapshotV1 {
            route: self.route.clone(),
        }
    }
}

pub trait RuntimeTopologyMigrationOwnerV1: OrganStateMigrationV1 + fmt::Debug + Send {
    /// Bind this executable migration owner to the exact governed handoff plan.
    /// The runtime refuses a callback prepared for any other migration/rollback
    /// or writer-fence contract before consuming final-use authority.
    fn handoff_plan_digest(&self) -> Digest32;
}

#[derive(Debug)]
pub struct RuntimeTopologyApplyRequestV1 {
    pub governed: GovernedTopologyProposalV1,
    pub candidate_id: StableId,
    /// Identity selected by the external authority issuer. The runtime trusts
    /// it only when the signed final-use grant binds the same value.
    pub accepted_subject_id: StableId,
    /// Authoritative state owner for the exact writer-handoff plan. Plasticity
    /// supplies only the digest-bound plan; the external runtime owns execution.
    pub migration: Box<dyn RuntimeTopologyMigrationOwnerV1>,
    pub successor: RuntimeTopologySuccessorV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTopologyApplyReceiptV1 {
    pub proposal_id: StableId,
    pub candidate_id: StableId,
    pub admission_digest: Digest32,
    pub handoff_plan_digest: Digest32,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub predecessor_hierarchy_digest: Digest32,
    pub successor_hierarchy_digest: Digest32,
    pub final_use_request_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Debug)]
pub enum RuntimeTopologyExecutionError {
    Governance(TopologyGovernanceErrorV1),
    FinalUse(FinalUseError),
    Runtime(CnsHierarchyError),
    Binding,
    Generation,
    Unavailable,
}

impl fmt::Display for RuntimeTopologyExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeTopologyExecutionError {}

impl From<TopologyGovernanceErrorV1> for RuntimeTopologyExecutionError {
    fn from(value: TopologyGovernanceErrorV1) -> Self {
        Self::Governance(value)
    }
}

impl From<FinalUseError> for RuntimeTopologyExecutionError {
    fn from(value: FinalUseError) -> Self {
        Self::FinalUse(value)
    }
}

impl From<CnsHierarchyError> for RuntimeTopologyExecutionError {
    fn from(value: CnsHierarchyError) -> Self {
        Self::Runtime(value)
    }
}

pub(crate) struct ValidatedRuntimeTopologyTransitionV1 {
    pub binding: FinalUseBinding,
    pub proposal_id: StableId,
    pub candidate_id: StableId,
    pub admission_digest: Digest32,
    pub handoff: WriterHandoffPlanV1,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub predecessor_hierarchy_digest: Digest32,
    pub successor_hierarchy_digest: Digest32,
    pub final_use_request_digest: Digest32,
}

pub(crate) fn validate_runtime_topology_transition_v1(
    current_route: &CnsRouteV1,
    current_generation: Generation,
    request: &RuntimeTopologyApplyRequestV1,
) -> Result<ValidatedRuntimeTopologyTransitionV1, RuntimeTopologyExecutionError> {
    validate_runtime_topology_transition_for_destination_v1(
        current_route,
        current_generation,
        request,
        TOPOLOGY_DESTINATION,
    )
}

pub(crate) fn validate_runtime_topology_recovery_v1(
    current_route: &CnsRouteV1,
    current_generation: Generation,
    request: &RuntimeTopologyApplyRequestV1,
) -> Result<ValidatedRuntimeTopologyTransitionV1, RuntimeTopologyExecutionError> {
    validate_runtime_topology_transition_for_destination_v1(
        current_route,
        current_generation,
        request,
        TOPOLOGY_RECOVERY_DESTINATION,
    )
}

fn validate_runtime_topology_transition_for_destination_v1(
    current_route: &CnsRouteV1,
    current_generation: Generation,
    request: &RuntimeTopologyApplyRequestV1,
    destination_id: &str,
) -> Result<ValidatedRuntimeTopologyTransitionV1, RuntimeTopologyExecutionError> {
    let rebuilt = admit_governed_topology_v1(
        request.governed.proposal.clone(),
        request.governed.handoffs.clone(),
        request.governed.source_authentication_digest,
        request.governed.evaluation_authentication_digest,
    )?;
    if rebuilt != request.governed || request.governed.proposal.authority.grants_any() {
        return Err(RuntimeTopologyExecutionError::Binding);
    }

    let proposal = &request.governed.proposal;
    let successor = request.successor.snapshot();
    if proposal.baseline_generation != current_generation
        || proposal.candidate_generation != successor.route.generation
        || current_generation
            .next()
            .map_err(|_| RuntimeTopologyExecutionError::Generation)?
            != successor.route.generation
        || current_route.generation != current_generation
        || current_route.cns != successor.route.cns
    {
        return Err(RuntimeTopologyExecutionError::Generation);
    }

    let candidate = proposal
        .candidates
        .iter()
        .find(|candidate| candidate.candidate_id == request.candidate_id)
        .ok_or(RuntimeTopologyExecutionError::Binding)?;
    if candidate.kind != TopologyCandidateKindV2::Update || candidate.changes.len() != 1 {
        return Err(RuntimeTopologyExecutionError::Binding);
    }
    let change = &candidate.changes[0];
    if change
        .predecessor_digest
        .is_some_and(|digest| digest != current_route.hierarchy_digest)
        || change
            .candidate_digest
            .is_some_and(|digest| digest != successor.route.hierarchy_digest)
    {
        return Err(RuntimeTopologyExecutionError::Binding);
    }

    let handoff = request
        .governed
        .handoffs
        .iter()
        .find(|handoff| handoff.module_id == change.module_id)
        .ok_or(RuntimeTopologyExecutionError::Binding)?
        .clone();
    validate_writer_handoff_plan_v1(&handoff, Some(change.writer_handoff_digest))?;
    if request.migration.handoff_plan_digest() != handoff.plan_digest {
        return Err(RuntimeTopologyExecutionError::Binding);
    }
    if handoff.source_store_digest != current_route.hierarchy_digest
        || handoff.migration_digest != change.migration_digest
        || handoff.rollback_digest != change.rollback_digest
        || handoff.predecessor_writer_fence != current_generation.get()
        || handoff.successor_writer_fence != successor.route.generation.get()
    {
        return Err(RuntimeTopologyExecutionError::Binding);
    }

    let final_use_request_digest = topology_execution_request_digest_v1(
        request.governed.admission_digest,
        &request.candidate_id,
        &handoff,
        current_route.hierarchy_digest,
        successor.route.hierarchy_digest,
        current_generation,
        successor.route.generation,
    );
    let scope_digest = topology_execution_scope_digest_v1(current_route);
    let payload_digest = topology_execution_payload_digest_v1(
        request.governed.admission_digest,
        proposal.proposal_digest,
        &request.candidate_id,
        successor.route.hierarchy_digest,
        handoff.plan_digest,
    );
    let binding = FinalUseBinding {
        subject_id: request.accepted_subject_id.to_string(),
        destination_id: destination_id.to_string(),
        request_sha256: final_use_request_digest.into_array(),
        scope_sha256: scope_digest.into_array(),
        payload_sha256: payload_digest.into_array(),
    };

    Ok(ValidatedRuntimeTopologyTransitionV1 {
        binding,
        proposal_id: proposal.proposal_id.clone(),
        candidate_id: request.candidate_id.clone(),
        admission_digest: request.governed.admission_digest,
        handoff,
        predecessor_generation: current_generation,
        successor_generation: successor.route.generation,
        predecessor_hierarchy_digest: current_route.hierarchy_digest,
        successor_hierarchy_digest: successor.route.hierarchy_digest,
        final_use_request_digest,
    })
}

pub fn runtime_topology_final_use_binding_v1(
    current: &RuntimeTopologySnapshotV1,
    request: &RuntimeTopologyApplyRequestV1,
) -> Result<FinalUseBinding, RuntimeTopologyExecutionError> {
    Ok(
        validate_runtime_topology_transition_v1(&current.route, current.route.generation, request)?
            .binding,
    )
}

pub fn runtime_topology_recovery_final_use_binding_v1(
    current: &RuntimeTopologySnapshotV1,
    request: &RuntimeTopologyApplyRequestV1,
) -> Result<FinalUseBinding, RuntimeTopologyExecutionError> {
    Ok(
        validate_runtime_topology_recovery_v1(&current.route, current.route.generation, request)?
            .binding,
    )
}

fn topology_execution_request_digest_v1(
    admission_digest: Digest32,
    candidate_id: &StableId,
    handoff: &WriterHandoffPlanV1,
    predecessor_hierarchy_digest: Digest32,
    successor_hierarchy_digest: Digest32,
    predecessor_generation: Generation,
    successor_generation: Generation,
) -> Digest32 {
    let mut bytes = b"hepta.runtime.topology-execution-request.v1\0".to_vec();
    for digest in [
        admission_digest,
        handoff.plan_digest,
        handoff.source_store_digest,
        handoff.migration_digest,
        handoff.rollback_digest,
        handoff.acknowledgement_contract_digest,
        predecessor_hierarchy_digest,
        successor_hierarchy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, candidate_id);
    bytes.extend_from_slice(&predecessor_generation.get().to_be_bytes());
    bytes.extend_from_slice(&successor_generation.get().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn topology_execution_scope_digest_v1(route: &CnsRouteV1) -> Digest32 {
    let mut bytes = b"hepta.runtime.topology-execution-scope.v1\0".to_vec();
    push_id(&mut bytes, &route.cns);
    push_id(&mut bytes, &route.source.system);
    push_id(&mut bytes, &route.source.organ);
    bytes.extend_from_slice(&(route.output_port as u64).to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn topology_execution_payload_digest_v1(
    admission_digest: Digest32,
    proposal_digest: Digest32,
    candidate_id: &StableId,
    successor_hierarchy_digest: Digest32,
    handoff_plan_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.runtime.topology-execution-payload.v1\0".to_vec();
    for digest in [
        admission_digest,
        proposal_digest,
        successor_hierarchy_digest,
        handoff_plan_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, candidate_id);
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}
