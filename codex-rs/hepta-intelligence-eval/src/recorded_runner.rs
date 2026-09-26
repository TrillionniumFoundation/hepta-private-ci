//! Public product runner with mandatory durable attempt recording.
//!
//! The lower-level composition remains crate-private. This facade records the
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
        };
        let result = self.inner.evaluate_temporal_comparison(
            product_plan,
            candidate_plan,
            baseline_plan,
            &mut recorded_provider,
        );
        let consumed = recorded_provider.consumed_record_digest;
        drop(recorded_provider);

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
        self.journal
            .append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
                self.attempt_id.clone(),
                self.plan_digest,
                receipt.record_digest,
            ))
            .map_err(map_journal_to_provider)?;
        self.consumed_record_digest = Some(receipt.record_digest);
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
