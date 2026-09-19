use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_SAMPLES: u32 = 1_000_000;
const Q32_ONE_RAW: i128 = 1_i128 << 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduConditionalIdentificationDecisionV1 {
    Accepted,
    Rejected,
    Unavailable,
}

impl NduConditionalIdentificationDecisionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Accepted => 0,
            Self::Rejected => 1,
            Self::Unavailable => 2,
        }
    }
}

/// Independent evidence about whether the conditional-moment regression is
/// identified on one frozen, pre-boundary feature/conditioning profile.
/// learning.eval consumes these facts; it does not manufacture the observations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConditionalIdentificationEvidenceV1 {
    pub receipt_id: StableId,
    pub coefficient_manifest_digest: Digest32,
    pub objective_class_digest: Digest32,
    pub conditioning_spec_digest: Digest32,
    pub training_fold_digest: Digest32,
    pub holdout_fold_digest: Digest32,
    pub pre_boundary_feature_digest: Digest32,
    pub outcome_time_policy_digest: Digest32,
    pub overlap_support_digest: Digest32,
    pub leakage_audit_digest: Digest32,
    pub sample_count: u32,
    pub minimum_sample_count: u32,
    pub maximum_abs_standardized_conditional_mean_q32: i64,
    pub evaluator_identity: StableId,
    pub candidate_producer_identity: StableId,
    pub expires_unix_ms: u64,
}

/// Owner-local immutable decision. It is not a registered effect/activation
/// protocol; its digest may be bound by a higher-level admitted composition.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduConditionalIdentificationReceiptV1 {
    receipt_id: StableId,
    coefficient_manifest_digest: Digest32,
    objective_class_digest: Digest32,
    conditioning_spec_digest: Digest32,
    training_fold_digest: Digest32,
    holdout_fold_digest: Digest32,
    pre_boundary_feature_digest: Digest32,
    outcome_time_policy_digest: Digest32,
    sample_count: u32,
    maximum_abs_standardized_conditional_mean_q32: i64,
    evaluator_identity: StableId,
    expires_unix_ms: u64,
    decision: NduConditionalIdentificationDecisionV1,
}

impl NduConditionalIdentificationReceiptV1 {
    #[must_use]
    pub const fn coefficient_manifest_digest(&self) -> Digest32 {
        self.coefficient_manifest_digest
    }

    #[must_use]
    pub const fn objective_class_digest(&self) -> Digest32 {
        self.objective_class_digest
    }

    #[must_use]
    pub const fn conditioning_spec_digest(&self) -> Digest32 {
        self.conditioning_spec_digest
    }

    #[must_use]
    pub fn evaluator_identity(&self) -> &StableId {
        &self.evaluator_identity
    }

    #[must_use]
    pub const fn expires_unix_ms(&self) -> u64 {
        self.expires_unix_ms
    }

    #[must_use]
    pub const fn decision(&self) -> NduConditionalIdentificationDecisionV1 {
        self.decision
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduConditionalIdentificationError {
    SelfEvaluation,
    MissingDigest(&'static str),
    InvalidSampleBounds,
    NegativeDiagnostic,
    Expired,
}

impl fmt::Display for NduConditionalIdentificationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduConditionalIdentificationError {}

pub fn evaluate_ndu_conditional_identification_v1(
    evidence: &NduConditionalIdentificationEvidenceV1,
    now_unix_ms: u64,
) -> Result<NduConditionalIdentificationReceiptV1, NduConditionalIdentificationError> {
    if evidence.evaluator_identity == evidence.candidate_producer_identity {
        return Err(NduConditionalIdentificationError::SelfEvaluation);
    }
    for (name, digest) in [
        ("coefficient manifest", evidence.coefficient_manifest_digest),
        ("objective class", evidence.objective_class_digest),
        ("conditioning spec", evidence.conditioning_spec_digest),
        ("training fold", evidence.training_fold_digest),
        ("holdout fold", evidence.holdout_fold_digest),
        ("pre-boundary feature profile", evidence.pre_boundary_feature_digest),
        ("outcome time policy", evidence.outcome_time_policy_digest),
    ] {
        require_digest(name, digest)?;
    }
    if evidence.minimum_sample_count < 2
        || evidence.minimum_sample_count > MAX_SAMPLES
        || evidence.sample_count > MAX_SAMPLES
    {
        return Err(NduConditionalIdentificationError::InvalidSampleBounds);
    }
    if evidence.maximum_abs_standardized_conditional_mean_q32 < 0 {
        return Err(NduConditionalIdentificationError::NegativeDiagnostic);
    }
    if evidence.expires_unix_ms <= now_unix_ms {
        return Err(NduConditionalIdentificationError::Expired);
    }

    let support_available =
        !evidence.overlap_support_digest.is_zero() && !evidence.leakage_audit_digest.is_zero();
    let enough_samples = evidence.sample_count >= evidence.minimum_sample_count;
    let folds_are_separate = evidence.training_fold_digest != evidence.holdout_fold_digest;
    let conditional_mean_ok =
        conditional_mean_below_002(evidence.maximum_abs_standardized_conditional_mean_q32);

    let decision = if !support_available || !enough_samples {
        NduConditionalIdentificationDecisionV1::Unavailable
    } else if !folds_are_separate || !conditional_mean_ok {
        NduConditionalIdentificationDecisionV1::Rejected
    } else {
        NduConditionalIdentificationDecisionV1::Accepted
    };

    Ok(NduConditionalIdentificationReceiptV1 {
        receipt_id: evidence.receipt_id.clone(),
        coefficient_manifest_digest: evidence.coefficient_manifest_digest,
        objective_class_digest: evidence.objective_class_digest,
        conditioning_spec_digest: evidence.conditioning_spec_digest,
        training_fold_digest: evidence.training_fold_digest,
        holdout_fold_digest: evidence.holdout_fold_digest,
        pre_boundary_feature_digest: evidence.pre_boundary_feature_digest,
        outcome_time_policy_digest: evidence.outcome_time_policy_digest,
        sample_count: evidence.sample_count,
        maximum_abs_standardized_conditional_mean_q32: evidence
            .maximum_abs_standardized_conditional_mean_q32,
        evaluator_identity: evidence.evaluator_identity.clone(),
        expires_unix_ms: evidence.expires_unix_ms,
        decision,
    })
}

pub fn canonical_ndu_conditional_identification_receipt_digest_v1(
    receipt: &NduConditionalIdentificationReceiptV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.ndu-conditional-identification.v1".to_vec();
    push_id(&mut bytes, &receipt.receipt_id);
    for digest in [
        receipt.coefficient_manifest_digest,
        receipt.objective_class_digest,
        receipt.conditioning_spec_digest,
        receipt.training_fold_digest,
        receipt.holdout_fold_digest,
        receipt.pre_boundary_feature_digest,
        receipt.outcome_time_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.sample_count.to_be_bytes());
    bytes.extend_from_slice(
        &receipt
            .maximum_abs_standardized_conditional_mean_q32
            .to_be_bytes(),
    );
    push_id(&mut bytes, &receipt.evaluator_identity);
    bytes.extend_from_slice(&receipt.expires_unix_ms.to_be_bytes());
    bytes.push(receipt.decision.tag());
    Digest32::of_bytes(&bytes)
}

fn conditional_mean_below_002(raw: i64) -> bool {
    i128::from(raw) * 100 < 2 * Q32_ONE_RAW
}

fn require_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), NduConditionalIdentificationError> {
    if digest.is_zero() {
        return Err(NduConditionalIdentificationError::MissingDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "ndu_conditional_identification_tests.rs"]
mod tests;
