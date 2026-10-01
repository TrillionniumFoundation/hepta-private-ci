//! Consumption of a product qualification reauthenticates the exact sealed
//! request against current host trust. Caller-supplied metrics never issue
//! eligibility here: only the fenced, durably published runner receipt does.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use crate::EvaluationClaimScopeV1;
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationError;
use crate::ProductQualificationReceiptV1;
use crate::ProductTimingEvidenceV1;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationEvidenceV1;
use crate::authenticate_evaluation_evidence_v2;

impl ProductQualificationReceiptV1 {
    /// Revalidate a sealed, published qualification at its actual consumption
    /// time. Expired/revoked/rotated trust and substituted request data fail
    /// before any consumer may use the original qualification disposition.
    #[allow(clippy::too_many_arguments)]
    pub fn revalidate_consumption(
        &self,
        bundle: &IndependentEvaluationBundleV1,
        roles: &[MetricRoleContractV2],
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<&SignedEvaluationDecisionV1, ProductEvaluationError> {
        self.validate_integrity()?;
        if self.candidate_id != bundle.candidate_id
            || self.decision.decision.baseline_id != bundle.baseline_id
            || self.decision.decision.evaluation_id != bundle.evaluation_id
            || self.generator != bundle.generator
            || self.evaluator != bundle.evaluator
            || self.objective_digest != bundle.objective_digest
            || self.dataset_digest != bundle.dataset_digest
            || self.snapshot_ids != bundle.snapshot_ids
            || self.claim_scope != bundle.claim_scope
        {
            return Err(ProductEvaluationError::Binding("qualification consumption"));
        }
        let authentication = match timing {
            ProductTimingEvidenceV1::Qualification => {
                if self.claim_scope != EvaluationClaimScopeV1::Qualification {
                    return Err(ProductEvaluationError::Binding("qualification scope"));
                }
                authenticate_evaluation_evidence_v2(bundle, roles, evidence, verifier, now)?
            }
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => {
                if self.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
                    return Err(ProductEvaluationError::Binding("longitudinal scope"));
                }
                crate::longitudinal_time::authenticate_longitudinal_evidence_v3(
                    bundle,
                    roles,
                    evidence,
                    timing,
                    minimum_window_micros,
                    verifier,
                    now,
                )?
            }
        };
        if authentication.trust_digest() != self.decision.trust_digest
            || authentication.authentication_digest() != self.decision.authentication_digest
        {
            return Err(ProductEvaluationError::Binding(
                "qualification authentication",
            ));
        }
        Ok(&self.decision)
    }
}
