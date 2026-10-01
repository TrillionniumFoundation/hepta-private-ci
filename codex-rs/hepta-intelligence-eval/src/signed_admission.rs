//! Consumer-bound admission for independently signed evaluation evidence.
//!
//! This is the only public non-product facade over the crate-internal V2
//! verifier. It binds an authenticated decision to one concrete downstream use
//! and returns an integrity-sealed, authority-free receipt. It does not consume a
//! final holdout, publish product qualification evidence, or mint selection,
//! activation, promotion, or release authority. Product qualification must still
//! use [`crate::ProductEvaluationRunnerV1`].

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDispositionV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedEligibilityAdmissionReceiptV1 {
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub consumer_binding_digest: Digest32,
    pub decision: SignedEvaluationDecisionV1,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

impl SignedEligibilityAdmissionReceiptV1 {
    pub fn validate_integrity(&self) -> Result<(), SignedEligibilityAdmissionError> {
        if self.objective_digest.is_zero()
            || self.dataset_digest.is_zero()
            || self.consumer_binding_digest.is_zero()
            || self.decision.trust_digest.is_zero()
            || self.decision.authentication_digest.is_zero()
            || self.decision.decision.evidence_digest.is_zero()
            || self.decision.decision.evaluation_id != self.evaluation_id
            || self.decision.decision.candidate_id != self.candidate_id
            || self.decision.decision.baseline_id != self.baseline_id
            || self.authority.grants_any()
            || self.decision.decision.authority.grants_any()
        {
            return Err(SignedEligibilityAdmissionError::Integrity(
                "signed eligibility admission",
            ));
        }
        let expected = admission_evidence_digest(self);
        if self.evidence_digest != expected || self.receipt_seal != admission_seal(self) {
            return Err(SignedEligibilityAdmissionError::Integrity(
                "signed eligibility admission seal",
            ));
        }
        Ok(())
    }
}

/// Authenticate and evaluate one frozen V2 bundle, then bind the result to one
/// concrete downstream use. The caller must derive `consumer_binding_digest`
/// from the complete request/proposal context that will consume the decision.
pub fn admit_signed_eligibility_v2(
    bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    consumer_binding_digest: Digest32,
    now: u64,
) -> Result<SignedEligibilityAdmissionReceiptV1, SignedEligibilityAdmissionError> {
    if consumer_binding_digest.is_zero() {
        return Err(SignedEligibilityAdmissionError::Binding(
            "consumer binding digest",
        ));
    }
    let evaluation_id = bundle.evaluation_id.clone();
    let candidate_id = bundle.candidate_id.clone();
    let baseline_id = bundle.baseline_id.clone();
    let objective_digest = bundle.objective_digest;
    let dataset_digest = bundle.dataset_digest;
    let decision = crate::signed_evaluation::decide_with_signed_evidence_v2(
        bundle,
        metric_roles,
        evidence,
        verifier,
        now,
    )?;
    let mut receipt = SignedEligibilityAdmissionReceiptV1 {
        evaluation_id,
        candidate_id,
        baseline_id,
        objective_digest,
        dataset_digest,
        consumer_binding_digest,
        decision,
        evidence_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
        receipt_seal: Digest32::ZERO,
    };
    receipt.evidence_digest = admission_evidence_digest(&receipt);
    receipt.receipt_seal = admission_seal(&receipt);
    receipt.validate_integrity()?;
    Ok(receipt)
}

fn admission_evidence_digest(receipt: &SignedEligibilityAdmissionReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.consumer-bound-admission.v1".to_vec();
    for id in [
        &receipt.evaluation_id,
        &receipt.candidate_id,
        &receipt.baseline_id,
    ] {
        push_id(&mut bytes, id);
    }
    for digest in [
        receipt.objective_digest,
        receipt.dataset_digest,
        receipt.consumer_binding_digest,
        receipt.decision.decision.evidence_digest,
        receipt.decision.trust_digest,
        receipt.decision.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(match receipt.decision.decision.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        IndependentEvaluationDispositionV1::Ineligible => 1,
        IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    bytes.extend_from_slice(&(receipt.decision.decision.failed_metrics.len() as u64).to_be_bytes());
    for metric in &receipt.decision.decision.failed_metrics {
        push_id(&mut bytes, metric);
    }
    bytes.push(u8::from(receipt.authority.grants_any()));
    bytes.push(u8::from(receipt.decision.decision.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn admission_seal(receipt: &SignedEligibilityAdmissionReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.consumer-bound-admission-receipt.v1".to_vec();
    bytes.extend_from_slice(admission_evidence_digest(receipt).as_array());
    bytes.extend_from_slice(receipt.evidence_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SignedEligibilityAdmissionError {
    Binding(&'static str),
    Integrity(&'static str),
    Evaluation(SignedEvaluationError),
}

impl fmt::Display for SignedEligibilityAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SignedEligibilityAdmissionError {}
impl From<SignedEvaluationError> for SignedEligibilityAdmissionError {
    fn from(value: SignedEvaluationError) -> Self {
        Self::Evaluation(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IndependentEvaluationDecisionV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid test id")
    }

    fn fixture() -> SignedEligibilityAdmissionReceiptV1 {
        let mut receipt = SignedEligibilityAdmissionReceiptV1 {
            evaluation_id: id("evaluation:1"),
            candidate_id: id("candidate:1"),
            baseline_id: id("candidate:0"),
            objective_digest: Digest32::of_bytes(b"objective"),
            dataset_digest: Digest32::of_bytes(b"dataset"),
            consumer_binding_digest: Digest32::of_bytes(b"consumer"),
            decision: SignedEvaluationDecisionV1 {
                decision: IndependentEvaluationDecisionV1 {
                    evaluation_id: id("evaluation:1"),
                    candidate_id: id("candidate:1"),
                    baseline_id: id("candidate:0"),
                    disposition:
                        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                    failed_metrics: Vec::new(),
                    evidence_digest: Digest32::of_bytes(b"decision"),
                    authority: AuthorityPosture::DENY_ALL,
                },
                trust_digest: Digest32::of_bytes(b"trust"),
                authentication_digest: Digest32::of_bytes(b"authentication"),
            },
            evidence_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
            receipt_seal: Digest32::ZERO,
        };
        receipt.evidence_digest = admission_evidence_digest(&receipt);
        receipt.receipt_seal = admission_seal(&receipt);
        receipt
    }

    #[test]
    fn consumer_binding_is_integrity_bound_and_authority_free() {
        let receipt = fixture();
        assert!(receipt.validate_integrity().is_ok());
        assert!(!receipt.authority.grants_any());

        let mut changed = receipt;
        changed.consumer_binding_digest = Digest32::of_bytes(b"different consumer");
        assert!(matches!(
            changed.validate_integrity(),
            Err(SignedEligibilityAdmissionError::Integrity(_))
        ));
    }

    #[test]
    fn decision_identity_is_integrity_bound() {
        let mut receipt = fixture();
        receipt.decision.decision.candidate_id = id("candidate:other");
        assert!(matches!(
            receipt.validate_integrity(),
            Err(SignedEligibilityAdmissionError::Integrity(_))
        ));
    }
}
