//! Default production surface for the strict registered paired profile.
//! The existing fenced owner remains the sole holdout authority; this facade
//! exposes no unregistered temporal execution or caller-supplied clock.

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_types::Digest32;

use crate::AuthenticatedPairedRegistrationV1;
use crate::FencedFinalHoldoutOwnerV1;
use crate::FinalHoldoutCasAnchorV1;
use crate::FinalHoldoutCasStoreV1;
use crate::IndependentEvaluationBundleV1;
use crate::PairedFinalHoldoutProviderV1;
use crate::PairedSupervisedErrorV1;
use crate::ProductPairedEvaluationReceiptV1;
use crate::ProductPairedQualificationReceiptV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationEvidenceV1;
use crate::product_runner::ProductEvaluationRunnerV1;

/// A bounded facade over the original fenced custody owner. Original G/O
/// registration and current activated trust are checked before provider/CAS
/// effects; independent E evidence is checked again before publication.
pub struct RegisteredPairedEvaluationRunnerV1<S> {
    runner: ProductEvaluationRunnerV1<S>,
}

impl<S: FinalHoldoutCasStoreV1> RegisteredPairedEvaluationRunnerV1<S> {
    #[must_use]
    pub fn new(holdout: FencedFinalHoldoutOwnerV1<S>) -> Self {
        Self {
            runner: ProductEvaluationRunnerV1::new(holdout),
        }
    }

    #[must_use]
    pub fn holdout_state_digest(&self) -> Digest32 {
        self.runner.holdout_state_digest()
    }

    #[must_use]
    pub fn holdout_anchor(&self) -> FinalHoldoutCasAnchorV1 {
        self.runner.holdout_anchor()
    }

    pub fn evaluate_registered_paired_supervised<P: PairedFinalHoldoutProviderV1>(
        &mut self,
        registration: &AuthenticatedPairedRegistrationV1,
        provider: &mut P,
        trust: &ActivatedLearningTrustV1,
    ) -> Result<ProductPairedEvaluationReceiptV1, PairedSupervisedErrorV1> {
        self.runner
            .evaluate_registered_paired_supervised(registration, provider, trust)
    }

    pub fn paired_qualification_bundle(
        &self,
        execution: &ProductPairedEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
    ) -> Result<IndependentEvaluationBundleV1, PairedSupervisedErrorV1> {
        self.runner.paired_qualification_bundle(execution, context)
    }

    pub fn qualify_paired_and_persist<E: ProductQualificationEvidenceSinkV1>(
        &self,
        execution: &ProductPairedEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        trust: &ActivatedLearningTrustV1,
        sink: &mut E,
    ) -> Result<ProductPairedQualificationReceiptV1, PairedSupervisedErrorV1> {
        self.runner
            .qualify_paired_and_persist(execution, context, evidence, trust, sink)
    }
}
