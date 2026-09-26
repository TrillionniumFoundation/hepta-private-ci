//! Canonical audited product runner.
//!
//! This composition couples the product evaluator to a durable attempt journal
//! and a reconciling evidence sink. A final-holdout transition can therefore
//! never disappear behind an ordinary error return, and an accepted-but-unknown
//! publication can be reconciled without duplicating evidence.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::EvaluationAttemptCasStoreV1;
use crate::EvaluationAttemptErrorV1;
use crate::EvaluationAttemptJournalV1;
use crate::EvaluationAttemptPhaseV1;
use crate::FinalHoldoutCasStoreError;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutProviderV1;
use crate::FencedHoldoutError;
use crate::IdempotentQualificationEvidenceSinkV1;
use crate::ProductEvaluationError;
use crate::ProductEvaluationRunnerV1;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductFrozenEvaluationPlanV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationReceiptV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::ProductTimingEvidenceV1;
use crate::ReconcilingQualificationEvidenceSinkV1;
use crate::SignedEvaluationEvidenceV1;
use crate::TemporalEvaluationPlan;

pub struct AuditedProductEvaluationRunnerV1<H, A> {
    product: ProductEvaluationRunnerV1<H>,
    attempts: EvaluationAttemptJournalV1<A>,
}

impl<H, A> AuditedProductEvaluationRunnerV1<H, A>
where
    H: FinalHoldoutCasStoreV1,
    A: EvaluationAttemptCasStoreV1,
{
    #[must_use]
    pub const fn new(
        product: ProductEvaluationRunnerV1<H>,
        attempts: EvaluationAttemptJournalV1<A>,
    ) -> Self {
        Self { product, attempts }
    }

    pub fn evaluate_temporal_comparison<P: FinalHoldoutProviderV1>(
        &mut self,
        attempt_id: StableId,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
    ) -> Result<ProductTemporalEvaluationReceiptV1, AuditedProductEvaluationErrorV1> {
        let plan_digest = product_plan.frozen_plan.plan_digest;
        let holdout_before = self.product.holdout_state_digest();
        self.attempts
            .begin(attempt_id.clone(), plan_digest, holdout_before)?;

        match self.product.evaluate_temporal_comparison(
            product_plan,
            candidate_plan,
            baseline_plan,
            provider,
        ) {
            Ok(receipt) => {
                let holdout_after = self.product.holdout_state_digest();
                self.attempts.transition(
                    attempt_id,
                    plan_digest,
                    EvaluationAttemptPhaseV1::TemporalEvaluated,
                    holdout_before,
                    holdout_after,
                    receipt.execution_digest,
                    Digest32::ZERO,
                    Digest32::ZERO,
                )?;
                Ok(receipt)
            }
            Err(error) => {
                let holdout_after = self.product.holdout_state_digest();
                let phase = if holdout_after != holdout_before {
                    EvaluationAttemptPhaseV1::HoldoutConsumedWithoutTerminalReceipt
                } else if holdout_commit_unknown(&error) {
                    EvaluationAttemptPhaseV1::HoldoutConsumptionIndeterminate
                } else {
                    EvaluationAttemptPhaseV1::RejectedBeforeHoldout
                };
                self.attempts.transition(
                    attempt_id,
                    plan_digest,
                    phase,
                    holdout_before,
                    holdout_after,
                    Digest32::ZERO,
                    Digest32::ZERO,
                    product_error_digest(&error),
                )?;
                Err(AuditedProductEvaluationErrorV1::Product(error))
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist<S: IdempotentQualificationEvidenceSinkV1>(
        &mut self,
        attempt_id: StableId,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        sink: &mut S,
    ) -> Result<ProductQualificationReceiptV1, AuditedProductEvaluationErrorV1> {
        let latest = self
            .attempts
            .latest(&attempt_id)
            .cloned()
            .ok_or(EvaluationAttemptErrorV1::Missing)?;
        if latest.plan_digest != temporal.product_plan.frozen_plan.plan_digest
            || latest.execution_digest != temporal.execution_digest
            || latest.holdout_after != self.product.holdout_state_digest()
            || !matches!(
                latest.phase,
                EvaluationAttemptPhaseV1::TemporalEvaluated
                    | EvaluationAttemptPhaseV1::PublicationIndeterminate
            )
        {
            return Err(EvaluationAttemptErrorV1::RetryForbidden.into());
        }

        let mut reconciling = ReconcilingQualificationEvidenceSinkV1::new(sink);
        match self.product.qualify_and_persist(
            temporal,
            context,
            evidence,
            timing,
            verifier,
            now,
            &mut reconciling,
        ) {
            Ok(receipt) => {
                self.attempts.transition(
                    attempt_id,
                    latest.plan_digest,
                    EvaluationAttemptPhaseV1::Published,
                    latest.holdout_before,
                    latest.holdout_after,
                    temporal.execution_digest,
                    receipt.publication_digest,
                    Digest32::ZERO,
                )?;
                Ok(receipt)
            }
            Err(error) => {
                let is_indeterminate = matches!(
                    error,
                    ProductEvaluationError::Sink(ProductEvidenceSinkErrorV1::Indeterminate)
                );
                if latest.phase == EvaluationAttemptPhaseV1::TemporalEvaluated {
                    self.attempts.transition(
                        attempt_id,
                        latest.plan_digest,
                        if is_indeterminate {
                            EvaluationAttemptPhaseV1::PublicationIndeterminate
                        } else {
                            EvaluationAttemptPhaseV1::QualificationRejected
                        },
                        latest.holdout_before,
                        latest.holdout_after,
                        temporal.execution_digest,
                        Digest32::ZERO,
                        product_error_digest(&error),
                    )?;
                }
                Err(AuditedProductEvaluationErrorV1::Product(error))
            }
        }
    }

    #[must_use]
    pub fn product(&self) -> &ProductEvaluationRunnerV1<H> {
        &self.product
    }

    #[must_use]
    pub fn attempts(&self) -> &EvaluationAttemptJournalV1<A> {
        &self.attempts
    }

    #[must_use]
    pub fn attempts_mut(&mut self) -> &mut EvaluationAttemptJournalV1<A> {
        &mut self.attempts
    }

    #[must_use]
    pub fn into_parts(self) -> (ProductEvaluationRunnerV1<H>, EvaluationAttemptJournalV1<A>) {
        (self.product, self.attempts)
    }
}

fn holdout_commit_unknown(error: &ProductEvaluationError) -> bool {
    matches!(
        error,
        ProductEvaluationError::Holdout(
            FencedHoldoutError::Poisoned
                | FencedHoldoutError::Store(
                    FinalHoldoutCasStoreError::Conflict
                        | FinalHoldoutCasStoreError::Indeterminate
                )
        )
    )
}

fn product_error_digest(error: &ProductEvaluationError) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.product-error.v1\0".to_vec();
    bytes.extend_from_slice(format!("{error:?}").as_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Debug)]
pub enum AuditedProductEvaluationErrorV1 {
    Product(ProductEvaluationError),
    Attempt(EvaluationAttemptErrorV1),
}

impl fmt::Display for AuditedProductEvaluationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for AuditedProductEvaluationErrorV1 {}

impl From<ProductEvaluationError> for AuditedProductEvaluationErrorV1 {
    fn from(value: ProductEvaluationError) -> Self {
        Self::Product(value)
    }
}

impl From<EvaluationAttemptErrorV1> for AuditedProductEvaluationErrorV1 {
    fn from(value: EvaluationAttemptErrorV1) -> Self {
        Self::Attempt(value)
    }
}
