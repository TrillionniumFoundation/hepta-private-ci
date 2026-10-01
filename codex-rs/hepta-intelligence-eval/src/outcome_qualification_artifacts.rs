//! Multi-outcome artifacts reuse the same typed codec, store and verified resume
//! as single-outcome qualification. The two receipt families remain distinct.
use std::path::Path;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FinalHoldoutCasStoreV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductEvaluationError;
use crate::ProductOutcomeEvaluationReceiptV1;
use crate::ProductOutcomeQualificationReceiptV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductTimingEvidenceV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationEvidenceV1;
use crate::recorded_publication::RecordedPublicationSinkV1;
use crate::recorded_publication::archive;

pub(crate) struct PreparedOutcomeQualificationV1<'a> {
    attempt_id: &'a StableId,
    temporal: &'a ProductOutcomeEvaluationReceiptV1,
    context: &'a ProductQualificationContextV1,
    archive: archive::PreparedArchive,
}

impl PreparedOutcomeQualificationV1<'_> {
    pub(crate) fn identity(&self) -> archive::PublicationArchiveIdentityV1 {
        self.archive.identity()
    }
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    #[allow(clippy::too_many_arguments)]
    pub fn qualify_outcomes_and_persist_with_artifacts<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        &self,
        attempt_id: &StableId,
        temporal: &ProductOutcomeEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        artifact_host_binding: Digest32,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductOutcomeQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let prepared = self.prepare_outcome_qualification(
            archive::ArchiveAttemptV1 {
                attempt_id,
                host_binding: artifact_host_binding,
            },
            temporal,
            context,
            evidence,
            timing,
        )?;
        self.qualify_prepared_outcome(
            prepared,
            archive::QualificationPublicationIoV1 {
                journal,
                root: artifact_root.as_ref(),
                verifier,
                now,
                sink,
            },
        )
    }

    pub(crate) fn prepare_outcome_qualification<'a>(
        &self,
        attempt: archive::ArchiveAttemptV1<'a>,
        temporal: &'a ProductOutcomeEvaluationReceiptV1,
        context: &'a ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
    ) -> Result<PreparedOutcomeQualificationV1<'a>, RecordedProductEvaluationErrorV1> {
        let bundle = self
            .outcome_qualification_bundle(temporal, context)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let archive = archive::Archive::new(
            archive::OUTCOME,
            attempt.attempt_id,
            attempt.host_binding,
            self.namespace,
            temporal.execution_digest(),
            temporal.carrier.holdout.record_digest,
            bundle,
            temporal.carrier.product_plan.metric_roles.clone(),
            evidence,
            timing,
        )
        .prepare()?;
        Ok(PreparedOutcomeQualificationV1 {
            attempt_id: attempt.attempt_id,
            temporal,
            context,
            archive,
        })
    }

    pub(crate) fn qualify_prepared_outcome<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        prepared: PreparedOutcomeQualificationV1<'_>,
        io: archive::QualificationPublicationIoV1<'_, J>,
    ) -> Result<ProductOutcomeQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let decision = prepared
            .archive
            .persist(io.journal, io.root, io.verifier, io.now)?;
        let temporal = prepared.temporal;
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: prepared.attempt_id.clone(),
            plan_digest: temporal.carrier.product_plan.frozen_plan.plan_digest,
            holdout_record_digest: temporal.carrier.holdout.record_digest,
            journal: io.journal,
            inner: io.sink,
            journal_error: None,
        };
        let result = recorded.persist(temporal.execution_digest(), &decision);
        if let Some(error) = recorded.journal_error {
            return Err(RecordedProductEvaluationErrorV1::Journal(error));
        }
        let publication_digest = result.map_err(|error| {
            RecordedProductEvaluationErrorV1::Evaluation(ProductEvaluationError::Sink(error))
        })?;
        if publication_digest.is_zero() || decision.decision.authority.grants_any() {
            return Err(RecordedProductEvaluationErrorV1::Evaluation(
                ProductEvaluationError::Integrity("outcome publication"),
            ));
        }
        Ok(ProductOutcomeQualificationReceiptV1 {
            decision,
            execution_digest: temporal.execution_digest(),
            publication_digest,
            objective_digest: temporal.carrier.product_plan.frozen_plan.objective_digest,
            dataset_digest: temporal.carrier.product_plan.frozen_plan.dataset_digest,
            evaluator: prepared.context.evaluator.clone(),
            snapshot_ids: temporal.carrier.snapshot_ids.clone(),
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn recover_persisted_outcome_qualification<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        artifact_host_binding: Digest32,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let decision = archive::recover(
            journal,
            attempt_id,
            artifact_root.as_ref(),
            artifact_host_binding,
            self.namespace,
            archive::OUTCOME,
            verifier,
            now,
        )?;
        Self::resume_decided_publication(journal, attempt_id, &decision, sink)
    }
}
