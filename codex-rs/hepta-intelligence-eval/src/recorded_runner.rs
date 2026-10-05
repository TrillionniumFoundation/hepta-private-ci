//! Product runner with write-ahead attempt identity and publication bookkeeping.
//!
//! A durable intent precedes all provider/holdout calls. An existing attempt is
//! never automatically re-executed; recovery reads existing owner records. The
//! provider also rejects a holdout replay even if a caller replaces its journal.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FencedFinalHoldoutOwnerV1;
use crate::FencedHoldoutError;
use crate::FinalHoldoutCasAnchorV1;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::FinalHoldoutProviderV1;
use crate::HoldoutUseDispositionV1;
use crate::ProductEvaluationAttemptJournalErrorV1;
use crate::ProductEvaluationAttemptJournalV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductEvaluationError;
use crate::ProductEvaluationRunnerV1;
use crate::ProductFrozenEvaluationPlanV1;
use crate::ProductProviderErrorV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductQualificationReceiptV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::ProductTimingEvidenceV1;
use crate::SignedEvaluationEvidenceV1;
use crate::TemporalComparisonInputsV1;
use crate::TemporalEvaluationPlan;
use crate::recorded_publication::RecordedPublicationSinkV1;

#[path = "recorded_failure.rs"]
mod failure;
#[path = "outcome_runner.rs"]
mod outcomes;

pub struct RecordedProductEvaluationRunnerV1<S> {
    pub(crate) inner: ProductEvaluationRunnerV1<S>,
    pub(crate) namespace: Digest32,
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    #[must_use]
    pub fn new(holdout: FencedFinalHoldoutOwnerV1<S>) -> Self {
        let namespace = holdout.binding();
        Self { inner: ProductEvaluationRunnerV1::new(holdout), namespace }
    }

    #[must_use]
    pub fn holdout_state_digest(&self) -> Digest32 {
        self.inner.holdout_state_digest()
    }

    #[must_use]
    pub fn holdout_anchor(&self) -> FinalHoldoutCasAnchorV1 {
        self.inner.holdout_anchor()
    }

    pub fn evaluate_temporal_comparison<P, J>(
        &mut self,
        attempt_id: StableId,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
        journal: &mut J,
    ) -> Result<ProductTemporalEvaluationReceiptV1, RecordedProductEvaluationErrorV1>
    where
        P: FinalHoldoutProviderV1,
        J: DurableProductEvaluationAttemptJournalV1,
    {
        self.evaluate_recorded(attempt_id, product_plan, candidate_plan, baseline_plan,
            provider, journal, |receipt, _| {
                let execution_digest = receipt.execution_digest;
                Ok((receipt, execution_digest))
            })
    }

    // The finish callback is private. Multi-outcome composition must finish
    // before ComparisonSealed is appended; the one-stream carrier never escapes
    // as an externally qualifiable substitute for the measured channel result.
    #[allow(clippy::too_many_arguments)]
    fn evaluate_recorded<P, J, T, F>(
        &mut self,
        attempt_id: StableId,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
        journal: &mut J,
        finish: F,
    ) -> Result<T, RecordedProductEvaluationErrorV1>
    where
        P: FinalHoldoutProviderV1,
        J: DurableProductEvaluationAttemptJournalV1,
        F: FnOnce(ProductTemporalEvaluationReceiptV1, &mut P)
            -> Result<(T, Digest32), ProductEvaluationError>,
    {
        let plan_digest = product_plan.frozen_plan.plan_digest;
        if journal.latest(&attempt_id)?.is_some() {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { attempt_id });
        }
        let before = self.inner.holdout_state_digest();
        journal.append(ProductEvaluationAttemptTransitionV1::intent(
            attempt_id.clone(), plan_digest, self.namespace, before,
        ))?;
        let (result, consumed, journal_error) = {
            let mut recorded_provider = RecordedHoldoutProviderV1 {
                attempt_id: attempt_id.clone(), plan_digest, inner: provider, journal,
                consumed_record_digest: None, journal_error: None,
            };
            let result = self.inner.evaluate_temporal_comparison(
                product_plan, candidate_plan, baseline_plan, &mut recorded_provider,
            );
            (result, recorded_provider.consumed_record_digest, recorded_provider.journal_error)
        };
        if let Some(journal_error) = journal_error {
            let holdout_record_digest = consumed.ok_or(RecordedProductEvaluationErrorV1::Invariant(
                "attempt journal failed without an observed holdout receipt",
            ))?;
            return match result {
                Err(evaluation) => Err(RecordedProductEvaluationErrorV1::HoldoutConsumedButJournalFailed {
                    attempt_id, plan_digest, holdout_record_digest, evaluation, journal: journal_error,
                }),
                Ok(_) => Err(RecordedProductEvaluationErrorV1::Invariant(
                    "attempt journal failure did not abort holdout release",
                )),
            };
        }
        let result = result.and_then(|receipt| finish(receipt, provider));
        match result {
            Ok((receipt, execution_digest)) => {
                let holdout_record_digest = consumed.ok_or(RecordedProductEvaluationErrorV1::Invariant(
                    "successful evaluation without recorded holdout consumption",
                ))?;
                journal.append(ProductEvaluationAttemptTransitionV1::comparison_sealed(
                    attempt_id.clone(), plan_digest, holdout_record_digest, execution_digest,
                )).map_err(|journal| RecordedProductEvaluationErrorV1::ComparisonSealedButJournalFailed {
                    attempt_id, plan_digest, holdout_record_digest, execution_digest, journal,
                })?;
                Ok(receipt)
            }
            Err(error) => {
                let failure_digest = evaluation_failure_digest(&error);
                if let Some(holdout_record_digest) = consumed {
                    if let Err(journal) = journal.append(ProductEvaluationAttemptTransitionV1::failed(
                        attempt_id.clone(), plan_digest, holdout_record_digest, failure_digest,
                    )) {
                        return Err(RecordedProductEvaluationErrorV1::EvaluationFailedButJournalFailed {
                            attempt_id, plan_digest, holdout_record_digest, failure_digest,
                            evaluation: error, journal,
                        });
                    }
                } else if self.inner.holdout_state_digest() == before
                    && !matches!(&error, ProductEvaluationError::Holdout(
                        FencedHoldoutError::Indeterminate | FencedHoldoutError::Poisoned
                        | FencedHoldoutError::Conflict | FencedHoldoutError::Store(_)
                    ))
                {
                    journal.append(ProductEvaluationAttemptTransitionV1 {
                        attempt_id, plan_digest,
                        phase: ProductEvaluationAttemptPhaseV1::RejectedBeforeHoldout,
                        holdout_record_digest: self.namespace,
                        terminal_digest: failure_digest,
                    })?;
                }
                // Unknown owner commits retain their discoverable intent.
                Err(RecordedProductEvaluationErrorV1::Evaluation(error))
            }
        }
    }

    pub fn qualification_bundle(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
    ) -> Result<crate::IndependentEvaluationBundleV1, ProductEvaluationError> {
        self.inner.qualification_bundle(temporal, context)
    }

    // The unarchived qualification boundary is an internal composition helper.
    // Cross-crate product callers must use the typed-archive or selected-host
    // methods, which persist exact recovery objects before QualificationDecided.
    #[allow(dead_code, clippy::too_many_arguments)]
    pub(crate) fn qualify_and_persist<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        attempt_id: &StableId,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        journal: &mut J,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let latest = journal.latest(attempt_id)?.ok_or(
            RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { attempt_id: attempt_id.clone() },
        )?;
        latest.validate_integrity()?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::ComparisonSealed
            || latest.transition.plan_digest != temporal.product_plan.frozen_plan.plan_digest
            || latest.transition.holdout_record_digest != temporal.holdout.record_digest
            || latest.transition.terminal_digest != temporal.execution_digest
        {
            return Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { attempt_id: attempt_id.clone() });
        }
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: latest.transition.plan_digest,
            holdout_record_digest: latest.transition.holdout_record_digest,
            journal, inner: sink, journal_error: None,
        };
        let result = self.inner.qualify_and_persist(
            temporal, context, evidence, timing, verifier, now, &mut recorded,
        );
        if let Some(error) = recorded.journal_error {
            return Err(RecordedProductEvaluationErrorV1::Journal(error));
        }
        result.map_err(RecordedProductEvaluationErrorV1::Evaluation)
    }
}

struct RecordedHoldoutProviderV1<'a, P, J> {
    attempt_id: StableId,
    plan_digest: Digest32,
    inner: &'a mut P,
    journal: &'a mut J,
    consumed_record_digest: Option<Digest32>,
    journal_error: Option<ProductEvaluationAttemptJournalErrorV1>,
}

impl<P: FinalHoldoutProviderV1, J: ProductEvaluationAttemptJournalV1> FinalHoldoutProviderV1
    for RecordedHoldoutProviderV1<'_, P, J>
{
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.inner.manifest_digest()
    }

    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.consumed_record_digest = Some(receipt.record_digest);
        if let Err(error) = self.journal.append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
            self.attempt_id.clone(), self.plan_digest, receipt.record_digest,
        )) {
            self.journal_error = Some(error);
            return Err(map_journal_to_provider(error));
        }
        if receipt.disposition == HoldoutUseDispositionV1::IdempotentReplay {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.inner.release_after_consumption(receipt)
    }
}

fn map_journal_to_provider(error: ProductEvaluationAttemptJournalErrorV1) -> ProductProviderErrorV1 {
    match error {
        ProductEvaluationAttemptJournalErrorV1::Binding
        | ProductEvaluationAttemptJournalErrorV1::NotRegular
        | ProductEvaluationAttemptJournalErrorV1::AlreadyInitialized
        | ProductEvaluationAttemptJournalErrorV1::Corrupt
        | ProductEvaluationAttemptJournalErrorV1::Conflict
        | ProductEvaluationAttemptJournalErrorV1::MissingConsumption
        | ProductEvaluationAttemptJournalErrorV1::Capacity => ProductProviderErrorV1::Rejected,
        ProductEvaluationAttemptJournalErrorV1::Busy
        | ProductEvaluationAttemptJournalErrorV1::Io(_) => ProductProviderErrorV1::Unavailable,
        ProductEvaluationAttemptJournalErrorV1::Indeterminate => ProductProviderErrorV1::Indeterminate,
    }
}

fn evaluation_failure_digest(error: &ProductEvaluationError) -> Digest32 {
    failure::product_evaluation_failure_digest_v2(error)
}

#[derive(Debug)]
pub enum RecordedProductEvaluationErrorV1 {
    Evaluation(ProductEvaluationError),
    Journal(ProductEvaluationAttemptJournalErrorV1),
    AttemptRequiresRecovery { attempt_id: StableId },
    HoldoutConsumedButJournalFailed {
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        evaluation: ProductEvaluationError,
        journal: ProductEvaluationAttemptJournalErrorV1,
    },
    ComparisonSealedButJournalFailed {
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        execution_digest: Digest32,
        journal: ProductEvaluationAttemptJournalErrorV1,
    },
    EvaluationFailedButJournalFailed {
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        failure_digest: Digest32,
        evaluation: ProductEvaluationError,
        journal: ProductEvaluationAttemptJournalErrorV1,
    },
    Invariant(&'static str),
}

impl fmt::Display for RecordedProductEvaluationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for RecordedProductEvaluationErrorV1 {}
impl From<ProductEvaluationAttemptJournalErrorV1> for RecordedProductEvaluationErrorV1 {
    fn from(value: ProductEvaluationAttemptJournalErrorV1) -> Self {
        Self::Journal(value)
    }
}

#[cfg(test)]
#[path = "recorded_runner_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "outcome_tests.rs"]
mod outcome_tests;
