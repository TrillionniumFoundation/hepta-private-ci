//! Proposal-only plasticity adapter for the `CellRoleV1::Plasticity` role.
//!
//! The adapter binds the existing governed parameter-plasticity proposal to a
//! typed cell-role step.  It deliberately exposes a *next snapshot candidate*
//! and never exposes an API that mutates, promotes, installs, or grants
//! authority to the selected snapshot.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_plasticity::Error as PlasticityError;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::ParameterCandidateV2;
use codex_hepta_plasticity::ParameterProposalV2;
use codex_hepta_plasticity::ProposalStatus;
use codex_hepta_plasticity::verify_parameter_proposal_v2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellAdapterContextV1;
use crate::CellRoleAdapterErrorV1;
use crate::CellRoleMetricKindV1;
use crate::CellRoleMetricProfileV1;
use crate::CellRoleMetricReceiptV1;
use crate::CellRoleStepV1;
use crate::step_receipt;

/// Stable schema identifier for the role-level proposal projection.
pub const PLASTICITY_UPDATE_PROPOSAL_SCHEMA_V1: &str =
    "hepta.cell-role.plasticity-update-proposal.v1";

/// The output mode is intentionally not an installation or promotion command.
/// A downstream artifact/evaluation owner must independently accept any
/// candidate before it can become selected.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlasticityUpdateModeV1 {
    NextSnapshotCandidate,
}

/// Inputs that come from the governed plasticity owner and the artifact
/// materializer. The existing `ParameterProposalV2` verifies digest bindings,
/// candidate deltas, and trust-region arithmetic; it does not authenticate
/// provenance or independent observation by itself. This wrapper binds the
/// resulting candidate to a parameter group and externally materialized
/// next-snapshot artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityUpdateInputV1 {
    pub proposal: ParameterProposalV2,
    pub candidate_id: StableId,
    /// Digest of the independently materialized candidate parameter snapshot.
    /// This is not a command to install it.
    pub candidate_snapshot_digest: Digest32,
    /// Explicit parameter-group mapping; no implicit broadcast is permitted.
    pub parameter_group_digest: Digest32,
    /// Must equal the proposal's verified norm-profile digest.
    pub trust_region_digest: Digest32,
}

/// Authority-free, typed projection of one admissible plasticity candidate.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityUpdateProposalV1 {
    pub schema: &'static str,
    pub mode: PlasticityUpdateModeV1,
    pub proposal_id: StableId,
    pub cell_id: StableId,
    /// Runtime generation at which the proposal was produced. It must equal
    /// `baseline_generation`; the adapter never advances runtime generation.
    pub context_generation: Generation,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    /// Runtime state remains at this predecessor while the candidate is only a
    /// next-snapshot proposal. The shared step receipt repeats this digest for
    /// both predecessor and successor.
    pub state_predecessor_digest: Digest32,
    pub selected_snapshot_digest: Digest32,
    pub candidate_snapshot_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub window_digest: Digest32,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub parameter_group_digest: Digest32,
    pub trust_region_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    /// Digest of the fully verified source `ParameterProposalV2`.
    pub source_proposal_digest: Digest32,
    /// Digest of the source candidate payload, including every delta/evidence.
    pub source_candidate_digest: Digest32,
    pub candidate_id: StableId,
    pub candidate_delta_digest: Digest32,
    pub candidate_delta_count: u32,
    pub candidate_count: u32,
    /// This remains `DENY_ALL`; promotion/installation is owned elsewhere.
    pub authority: AuthorityPosture,
    pub proposal_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityAdapterErrorV1 {
    Context(CellRoleAdapterErrorV1),
    Proposal(PlasticityError),
    EmptyDigest(&'static str),
    CandidateNotFound(String),
    CandidateNotUpdate(String),
    CandidateSnapshotEqualsSelected,
    TrustRegionMismatch,
    ParameterGroupMismatch,
    ContextGenerationMismatch,
    ContextStateMissing,
    SourceProposalMismatch,
    SourceCandidateMismatch,
    ProposalDigestMismatch,
    AuthorityGranted,
}

impl fmt::Display for PlasticityAdapterErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlasticityAdapterErrorV1 {}

impl From<CellRoleAdapterErrorV1> for PlasticityAdapterErrorV1 {
    fn from(value: CellRoleAdapterErrorV1) -> Self {
        Self::Context(value)
    }
}

impl From<PlasticityError> for PlasticityAdapterErrorV1 {
    fn from(value: PlasticityError) -> Self {
        Self::Proposal(value)
    }
}

/// Proposal-only adapter.  It never writes an artifact, mutates the selected
/// snapshot, changes the selected generation, promotes a candidate, or grants
/// authority.
pub struct PlasticityAdapterV1;

/// Role-neutral aliases used by circuit owners that compose learning roles.
/// They remain proposal-only and carry the exact same validation semantics.
pub type UpdateProposalV1 = PlasticityUpdateProposalV1;
pub type UpdateProposalInputV1 = PlasticityUpdateInputV1;
pub type UpdateProposalAdapterV1 = PlasticityAdapterV1;
pub type UpdateProposalErrorV1 = PlasticityAdapterErrorV1;

/// Evidence supplied by the artifact/evaluation owners when a proposal-only
/// update candidate is qualified for a later role-specific split.  This does
/// not publish the candidate or move the selected snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityCandidateQualificationInputV1<'a> {
    pub proposal: &'a PlasticityUpdateProposalV1,
    /// Receipt from the owner that materialized the candidate artifact in its
    /// CAS.  The bytes and publication remain outside this adapter.
    pub candidate_artifact_receipt_digest: Digest32,
    pub metric_profile: &'a CellRoleMetricProfileV1,
    pub metric_receipt: &'a CellRoleMetricReceiptV1,
}

/// Proposal-only candidate qualification receipt.  The four role-specific
/// observations make retention, forgetting, rollback and resource evidence
/// explicit instead of leaving them implicit in a single evaluation digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityCandidateQualificationReceiptV1 {
    pub schema: &'static str,
    pub candidate_id: StableId,
    pub cell_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub selected_snapshot_digest: Digest32,
    pub candidate_snapshot_digest: Digest32,
    pub candidate_artifact_receipt_digest: Digest32,
    pub trust_region_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub no_change_baseline_digest: Digest32,
    pub retention_receipt_digest: Digest32,
    pub forgetting_receipt_digest: Digest32,
    pub rollback_receipt_digest: Digest32,
    pub resource_receipt_digest: Digest32,
    pub future_window_digest: Digest32,
    pub metric_profile_digest: Digest32,
    pub metric_receipt_digest: Digest32,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub authority: AuthorityPosture,
    pub qualification_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlasticityCandidateQualificationErrorV1 {
    Projection(PlasticityAdapterErrorV1),
    EmptyDigest(&'static str),
    RoleMismatch,
    ProfileDigestMismatch,
    MetricReceiptDigestMismatch,
    GenerationMismatch,
    CellMismatch,
    EvaluatorMismatch,
    FutureWindowMismatch,
    MetricObservationMismatch(CellRoleMetricKindV1),
    AuthorityGranted,
    QualificationDigestMismatch,
}

impl fmt::Display for PlasticityCandidateQualificationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PlasticityCandidateQualificationErrorV1 {}

/// Qualify one already verified update projection against role-specific
/// metrics.  This is intentionally the last Plasticity-side step before an
/// independent split planner; it never appends a registry, installs bytes,
/// advances a generation, or grants authority.
pub fn qualify_plasticity_candidate_v1(
    input: PlasticityCandidateQualificationInputV1<'_>,
) -> Result<PlasticityCandidateQualificationReceiptV1, PlasticityCandidateQualificationErrorV1> {
    verify_update_projection(input.proposal)
        .map_err(PlasticityCandidateQualificationErrorV1::Projection)?;
    let proposal = input.proposal;
    if input.candidate_artifact_receipt_digest.is_zero() {
        return Err(PlasticityCandidateQualificationErrorV1::EmptyDigest(
            "candidate artifact receipt",
        ));
    }
    if input.metric_profile.role != CellRoleV1::Plasticity
        || input.metric_receipt.role != CellRoleV1::Plasticity
    {
        return Err(PlasticityCandidateQualificationErrorV1::RoleMismatch);
    }
    input
        .metric_profile
        .validate()
        .map_err(|_| PlasticityCandidateQualificationErrorV1::RoleMismatch)?;
    if input
        .metric_profile
        .content_digest()
        .map_err(|_| PlasticityCandidateQualificationErrorV1::ProfileDigestMismatch)?
        != input.metric_receipt.profile_digest
    {
        return Err(PlasticityCandidateQualificationErrorV1::ProfileDigestMismatch);
    }
    if input.metric_receipt.cell_id != proposal.cell_id
        || input.metric_receipt.generation != proposal.candidate_generation
    {
        return Err(PlasticityCandidateQualificationErrorV1::CellMismatch);
    }
    if input.metric_receipt.proposer_id != proposal.proposer_id
        || input.metric_receipt.evaluator_id != proposal.evaluator_id
        || proposal.proposer_id == proposal.evaluator_id
    {
        return Err(PlasticityCandidateQualificationErrorV1::EvaluatorMismatch);
    }
    if input.metric_receipt.evaluation_window_digest != input.metric_profile.future_window_digest {
        return Err(PlasticityCandidateQualificationErrorV1::FutureWindowMismatch);
    }
    let metric_receipt_digest = input
        .metric_receipt
        .content_digest(input.metric_profile)
        .map_err(|_| PlasticityCandidateQualificationErrorV1::MetricReceiptDigestMismatch)?;
    let required = [
        (CellRoleMetricKindV1::PlasticityRetention, "retention"),
        (CellRoleMetricKindV1::PlasticityForgetting, "forgetting"),
        (CellRoleMetricKindV1::PlasticityRollback, "rollback"),
        (CellRoleMetricKindV1::PlasticityResourceCost, "resource"),
    ];
    let mut observations = Vec::with_capacity(required.len());
    for (kind, _) in required {
        let metric = input
            .metric_receipt
            .metrics
            .iter()
            .find(|metric| metric.kind == kind)
            .ok_or(PlasticityCandidateQualificationErrorV1::MetricObservationMismatch(kind))?;
        observations.push((kind, metric.observation_digest));
    }
    if proposal.authority.grants_any() {
        return Err(PlasticityCandidateQualificationErrorV1::AuthorityGranted);
    }
    let mut result = PlasticityCandidateQualificationReceiptV1 {
        schema: "hepta.cell-role.plasticity-candidate-qualification.v1",
        candidate_id: proposal.candidate_id.clone(),
        cell_id: proposal.cell_id.clone(),
        baseline_generation: proposal.baseline_generation,
        candidate_generation: proposal.candidate_generation,
        selected_snapshot_digest: proposal.selected_snapshot_digest,
        candidate_snapshot_digest: proposal.candidate_snapshot_digest,
        candidate_artifact_receipt_digest: input.candidate_artifact_receipt_digest,
        trust_region_digest: proposal.trust_region_digest,
        rollback_predecessor_digest: proposal.rollback_predecessor_digest,
        no_change_baseline_digest: input.metric_profile.no_change_baseline_digest,
        retention_receipt_digest: observations[0].1,
        forgetting_receipt_digest: observations[1].1,
        rollback_receipt_digest: observations[2].1,
        resource_receipt_digest: observations[3].1,
        future_window_digest: input.metric_profile.future_window_digest,
        metric_profile_digest: input.metric_receipt.profile_digest,
        metric_receipt_digest,
        proposer_id: proposal.proposer_id.clone(),
        evaluator_id: proposal.evaluator_id.clone(),
        authority: AuthorityPosture::DENY_ALL,
        qualification_digest: Digest32::ZERO,
    };
    result.qualification_digest = digest_qualification(&result);
    Ok(result)
}

pub fn verify_plasticity_candidate_qualification_v1(
    receipt: &PlasticityCandidateQualificationReceiptV1,
) -> Result<(), PlasticityCandidateQualificationErrorV1> {
    if receipt.schema != "hepta.cell-role.plasticity-candidate-qualification.v1"
        || receipt.qualification_digest.is_zero()
        || receipt.qualification_digest != digest_qualification(receipt)
    {
        return Err(PlasticityCandidateQualificationErrorV1::QualificationDigestMismatch);
    }
    if receipt.candidate_snapshot_digest == receipt.selected_snapshot_digest
        || receipt.rollback_predecessor_digest != receipt.selected_snapshot_digest
        || receipt
            .baseline_generation
            .next()
            .map_err(|_| PlasticityCandidateQualificationErrorV1::GenerationMismatch)?
            != receipt.candidate_generation
    {
        return Err(PlasticityCandidateQualificationErrorV1::GenerationMismatch);
    }
    if receipt.authority.grants_any() {
        return Err(PlasticityCandidateQualificationErrorV1::AuthorityGranted);
    }
    Ok(())
}

fn digest_qualification(value: &PlasticityCandidateQualificationReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.cell-role.plasticity-candidate-qualification.v1".to_vec();
    bytes.extend_from_slice(value.schema.as_bytes());
    push_id(&mut bytes, &value.candidate_id);
    push_id(&mut bytes, &value.cell_id);
    bytes.extend_from_slice(&value.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&value.candidate_generation.get().to_be_bytes());
    for digest in [
        value.selected_snapshot_digest,
        value.candidate_snapshot_digest,
        value.candidate_artifact_receipt_digest,
        value.trust_region_digest,
        value.rollback_predecessor_digest,
        value.no_change_baseline_digest,
        value.retention_receipt_digest,
        value.forgetting_receipt_digest,
        value.rollback_receipt_digest,
        value.resource_receipt_digest,
        value.future_window_digest,
        value.metric_profile_digest,
        value.metric_receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &value.proposer_id);
    push_id(&mut bytes, &value.evaluator_id);
    bytes.push(value.authority.flags().wire_mask());
    Digest32::of_bytes(&bytes)
}

impl PlasticityAdapterV1 {
    pub const OWNER_MODULE: &'static str = "hepta-plasticity::parameter-proposal-v2";

    pub fn adapt(
        context: &CellAdapterContextV1,
        input: &PlasticityUpdateInputV1,
    ) -> Result<CellRoleStepV1<PlasticityUpdateProposalV1>, PlasticityAdapterErrorV1> {
        context.validate(CellRoleV1::Plasticity)?;
        verify_parameter_proposal_v2(&input.proposal)?;
        if context.generation != input.proposal.baseline_generation {
            return Err(PlasticityAdapterErrorV1::ContextGenerationMismatch);
        }
        if context.state_predecessor_digest.is_zero() {
            return Err(PlasticityAdapterErrorV1::ContextStateMissing);
        }
        if input.candidate_snapshot_digest.is_zero() {
            return Err(PlasticityAdapterErrorV1::EmptyDigest("candidate snapshot"));
        }
        if input.parameter_group_digest.is_zero() {
            return Err(PlasticityAdapterErrorV1::EmptyDigest("parameter group"));
        }
        if input.trust_region_digest.is_zero() {
            return Err(PlasticityAdapterErrorV1::EmptyDigest("trust region"));
        }
        if input.trust_region_digest != input.proposal.norm_profile.profile_digest {
            return Err(PlasticityAdapterErrorV1::TrustRegionMismatch);
        }
        // hepta-neuron's modulator-broadcast digest is the canonical parameter
        // group map digest. A second, unrelated group digest would permit an
        // implicit broadcast and cannot be admitted.
        if input.parameter_group_digest != input.proposal.modulator_broadcast_digest {
            return Err(PlasticityAdapterErrorV1::ParameterGroupMismatch);
        }
        if input.candidate_snapshot_digest == input.proposal.selected_artifact_digest {
            return Err(PlasticityAdapterErrorV1::CandidateSnapshotEqualsSelected);
        }
        if input.proposal.authority.grants_any() {
            return Err(PlasticityAdapterErrorV1::AuthorityGranted);
        }
        if input.proposal.rollback_predecessor_digest != input.proposal.selected_artifact_digest {
            return Err(PlasticityAdapterErrorV1::Proposal(
                PlasticityError::RollbackPredecessorMismatch,
            ));
        }

        let candidate = input
            .proposal
            .candidates
            .iter()
            .find(|candidate| candidate.candidate_id == input.candidate_id)
            .ok_or_else(|| {
                PlasticityAdapterErrorV1::CandidateNotFound(input.candidate_id.to_string())
            })?;
        if candidate.kind != ParameterCandidateKindV2::Update {
            return Err(PlasticityAdapterErrorV1::CandidateNotUpdate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.parameter_deltas.is_empty() {
            return Err(PlasticityAdapterErrorV1::CandidateNotUpdate(
                candidate.candidate_id.to_string(),
            ));
        }
        let candidate_delta_digest = digest_candidate(candidate);
        let mut result = PlasticityUpdateProposalV1 {
            schema: PLASTICITY_UPDATE_PROPOSAL_SCHEMA_V1,
            mode: PlasticityUpdateModeV1::NextSnapshotCandidate,
            proposal_id: input.proposal.proposal_id.clone(),
            cell_id: context.cell_id.clone(),
            context_generation: context.generation,
            baseline_generation: input.proposal.baseline_generation,
            candidate_generation: input.proposal.candidate_generation,
            state_predecessor_digest: context.state_predecessor_digest,
            selected_snapshot_digest: input.proposal.selected_artifact_digest,
            candidate_snapshot_digest: input.candidate_snapshot_digest,
            rollback_predecessor_digest: input.proposal.rollback_predecessor_digest,
            window_digest: input.proposal.window.window_digest,
            dataset_digest: input.proposal.dataset_digest,
            update_rule_digest: input.proposal.update_rule_digest,
            eligibility_digest: input.proposal.eligibility_digest,
            modulator_digest: input.proposal.modulator_digest,
            modulator_broadcast_digest: input.proposal.modulator_broadcast_digest,
            parameter_group_digest: input.parameter_group_digest,
            trust_region_digest: input.trust_region_digest,
            evaluation_digest: input.proposal.evaluation_digest,
            proposer_id: input.proposal.proposer_id.clone(),
            evaluator_id: input.proposal.evaluator_id.clone(),
            source_proposal_digest: input.proposal.proposal_digest,
            source_candidate_digest: candidate_delta_digest,
            candidate_id: candidate.candidate_id.clone(),
            candidate_delta_digest,
            candidate_delta_count: u32::try_from(candidate.parameter_deltas.len())
                .unwrap_or(u32::MAX),
            candidate_count: u32::try_from(input.proposal.candidates.len()).unwrap_or(u32::MAX),
            authority: AuthorityPosture::DENY_ALL,
            proposal_digest: Digest32::ZERO,
        };
        result.proposal_digest = digest_update_projection(&result);
        verify_update_projection_against_source(&result, &input.proposal)?;
        // This is a proposal step: no runtime state has moved to the candidate
        // snapshot. Keep predecessor and successor identical in the receipt.
        let receipt = step_receipt(
            context,
            CellRoleV1::Plasticity,
            context.state_predecessor_digest,
            result.proposal_digest,
            0,
            0,
            crate::CellStepStatusV1::Accepted,
        )?;
        Ok(CellRoleStepV1 { result, receipt })
    }
}

fn digest_candidate(candidate: &ParameterCandidateV2) -> Digest32 {
    let mut bytes = b"hepta.cell-role.plasticity-candidate.v1\0".to_vec();
    bytes.extend_from_slice(candidate.candidate_id.as_str().as_bytes());
    bytes.push(match candidate.kind {
        ParameterCandidateKindV2::NoChange => 0,
        ParameterCandidateKindV2::Update => 1,
    });
    for delta in &candidate.parameter_deltas {
        bytes.extend_from_slice(delta.layer_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(delta.parameter_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(&delta.delta.raw().to_be_bytes());
        bytes.extend_from_slice(&delta.lower_bound.raw().to_be_bytes());
        bytes.extend_from_slice(&delta.upper_bound.raw().to_be_bytes());
        bytes.extend_from_slice(delta.evidence_digest.as_array());
    }
    bytes.extend_from_slice(
        &candidate
            .norm_metrics
            .global_delta_squared_l2_raw_q64
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &candidate
            .norm_metrics
            .global_baseline_squared_l2_raw_q64
            .to_be_bytes(),
    );
    for layer in &candidate.norm_metrics.layers {
        push_id(&mut bytes, &layer.layer_id);
        bytes.extend_from_slice(&layer.delta_squared_l2_raw_q64.to_be_bytes());
        bytes.extend_from_slice(&layer.baseline_squared_l2_raw_q64.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn digest_update_projection(proposal: &PlasticityUpdateProposalV1) -> Digest32 {
    let mut bytes = b"hepta.cell-role.plasticity-update-proposal.v1\0".to_vec();
    bytes.extend_from_slice(proposal.schema.as_bytes());
    bytes.push(match proposal.mode {
        PlasticityUpdateModeV1::NextSnapshotCandidate => 0,
    });
    push_id(&mut bytes, &proposal.proposal_id);
    push_id(&mut bytes, &proposal.cell_id);
    bytes.extend_from_slice(&proposal.context_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.baseline_generation.get().to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_generation.get().to_be_bytes());
    bytes.extend_from_slice(proposal.state_predecessor_digest.as_array());
    for digest in [
        proposal.selected_snapshot_digest,
        proposal.candidate_snapshot_digest,
        proposal.rollback_predecessor_digest,
        proposal.window_digest,
        proposal.dataset_digest,
        proposal.update_rule_digest,
        proposal.eligibility_digest,
        proposal.modulator_digest,
        proposal.modulator_broadcast_digest,
        proposal.parameter_group_digest,
        proposal.trust_region_digest,
        proposal.evaluation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &proposal.proposer_id);
    push_id(&mut bytes, &proposal.evaluator_id);
    bytes.extend_from_slice(proposal.source_proposal_digest.as_array());
    bytes.extend_from_slice(proposal.source_candidate_digest.as_array());
    push_id(&mut bytes, &proposal.candidate_id);
    bytes.extend_from_slice(proposal.candidate_delta_digest.as_array());
    bytes.extend_from_slice(&proposal.candidate_delta_count.to_be_bytes());
    bytes.extend_from_slice(&proposal.candidate_count.to_be_bytes());
    bytes.push(proposal.authority.flags().wire_mask());
    Digest32::of_bytes(&bytes)
}

/// Verify the role-level projection's own canonical digest and immutable
/// invariants without touching any selected snapshot.
pub fn verify_update_projection(
    proposal: &PlasticityUpdateProposalV1,
) -> Result<(), PlasticityAdapterErrorV1> {
    if proposal.schema != PLASTICITY_UPDATE_PROPOSAL_SCHEMA_V1 {
        return Err(PlasticityAdapterErrorV1::ProposalDigestMismatch);
    }
    if proposal.mode != PlasticityUpdateModeV1::NextSnapshotCandidate {
        return Err(PlasticityAdapterErrorV1::ProposalDigestMismatch);
    }
    if proposal.proposal_id.as_str().is_empty() || proposal.cell_id.as_str().is_empty() {
        return Err(PlasticityAdapterErrorV1::ProposalDigestMismatch);
    }
    if proposal.context_generation != proposal.baseline_generation {
        return Err(PlasticityAdapterErrorV1::ContextGenerationMismatch);
    }
    if proposal.candidate_generation
        != proposal.baseline_generation.next().map_err(|_| {
            PlasticityAdapterErrorV1::Proposal(PlasticityError::GenerationNotExactSuccessor)
        })?
    {
        return Err(PlasticityAdapterErrorV1::Proposal(
            PlasticityError::GenerationNotExactSuccessor,
        ));
    }
    if proposal.state_predecessor_digest.is_zero() {
        return Err(PlasticityAdapterErrorV1::ContextStateMissing);
    }
    for (name, digest) in [
        ("selected snapshot", proposal.selected_snapshot_digest),
        ("candidate snapshot", proposal.candidate_snapshot_digest),
        ("rollback predecessor", proposal.rollback_predecessor_digest),
        ("window", proposal.window_digest),
        ("dataset", proposal.dataset_digest),
        ("update rule", proposal.update_rule_digest),
        ("eligibility", proposal.eligibility_digest),
        ("modulator", proposal.modulator_digest),
        ("modulator broadcast", proposal.modulator_broadcast_digest),
        ("parameter group", proposal.parameter_group_digest),
        ("trust region", proposal.trust_region_digest),
        ("evaluation", proposal.evaluation_digest),
        ("source proposal", proposal.source_proposal_digest),
        ("source candidate", proposal.source_candidate_digest),
        ("candidate delta", proposal.candidate_delta_digest),
    ] {
        if digest.is_zero() {
            return Err(PlasticityAdapterErrorV1::EmptyDigest(name));
        }
    }
    if proposal.selected_snapshot_digest == proposal.candidate_snapshot_digest {
        return Err(PlasticityAdapterErrorV1::CandidateSnapshotEqualsSelected);
    }
    if proposal.rollback_predecessor_digest != proposal.selected_snapshot_digest {
        return Err(PlasticityAdapterErrorV1::Proposal(
            PlasticityError::RollbackPredecessorMismatch,
        ));
    }
    if proposal.parameter_group_digest != proposal.modulator_broadcast_digest {
        return Err(PlasticityAdapterErrorV1::ParameterGroupMismatch);
    }
    if proposal.candidate_delta_count == 0 || proposal.candidate_count == 0 {
        return Err(PlasticityAdapterErrorV1::ProposalDigestMismatch);
    }
    if proposal.authority.grants_any() {
        return Err(PlasticityAdapterErrorV1::AuthorityGranted);
    }
    if proposal.proposal_digest.is_zero()
        || proposal.proposal_digest != digest_update_projection(proposal)
    {
        return Err(PlasticityAdapterErrorV1::ProposalDigestMismatch);
    }
    Ok(())
}

/// Replay the role projection against the immutable source proposal. This
/// rechecks eligibility/modulator/group/trust-region bindings and every
/// candidate delta rather than trusting copied digests. Provenance and
/// independent-observer status remain owned by the learning/evaluation
/// evidence owners and are deliberately not manufactured here.
pub fn verify_update_projection_against_source(
    projection: &PlasticityUpdateProposalV1,
    source: &ParameterProposalV2,
) -> Result<(), PlasticityAdapterErrorV1> {
    verify_update_projection(projection)?;
    verify_parameter_proposal_v2(source)?;
    if source.status != ProposalStatus::RequiresIndependentAcceptance {
        return Err(PlasticityAdapterErrorV1::SourceProposalMismatch);
    }
    if projection.source_proposal_digest != source.proposal_digest
        || projection.proposal_id != source.proposal_id
        || projection.proposer_id != source.proposer_id
        || projection.evaluator_id != source.evaluator_id
        || projection.selected_snapshot_digest != source.selected_artifact_digest
        || projection.baseline_generation != source.baseline_generation
        || projection.candidate_generation != source.candidate_generation
        || projection.window_digest != source.window.window_digest
        || projection.dataset_digest != source.dataset_digest
        || projection.update_rule_digest != source.update_rule_digest
        || projection.modulator_digest != source.modulator_digest
        || projection.modulator_broadcast_digest != source.modulator_broadcast_digest
        || projection.parameter_group_digest != source.modulator_broadcast_digest
        || projection.eligibility_digest != source.eligibility_digest
        || projection.evaluation_digest != source.evaluation_digest
        || projection.rollback_predecessor_digest != source.rollback_predecessor_digest
        || projection.trust_region_digest != source.norm_profile.profile_digest
    {
        return Err(PlasticityAdapterErrorV1::SourceProposalMismatch);
    }
    let candidate = source
        .candidates
        .iter()
        .find(|candidate| candidate.candidate_id == projection.candidate_id)
        .ok_or_else(|| {
            PlasticityAdapterErrorV1::CandidateNotFound(projection.candidate_id.to_string())
        })?;
    if candidate.kind != ParameterCandidateKindV2::Update || candidate.parameter_deltas.is_empty() {
        return Err(PlasticityAdapterErrorV1::CandidateNotUpdate(
            candidate.candidate_id.to_string(),
        ));
    }
    if projection.source_candidate_digest != digest_candidate(candidate)
        || projection.candidate_delta_digest != digest_candidate(candidate)
        || projection.candidate_delta_count
            != u32::try_from(candidate.parameter_deltas.len()).unwrap_or(u32::MAX)
        || projection.candidate_count != u32::try_from(source.candidates.len()).unwrap_or(u32::MAX)
    {
        return Err(PlasticityAdapterErrorV1::SourceCandidateMismatch);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CellRoleMetricV1;
    use codex_hepta_plasticity::LayerNormDenominatorV2;
    use codex_hepta_plasticity::ParameterCandidateRequestV2;
    use codex_hepta_plasticity::ParameterDeltaV2;
    use codex_hepta_plasticity::ParameterProposalRequestV2;
    use codex_hepta_plasticity::ProposalWindowV2;
    use codex_hepta_plasticity::propose_v2;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::FixedQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }
    fn context() -> CellAdapterContextV1 {
        CellAdapterContextV1 {
            cell_id: id("cell.plasticity.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest("scope"),
            role: CellRoleV1::Plasticity,
            capability_digest: digest("capability"),
            input_frontier_digest: digest("frontier"),
            state_predecessor_digest: digest("selected"),
            resource_receipt_digest: digest("resource"),
            evidence_digest: digest("evidence"),
        }
    }
    fn proposal() -> ParameterProposalV2 {
        propose_v2(ParameterProposalRequestV2 {
            proposal_id: id("plasticity.proposal.1"),
            proposer_id: id("plasticity.proposer"),
            evaluator_id: id("plasticity.evaluator"),
            selected_artifact_digest: digest("selected"),
            window: ProposalWindowV2 {
                window_id: id("window.1"),
                window_digest: digest("window"),
            },
            baseline_generation: Generation::new(1).expect("generation"),
            candidate_generation: Generation::new(2).expect("generation"),
            dataset_digest: digest("dataset"),
            update_rule_digest: digest("rule"),
            modulator_digest: digest("modulator"),
            modulator_broadcast_digest: digest("modulator-broadcast"),
            eligibility_digest: digest("eligibility"),
            evaluation_digest: digest("evaluation"),
            rollback_predecessor_digest: digest("selected"),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer.1"),
                baseline_squared_l2_raw_q64: 1_u128 << 64,
            }],
            candidates: vec![
                ParameterCandidateRequestV2 {
                    candidate_id: id("candidate.no-change"),
                    kind: ParameterCandidateKindV2::NoChange,
                    parameter_deltas: vec![],
                },
                ParameterCandidateRequestV2 {
                    candidate_id: id("candidate.update"),
                    kind: ParameterCandidateKindV2::Update,
                    parameter_deltas: vec![ParameterDeltaV2 {
                        layer_id: id("layer.1"),
                        parameter_id: id("parameter.1"),
                        delta: FixedQ32::from_raw(1),
                        lower_bound: FixedQ32::from_raw(-1 << 20),
                        upper_bound: FixedQ32::from_raw(1 << 20),
                        evidence_digest: digest("delta-evidence"),
                    }],
                },
            ],
        })
        .expect("proposal")
    }

    fn input() -> PlasticityUpdateInputV1 {
        let proposal = proposal();
        PlasticityUpdateInputV1 {
            trust_region_digest: proposal.norm_profile.profile_digest,
            parameter_group_digest: proposal.modulator_broadcast_digest,
            proposal,
            candidate_id: id("candidate.update"),
            candidate_snapshot_digest: digest("candidate-snapshot"),
        }
    }

    fn qualification_profile() -> CellRoleMetricProfileV1 {
        CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::Plasticity,
            digest("plasticity-objective"),
            digest("no-change-baseline"),
            digest("plasticity-policy"),
            digest("future-window"),
        )
    }

    fn qualification_metrics(
        proposal: &PlasticityUpdateProposalV1,
        profile: &CellRoleMetricProfileV1,
    ) -> CellRoleMetricReceiptV1 {
        CellRoleMetricReceiptV1 {
            cell_id: proposal.cell_id.clone(),
            generation: proposal.candidate_generation,
            role: CellRoleV1::Plasticity,
            proposer_id: proposal.proposer_id.clone(),
            evaluator_id: proposal.evaluator_id.clone(),
            profile_digest: profile.content_digest().expect("profile digest"),
            baseline_digest: profile.no_change_baseline_digest,
            evaluation_window_digest: profile.future_window_digest,
            metrics: profile
                .required_metrics
                .iter()
                .map(|kind| CellRoleMetricV1 {
                    kind: *kind,
                    unit: kind.unit(),
                    value: 1,
                    sample_count: 1,
                    observation_digest: digest(&kind.tag().to_string()),
                })
                .collect(),
            evidence_digest: digest("plasticity-metric-evidence"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn adapts_update_as_next_snapshot_only_and_denies_authority() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        assert_eq!(
            adapted.result.mode,
            PlasticityUpdateModeV1::NextSnapshotCandidate
        );
        assert_ne!(
            adapted.result.selected_snapshot_digest,
            adapted.result.candidate_snapshot_digest
        );
        assert_eq!(
            adapted.result.rollback_predecessor_digest,
            adapted.result.selected_snapshot_digest
        );
        assert_eq!(adapted.result.authority, AuthorityPosture::DENY_ALL);
        assert_eq!(adapted.receipt.authority, AuthorityPosture::DENY_ALL);
        assert_eq!(
            adapted.receipt.state_predecessor_digest,
            adapted.receipt.state_successor_digest
        );
        assert_eq!(adapted.receipt.state_successor_digest, digest("selected"));
        assert_eq!(adapted.result.candidate_delta_count, 1);
        assert!(!adapted.result.proposal_digest.is_zero());
    }

    #[test]
    fn canonical_digest_rejects_eligibility_tamper() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let mut projection = adapted.result;
        projection.eligibility_digest = digest("tampered-eligibility");
        assert_eq!(
            verify_update_projection(&projection),
            Err(PlasticityAdapterErrorV1::ProposalDigestMismatch)
        );
    }

    #[test]
    fn canonical_digest_rejects_parameter_group_tamper() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let mut projection = adapted.result;
        projection.parameter_group_digest = digest("tampered-group");
        assert!(matches!(
            verify_update_projection(&projection),
            Err(PlasticityAdapterErrorV1::ParameterGroupMismatch)
                | Err(PlasticityAdapterErrorV1::ProposalDigestMismatch)
        ));
    }

    #[test]
    fn canonical_digest_rejects_evaluation_tamper() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let mut projection = adapted.result;
        projection.evaluation_digest = digest("tampered-evaluation");
        assert_eq!(
            verify_update_projection(&projection),
            Err(PlasticityAdapterErrorV1::ProposalDigestMismatch)
        );
    }

    #[test]
    fn canonical_digest_rejects_candidate_delta_tamper() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let mut projection = adapted.result;
        projection.candidate_delta_digest = digest("tampered-delta");
        assert_eq!(
            verify_update_projection(&projection),
            Err(PlasticityAdapterErrorV1::ProposalDigestMismatch)
        );
    }

    #[test]
    fn canonical_digest_rejects_generation_tamper() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let mut projection = adapted.result;
        projection.candidate_generation = Generation::new(3).expect("generation");
        assert!(matches!(
            verify_update_projection(&projection),
            Err(PlasticityAdapterErrorV1::ContextGenerationMismatch)
                | Err(PlasticityAdapterErrorV1::Proposal(_))
                | Err(PlasticityAdapterErrorV1::ProposalDigestMismatch)
        ));
    }

    #[test]
    fn context_generation_must_match_selected_baseline() {
        let mut context = context();
        context.generation = Generation::new(2).expect("generation");
        assert_eq!(
            PlasticityAdapterV1::adapt(&context, &input()),
            Err(PlasticityAdapterErrorV1::ContextGenerationMismatch)
        );
    }

    #[test]
    fn source_replay_rejects_changed_source_proposal() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let mut source = input().proposal;
        source.evaluation_digest = digest("changed-source-evaluation");
        assert!(matches!(
            verify_update_projection_against_source(&adapted.result, &source),
            Err(PlasticityAdapterErrorV1::Proposal(_))
                | Err(PlasticityAdapterErrorV1::SourceProposalMismatch)
        ));
    }

    #[test]
    fn rejects_selected_snapshot_reuse() {
        let mut input = input();
        input.candidate_snapshot_digest = input.proposal.selected_artifact_digest;
        assert_eq!(
            PlasticityAdapterV1::adapt(&context(), &input),
            Err(PlasticityAdapterErrorV1::CandidateSnapshotEqualsSelected)
        );
    }

    #[test]
    fn rejects_no_change_candidate_for_update_role() {
        let mut input = input();
        input.candidate_id = id("candidate.no-change");
        assert!(matches!(
            PlasticityAdapterV1::adapt(&context(), &input),
            Err(PlasticityAdapterErrorV1::CandidateNotUpdate(_))
        ));
    }

    #[test]
    fn rejects_trust_region_mismatch() {
        let mut input = input();
        input.trust_region_digest = digest("tampered-trust-region");
        assert_eq!(
            PlasticityAdapterV1::adapt(&context(), &input),
            Err(PlasticityAdapterErrorV1::TrustRegionMismatch)
        );
    }

    #[test]
    fn qualifies_candidate_with_role_metrics_without_installing_it() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let profile = qualification_profile();
        let metrics = qualification_metrics(&adapted.result, &profile);
        let qualified = qualify_plasticity_candidate_v1(PlasticityCandidateQualificationInputV1 {
            proposal: &adapted.result,
            candidate_artifact_receipt_digest: digest("candidate-artifact-receipt"),
            metric_profile: &profile,
            metric_receipt: &metrics,
        })
        .expect("qualification");
        verify_plasticity_candidate_qualification_v1(&qualified).expect("replay");
        assert_eq!(qualified.authority, AuthorityPosture::DENY_ALL);
        assert_ne!(
            qualified.selected_snapshot_digest,
            qualified.candidate_snapshot_digest
        );
    }

    #[test]
    fn candidate_qualification_rejects_metric_observation_tamper() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let profile = qualification_profile();
        let mut metrics = qualification_metrics(&adapted.result, &profile);
        metrics.evaluation_window_digest = digest("tampered-future-window");
        let result = qualify_plasticity_candidate_v1(PlasticityCandidateQualificationInputV1 {
            proposal: &adapted.result,
            candidate_artifact_receipt_digest: digest("candidate-artifact-receipt"),
            metric_profile: &profile,
            metric_receipt: &metrics,
        });
        assert!(matches!(
            result,
            Err(PlasticityCandidateQualificationErrorV1::FutureWindowMismatch)
        ));
    }

    #[test]
    fn candidate_qualification_rejects_zero_artifact_receipt() {
        let adapted = PlasticityAdapterV1::adapt(&context(), &input()).expect("adapt");
        let profile = qualification_profile();
        let metrics = qualification_metrics(&adapted.result, &profile);
        let result = qualify_plasticity_candidate_v1(PlasticityCandidateQualificationInputV1 {
            proposal: &adapted.result,
            candidate_artifact_receipt_digest: Digest32::ZERO,
            metric_profile: &profile,
            metric_receipt: &metrics,
        });
        assert!(matches!(
            result,
            Err(PlasticityCandidateQualificationErrorV1::EmptyDigest(
                "candidate artifact receipt"
            ))
        ));
    }

    #[test]
    fn authority_posture_cannot_be_constructed_with_grants() {
        // AuthorityPosture is sealed in hepta-types. A non-zero wire mask is
        // rejected before a proposal can reach this adapter.
        assert!(AuthorityPosture::try_from_wire_bytes(&[1]).is_err());
        let proposal = proposal();
        assert_eq!(proposal.authority, AuthorityPosture::DENY_ALL);
        assert!(!proposal.authority.grants_any());
    }
}
