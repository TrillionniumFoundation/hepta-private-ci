use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibratedIntuitionReceiptV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RiskPolicyV1 {
    /// Low and elevated risk may use the calibrated fast path. High risk must
    /// use the existing slow path.
    HighAlwaysSlowPath,
    /// Reserved for a stricter profile. V1 execution rejects this until the
    /// calibrated kernel exposes an elevated-risk slow-path reason.
    LowOnlyFastPath,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScorerContractV1 {
    pub contract_digest: Digest32,
    pub policy_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub model_artifact_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub utility_semantics_digest: Digest32,
    pub confidence_semantics_digest: Digest32,
    pub ood_semantics_digest: Digest32,
    pub calibration_artifact_digest: Digest32,
    pub ood_artifact_digest: Digest32,
    pub ood_detector_digest: Digest32,
    pub generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScoreEvidenceV1 {
    pub candidate_id: StableId,
    pub feature_digest: Digest32,
    pub utility: FixedQ32,
    pub calibrated_confidence: ProbabilityQ32,
    pub ood_score: ProbabilityQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPolicyProfileV1 {
    pub profile_digest: Digest32,
    pub policy_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub minimum_confidence: ProbabilityQ32,
    pub maximum_ece_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    pub risk_policy: RiskPolicyV1,
    pub require_zero_omissions: bool,
}

/// Secret qualification key provisioned by a trusted host boundary.
///
/// The secret is deliberately not exposed through accessors or `Debug`.
pub struct QualificationMacKeyV1 {
    pub(crate) key_id: StableId,
    pub(crate) key_epoch: u64,
    pub(crate) secret: [u8; 32],
    pub(crate) revoked: bool,
}

impl QualificationMacKeyV1 {
    #[must_use]
    pub fn from_trusted_bytes(
        key_id: StableId,
        key_epoch: u64,
        secret: [u8; 32],
        revoked: bool,
    ) -> Self {
        Self {
            key_id,
            key_epoch,
            secret,
            revoked,
        }
    }

    #[must_use]
    pub fn key_id(&self) -> &StableId {
        &self.key_id
    }

    #[must_use]
    pub const fn key_epoch(&self) -> u64 {
        self.key_epoch
    }

    #[must_use]
    pub const fn revoked(&self) -> bool {
        self.revoked
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationMacV1 {
    pub key_id: StableId,
    pub key_epoch: u64,
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub tag: Digest32,
}

pub struct QualifiedArtifactsV1<'a> {
    pub profile: &'a QualificationMacV1,
    pub calibration: &'a QualificationMacV1,
    pub ood: &'a QualificationMacV1,
    pub completeness: &'a QualificationMacV1,
    pub scorer_output: &'a QualificationMacV1,
}

pub struct QualificationTrustV1<'a> {
    pub artifact_key: &'a QualificationMacKeyV1,
    pub scorer_key: &'a QualificationMacKeyV1,
    pub subject_id: &'a StableId,
    pub expected_generation: u64,
}

pub struct QualifiedDecisionRequestV1<'a> {
    pub request: CalibratedDecisionRequestV1,
    pub profile: CanonicalPolicyProfileV1,
    pub scorer_contract: LearnedScorerContractV1,
    pub score_evidence: Vec<LearnedScoreEvidenceV1>,
    pub artifacts: QualifiedArtifactsV1<'a>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedIntuitionReceiptV1 {
    pub decision: CalibratedIntuitionReceiptV1,
    pub policy_profile_digest: Digest32,
    pub scorer_contract_digest: Digest32,
    pub scorer_output_digest: Digest32,
    pub profile_authentication_digest: Digest32,
    pub calibration_authentication_digest: Digest32,
    pub ood_authentication_digest: Digest32,
    pub completeness_authentication_digest: Digest32,
    pub scorer_authentication_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedError {
    Calibrated(CalibratedError),
    EmptyDigest(&'static str),
    ProfileDigestMismatch,
    ProfileBindingMismatch,
    ProfileWindowInvalid,
    ProfileExpired,
    ProfileThresholdMismatch,
    IncompleteCandidateSet,
    UnsupportedRiskPolicy,
    ScorerContractDigestMismatch,
    ScorerContractBindingMismatch,
    ScoreEvidenceCountMismatch,
    ScoreEvidenceMismatch(String),
    ArtifactDigestMismatch(&'static str),
    AuthenticationKeyMismatch,
    AuthenticationKeyRevoked,
    AuthenticationSubjectMismatch,
    AuthenticationScopeMismatch,
    AuthenticationPayloadMismatch,
    AuthenticationGenerationMismatch,
    AuthenticationWindowInvalid,
    AuthenticationExpired,
    AuthenticationTagMismatch,
    DecisionSpecificSequenceMismatch(&'static str),
    Arithmetic,
}

impl fmt::Display for QualifiedError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualifiedError {}

impl From<CalibratedError> for QualifiedError {
    fn from(value: CalibratedError) -> Self {
        Self::Calibrated(value)
    }
}
