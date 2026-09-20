//! Typed, qualification-only model receipts.
//!
//! A [`ModelReceipt`] records the immutable inputs and digests for one
//! provisional model attempt.  It is deliberately a data contract, not an
//! inference or routing API: the only constructible claim level is a local
//! shadow/contract claim and every authority bit is validated as false.  The
//! receipt can therefore be used by the H7 trajectory shadow without giving
//! that shadow a production caller, writer, model route, or effect capability.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use thiserror::Error;

use crate::framing::frame_part;

/// Schema version for the local model-receipt contract.
pub const MODEL_RECEIPT_SCHEMA_VERSION: u32 = 1;
/// Namespace fence for receipts that must never be consumed as runtime
/// authority.
pub const MODEL_RECEIPT_NAMESPACE: &str = "local_qualification_only";

/// All model-receipt authority switches are compile-time-negative contracts.
pub const MODEL_RECEIPT_SHADOW_ONLY: bool = true;
pub const MODEL_RECEIPT_RUNTIME_AUTHORITY: bool = false;
pub const MODEL_RECEIPT_PRODUCTION_AUTHORITY: bool = false;
pub const MODEL_RECEIPT_PRODUCTION_CALLER: bool = false;
pub const MODEL_RECEIPT_PRODUCTION_WRITER: bool = false;
pub const MODEL_RECEIPT_EXTERNAL_EFFECTS: bool = false;
pub const MODEL_RECEIPT_EFFECT_AUTHORITY: bool = false;
pub const MODEL_RECEIPT_OPERATOR_ACCEPTANCE: bool = false;
pub const MODEL_RECEIPT_PROMOTION: bool = false;
pub const MODEL_RECEIPT_G5_ALLOWED: bool = false;
pub const MODEL_RECEIPT_EXECUTE_ALLOWED: bool = false;

/// The highest claim represented by this contract.  A schema revision is
/// required before a future implementation can introduce a stronger claim.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ModelClaimLevel {
    #[serde(rename = "L0_BASELINE_L1_SHADOW_CONTRACT_ONLY")]
    L0BaselineL1ShadowContractOnly,
}

impl ModelClaimLevel {
    /// Return the machine-readable claim value used by the plan/index files.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::L0BaselineL1ShadowContractOnly => "L0_BASELINE_L1_SHADOW_CONTRACT_ONLY",
        }
    }
}

/// Classification of the evidence attached to a model receipt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ModelEvidenceClass {
    #[serde(rename = "DETERMINISTIC_SHADOW_CONTRACT_FIXTURE")]
    DeterministicShadowContractFixture,
}

impl ModelEvidenceClass {
    /// Return the machine-readable evidence class.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::DeterministicShadowContractFixture => "DETERMINISTIC_SHADOW_CONTRACT_FIXTURE",
        }
    }
}

/// Status of the evidence itself.  `NotMeasured` is intentional: digest
/// binding and schema validation do not measure model quality, latency, or
/// Neural Engine execution.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ModelEvidenceStatus {
    #[serde(rename = "NOT_MEASURED")]
    NotMeasured,
}

impl ModelEvidenceStatus {
    /// Return the machine-readable evidence status.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NotMeasured => "NOT_MEASURED",
        }
    }
}

/// Efficacy status carried by this contract.  The sole value is deliberately
/// negative; a local receipt cannot establish efficacy.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ModelEfficacyStatus {
    #[serde(rename = "NO_EFFICACY_CLAIM")]
    NoEfficacyClaim,
}

impl ModelEfficacyStatus {
    /// Return the machine-readable efficacy status.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NoEfficacyClaim => "NO_EFFICACY_CLAIM",
        }
    }
}

/// Approval state for a local shadow receipt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ModelApprovalState {
    #[serde(rename = "NOT_APPROVED")]
    NotApproved,
}

impl ModelApprovalState {
    /// Return the machine-readable approval state.
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::NotApproved => "NOT_APPROVED",
        }
    }
}

/// Immutable digest bindings for one model attempt.
///
/// The fields are intentionally raw SHA-256 values rather than paths or
/// payloads.  A caller may bind a real artifact later, but this contract does
/// not imply that the artifact was installed, executed, or measured.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelReceiptBindings {
    pub input_digest: Sha256Digest,
    pub output_digest: Sha256Digest,
    pub artifact_sha256: Sha256Digest,
    pub model_sha256: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub graph_digest: Sha256Digest,
    pub calibration_digest: Sha256Digest,
    pub evidence_digest: Sha256Digest,
    pub snapshot_digest: Sha256Digest,
    pub causal_parent_sha256: Option<Sha256Digest>,
    pub fence_sha256: Sha256Digest,
}

impl ModelReceiptBindings {
    fn validate(&self) -> Result<(), ModelReceiptError> {
        validate_digest(&self.input_digest, "input digest")?;
        validate_digest(&self.output_digest, "output digest")?;
        validate_digest(&self.artifact_sha256, "artifact digest")?;
        validate_digest(&self.model_sha256, "model digest")?;
        validate_digest(&self.policy_digest, "policy digest")?;
        validate_digest(&self.graph_digest, "graph digest")?;
        validate_digest(&self.calibration_digest, "calibration digest")?;
        validate_digest(&self.evidence_digest, "evidence digest")?;
        validate_digest(&self.snapshot_digest, "snapshot digest")?;
        if let Some(parent) = &self.causal_parent_sha256 {
            validate_digest(parent, "causal parent digest")?;
        }
        validate_digest(&self.fence_sha256, "fence digest")
    }
}

/// One typed, provisional model attempt receipt.
///
/// `parent_attempt_id` and `parent_receipt_sha256` form an append-only
/// attempt chain.  They are separate from `causal_parent_sha256`, which
/// points at the event/state that caused the attempt.  The latter is optional
/// for a chain root, while chain children must carry both parent fields.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub attempt_id: String,
    pub attempt_seq: u32,
    pub parent_attempt_id: Option<String>,
    pub parent_receipt_sha256: Option<Sha256Digest>,
    pub input_digest: Sha256Digest,
    pub output_digest: Sha256Digest,
    pub artifact_sha256: Sha256Digest,
    pub model_sha256: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub graph_digest: Sha256Digest,
    pub calibration_digest: Sha256Digest,
    pub evidence_digest: Sha256Digest,
    pub snapshot_digest: Sha256Digest,
    pub causal_parent_sha256: Option<Sha256Digest>,
    pub fence_sha256: Sha256Digest,
    pub claim_level: ModelClaimLevel,
    pub evidence_class: ModelEvidenceClass,
    pub evidence_status: ModelEvidenceStatus,
    pub efficacy_status: ModelEfficacyStatus,
    pub approval_state: ModelApprovalState,
    pub shadow_only: bool,
    pub runtime_authority: bool,
    pub production_authority: bool,
    pub production_caller: bool,
    pub production_writer: bool,
    pub external_effects: bool,
    pub effect_authority: bool,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub g5_allowed: bool,
    pub execute_allowed: bool,
    pub receipt_sha256: Sha256Digest,
}

/// The fields included in a receipt digest.  `receipt_sha256` is excluded so
/// the digest is self-describing and can be recomputed after deserialization.
#[derive(Serialize)]
struct ModelReceiptDigest<'a> {
    schema_version: u32,
    namespace: &'a str,
    attempt_id: &'a str,
    attempt_seq: u32,
    parent_attempt_id: &'a Option<String>,
    parent_receipt_sha256: &'a Option<Sha256Digest>,
    input_digest: &'a Sha256Digest,
    output_digest: &'a Sha256Digest,
    artifact_sha256: &'a Sha256Digest,
    model_sha256: &'a Sha256Digest,
    policy_digest: &'a Sha256Digest,
    graph_digest: &'a Sha256Digest,
    calibration_digest: &'a Sha256Digest,
    evidence_digest: &'a Sha256Digest,
    snapshot_digest: &'a Sha256Digest,
    causal_parent_sha256: &'a Option<Sha256Digest>,
    fence_sha256: &'a Sha256Digest,
    claim_level: ModelClaimLevel,
    evidence_class: ModelEvidenceClass,
    evidence_status: ModelEvidenceStatus,
    efficacy_status: ModelEfficacyStatus,
    approval_state: ModelApprovalState,
    shadow_only: bool,
    runtime_authority: bool,
    production_authority: bool,
    production_caller: bool,
    production_writer: bool,
    external_effects: bool,
    effect_authority: bool,
    operator_acceptance: bool,
    promotion: bool,
    g5_allowed: bool,
    execute_allowed: bool,
}

impl ModelReceipt {
    /// Construct a new local qualification receipt and compute its digest.
    ///
    /// This constructor is the only convenience path supplied by the module;
    /// it fixes every claim, approval, and authority field to the negative
    /// qualification values above.
    pub fn qualification(
        attempt_id: impl Into<String>,
        attempt_seq: u32,
        parent_attempt_id: Option<String>,
        parent_receipt_sha256: Option<Sha256Digest>,
        bindings: ModelReceiptBindings,
    ) -> Result<Self, ModelReceiptError> {
        let mut receipt = Self {
            schema_version: MODEL_RECEIPT_SCHEMA_VERSION,
            namespace: MODEL_RECEIPT_NAMESPACE.to_string(),
            attempt_id: attempt_id.into(),
            attempt_seq,
            parent_attempt_id,
            parent_receipt_sha256,
            input_digest: bindings.input_digest,
            output_digest: bindings.output_digest,
            artifact_sha256: bindings.artifact_sha256,
            model_sha256: bindings.model_sha256,
            policy_digest: bindings.policy_digest,
            graph_digest: bindings.graph_digest,
            calibration_digest: bindings.calibration_digest,
            evidence_digest: bindings.evidence_digest,
            snapshot_digest: bindings.snapshot_digest,
            causal_parent_sha256: bindings.causal_parent_sha256,
            fence_sha256: bindings.fence_sha256,
            claim_level: ModelClaimLevel::L0BaselineL1ShadowContractOnly,
            evidence_class: ModelEvidenceClass::DeterministicShadowContractFixture,
            evidence_status: ModelEvidenceStatus::NotMeasured,
            efficacy_status: ModelEfficacyStatus::NoEfficacyClaim,
            approval_state: ModelApprovalState::NotApproved,
            shadow_only: MODEL_RECEIPT_SHADOW_ONLY,
            runtime_authority: MODEL_RECEIPT_RUNTIME_AUTHORITY,
            production_authority: MODEL_RECEIPT_PRODUCTION_AUTHORITY,
            production_caller: MODEL_RECEIPT_PRODUCTION_CALLER,
            production_writer: MODEL_RECEIPT_PRODUCTION_WRITER,
            external_effects: MODEL_RECEIPT_EXTERNAL_EFFECTS,
            effect_authority: MODEL_RECEIPT_EFFECT_AUTHORITY,
            operator_acceptance: MODEL_RECEIPT_OPERATOR_ACCEPTANCE,
            promotion: MODEL_RECEIPT_PROMOTION,
            g5_allowed: MODEL_RECEIPT_G5_ALLOWED,
            execute_allowed: MODEL_RECEIPT_EXECUTE_ALLOWED,
            receipt_sha256: Sha256Digest::for_bytes(b"uncomputed"),
        };
        receipt.receipt_sha256 = receipt.compute_digest()?;
        receipt.validate()?;
        Ok(receipt)
    }

    /// Validate schema, digest bindings, claim status, and authority fences.
    pub fn validate(&self) -> Result<(), ModelReceiptError> {
        if self.schema_version != MODEL_RECEIPT_SCHEMA_VERSION
            || self.namespace != MODEL_RECEIPT_NAMESPACE
        {
            return Err(ModelReceiptError::SchemaMismatch);
        }
        validate_identifier(&self.attempt_id, "attempt id")?;
        if self.attempt_seq == 0 {
            return Err(ModelReceiptError::Invalid(
                "attempt sequence must be non-zero".to_string(),
            ));
        }
        match (&self.parent_attempt_id, &self.parent_receipt_sha256) {
            (None, None) => {}
            (Some(parent), Some(digest)) => {
                validate_identifier(parent, "parent attempt id")?;
                if parent == &self.attempt_id {
                    return Err(ModelReceiptError::SelfParent);
                }
                validate_digest(digest, "parent receipt digest")?;
            }
            _ => return Err(ModelReceiptError::ParentBinding),
        }
        if self.attempt_seq == 1
            && (self.parent_attempt_id.is_some() || self.parent_receipt_sha256.is_some())
        {
            return Err(ModelReceiptError::ParentMismatch);
        }
        if self.attempt_seq > 1
            && (self.parent_attempt_id.is_none() || self.parent_receipt_sha256.is_none())
        {
            return Err(ModelReceiptError::ParentBinding);
        }
        let bindings = ModelReceiptBindings {
            input_digest: self.input_digest.clone(),
            output_digest: self.output_digest.clone(),
            artifact_sha256: self.artifact_sha256.clone(),
            model_sha256: self.model_sha256.clone(),
            policy_digest: self.policy_digest.clone(),
            graph_digest: self.graph_digest.clone(),
            calibration_digest: self.calibration_digest.clone(),
            evidence_digest: self.evidence_digest.clone(),
            snapshot_digest: self.snapshot_digest.clone(),
            causal_parent_sha256: self.causal_parent_sha256.clone(),
            fence_sha256: self.fence_sha256.clone(),
        };
        bindings.validate()?;
        validate_digest(&self.receipt_sha256, "receipt digest")?;
        if self.claim_level != ModelClaimLevel::L0BaselineL1ShadowContractOnly
            || self.evidence_class != ModelEvidenceClass::DeterministicShadowContractFixture
            || self.evidence_status != ModelEvidenceStatus::NotMeasured
            || self.efficacy_status != ModelEfficacyStatus::NoEfficacyClaim
            || self.approval_state != ModelApprovalState::NotApproved
        {
            return Err(ModelReceiptError::ShadowClaimBoundary);
        }
        if !self.shadow_only
            || self.runtime_authority
            || self.production_authority
            || self.production_caller
            || self.production_writer
            || self.external_effects
            || self.effect_authority
            || self.operator_acceptance
            || self.promotion
            || self.g5_allowed
            || self.execute_allowed
        {
            return Err(ModelReceiptError::AuthorityBoundary);
        }
        if self.receipt_sha256 != self.compute_digest()? {
            return Err(ModelReceiptError::DigestMismatch("receipt"));
        }
        Ok(())
    }

    /// Recompute and return the receipt digest after validation.
    pub fn digest(&self) -> Result<Sha256Digest, ModelReceiptError> {
        self.validate()?;
        Ok(self.receipt_sha256.clone())
    }

    /// Whether this value remains inside the local shadow boundary.
    pub fn is_shadow_only(&self) -> bool {
        self.shadow_only
            && self.namespace == MODEL_RECEIPT_NAMESPACE
            && self.claim_level == ModelClaimLevel::L0BaselineL1ShadowContractOnly
            && self.evidence_class == ModelEvidenceClass::DeterministicShadowContractFixture
            && self.evidence_status == ModelEvidenceStatus::NotMeasured
            && self.efficacy_status == ModelEfficacyStatus::NoEfficacyClaim
            && self.approval_state == ModelApprovalState::NotApproved
            && !self.runtime_authority
            && !self.production_authority
            && !self.production_caller
            && !self.production_writer
            && !self.external_effects
            && !self.effect_authority
            && !self.operator_acceptance
            && !self.promotion
            && !self.g5_allowed
            && !self.execute_allowed
    }

    fn compute_digest(&self) -> Result<Sha256Digest, ModelReceiptError> {
        let payload = ModelReceiptDigest {
            schema_version: self.schema_version,
            namespace: &self.namespace,
            attempt_id: &self.attempt_id,
            attempt_seq: self.attempt_seq,
            parent_attempt_id: &self.parent_attempt_id,
            parent_receipt_sha256: &self.parent_receipt_sha256,
            input_digest: &self.input_digest,
            output_digest: &self.output_digest,
            artifact_sha256: &self.artifact_sha256,
            model_sha256: &self.model_sha256,
            policy_digest: &self.policy_digest,
            graph_digest: &self.graph_digest,
            calibration_digest: &self.calibration_digest,
            evidence_digest: &self.evidence_digest,
            snapshot_digest: &self.snapshot_digest,
            causal_parent_sha256: &self.causal_parent_sha256,
            fence_sha256: &self.fence_sha256,
            claim_level: self.claim_level,
            evidence_class: self.evidence_class,
            evidence_status: self.evidence_status,
            efficacy_status: self.efficacy_status,
            approval_state: self.approval_state,
            shadow_only: self.shadow_only,
            runtime_authority: self.runtime_authority,
            production_authority: self.production_authority,
            production_caller: self.production_caller,
            production_writer: self.production_writer,
            external_effects: self.external_effects,
            effect_authority: self.effect_authority,
            operator_acceptance: self.operator_acceptance,
            promotion: self.promotion,
            g5_allowed: self.g5_allowed,
            execute_allowed: self.execute_allowed,
        };
        let bytes = serde_json::to_vec(&payload)
            .map_err(|error| ModelReceiptError::Serialization(error.to_string()))?;
        let mut hasher = sha2::Sha256::new();
        frame_part(&mut hasher, b"hepta:model-receipt:v1");
        frame_part(&mut hasher, &bytes);
        Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
    }
}

/// A strictly linear append-only chain of model-attempt receipts.
#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ModelReceiptChain {
    pub attempts: Vec<ModelReceipt>,
    pub head_receipt_sha256: Option<Sha256Digest>,
}

impl ModelReceiptChain {
    /// Append one receipt without mutating the chain on any rejection.
    pub fn append(&mut self, receipt: ModelReceipt) -> Result<(), ModelReceiptError> {
        self.validate()?;
        receipt.validate()?;
        let expected = u32::try_from(self.attempts.len() + 1)
            .map_err(|_| ModelReceiptError::Invalid("attempt chain is too long".to_string()))?;
        if receipt.attempt_seq != expected {
            return Err(ModelReceiptError::NonContiguousAttempt {
                expected,
                actual: receipt.attempt_seq,
            });
        }
        if let Some(previous) = self.attempts.last() {
            if receipt.parent_attempt_id.as_deref() != Some(previous.attempt_id.as_str())
                || receipt.parent_receipt_sha256.as_ref() != Some(&previous.receipt_sha256)
            {
                return Err(ModelReceiptError::ParentMismatch);
            }
        } else if receipt.parent_attempt_id.is_some() || receipt.parent_receipt_sha256.is_some() {
            return Err(ModelReceiptError::ParentMismatch);
        }
        if self
            .attempts
            .iter()
            .any(|attempt| attempt.attempt_id == receipt.attempt_id)
        {
            return Err(ModelReceiptError::DuplicateAttemptId);
        }
        self.head_receipt_sha256 = Some(receipt.receipt_sha256.clone());
        self.attempts.push(receipt);
        Ok(())
    }

    /// Validate every receipt and the complete predecessor/head chain.
    pub fn validate(&self) -> Result<(), ModelReceiptError> {
        match (&self.attempts[..], &self.head_receipt_sha256) {
            ([], None) => {}
            ([], Some(_)) => return Err(ModelReceiptError::ChainHeadMismatch),
            ([_, ..], None) => return Err(ModelReceiptError::ChainHeadMismatch),
            _ => {}
        }
        let mut previous: Option<&ModelReceipt> = None;
        for (index, attempt) in self.attempts.iter().enumerate() {
            attempt.validate()?;
            let expected = u32::try_from(index + 1)
                .map_err(|_| ModelReceiptError::Invalid("attempt chain is too long".to_string()))?;
            if attempt.attempt_seq != expected {
                return Err(ModelReceiptError::NonContiguousAttempt {
                    expected,
                    actual: attempt.attempt_seq,
                });
            }
            if let Some(previous) = previous {
                if attempt.parent_attempt_id.as_deref() != Some(previous.attempt_id.as_str())
                    || attempt.parent_receipt_sha256.as_ref() != Some(&previous.receipt_sha256)
                {
                    return Err(ModelReceiptError::ParentMismatch);
                }
            } else if attempt.parent_attempt_id.is_some() || attempt.parent_receipt_sha256.is_some()
            {
                return Err(ModelReceiptError::ParentMismatch);
            }
            if self
                .attempts
                .iter()
                .take(index)
                .any(|prior| prior.attempt_id == attempt.attempt_id)
            {
                return Err(ModelReceiptError::DuplicateAttemptId);
            }
            previous = Some(attempt);
        }
        if self.head_receipt_sha256.as_ref()
            != self.attempts.last().map(|attempt| &attempt.receipt_sha256)
        {
            return Err(ModelReceiptError::ChainHeadMismatch);
        }
        Ok(())
    }

    /// Return the current chain head after validation.
    pub fn head(&self) -> Result<Option<&ModelReceipt>, ModelReceiptError> {
        self.validate()?;
        Ok(self.attempts.last())
    }
}

/// Errors raised by receipt or chain validation.
#[derive(Clone, Debug, Eq, PartialEq, Error)]
pub enum ModelReceiptError {
    #[error("invalid model receipt: {0}")]
    Invalid(String),
    #[error("model receipt schema or namespace mismatch")]
    SchemaMismatch,
    #[error("model receipt crosses the shadow-only authority boundary")]
    AuthorityBoundary,
    #[error("model receipt carries a claim or approval outside the shadow contract")]
    ShadowClaimBoundary,
    #[error("model receipt digest mismatch for {0}")]
    DigestMismatch(&'static str),
    #[error("model receipt parent fields must be supplied together")]
    ParentBinding,
    #[error("model receipt cannot parent itself")]
    SelfParent,
    #[error("model receipt parent does not match chain predecessor")]
    ParentMismatch,
    #[error("model receipt chain head does not match its last attempt")]
    ChainHeadMismatch,
    #[error("model receipt chain contains a duplicate attempt id")]
    DuplicateAttemptId,
    #[error("model receipt attempt sequence is not contiguous (expected {expected}, got {actual})")]
    NonContiguousAttempt { expected: u32, actual: u32 },
    #[error("model receipt serialization failed: {0}")]
    Serialization(String),
}

fn validate_digest(digest: &Sha256Digest, label: &'static str) -> Result<(), ModelReceiptError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|_| ModelReceiptError::DigestMismatch(label))
}

fn validate_identifier(value: &str, label: &'static str) -> Result<(), ModelReceiptError> {
    if value.trim().is_empty()
        || value.len() > 256
        || value.as_bytes().contains(&0)
        || value.chars().any(char::is_control)
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(ModelReceiptError::Invalid(format!(
            "{label} contains an invalid identifier"
        )));
    }
    Ok(())
}
