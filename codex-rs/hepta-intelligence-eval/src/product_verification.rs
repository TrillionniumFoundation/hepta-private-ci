//! Public consumption boundary for an already frozen, independently signed
//! evaluation. Qualification creation and persistence remain owned by
//! `ProductEvaluationRunnerV1`; this verifier consumes no holdout and grants no
//! authority.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;

use crate::IndependentEvaluationBundleV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;

/// Verify prepared product evidence without exporting the low-level evaluator
/// implementation across crate boundaries.
pub fn decide_with_signed_evidence_v2(
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedEvaluationDecisionV1, SignedEvaluationError> {
    crate::signed_evaluation::decide_with_signed_evidence_v2(
        bundle, roles, evidence, verifier, now,
    )
}
