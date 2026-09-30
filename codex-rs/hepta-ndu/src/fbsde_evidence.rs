use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32};

use crate::{
    NduFbsdePublicationBindingV1, NduFbsdeReferenceReceiptV1,
    NduFbsdeShadowGateReceiptV1, NduFbsdeTrainingCandidateV1,
};

const ROLLBACK_HOLDOUT_RMSE: u16 = 1 << 0;
const ROLLBACK_CALIBRATION: u16 = 1 << 1;
const ROLLBACK_UTILITY: u16 = 1 << 2;
const ROLLBACK_FAILURES: u16 = 1 << 3;
const ROLLBACK_SAMPLE_FLOOR: u16 = 1 << 4;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduFbsdeIndependentEvidenceErrorV2 {
    EmptyDigest(&'static str),
    InvalidPolicy,
    InvalidObservation,
    CandidateMismatch,
    ReferenceMismatch,
    ArtifactMismatch,
    ShadowGateMismatch,
    RollbackTriggered,
    InsufficientShadowVolume,
    InvalidWindow,
    ReceiptDigestMismatch,
    Authority,
}

impl fmt::Display for NduFbsdeIndependentEvidenceErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduFbsdeIndependentEvidenceErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeRollbackPolicyV1 {
    pub maximum_holdout_rmse_q24: i64,
    pub maximum_calibration_error_q24: i64,
    pub minimum_utility_improvement_q24: i64,
    pub maximum_failures: u64,
    pub minimum_runtime_decisions: u64,
    pub policy_digest: Digest32,
}

impl NduFbsdeRollbackPolicyV1 {
    pub fn new(
        maximum_holdout_rmse_q24: i64,
        maximum_calibration_error_q24: i64,
        minimum_utility_improvement_q24: i64,
        maximum_failures: u64,
        minimum_runtime_decisions: u64,
    ) -> Result<Self, NduFbsdeIndependentEvidenceErrorV2> {
        if maximum_holdout_rmse_q24 < 0
            || maximum_calibration_error_q24 < 0
            || minimum_utility_improvement_q24 < 0
            || minimum_runtime_decisions == 0
        {
            return Err(NduFbsdeIndependentEvidenceErrorV2::InvalidPolicy);
        }
        let policy_digest = Digest32::of_parts(&[
            b"hepta.ndu.fbsde.rollback-policy.v1\0",
            &maximum_holdout_rmse_q24.to_be_bytes(),
            &maximum_calibration_error_q24.to_be_bytes(),
            &minimum_utility_improvement_q24.to_be_bytes(),
            &maximum_failures.to_be_bytes(),
            &minimum_runtime_decisions.to_be_bytes(),
        ]);
        Ok(Self {
            maximum_holdout_rmse_q24,
            maximum_calibration_error_q24,
            minimum_utility_improvement_q24,
            maximum_failures,
            minimum_runtime_decisions,
            policy_digest,
        })
    }

    pub fn validate(&self) -> Result<(), NduFbsdeIndependentEvidenceErrorV2> {
        let rebuilt = Self::new(
            self.maximum_holdout_rmse_q24,
            self.maximum_calibration_error_q24,
            self.minimum_utility_improvement_q24,
            self.maximum_failures,
            self.minimum_runtime_decisions,
        )?;
        if rebuilt.policy_digest != self.policy_digest {
            return Err(NduFbsdeIndependentEvidenceErrorV2::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeRuntimeObservationV1 {
    pub candidate_digest: Digest32,
    pub holdout_rmse_q24: i64,
    pub calibration_error_q24: i64,
    pub utility_improvement_q24: i64,
    pub observed_failure_count: u64,
    pub observed_episode_count: u64,
    pub observed_decision_count: u64,
    pub window_start_ms: u64,
    pub window_end_ms: u64,
    pub observation_digest: Digest32,
}

impl NduFbsdeRuntimeObservationV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        candidate_digest: Digest32,
        holdout_rmse_q24: i64,
        calibration_error_q24: i64,
        utility_improvement_q24: i64,
        observed_failure_count: u64,
        observed_episode_count: u64,
        observed_decision_count: u64,
        window_start_ms: u64,
        window_end_ms: u64,
    ) -> Result<Self, NduFbsdeIndependentEvidenceErrorV2> {
        require_digest(candidate_digest, "candidate")?;
        if holdout_rmse_q24 < 0
            || calibration_error_q24 < 0
            || utility_improvement_q24 < 0
            || observed_episode_count == 0
            || observed_decision_count == 0
            || window_start_ms == 0
            || window_end_ms <= window_start_ms
        {
            return Err(NduFbsdeIndependentEvidenceErrorV2::InvalidObservation);
        }
        let observation_digest = digest_observation(
            candidate_digest,
            holdout_rmse_q24,
            calibration_error_q24,
            utility_improvement_q24,
            observed_failure_count,
            observed_episode_count,
            observed_decision_count,
            window_start_ms,
            window_end_ms,
        );
        Ok(Self {
            candidate_digest,
            holdout_rmse_q24,
            calibration_error_q24,
            utility_improvement_q24,
            observed_failure_count,
            observed_episode_count,
            observed_decision_count,
            window_start_ms,
            window_end_ms,
            observation_digest,
        })
    }

    pub fn validate(&self) -> Result<(), NduFbsdeIndependentEvidenceErrorV2> {
        let rebuilt = Self::new(
            self.candidate_digest,
            self.holdout_rmse_q24,
            self.calibration_error_q24,
            self.utility_improvement_q24,
            self.observed_failure_count,
            self.observed_episode_count,
            self.observed_decision_count,
            self.window_start_ms,
            self.window_end_ms,
        )?;
        if rebuilt.observation_digest != self.observation_digest {
            return Err(NduFbsdeIndependentEvidenceErrorV2::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeRollbackReceiptV1 {
    candidate_digest: Digest32,
    policy_digest: Digest32,
    observation_digest: Digest32,
    reason_mask: u16,
    triggered: bool,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduFbsdeRollbackReceiptV1 {
    #[must_use]
    pub const fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    #[must_use]
    pub const fn reason_mask(&self) -> u16 {
        self.reason_mask
    }

    #[must_use]
    pub const fn triggered(&self) -> bool {
        self.triggered
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), NduFbsdeIndependentEvidenceErrorV2> {
        require_digest(self.candidate_digest, "candidate")?;
        require_digest(self.policy_digest, "rollback policy")?;
        require_digest(self.observation_digest, "runtime observation")?;
        if self.triggered != (self.reason_mask != 0)
            || self.authority != AuthorityPosture::DENY_ALL
            || digest_rollback_receipt(
                self.candidate_digest,
                self.policy_digest,
                self.observation_digest,
                self.reason_mask,
                self.triggered,
            ) != self.receipt_digest
        {
            return Err(NduFbsdeIndependentEvidenceErrorV2::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

pub fn evaluate_fbsde_rollback_v1(
    policy: &NduFbsdeRollbackPolicyV1,
    observation: &NduFbsdeRuntimeObservationV1,
) -> Result<NduFbsdeRollbackReceiptV1, NduFbsdeIndependentEvidenceErrorV2> {
    policy.validate()?;
    observation.validate()?;
    let mut reason_mask = 0_u16;
    if observation.holdout_rmse_q24 > policy.maximum_holdout_rmse_q24 {
        reason_mask |= ROLLBACK_HOLDOUT_RMSE;
    }
    if observation.calibration_error_q24 > policy.maximum_calibration_error_q24 {
        reason_mask |= ROLLBACK_CALIBRATION;
    }
    if observation.utility_improvement_q24 < policy.minimum_utility_improvement_q24 {
        reason_mask |= ROLLBACK_UTILITY;
    }
    if observation.observed_failure_count > policy.maximum_failures {
        reason_mask |= ROLLBACK_FAILURES;
    }
    if observation.observed_decision_count < policy.minimum_runtime_decisions {
        reason_mask |= ROLLBACK_SAMPLE_FLOOR;
    }
    let triggered = reason_mask != 0;
    let receipt_digest = digest_rollback_receipt(
        observation.candidate_digest,
        policy.policy_digest,
        observation.observation_digest,
        reason_mask,
        triggered,
    );
    let receipt = NduFbsdeRollbackReceiptV1 {
        candidate_digest: observation.candidate_digest,
        policy_digest: policy.policy_digest,
        observation_digest: observation.observation_digest,
        reason_mask,
        triggered,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.validate()?;
    Ok(receipt)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeIndependentEvidenceV2 {
    pub registered_dataset_digest: Digest32,
    pub immutable_dataset_locator_binding_digest: Digest32,
    pub filtration_audit_digest: Digest32,
    pub leakage_audit_digest: Digest32,
    pub independent_numerical_oracle_digest: Digest32,
    pub convergence_envelope_digest: Digest32,
    pub calibration_acceptance_digest: Digest32,
    pub utility_improvement_acceptance_digest: Digest32,
    pub regression_acceptance_digest: Digest32,
    pub shadow_volume_receipt_digest: Digest32,
    pub advisory_runtime_receipt_digest: Digest32,
    pub restricted_write_runtime_receipt_digest: Digest32,
    pub target_host_receipt_digest: Digest32,
    pub rollback_policy_digest: Digest32,
    pub observed_episode_count: u64,
    pub observed_decision_count: u64,
    pub minimum_episode_count: u64,
    pub minimum_decision_count: u64,
    pub window_start_ms: u64,
    pub window_end_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFbsdeIndependentAcceptanceReceiptV2 {
    candidate_digest: Digest32,
    reference_receipt_digest: Digest32,
    publication_digest: Digest32,
    shadow_gate_receipt_digest: Digest32,
    rollback_receipt_digest: Digest32,
    evidence_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
    production_activation: bool,
}

impl NduFbsdeIndependentAcceptanceReceiptV2 {
    #[must_use]
    pub const fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    #[must_use]
    pub const fn evidence_digest(&self) -> Digest32 {
        self.evidence_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    #[must_use]
    pub const fn production_activation(&self) -> bool {
        self.production_activation
    }

    pub fn validate(&self) -> Result<(), NduFbsdeIndependentEvidenceErrorV2> {
        for (digest, field) in [
            (self.candidate_digest, "candidate"),
            (self.reference_receipt_digest, "reference receipt"),
            (self.publication_digest, "publication"),
            (self.shadow_gate_receipt_digest, "shadow gate receipt"),
            (self.rollback_receipt_digest, "rollback receipt"),
            (self.evidence_digest, "independent evidence"),
        ] {
            require_digest(digest, field)?;
        }
        if self.authority != AuthorityPosture::DENY_ALL
            || self.production_activation
            || digest_acceptance_receipt(
                self.candidate_digest,
                self.reference_receipt_digest,
                self.publication_digest,
                self.shadow_gate_receipt_digest,
                self.rollback_receipt_digest,
                self.evidence_digest,
            ) != self.receipt_digest
        {
            return Err(NduFbsdeIndependentEvidenceErrorV2::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

pub fn seal_fbsde_independent_acceptance_v2(
    candidate: &NduFbsdeTrainingCandidateV1,
    reference: &NduFbsdeReferenceReceiptV1,
    publication: &NduFbsdePublicationBindingV1,
    shadow_gate: &NduFbsdeShadowGateReceiptV1,
    rollback: &NduFbsdeRollbackReceiptV1,
    evidence: &NduFbsdeIndependentEvidenceV2,
) -> Result<NduFbsdeIndependentAcceptanceReceiptV2, NduFbsdeIndependentEvidenceErrorV2> {
    if candidate.authority() != AuthorityPosture::DENY_ALL
        || publication.authority() != AuthorityPosture::DENY_ALL
        || shadow_gate.authority() != AuthorityPosture::DENY_ALL
        || shadow_gate.production_activation()
    {
        return Err(NduFbsdeIndependentEvidenceErrorV2::Authority);
    }
    if reference.candidate_digest() != candidate.candidate_digest()
        || rollback.candidate_digest() != candidate.candidate_digest()
    {
        return Err(NduFbsdeIndependentEvidenceErrorV2::CandidateMismatch);
    }
    if reference.artifact_bytes_digest() != candidate.artifact_bytes_digest()
        || publication.artifact_bytes_digest() != candidate.artifact_bytes_digest()
    {
        return Err(NduFbsdeIndependentEvidenceErrorV2::ArtifactMismatch);
    }
    rollback.validate()?;
    if rollback.triggered() {
        return Err(NduFbsdeIndependentEvidenceErrorV2::RollbackTriggered);
    }
    validate_independent_evidence(evidence)?;
    if evidence.registered_dataset_digest != candidate.dataset_digest()
        || evidence.rollback_policy_digest.is_zero()
    {
        return Err(NduFbsdeIndependentEvidenceErrorV2::ReferenceMismatch);
    }
    let evidence_digest = digest_independent_evidence(evidence);
    let receipt_digest = digest_acceptance_receipt(
        candidate.candidate_digest(),
        reference.receipt_digest(),
        publication.publication_digest(),
        shadow_gate.receipt_digest(),
        rollback.receipt_digest(),
        evidence_digest,
    );
    let receipt = NduFbsdeIndependentAcceptanceReceiptV2 {
        candidate_digest: candidate.candidate_digest(),
        reference_receipt_digest: reference.receipt_digest(),
        publication_digest: publication.publication_digest(),
        shadow_gate_receipt_digest: shadow_gate.receipt_digest(),
        rollback_receipt_digest: rollback.receipt_digest(),
        evidence_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
        production_activation: false,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn validate_independent_evidence(
    evidence: &NduFbsdeIndependentEvidenceV2,
) -> Result<(), NduFbsdeIndependentEvidenceErrorV2> {
    for (digest, field) in [
        (evidence.registered_dataset_digest, "registered dataset"),
        (
            evidence.immutable_dataset_locator_binding_digest,
            "immutable dataset locator",
        ),
        (evidence.filtration_audit_digest, "filtration audit"),
        (evidence.leakage_audit_digest, "leakage audit"),
        (
            evidence.independent_numerical_oracle_digest,
            "independent numerical oracle",
        ),
        (
            evidence.convergence_envelope_digest,
            "convergence envelope",
        ),
        (
            evidence.calibration_acceptance_digest,
            "calibration acceptance",
        ),
        (
            evidence.utility_improvement_acceptance_digest,
            "utility improvement acceptance",
        ),
        (
            evidence.regression_acceptance_digest,
            "regression acceptance",
        ),
        (evidence.shadow_volume_receipt_digest, "shadow volume"),
        (
            evidence.advisory_runtime_receipt_digest,
            "advisory runtime receipt",
        ),
        (
            evidence.restricted_write_runtime_receipt_digest,
            "restricted-write runtime receipt",
        ),
        (evidence.target_host_receipt_digest, "target-host receipt"),
        (evidence.rollback_policy_digest, "rollback policy"),
    ] {
        require_digest(digest, field)?;
    }
    if evidence.minimum_episode_count == 0
        || evidence.minimum_decision_count == 0
        || evidence.observed_episode_count < evidence.minimum_episode_count
        || evidence.observed_decision_count < evidence.minimum_decision_count
    {
        return Err(NduFbsdeIndependentEvidenceErrorV2::InsufficientShadowVolume);
    }
    if evidence.window_start_ms == 0 || evidence.window_end_ms <= evidence.window_start_ms {
        return Err(NduFbsdeIndependentEvidenceErrorV2::InvalidWindow);
    }
    Ok(())
}

fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduFbsdeIndependentEvidenceErrorV2> {
    if digest.is_zero() {
        Err(NduFbsdeIndependentEvidenceErrorV2::EmptyDigest(field))
    } else {
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
fn digest_observation(
    candidate_digest: Digest32,
    holdout_rmse_q24: i64,
    calibration_error_q24: i64,
    utility_improvement_q24: i64,
    observed_failure_count: u64,
    observed_episode_count: u64,
    observed_decision_count: u64,
    window_start_ms: u64,
    window_end_ms: u64,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.fbsde.runtime-observation.v1\0",
        candidate_digest.as_array(),
        &holdout_rmse_q24.to_be_bytes(),
        &calibration_error_q24.to_be_bytes(),
        &utility_improvement_q24.to_be_bytes(),
        &observed_failure_count.to_be_bytes(),
        &observed_episode_count.to_be_bytes(),
        &observed_decision_count.to_be_bytes(),
        &window_start_ms.to_be_bytes(),
        &window_end_ms.to_be_bytes(),
    ])
}

fn digest_rollback_receipt(
    candidate_digest: Digest32,
    policy_digest: Digest32,
    observation_digest: Digest32,
    reason_mask: u16,
    triggered: bool,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.fbsde.rollback-receipt.v1\0",
        candidate_digest.as_array(),
        policy_digest.as_array(),
        observation_digest.as_array(),
        &reason_mask.to_be_bytes(),
        &[u8::from(triggered)],
        &[0],
    ])
}

fn digest_independent_evidence(evidence: &NduFbsdeIndependentEvidenceV2) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.fbsde.independent-evidence.v2\0",
        evidence.registered_dataset_digest.as_array(),
        evidence.immutable_dataset_locator_binding_digest.as_array(),
        evidence.filtration_audit_digest.as_array(),
        evidence.leakage_audit_digest.as_array(),
        evidence.independent_numerical_oracle_digest.as_array(),
        evidence.convergence_envelope_digest.as_array(),
        evidence.calibration_acceptance_digest.as_array(),
        evidence.utility_improvement_acceptance_digest.as_array(),
        evidence.regression_acceptance_digest.as_array(),
        evidence.shadow_volume_receipt_digest.as_array(),
        evidence.advisory_runtime_receipt_digest.as_array(),
        evidence.restricted_write_runtime_receipt_digest.as_array(),
        evidence.target_host_receipt_digest.as_array(),
        evidence.rollback_policy_digest.as_array(),
        &evidence.observed_episode_count.to_be_bytes(),
        &evidence.observed_decision_count.to_be_bytes(),
        &evidence.minimum_episode_count.to_be_bytes(),
        &evidence.minimum_decision_count.to_be_bytes(),
        &evidence.window_start_ms.to_be_bytes(),
        &evidence.window_end_ms.to_be_bytes(),
    ])
}

fn digest_acceptance_receipt(
    candidate_digest: Digest32,
    reference_receipt_digest: Digest32,
    publication_digest: Digest32,
    shadow_gate_receipt_digest: Digest32,
    rollback_receipt_digest: Digest32,
    evidence_digest: Digest32,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.fbsde.independent-acceptance-receipt.v2\0",
        candidate_digest.as_array(),
        reference_receipt_digest.as_array(),
        publication_digest.as_array(),
        shadow_gate_receipt_digest.as_array(),
        rollback_receipt_digest.as_array(),
        evidence_digest.as_array(),
        &[0],
        &[0],
    ])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn rollback_trigger_is_deterministic_and_fail_closed() {
        let policy = NduFbsdeRollbackPolicyV1::new(100, 50, 20, 1, 100)
            .expect("policy");
        let observation = NduFbsdeRuntimeObservationV1::new(
            digest("candidate"),
            101,
            40,
            21,
            0,
            10,
            100,
            1,
            2,
        )
        .expect("observation");
        let receipt = evaluate_fbsde_rollback_v1(&policy, &observation)
            .expect("rollback evaluation");
        assert!(receipt.triggered());
        assert_eq!(receipt.reason_mask(), ROLLBACK_HOLDOUT_RMSE);
        assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    }
}
