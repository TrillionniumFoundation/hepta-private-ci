//! Public, authority-free plasticity proposal data types.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub(crate) const MAX_PARAMETER_DELTAS: usize = 4_096;
pub(crate) const MAX_TOPOLOGY_DELTAS: usize = 256;
pub(crate) const MAX_PROPOSALS: usize = 4_096;
pub(crate) const MAX_CANDIDATES: usize = 32;
pub(crate) const MAX_NORM_LAYERS: usize = 256;
pub(crate) const PER_LAYER_MAX_RELATIVE_PPM: u32 = 5_000;
pub(crate) const GLOBAL_MAX_RELATIVE_PPM: u32 = 2_500;
pub(crate) const PPM_DENOMINATOR: u128 = 1_000_000;
pub(crate) const LEGACY_V1: u16 = 1;
pub(crate) const PARAMETER_V2: u16 = 2;

/// A parameter delta from the legacy internal V1 record.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ParameterDelta {
    pub parameter_id: StableId,
    pub delta: FixedQ32,
    pub lower_bound: FixedQ32,
    pub upper_bound: FixedQ32,
    pub evidence_digest: Digest32,
}

/// A topology operation from the legacy internal V1 record.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum TopologyOperation {
    Add,
    Remove,
    Replace,
}

/// A topology delta from the legacy internal V1 record.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct TopologyDelta {
    pub module_id: StableId,
    pub operation: TopologyOperation,
    pub predecessor_digest: Digest32,
    pub candidate_digest: Digest32,
    pub evidence_digest: Digest32,
}

/// Historical internal V1 write request. New writes are intentionally denied.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProposalRequest {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub evaluation_digest: Digest32,
    pub evaluation_eligible: bool,
    pub maximum_absolute_delta: FixedQ32,
    pub parameter_deltas: Vec<ParameterDelta>,
    pub topology_deltas: Vec<TopologyDelta>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProposalStatus {
    RequiresIndependentAcceptance,
}

/// Historical internal V1 record. It is retained for explicit read dispatch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlasticityProposal {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub evaluation_digest: Digest32,
    pub parameter_deltas: Vec<ParameterDelta>,
    pub topology_deltas: Vec<TopologyDelta>,
    pub proposal_digest: Digest32,
    pub status: ProposalStatus,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProposalVersion {
    LegacyV1,
    ParameterV2,
}

impl ProposalVersion {
    pub const fn as_u16(self) -> u16 {
        match self {
            Self::LegacyV1 => LEGACY_V1,
            Self::ParameterV2 => PARAMETER_V2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProposalWindowV2 {
    pub window_id: StableId,
    pub window_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct LayerNormDenominatorV2 {
    pub layer_id: StableId,
    pub baseline_squared_l2_raw_q64: u128,
}

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct ParameterDeltaV2 {
    pub layer_id: StableId,
    pub parameter_id: StableId,
    pub delta: FixedQ32,
    pub lower_bound: FixedQ32,
    pub upper_bound: FixedQ32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ParameterCandidateKindV2 {
    NoChange,
    Update,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterCandidateRequestV2 {
    pub candidate_id: StableId,
    pub kind: ParameterCandidateKindV2,
    pub parameter_deltas: Vec<ParameterDeltaV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterProposalRequestV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    /// A caller-supplied role label; inequality does not authenticate independence.
    pub evaluator_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub norm_layers: Vec<LayerNormDenominatorV2>,
    /// The bounded set supplied by the caller, not a generator-completeness proof.
    pub candidates: Vec<ParameterCandidateRequestV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterNormProfileV2 {
    pub profile_digest: Digest32,
    pub per_layer_max_relative_ppm: u32,
    pub global_max_relative_ppm: u32,
    pub layers: Vec<LayerNormDenominatorV2>,
    pub global_baseline_squared_l2_raw_q64: u128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LayerRelativeNormV2 {
    pub layer_id: StableId,
    pub delta_squared_l2_raw_q64: u128,
    pub baseline_squared_l2_raw_q64: u128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateNormMetricsV2 {
    pub layers: Vec<LayerRelativeNormV2>,
    pub global_delta_squared_l2_raw_q64: u128,
    pub global_baseline_squared_l2_raw_q64: u128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterCandidateV2 {
    pub candidate_id: StableId,
    pub kind: ParameterCandidateKindV2,
    pub parameter_deltas: Vec<ParameterDeltaV2>,
    pub norm_metrics: CandidateNormMetricsV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterProposalV2 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub modulator_digest: Digest32,
    pub modulator_broadcast_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub norm_profile: ParameterNormProfileV2,
    pub candidates: Vec<ParameterCandidateV2>,
    pub proposal_digest: Digest32,
    pub status: ProposalStatus,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProposalRecord {
    LegacyV1(Box<PlasticityProposal>),
    ParameterV2(Box<ParameterProposalV2>),
}

impl ProposalRecord {
    pub const fn version(&self) -> ProposalVersion {
        match self {
            Self::LegacyV1(_) => ProposalVersion::LegacyV1,
            Self::ParameterV2(_) => ProposalVersion::ParameterV2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProposalDigestVerification {
    UnavailableLegacyMissingMaximumAbsoluteDelta,
    VerifiedV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProposalReadResult {
    pub record: ProposalRecord,
    pub digest_verification: ProposalDigestVerification,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProposalWriteRequest {
    LegacyV1(Box<ProposalRequest>),
    ParameterV2(Box<ParameterProposalRequestV2>),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AppendDisposition {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    UnsupportedVersion(u16),
    VersionPayloadMismatch,
    LegacyWriteDisabled,
    SelfEvaluation,
    EvaluationIneligible,
    GenerationNotAdvanced,
    GenerationNotExactSuccessor,
    EmptyDigest(&'static str),
    InvalidMaximumDelta,
    ParameterLimitExceeded,
    TopologyLimitExceeded,
    CandidateCountOutOfRange,
    NormLayerCountOutOfRange,
    DuplicateCandidate(String),
    DuplicateParameter(String),
    DuplicateTopology(String),
    DuplicateNormLayer(String),
    MissingNormLayer(String),
    MissingNoChangeCandidate,
    MultipleNoChangeCandidates,
    NoChangeHasDeltas(String),
    UpdateHasNoDeltas(String),
    ZeroParameterDelta(String),
    InvertedBounds(String),
    DeltaOutsideBounds(String),
    DeltaLimitExceeded(String),
    TopologyDigestUnchanged(String),
    ZeroNormDenominator(String),
    NormProfileMismatch,
    NormMetricsMismatch(String),
    PerLayerTrustRegionExceeded(String),
    GlobalTrustRegionExceeded(String),
    RollbackPredecessorMismatch,
    ProposalDigestMismatch,
    AuthorityGranted,
    NonCanonicalOrder(&'static str),
    Arithmetic,
    RegistryCapacityExceeded,
    ProposalConflict(String),
    RegistrySlotConflict(String),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}
