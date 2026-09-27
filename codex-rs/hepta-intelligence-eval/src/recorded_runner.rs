//! Public product runner with mandatory durable attempt recording.
//!
//! The lower-level composition remains compatibility-only. This facade records
//! irreversible final-holdout consumption before forwarding released data, and
//! records exactly one sealed or failed terminal state before returning.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::FencedFinalHoldoutOwnerV1;
use crate::FinalHoldoutCasAnchorV1;
use crate::FinalHoldoutCasStoreV1;
use crate::FinalHoldoutJournalReceiptV1;
use crate::FinalHoldoutProviderV1;
use crate::ProductEvaluationAttemptJournalErrorV1;
use crate::ProductEvaluationAttemptJournalV1;
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

pub struct RecordedProductEvaluationRunnerV1<S> {
    inner: ProductEvaluationRunnerV1<S>,
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    #[must_use]
    pub fn new(holdout: FencedFinalHoldoutOwnerV1<S>) -> Self {
        Self {
            inner: ProductEvaluationRunnerV1::new(holdout),
        }
    }

    #[must_use]
    pub fn holdout_state_digest(&self) -> Digest32 {
        self.inner.holdout_state_digest()
    }

    #[must_use]
    pub fn holdout_anchor(&self) -> FinalHoldoutCasAnchorV1 {
        self.inner.holdout_anchor()
    }

    pub fn evaluate_temporal_comparison<
        P: FinalHoldoutProviderV1,
        J: ProductEvaluationAttemptJournalV1,
    >(
        &mut self,
        attempt_id: StableId,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
        journal: &mut J,
    ) -> Result<ProductTemporalEvaluationReceiptV1, RecordedProductEvaluationErrorV1> {
        let plan_digest = product_plan.frozen_plan.plan_digest;
        let mut recorded_provider = RecordedHoldoutProviderV1 {
            attempt_id: attempt_id.clone(),
            plan_digest,
            inner: provider,
            journal,
            consumed_record_digest: None,
            journal_error: None,
        };
        let result = self.inner.evaluate_temporal_comparison(
            product_plan,
            candidate_plan,
            baseline_plan,
            &mut recorded_provider,
        );
        let consumed = recorded_provider.consumed_record_digest;
        let journal_error = recorded_provider.journal_error;
        drop(recorded_provider);

        if let Some(journal_error) = journal_error {
            let holdout_record_digest = consumed.ok_or(
                RecordedProductEvaluationErrorV1::Invariant(
                    "attempt journal failed without an observed holdout receipt",
                ),
            )?;
            return match result {
                Err(evaluation) => Err(
                    RecordedProductEvaluationErrorV1::HoldoutConsumedButJournalFailed {
                        attempt_id,
                        plan_digest,
                        holdout_record_digest,
                        evaluation,
                        journal: journal_error,
                    },
                ),
                Ok(_) => Err(RecordedProductEvaluationErrorV1::Invariant(
                    "attempt journal failure did not abort holdout release",
                )),
            };
        }

        match result {
            Ok(receipt) => {
                let holdout_record_digest = consumed.ok_or(
                    RecordedProductEvaluationErrorV1::Invariant(
                        "successful evaluation without recorded holdout consumption",
                    ),
                )?;
                journal.append(
                    ProductEvaluationAttemptTransitionV1::comparison_sealed(
                        attempt_id,
                        plan_digest,
                        holdout_record_digest,
                        receipt.execution_digest,
                    ),
                )?;
                Ok(receipt)
            }
            Err(error) => {
                if let Some(holdout_record_digest) = consumed {
                    let failure_digest = evaluation_failure_digest(&error);
                    if let Err(journal_error) = journal.append(
                        ProductEvaluationAttemptTransitionV1::failed(
                            attempt_id,
                            plan_digest,
                            holdout_record_digest,
                            failure_digest,
                        ),
                    ) {
                        return Err(RecordedProductEvaluationErrorV1::EvaluationAndJournal {
                            evaluation: error,
                            journal: journal_error,
                        });
                    }
                }
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

    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist(
        &self,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductQualificationReceiptV1, ProductEvaluationError> {
        self.inner.qualify_and_persist(
            temporal,
            context,
            evidence,
            timing,
            verifier,
            now,
            sink,
        )
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
        // The authoritative owner has already consumed the holdout before this
        // callback. Preserve that irreversible fact even when the attempt journal
        // write is rejected or its commit status is unknown.
        self.consumed_record_digest = Some(receipt.record_digest);
        if let Err(error) = self.journal.append(
            ProductEvaluationAttemptTransitionV1::holdout_consumed(
                self.attempt_id.clone(),
                self.plan_digest,
                receipt.record_digest,
            ),
        ) {
            self.journal_error = Some(error);
            return Err(map_journal_to_provider(error));
        }
        self.inner.release_after_consumption(receipt)
    }
}

fn map_journal_to_provider(
    error: ProductEvaluationAttemptJournalErrorV1,
) -> ProductProviderErrorV1 {
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
        ProductEvaluationAttemptJournalErrorV1::Indeterminate => {
            ProductProviderErrorV1::Indeterminate
        }
    }
}

fn evaluation_failure_digest(error: &ProductEvaluationError) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.product-evaluation-failure.v1".to_vec();
    bytes.extend_from_slice(format!("{error:?}").as_bytes());
    Digest32::of_bytes(&bytes)
}

#[derive(Debug)]
pub enum RecordedProductEvaluationErrorV1 {
    Evaluation(ProductEvaluationError),
    Journal(ProductEvaluationAttemptJournalErrorV1),
    /// The final holdout is irreversibly consumed, but the lifecycle journal did
    /// not return a durable acknowledgement. Reopen/reconcile the journal using
    /// the included attempt and digest coordinates before any operator action.
    HoldoutConsumedButJournalFailed {
        attempt_id: StableId,
        plan_digest: Digest32,
        holdout_record_digest: Digest32,
        evaluation: ProductEvaluationError,
        journal: ProductEvaluationAttemptJournalErrorV1,
    },
    EvaluationAndJournal {
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
mod tests {
    use super::*;
    use codex_hepta_types::FixedQ32;

    use crate::CrossFoldPartitionV1;
    use crate::CrossFoldPlanV1;
    use crate::EvaluationClaimScopeV1;
    use crate::EvaluationDirectionV1;
    use crate::FinalHoldoutJournalV1;
    use crate::MetricContractV1;
    use crate::ProductEvaluationAttemptReceiptV1;
    use crate::freeze_cross_fold_plan;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn frozen_plan() -> crate::CrossFoldPlanReceiptV1 {
        freeze_cross_fold_plan(CrossFoldPlanV1 {
            plan_id: id("recorded-runner-plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            objective_digest: digest("objective"),
            dataset_digest: digest("dataset"),
            estimand_digest: digest("estimand"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::ZERO),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: vec![
                CrossFoldPartitionV1 {
                    fold_id: id("fold-a"),
                    training_principals: vec![id("train-principal-a")],
                    training_episodes: vec![id("train-episode-a")],
                    training_windows: vec![id("train-window-a")],
                    holdout_principals: vec![id("holdout-principal-a")],
                    holdout_episodes: vec![id("holdout-episode-a")],
                    holdout_windows: vec![id("holdout-window-a")],
                    model_digest: digest("model-a"),
                    predictions_digest: digest("predictions-a"),
                },
                CrossFoldPartitionV1 {
                    fold_id: id("fold-b"),
                    training_principals: vec![id("train-principal-b")],
                    training_episodes: vec![id("train-episode-b")],
                    training_windows: vec![id("train-window-b")],
                    holdout_principals: vec![id("holdout-principal-b")],
                    holdout_episodes: vec![id("holdout-episode-b")],
                    holdout_windows: vec![id("final-window")],
                    model_digest: digest("model-b"),
                    predictions_digest: digest("predictions-b"),
                },
            ],
            final_holdout_window_id: id("final-window"),
            final_holdout_digest: digest("final-holdout"),
        })
        .expect("freeze test plan")
    }

    struct NeverReleaseProvider {
        release_calls: usize,
    }

    impl FinalHoldoutProviderV1 for NeverReleaseProvider {
        fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
            Ok(digest("final-holdout"))
        }

        fn release_after_consumption(
            &mut self,
            _receipt: &FinalHoldoutJournalReceiptV1,
        ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
            self.release_calls += 1;
            panic!("provider release must be blocked when attempt journaling fails")
        }
    }

    struct IndeterminateJournal;

    impl ProductEvaluationAttemptJournalV1 for IndeterminateJournal {
        fn append(
            &mut self,
            _transition: ProductEvaluationAttemptTransitionV1,
        ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1>
        {
            Err(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
        }

        fn latest(
            &mut self,
            _attempt_id: &StableId,
        ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
        {
            Ok(None)
        }
    }

    #[test]
    fn journal_failure_preserves_consumed_holdout_and_blocks_release() {
        let plan = frozen_plan();
        let mut holdout = FinalHoldoutJournalV1::new();
        let receipt = holdout
            .consume(holdout.head_digest(), &plan)
            .expect("consume holdout");
        let mut provider = NeverReleaseProvider { release_calls: 0 };
        let mut journal = IndeterminateJournal;

        {
            let mut recorded = RecordedHoldoutProviderV1 {
                attempt_id: id("attempt-1"),
                plan_digest: plan.plan_digest,
                inner: &mut provider,
                journal: &mut journal,
                consumed_record_digest: None,
                journal_error: None,
            };
            assert!(matches!(
                recorded.release_after_consumption(&receipt),
                Err(ProductProviderErrorV1::Indeterminate)
            ));
            assert_eq!(
                recorded.consumed_record_digest,
                Some(receipt.record_digest)
            );
            assert_eq!(
                recorded.journal_error,
                Some(ProductEvaluationAttemptJournalErrorV1::Indeterminate)
            );
        }
        assert_eq!(provider.release_calls, 0);
    }
}
