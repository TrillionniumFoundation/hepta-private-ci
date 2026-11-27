//! Current-use verification of a sealed, already published qualification.
//!
//! This boundary never consumes a holdout or publishes new evidence. The host
//! retains ownership of the current verifier, clock and longitudinal policy.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use crate::EvaluationClaimScopeV1;
use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationError;
use crate::ProductQualificationReceiptV1;
use crate::ProductTimingEvidenceV1;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationEvidenceV1;
use crate::decide_with_signed_evidence_v2;
use crate::decide_with_signed_longitudinal_evidence_v3;

/// Revalidate the exact signed evidence behind an already published product
/// qualification under the current host trust and time. Consumers must retain
/// the receipt's evidence and publication digests in their own use commitments.
/// Eligibility and any later selection or effect authority remain separate.
#[allow(clippy::too_many_arguments)]
pub fn revalidate_product_qualification_v1(
    qualification: &ProductQualificationReceiptV1,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    timing: ProductTimingEvidenceV1<'_>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedEvaluationDecisionV1, ProductEvaluationError> {
    qualification.validate_integrity()?;
    let mut snapshot_ids = bundle.snapshot_ids.clone();
    snapshot_ids.sort_unstable();
    if qualification.candidate_id != bundle.candidate_id
        || qualification.generator != bundle.generator
        || qualification.evaluator != bundle.evaluator
        || qualification.objective_digest != bundle.objective_digest
        || qualification.dataset_digest != bundle.dataset_digest
        || qualification.claim_scope != bundle.claim_scope
        || qualification.snapshot_ids != snapshot_ids
    {
        return Err(ProductEvaluationError::Binding("qualification use context"));
    }
    let decision = match timing {
        ProductTimingEvidenceV1::Qualification => {
            if bundle.claim_scope != EvaluationClaimScopeV1::Qualification {
                return Err(ProductEvaluationError::Binding("qualification scope"));
            }
            decide_with_signed_evidence_v2(bundle, roles, evidence, verifier, now)?
        }
        ProductTimingEvidenceV1::SystemLongitudinal {
            timing,
            minimum_window_micros,
        } => {
            if bundle.claim_scope != EvaluationClaimScopeV1::SystemLongitudinal {
                return Err(ProductEvaluationError::Binding("longitudinal scope"));
            }
            decide_with_signed_longitudinal_evidence_v3(
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
    // The decision digest commits the complete bundle. Authentication commits
    // the exact signing bytes and signatures (including roles and V3 timing)
    // under the current verifier. Equal dispositions alone are insufficient.
    if decision != qualification.decision {
        return Err(ProductEvaluationError::Binding(
            "qualification use evidence",
        ));
    }
    Ok(decision)
}
