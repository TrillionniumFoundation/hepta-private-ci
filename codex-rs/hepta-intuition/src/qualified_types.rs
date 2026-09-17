#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QualificationArtifactKindV1 {
    PolicyProfile,
    Calibration,
    Ood,
    Completeness,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationSignatureV1 {
    pub signer_id: StableId,
    pub signer_epoch: u64,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalPolicyProfileV1 {
    pub profile_id: StableId,
    pub policy_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub generation: u64,
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub minimum_confidence: ProbabilityQ32,
    pub maximum_ece_ppm: u32,
    pub maximum_ood_false_acceptance_ppm: u32,
    pub maximum_in_domain_score: ProbabilityQ32,
    pub maximum_fast_path_risk: RiskClass,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedPolicyProfileV1 {
    pub profile: CanonicalPolicyProfileV1,
    pub artifact_digest: Digest32,
    pub signature: QualificationSignatureV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScorerDescriptorV1 {
    /// Runtime producer of the bounded score vector. Model fitting and artifact
    /// persistence remain outside `intuition.policy`.
    pub producer_module: StableId,
    pub interface_digest: Digest32,
    pub feature_schema_digest: Digest32,
    pub score_semantics_digest: Digest32,
    pub model_digest: Digest32,
    pub generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedScorerOutputBindingV1 {
    pub descriptor: LearnedScorerDescriptorV1,
    pub state_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub predictions_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibrationQualificationPayloadV1 {
    pub calibration: CalibrationArtifactV1,
    pub profile_artifact_digest: Digest32,
    pub frozen_dataset_digest: Digest32,
    pub scorer_descriptor_digest: Digest32,
    pub model_digest: Digest32,
    pub frozen_predictions_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCalibrationQualificationV1 {
    pub payload: CalibrationQualificationPayloadV1,
    pub artifact_digest: Digest32,
    pub signature: QualificationSignatureV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OodQualificationPayloadV1 {
    pub ood: OodArtifactV1,
    pub profile_artifact_digest: Digest32,
    pub frozen_dataset_digest: Digest32,
    pub scorer_descriptor_digest: Digest32,
    pub model_digest: Digest32,
    pub frozen_predictions_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedOodQualificationV1 {
    pub payload: OodQualificationPayloadV1,
    pub artifact_digest: Digest32,
    pub signature: QualificationSignatureV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompletenessQualificationPayloadV1 {
    pub completeness: CandidateSetCompletenessBindingV1,
    pub profile_artifact_digest: Digest32,
    pub policy_digest: Digest32,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub generation: u64,
    pub scorer_descriptor_digest: Digest32,
    pub scorer_predictions_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedCompletenessQualificationV1 {
    pub payload: CompletenessQualificationPayloadV1,
    pub artifact_digest: Digest32,
    pub signature: QualificationSignatureV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedCalibratedDecisionRequestV1 {
    pub request: CalibratedDecisionRequestV1,
    pub policy_profile: SignedPolicyProfileV1,
    pub calibration_qualification: SignedCalibrationQualificationV1,
    pub ood_qualification: SignedOodQualificationV1,
    pub completeness_qualification: SignedCompletenessQualificationV1,
    pub scorer: LearnedScorerOutputBindingV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedCalibratedIntuitionReceiptV1 {
    pub decision: CalibratedIntuitionReceiptV1,
    pub policy_profile_artifact_digest: Digest32,
    pub calibration_qualification_digest: Digest32,
    pub ood_qualification_digest: Digest32,
    pub completeness_qualification_digest: Digest32,
    pub scorer_descriptor_digest: Digest32,
    pub scorer_predictions_digest: Digest32,
    pub qualification_bundle_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualificationError {
    InvalidVerifier,
    SignerMismatch,
    SignerEpochMismatch,
    SignatureMalformed,
    SignatureInvalid,
    DigestMismatch(&'static str),
    EmptyDigest(&'static str),
    ArtifactMismatch(&'static str),
    ProfileMismatch(&'static str),
    ScorerMismatch(&'static str),
    WindowInvalid,
    ArtifactExpired,
    UnsafeFastPathRisk,
    EmptyCalibrationDataset,
    InvalidCalibrationBins,
    EmptyOodDataset,
    MissingOodExamples,
    Arithmetic,
}

impl fmt::Display for QualificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for QualificationError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedCalibratedError {
    Calibrated(CalibratedError),
    Qualification(QualificationError),
}

impl fmt::Display for QualifiedCalibratedError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for QualifiedCalibratedError {}

impl From<CalibratedError> for QualifiedCalibratedError {
    fn from(value: CalibratedError) -> Self {
        Self::Calibrated(value)
    }
}
impl From<QualificationError> for QualifiedCalibratedError {
    fn from(value: QualificationError) -> Self {
        Self::Qualification(value)
    }
}

#[derive(Clone)]
pub struct QualificationArtifactVerifierV1 {
    signer_id: StableId,
    signer_epoch: u64,
    verifying_key: VerifyingKey,
}

impl QualificationArtifactVerifierV1 {
    pub fn new(
        signer_id: StableId,
        signer_epoch: u64,
        verifying_key: VerifyingKey,
    ) -> Result<Self, QualificationError> {
        if signer_epoch == 0 || verifying_key.is_weak() {
            return Err(QualificationError::InvalidVerifier);
        }
        Ok(Self {
            signer_id,
            signer_epoch,
            verifying_key,
        })
    }

    pub fn from_bytes(
        signer_id: StableId,
        signer_epoch: u64,
        public_key: [u8; 32],
    ) -> Result<Self, QualificationError> {
        let verifying_key = VerifyingKey::from_bytes(&public_key)
            .map_err(|_| QualificationError::InvalidVerifier)?;
        Self::new(signer_id, signer_epoch, verifying_key)
    }

    pub fn signer_id(&self) -> &StableId {
        &self.signer_id
    }

    pub const fn signer_epoch(&self) -> u64 {
        self.signer_epoch
    }

    fn verify_signature(
        &self,
        kind: QualificationArtifactKindV1,
        artifact_digest: Digest32,
        signature: &QualificationSignatureV1,
    ) -> Result<(), QualificationError> {
        if signature.signer_id != self.signer_id {
            return Err(QualificationError::SignerMismatch);
        }
        if signature.signer_epoch != self.signer_epoch {
            return Err(QualificationError::SignerEpochMismatch);
        }
        let signature_value = Signature::from_slice(&signature.signature)
            .map_err(|_| QualificationError::SignatureMalformed)?;
        let message = qualification_signature_message_v1(
            kind,
            artifact_digest,
            &signature.signer_id,
            signature.signer_epoch,
        )?;
        self.verifying_key
            .verify(&message, &signature_value)
            .map_err(|_| QualificationError::SignatureInvalid)
    }
}
