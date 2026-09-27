//! Resume the one publication boundary known not to have been invoked.
//!
//! QualificationDecided is durable before PublicationPending; the underlying
//! sink is invoked only after Pending is acknowledged. A Pending attempt may
//! therefore have an unknown write and is never passed back to the sink here.

use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FinalHoldoutCasStoreV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductEvaluationError;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationDecisionV1;
use crate::attempt_recovery::validated_history;
use crate::recorded_publication::RecordedPublicationSinkV1;

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    /// Publish the first time after a crash at QualificationDecided. The complete
    /// original decision must come from the host's immutable evidence archive.
    /// Its canonical request must match the durable preregistration exactly.
    /// This returns only an authority-free attempt receipt, not a newly minted
    /// qualification/selection token. Pending/Published and altered decisions
    /// are rejected before any sink call.
    pub fn resume_decided_publication<J: DurableProductEvaluationAttemptJournalV1>(
        journal: &mut J,
        attempt_id: &StableId,
        decision: &SignedEvaluationDecisionV1,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let rejected = || RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
            attempt_id: attempt_id.clone(),
        };
        let history = validated_history(journal, attempt_id).map_err(|error| match error {
            crate::ProductAttemptRecoveryErrorV1::Journal(error) => {
                RecordedProductEvaluationErrorV1::Journal(error)
            }
            _ => rejected(),
        })?;
        let latest = history.last().ok_or_else(rejected)?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::QualificationDecided {
            return Err(rejected());
        }
        let sealed = history
            .iter()
            .find(|receipt| {
                receipt.transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed
            })
            .ok_or_else(rejected)?;
        let execution = sealed.transition.terminal_digest;
        let request = ProductQualificationPublicationRequestV1::new(execution, decision)
            .map_err(|error| {
                RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(error))
            })?;
        if request.request_digest != latest.transition.terminal_digest {
            return Err(rejected());
        }
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: latest.transition.plan_digest,
            holdout_record_digest: latest.transition.holdout_record_digest,
            journal,
            inner: sink,
            journal_error: None,
        };
        let result = recorded.persist(execution, decision);
        if let Some(error) = recorded.journal_error {
            return Err(RecordedProductEvaluationErrorV1::Journal(error));
        }
        result.map_err(|error| {
            RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(error))
        })?;
        let receipt = recorded.journal.latest(attempt_id)?.ok_or_else(rejected)?;
        if receipt.transition.phase != ProductEvaluationAttemptPhaseV1::Published {
            return Err(rejected());
        }
        receipt.validate_integrity()?;
        Ok(receipt)
    }
}
