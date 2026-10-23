//! Request-bound consumption of the learning.eval owner's sealed product qualification.
//!
//! These are in-process host inputs, not a new wire protocol or trust issuer.
//! The host supplies already activated learning trust; request data never does.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;

use codex_hepta_intelligence::CanonicalPortInputV1;
use codex_hepta_intelligence::CanonicalStageV1;
use codex_hepta_intelligence::CurrentOwnerStateV1;
use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductQualificationReceiptV1;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// Data supplied by the evaluator. Every field is checked again at its use site.
#[derive(Clone, Debug)]
pub struct AgentdQualifiedEvaluationV1 {
    /// Emitted by the learning.eval product runner only after fenced holdout
    /// consumption, sealed estimator execution and durable evidence publication.
    pub qualification: ProductQualificationReceiptV1,
    pub use_attestation: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdEvaluationBindingV1 {
    pub run_id: StableId,
    pub objective_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub context_receipt_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub selected_candidate_id: StableId,
}

/// Canonical bytes the existing evaluator signs for this one actual prepared use.
/// A generic qualification signature cannot be replayed for a different context.
pub fn intelligence_evaluation_binding_payload_v2(
    binding: &AgentdEvaluationBindingV1,
    qualification: &ProductQualificationReceiptV1,
) -> Result<Vec<u8>, AgentdIntelligenceEvaluationError> {
    qualification
        .validate_integrity()
        .map_err(AgentdIntelligenceEvaluationError::Qualification)?;
    let digests = [
        binding.objective_digest,
        binding.snapshot_digest,
        binding.context_receipt_digest,
        binding.candidate_set_digest,
    ];
    if digests.iter().any(|digest| digest.is_zero()) {
        return Err(AgentdIntelligenceEvaluationError::Binding);
    }
    let mut bytes = b"hepta.agentd.evaluation-use.v2\0".to_vec();
    for id in [&binding.run_id, &binding.selected_candidate_id] {
        let length = u64::try_from(id.as_str().len())
            .map_err(|_| AgentdIntelligenceEvaluationError::Binding)?;
        bytes.extend_from_slice(&length.to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(qualification.evidence_digest.as_array());
    bytes.extend_from_slice(qualification.publication_digest.as_array());
    Ok(bytes)
}

pub(super) struct AgentdEvaluationSessionV1 {
    pub run_id: StableId,
    pub current_owner: CurrentOwnerStateV1,
    pub trust: Arc<ActivatedLearningTrustV1>,
    pub signed: AgentdQualifiedEvaluationV1,
}

impl AgentdEvaluationSessionV1 {
    pub(super) fn evaluate(
        self,
        input: &CanonicalPortInputV1,
        candidate: &StableId,
        now: u64,
    ) -> Result<Digest32, AgentdIntelligenceEvaluationError> {
        if input.run_id != self.run_id
            || input.stage != CanonicalStageV1::EvaluationAdmitted
            || self.current_owner.owner_id.as_str() != "learning.eval"
            || self.signed.qualification.objective_digest != input.objective_digest
            || &self.signed.qualification.candidate_id != candidate
            || self.signed.qualification.decision.trust_digest
                != self.trust.verifier().trust_digest()
            || self.signed.use_attestation.authority_epoch != self.current_owner.authority_epoch
        {
            return Err(AgentdIntelligenceEvaluationError::Binding);
        }
        self.signed
            .qualification
            .validate_current(self.trust.verifier(), now)
            .map_err(AgentdIntelligenceEvaluationError::Qualification)?;
        let binding = AgentdEvaluationBindingV1 {
            run_id: self.run_id,
            objective_digest: input.objective_digest,
            snapshot_digest: input.snapshot_digest,
            context_receipt_digest: input.predecessor_digest,
            candidate_set_digest: input.candidate_set_digest,
            selected_candidate_id: candidate.clone(),
        };
        let payload =
            intelligence_evaluation_binding_payload_v2(&binding, &self.signed.qualification)?;
        let verified = self
            .trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &self.signed.use_attestation,
                &payload,
                now,
            )
            .map_err(AgentdIntelligenceEvaluationError::Evidence)?;
        if verified.principal() != &self.signed.qualification.evaluator
            || verified.principal().signing_key_digest != self.current_owner.key_digest
        {
            return Err(AgentdIntelligenceEvaluationError::Binding);
        }
        let result = &self.signed.qualification.decision;
        if result.decision.authority.grants_any()
            || result.decision.disposition
                != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        {
            return Err(AgentdIntelligenceEvaluationError::Ineligible);
        }
        let mut receipt = b"hepta.agentd.evaluation-consumption.v2\0".to_vec();
        receipt.extend_from_slice(Digest32::of_bytes(&payload).as_array());
        receipt.extend_from_slice(result.authentication_digest.as_array());
        receipt.extend_from_slice(self.trust.distribution_digest().as_array());
        receipt.extend_from_slice(&self.signed.use_attestation.signature);
        Ok(Digest32::of_bytes(&receipt))
    }
}

#[derive(Debug)]
pub enum AgentdIntelligenceEvaluationError {
    Binding,
    Ineligible,
    Evidence(SignedEvidenceError),
    Qualification(ProductEvaluationError),
}

impl fmt::Display for AgentdIntelligenceEvaluationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdIntelligenceEvaluationError {}
