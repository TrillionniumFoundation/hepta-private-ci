use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NduFbsdeAcceptanceStageV1 {
    Shadow,
    Advisory,
    RestrictedWrite,
}

impl NduFbsdeAcceptanceStageV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Shadow => 1,
            Self::Advisory => 2,
            Self::RestrictedWrite => 3,
        }
    }

    const fn predecessor(self) -> Option<Self> {
        match self {
            Self::Shadow => None,
            Self::Advisory => Some(Self::Shadow),
            Self::RestrictedWrite => Some(Self::Advisory),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduFbsdeAcceptanceDispositionV1 {
    Eligible,
    Denied,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduFbsdeAcceptanceErrorV1 {
    EmptyDigest(&'static str),
    InvalidPolicy,
    InvalidMetrics,
    InsufficientShadowVolume,
    MissingPredecessor,
    StageRegression,
    CandidateMismatch,
    ReceiptDigest,
}

impl fmt::Display for NduFbsdeAcceptanceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduFbsdeAcceptanceErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeAcceptancePolicyV1 {
    minimum_shadow_samples: u64,
    maximum_convergence_residual_q24: i64,
    maximum_calibration_error_ppm: u32,
    minimum_utility_improvement_q24: i64,
    maximum_regression_failures: u32,
    policy_digest: Digest32,
}

impl NduFbsdeAcceptancePolicyV1 {
    pub fn new(
        minimum_shadow_samples: u64,
        maximum_convergence_residual_q24: i64,
        maximum_calibration_error_ppm: u32,
        minimum_utility_improvement_q24: i64,
        maximum_regression_failures: u32,
    ) -> Result<Self, NduFbsdeAcceptanceErrorV1> {
        if minimum_shadow_samples == 0
            || maximum_convergence_residual_q24 < 0
            || maximum_calibration_error_ppm > 1_000_000
            || minimum_utility_improvement_q24 <= 0
        {
            return Err(NduFbsdeAcceptanceErrorV1::InvalidPolicy);
        }
        let policy_digest = digest_acceptance_policy(
            minimum_shadow_samples,
            maximum_convergence_residual_q24,
            maximum_calibration_error_ppm,
            minimum_utility_improvement_q24,
            maximum_regression_failures,
        );
        Ok(Self {
            minimum_shadow_samples,
            maximum_convergence_residual_q24,
            maximum_calibration_error_ppm,
            minimum_utility_improvement_q24,
            maximum_regression_failures,
            policy_digest,
        })
    }

    #[must_use]
    pub const fn minimum_shadow_samples(&self) -> u64 {
        self.minimum_shadow_samples
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    pub fn validate(&self) -> Result<(), NduFbsdeAcceptanceErrorV1> {
        let rebuilt = Self::new(
            self.minimum_shadow_samples,
            self.maximum_convergence_residual_q24,
            self.maximum_calibration_error_ppm,
            self.minimum_utility_improvement_q24,
            self.maximum_regression_failures,
        )?;
        if rebuilt.policy_digest != self.policy_digest {
            return Err(NduFbsdeAcceptanceErrorV1::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeIndependentEvidenceV1 {
    pub candidate_digest: Digest32,
    pub registered_dataset_digest: Digest32,
    pub immutable_dataset_binding_digest: Digest32,
    pub filtration_audit_digest: Digest32,
    pub leakage_audit_digest: Digest32,
    pub independent_evaluator_identity_digest: Digest32,
    pub independent_evaluator_receipt_digest: Digest32,
    pub trusted_time_receipt_digest: Digest32,
    pub independent_oracle_digest: Digest32,
    pub convergence_envelope_digest: Digest32,
    pub calibration_receipt_digest: Digest32,
    pub utility_improvement_receipt_digest: Digest32,
    pub regression_receipt_digest: Digest32,
    pub rollback_trigger_digest: Digest32,
    pub runtime_receipt_digest: Digest32,
    pub production_policy_digest: Digest32,
    pub shadow_sample_count: u64,
    pub maximum_convergence_residual_q24: i64,
    pub calibration_error_ppm: u32,
    pub utility_improvement_lower_bound_q24: i64,
    pub regression_failure_count: u32,
}

impl NduFbsdeIndependentEvidenceV1 {
    pub fn validate_shape(&self) -> Result<(), NduFbsdeAcceptanceErrorV1> {
        for (field, digest) in [
            ("candidate", self.candidate_digest),
            ("registered dataset", self.registered_dataset_digest),
            ("immutable dataset binding", self.immutable_dataset_binding_digest),
            ("filtration audit", self.filtration_audit_digest),
            ("leakage audit", self.leakage_audit_digest),
            (
                "independent evaluator identity",
                self.independent_evaluator_identity_digest,
            ),
            (
                "independent evaluator receipt",
                self.independent_evaluator_receipt_digest,
            ),
            ("trusted time receipt", self.trusted_time_receipt_digest),
            ("independent oracle", self.independent_oracle_digest),
            ("convergence envelope", self.convergence_envelope_digest),
            ("calibration receipt", self.calibration_receipt_digest),
            ("utility improvement receipt", self.utility_improvement_receipt_digest),
            ("regression receipt", self.regression_receipt_digest),
            ("rollback trigger", self.rollback_trigger_digest),
            ("runtime receipt", self.runtime_receipt_digest),
            ("production policy", self.production_policy_digest),
        ] {
            require_digest(digest, field)?;
        }
        if self.shadow_sample_count == 0
            || self.maximum_convergence_residual_q24 < 0
            || self.calibration_error_ppm > 1_000_000
        {
            return Err(NduFbsdeAcceptanceErrorV1::InvalidMetrics);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeAcceptanceReceiptV1 {
    stage: NduFbsdeAcceptanceStageV1,
    disposition: NduFbsdeAcceptanceDispositionV1,
    candidate_digest: Digest32,
    production_policy_digest: Digest32,
    acceptance_policy_digest: Digest32,
    evidence_digest: Digest32,
    predecessor_receipt_digest: Option<Digest32>,
    shadow_sample_count: u64,
    maximum_convergence_residual_q24: i64,
    calibration_error_ppm: u32,
    utility_improvement_lower_bound_q24: i64,
    regression_failure_count: u32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduFbsdeAcceptanceReceiptV1 {
    #[must_use]
    pub const fn stage(&self) -> NduFbsdeAcceptanceStageV1 {
        self.stage
    }

    #[must_use]
    pub const fn disposition(&self) -> NduFbsdeAcceptanceDispositionV1 {
        self.disposition
    }

    #[must_use]
    pub const fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    #[must_use]
    pub const fn production_policy_digest(&self) -> Digest32 {
        self.production_policy_digest
    }

    #[must_use]
    pub const fn acceptance_policy_digest(&self) -> Digest32 {
        self.acceptance_policy_digest
    }

    #[must_use]
    pub const fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }

    #[must_use]
    pub const fn predecessor_receipt_digest(&self) -> Option<Digest32> {
        self.predecessor_receipt_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), NduFbsdeAcceptanceErrorV1> {
        if self.authority != AuthorityPosture::DENY_ALL {
            return Err(NduFbsdeAcceptanceErrorV1::ReceiptDigest);
        }
        for (field, digest) in [
            ("candidate", self.candidate_digest),
            ("production policy", self.production_policy_digest),
            ("acceptance policy", self.acceptance_policy_digest),
            ("evidence", self.evidence_digest),
        ] {
            require_digest(digest, field)?;
        }
        if let Some(predecessor) = self.predecessor_receipt_digest {
            require_digest(predecessor, "predecessor receipt")?;
        }
        let expected = digest_acceptance_receipt(
            self.stage,
            self.disposition,
            self.candidate_digest,
            self.production_policy_digest,
            self.acceptance_policy_digest,
            self.evidence_digest,
            self.predecessor_receipt_digest,
            self.shadow_sample_count,
            self.maximum_convergence_residual_q24,
            self.calibration_error_ppm,
            self.utility_improvement_lower_bound_q24,
            self.regression_failure_count,
        );
        if expected != self.receipt_digest {
            return Err(NduFbsdeAcceptanceErrorV1::ReceiptDigest);
        }
        Ok(())
    }
}

pub fn evaluate_ndu_fbsde_acceptance_v1(
    stage: NduFbsdeAcceptanceStageV1,
    policy: &NduFbsdeAcceptancePolicyV1,
    evidence: &NduFbsdeIndependentEvidenceV1,
    predecessor: Option<&NduFbsdeAcceptanceReceiptV1>,
) -> Result<NduFbsdeAcceptanceReceiptV1, NduFbsdeAcceptanceErrorV1> {
    policy.validate()?;
    evidence.validate_shape()?;
    let predecessor_receipt_digest = match stage.predecessor() {
        None => {
            if predecessor.is_some() {
                return Err(NduFbsdeAcceptanceErrorV1::StageRegression);
            }
            None
        }
        Some(required_stage) => {
            let previous = predecessor.ok_or(NduFbsdeAcceptanceErrorV1::MissingPredecessor)?;
            previous.validate()?;
            if previous.stage != required_stage
                || previous.disposition != NduFbsdeAcceptanceDispositionV1::Eligible
            {
                return Err(NduFbsdeAcceptanceErrorV1::StageRegression);
            }
            if previous.candidate_digest != evidence.candidate_digest
                || previous.production_policy_digest != evidence.production_policy_digest
                || previous.acceptance_policy_digest != policy.policy_digest
            {
                return Err(NduFbsdeAcceptanceErrorV1::CandidateMismatch);
            }
            Some(previous.receipt_digest)
        }
    };

    let eligible = evidence.shadow_sample_count >= policy.minimum_shadow_samples
        && evidence.maximum_convergence_residual_q24
            <= policy.maximum_convergence_residual_q24
        && evidence.calibration_error_ppm <= policy.maximum_calibration_error_ppm
        && evidence.utility_improvement_lower_bound_q24
            >= policy.minimum_utility_improvement_q24
        && evidence.regression_failure_count <= policy.maximum_regression_failures;
    let disposition = if eligible {
        NduFbsdeAcceptanceDispositionV1::Eligible
    } else {
        NduFbsdeAcceptanceDispositionV1::Denied
    };
    let evidence_digest = digest_evidence(evidence);
    let receipt_digest = digest_acceptance_receipt(
        stage,
        disposition,
        evidence.candidate_digest,
        evidence.production_policy_digest,
        policy.policy_digest,
        evidence_digest,
        predecessor_receipt_digest,
        evidence.shadow_sample_count,
        evidence.maximum_convergence_residual_q24,
        evidence.calibration_error_ppm,
        evidence.utility_improvement_lower_bound_q24,
        evidence.regression_failure_count,
    );
    let receipt = NduFbsdeAcceptanceReceiptV1 {
        stage,
        disposition,
        candidate_digest: evidence.candidate_digest,
        production_policy_digest: evidence.production_policy_digest,
        acceptance_policy_digest: policy.policy_digest,
        evidence_digest,
        predecessor_receipt_digest,
        shadow_sample_count: evidence.shadow_sample_count,
        maximum_convergence_residual_q24: evidence.maximum_convergence_residual_q24,
        calibration_error_ppm: evidence.calibration_error_ppm,
        utility_improvement_lower_bound_q24: evidence.utility_improvement_lower_bound_q24,
        regression_failure_count: evidence.regression_failure_count,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    if !eligible && stage != NduFbsdeAcceptanceStageV1::Shadow {
        return Err(NduFbsdeAcceptanceErrorV1::InsufficientShadowVolume);
    }
    Ok(receipt)
}

fn digest_acceptance_policy(
    minimum_shadow_samples: u64,
    maximum_convergence_residual_q24: i64,
    maximum_calibration_error_ppm: u32,
    minimum_utility_improvement_q24: i64,
    maximum_regression_failures: u32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.fbsde-acceptance-policy.v1\0".to_vec();
    bytes.extend_from_slice(&minimum_shadow_samples.to_be_bytes());
    bytes.extend_from_slice(&maximum_convergence_residual_q24.to_be_bytes());
    bytes.extend_from_slice(&maximum_calibration_error_ppm.to_be_bytes());
    bytes.extend_from_slice(&minimum_utility_improvement_q24.to_be_bytes());
    bytes.extend_from_slice(&maximum_regression_failures.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_evidence(evidence: &NduFbsdeIndependentEvidenceV1) -> Digest32 {
    let mut bytes = b"hepta.ndu.fbsde-independent-evidence.v1\0".to_vec();
    for digest in [
        evidence.candidate_digest,
        evidence.registered_dataset_digest,
        evidence.immutable_dataset_binding_digest,
        evidence.filtration_audit_digest,
        evidence.leakage_audit_digest,
        evidence.independent_evaluator_identity_digest,
        evidence.independent_evaluator_receipt_digest,
        evidence.trusted_time_receipt_digest,
        evidence.independent_oracle_digest,
        evidence.convergence_envelope_digest,
        evidence.calibration_receipt_digest,
        evidence.utility_improvement_receipt_digest,
        evidence.regression_receipt_digest,
        evidence.rollback_trigger_digest,
        evidence.runtime_receipt_digest,
        evidence.production_policy_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&evidence.shadow_sample_count.to_be_bytes());
    bytes.extend_from_slice(&evidence.maximum_convergence_residual_q24.to_be_bytes());
    bytes.extend_from_slice(&evidence.calibration_error_ppm.to_be_bytes());
    bytes.extend_from_slice(&evidence.utility_improvement_lower_bound_q24.to_be_bytes());
    bytes.extend_from_slice(&evidence.regression_failure_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_acceptance_receipt(
    stage: NduFbsdeAcceptanceStageV1,
    disposition: NduFbsdeAcceptanceDispositionV1,
    candidate_digest: Digest32,
    production_policy_digest: Digest32,
    acceptance_policy_digest: Digest32,
    evidence_digest: Digest32,
    predecessor_receipt_digest: Option<Digest32>,
    shadow_sample_count: u64,
    maximum_convergence_residual_q24: i64,
    calibration_error_ppm: u32,
    utility_improvement_lower_bound_q24: i64,
    regression_failure_count: u32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.fbsde-acceptance-receipt.v1\0".to_vec();
    bytes.push(stage.tag());
    bytes.push(match disposition {
        NduFbsdeAcceptanceDispositionV1::Eligible => 1,
        NduFbsdeAcceptanceDispositionV1::Denied => 2,
    });
    bytes.extend_from_slice(candidate_digest.as_array());
    bytes.extend_from_slice(production_policy_digest.as_array());
    bytes.extend_from_slice(acceptance_policy_digest.as_array());
    bytes.extend_from_slice(evidence_digest.as_array());
    match predecessor_receipt_digest {
        Some(predecessor) => {
            bytes.push(1);
            bytes.extend_from_slice(predecessor.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&shadow_sample_count.to_be_bytes());
    bytes.extend_from_slice(&maximum_convergence_residual_q24.to_be_bytes());
    bytes.extend_from_slice(&calibration_error_ppm.to_be_bytes());
    bytes.extend_from_slice(&utility_improvement_lower_bound_q24.to_be_bytes());
    bytes.extend_from_slice(&regression_failure_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), NduFbsdeAcceptanceErrorV1> {
    if value.is_zero() {
        return Err(NduFbsdeAcceptanceErrorV1::EmptyDigest(field));
    }
    Ok(())
}

#[cfg(test)]
#[path = "fbsde_acceptance_tests.rs"]
mod tests;
