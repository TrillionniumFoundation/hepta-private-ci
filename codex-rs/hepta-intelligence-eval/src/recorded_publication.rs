//! Write-ahead publication bookkeeping. This adapter never retries publication.
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ProductEvaluationAttemptJournalErrorV1;
use crate::ProductEvaluationAttemptJournalV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;

#[path = "qualification_archive.rs"]
pub(crate) mod archive;
#[path = "outcome_qualification_artifacts.rs"]
mod outcome_qualification_artifacts;
#[path = "qualification_artifacts.rs"]
mod qualification_artifacts;
#[path = "attempt_publication_resume.rs"]
mod resume;
#[path = "selected_host_publication.rs"]
mod selected_host_publication;
#[path = "selected_host_recovery_controller.rs"]
mod selected_host_recovery_controller;

pub(crate) struct RecordedPublicationSinkV1<'a, J> {
    pub(crate) attempt_id: StableId,
    pub(crate) plan_digest: Digest32,
    pub(crate) holdout_record_digest: Digest32,
    pub(crate) journal: &'a mut J,
    pub(crate) inner: &'a mut dyn ProductQualificationEvidenceSinkV1,
    pub(crate) journal_error: Option<ProductEvaluationAttemptJournalErrorV1>,
}

impl<J: ProductEvaluationAttemptJournalV1> RecordedPublicationSinkV1<'_, J> {
    fn record(
        &mut self,
        phase: ProductEvaluationAttemptPhaseV1,
        payload: Digest32,
    ) -> Result<(), ProductEvidenceSinkErrorV1> {
        let result = self.journal.append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: self.attempt_id.clone(),
            plan_digest: self.plan_digest,
            phase,
            holdout_record_digest: self.holdout_record_digest,
            terminal_digest: payload,
        });
        if let Err(error) = result {
            self.journal_error = Some(error);
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        Ok(())
    }
}

impl<J: ProductEvaluationAttemptJournalV1> ProductQualificationEvidenceSinkV1
    for RecordedPublicationSinkV1<'_, J>
{
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let request =
            crate::ProductQualificationPublicationRequestV1::new(execution_digest, decision)?;
        self.record(
            ProductEvaluationAttemptPhaseV1::QualificationDecided,
            request.request_digest,
        )?;
        self.record(
            ProductEvaluationAttemptPhaseV1::PublicationPending,
            request.request_digest,
        )?;
        let publication = self.inner.persist(execution_digest, decision)?;
        if publication.is_zero() {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        self.record(ProductEvaluationAttemptPhaseV1::Published, publication)?;
        Ok(publication)
    }
}

#[cfg(test)]
#[path = "recorded_publication_tests.rs"]
mod tests;
