//! Sealed repository-consumer admission for signed qualification evidence.
//!
//! The signature-verification primitives remain crate-private. Repository
//! consumers bind one verified decision to their exact use context and receive a
//! mutation-detecting receipt. This surface is not final-holdout qualification,
//! selection, activation, promotion, or release authority.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDecisionV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_with_signed_evidence_v2;

/// Closed set of repository-owned consumers permitted to request a sealed
/// admission receipt. Adding a consumer is an API/ownership change and must also
/// update the machine-readable caller inventory.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RepositoryEvaluationConsumerV1 {
    Agentd,
    Plasticity,
}

impl RepositoryEvaluationConsumerV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Agentd => 0,
            Self::Plasticity => 1,
        }
    }
}

/// A signed evaluation decision bound to one repository consumer and one exact
/// consumer-owned request digest.
///
/// Public semantic fields remain auditable. `receipt_seal` is private so an
/// external crate cannot manufacture a valid receipt after mutating any field.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RepositoryEvaluationAdmissionV1 {
    pub consumer: RepositoryEvaluationConsumerV1,
    pub consumer_binding: Digest32,
    pub evaluation_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    pub decision: IndependentEvaluationDecisionV1,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
    pub admission_digest: Digest32,
    receipt_seal: Digest32,
}

impl RepositoryEvaluationAdmissionV1 {
    /// Revalidate every public field and the private seal before use.
    pub fn validate_integrity(&self) -> Result<(), SignedEvaluationError> {
        if self.consumer_binding.is_zero()
            || self.objective_digest.is_zero()
            || self.dataset_digest.is_zero()
            || self.trust_digest.is_zero()
            || self.authentication_digest.is_zero()
            || self.admission_digest.is_zero()
            || self.decision.evidence_digest.is_zero()
            || self.decision.authority.grants_any()
            || self.decision.evaluation_id != self.evaluation_id
            || self.decision.candidate_id != self.candidate_id
            || self.decision.baseline_id != self.baseline_id
            || self.admission_digest != admission_digest(self)
            || self.receipt_seal != admission_seal(self)
        {
            return Err(SignedEvaluationError::IdentityBinding);
        }
        Ok(())
    }
}

/// Verify signed V2 evidence through the crate-private primitive and bind the
/// resulting authority-free decision to one exact repository-consumer context.
///
/// `consumer_binding` must be the digest of the consumer's final canonical use
/// payload. A generic evaluation signature therefore cannot be replayed into a
/// different run, candidate set, artifact frontier, or proposal context.
pub fn admit_repository_evaluation_v1(
    bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
    consumer: RepositoryEvaluationConsumerV1,
    consumer_binding: Digest32,
) -> Result<RepositoryEvaluationAdmissionV1, SignedEvaluationError> {
    if consumer_binding.is_zero() {
        return Err(SignedEvaluationError::IdentityBinding);
    }

    let evaluation_id = bundle.evaluation_id.clone();
    let candidate_id = bundle.candidate_id.clone();
    let baseline_id = bundle.baseline_id.clone();
    let objective_digest = bundle.objective_digest;
    let dataset_digest = bundle.dataset_digest;
    let signed = decide_with_signed_evidence_v2(bundle, metric_roles, evidence, verifier, now)?;

    if signed.decision.authority.grants_any()
        || signed.decision.evaluation_id != evaluation_id
        || signed.decision.candidate_id != candidate_id
        || signed.decision.baseline_id != baseline_id
    {
        return Err(SignedEvaluationError::IdentityBinding);
    }

    let mut receipt = RepositoryEvaluationAdmissionV1 {
        consumer,
        consumer_binding,
        evaluation_id,
        candidate_id,
        baseline_id,
        objective_digest,
        dataset_digest,
        decision: signed.decision,
        trust_digest: signed.trust_digest,
        authentication_digest: signed.authentication_digest,
        admission_digest: Digest32::ZERO,
        receipt_seal: Digest32::ZERO,
    };
    receipt.admission_digest = admission_digest(&receipt);
    receipt.receipt_seal = admission_seal(&receipt);
    receipt.validate_integrity()?;
    Ok(receipt)
}

fn admission_digest(receipt: &RepositoryEvaluationAdmissionV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.repository-admission.v1\0".to_vec();
    bytes.push(receipt.consumer.tag());
    bytes.extend_from_slice(receipt.consumer_binding.as_array());
    push_id(&mut bytes, &receipt.evaluation_id);
    push_id(&mut bytes, &receipt.candidate_id);
    push_id(&mut bytes, &receipt.baseline_id);
    bytes.extend_from_slice(receipt.objective_digest.as_array());
    bytes.extend_from_slice(receipt.dataset_digest.as_array());
    bytes.extend_from_slice(receipt.decision.evidence_digest.as_array());
    bytes.extend_from_slice(receipt.trust_digest.as_array());
    bytes.extend_from_slice(receipt.authentication_digest.as_array());
    bytes.push(match receipt.decision.disposition {
        crate::IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        crate::IndependentEvaluationDispositionV1::Ineligible => 1,
        crate::IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    bytes.extend_from_slice(&(receipt.decision.failed_metrics.len() as u64).to_be_bytes());
    for metric_id in &receipt.decision.failed_metrics {
        push_id(&mut bytes, metric_id);
    }
    bytes.push(u8::from(receipt.decision.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn admission_seal(receipt: &RepositoryEvaluationAdmissionV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.repository-admission-receipt.v1\0".to_vec();
    bytes.extend_from_slice(admission_digest(receipt).as_array());
    bytes.extend_from_slice(receipt.admission_digest.as_array());
    bytes.extend_from_slice(receipt.consumer_binding.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::AuthorityPosture;

    use super::*;
    use crate::IndependentEvaluationDispositionV1;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn receipt(consumer: RepositoryEvaluationConsumerV1) -> RepositoryEvaluationAdmissionV1 {
        let decision = IndependentEvaluationDecisionV1 {
            evaluation_id: id("evaluation"),
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            disposition: IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            failed_metrics: Vec::new(),
            evidence_digest: digest("decision"),
            authority: AuthorityPosture::DENY_ALL,
        };
        let mut receipt = RepositoryEvaluationAdmissionV1 {
            consumer,
            consumer_binding: digest("consumer-binding"),
            evaluation_id: id("evaluation"),
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            decision,
            trust_digest: digest("trust"),
            authentication_digest: digest("authentication"),
            admission_digest: Digest32::ZERO,
            receipt_seal: Digest32::ZERO,
        };
        receipt.admission_digest = admission_digest(&receipt);
        receipt.receipt_seal = admission_seal(&receipt);
        receipt
    }

    #[test]
    fn repository_admission_seal_detects_consumer_binding_mutation() {
        let mut receipt = receipt(RepositoryEvaluationConsumerV1::Agentd);
        receipt.validate_integrity().expect("valid receipt");
        receipt.consumer_binding = digest("different-binding");
        assert_eq!(
            receipt.validate_integrity(),
            Err(SignedEvaluationError::IdentityBinding)
        );
    }

    #[test]
    fn repository_consumer_identity_changes_the_admission_digest() {
        let agentd = receipt(RepositoryEvaluationConsumerV1::Agentd);
        let plasticity = receipt(RepositoryEvaluationConsumerV1::Plasticity);
        assert_ne!(agentd.admission_digest, plasticity.admission_digest);
    }
}
