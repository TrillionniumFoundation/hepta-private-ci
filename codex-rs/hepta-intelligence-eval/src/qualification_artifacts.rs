//! Single-outcome qualification artifacts generated from native typed objects.
//! This module is a child of the recorded runner; no raw public runner is added.
use std::path::Path;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FinalHoldoutCasStoreV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductQualificationReceiptV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::ProductTimingEvidenceV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationEvidenceV1;
use crate::recorded_publication::RecordedPublicationSinkV1;
use crate::recorded_publication::archive;

pub(crate) struct PreparedTemporalQualificationV1<'a> {
    attempt_id: &'a StableId,
    temporal: &'a ProductTemporalEvaluationReceiptV1,
    context: &'a ProductQualificationContextV1,
    evidence: &'a SignedEvaluationEvidenceV1,
    archive: archive::PreparedArchive,
}

impl PreparedTemporalQualificationV1<'_> {
    pub(crate) fn identity(&self) -> archive::PublicationArchiveIdentityV1 {
        self.archive.identity()
    }
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    /// Persist the complete typed qualification replay object, then bind its
    /// exact bytes in the independently anchored attempt history before deciding.
    /// The caller cannot supply alternative opaque bytes or a decoding callback.
    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist_with_artifacts<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        attempt_id: &StableId,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        artifact_host_binding: Digest32,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<ProductQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let prepared = self.prepare_temporal_qualification(
            archive::ArchiveAttemptV1 {
                attempt_id,
                host_binding: artifact_host_binding,
            },
            temporal,
            context,
            evidence,
            timing,
        )?;
        self.qualify_prepared_temporal(
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

    pub(crate) fn prepare_temporal_qualification<'a>(
        &self,
        attempt: archive::ArchiveAttemptV1<'a>,
        temporal: &'a ProductTemporalEvaluationReceiptV1,
        context: &'a ProductQualificationContextV1,
        evidence: &'a SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
    ) -> Result<PreparedTemporalQualificationV1<'a>, RecordedProductEvaluationErrorV1> {
        let bundle = self
            .qualification_bundle(temporal, context)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let archive = archive::Archive::new(
            archive::TEMPORAL,
            attempt.attempt_id,
            attempt.host_binding,
            self.namespace,
            temporal.execution_digest,
            temporal.holdout.record_digest,
            bundle,
            temporal.product_plan.metric_roles.clone(),
            evidence,
            timing,
        )
        .prepare()?;
        Ok(PreparedTemporalQualificationV1 {
            attempt_id: attempt.attempt_id,
            temporal,
            context,
            evidence,
            archive,
        })
    }

    pub(crate) fn qualify_prepared_temporal<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        prepared: PreparedTemporalQualificationV1<'_>,
        io: archive::QualificationPublicationIoV1<'_, J>,
    ) -> Result<ProductQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        prepared
            .archive
            .persist(io.journal, io.root, io.verifier, io.now)?;
        let temporal = prepared.temporal;
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: prepared.attempt_id.clone(),
            plan_digest: temporal.product_plan.frozen_plan.plan_digest,
            holdout_record_digest: temporal.holdout.record_digest,
            journal: io.journal,
            inner: io.sink,
            journal_error: None,
        };
        let result = self.inner.qualify_and_persist(
            temporal,
            prepared.context,
            prepared.evidence,
            prepared.archive.timing(),
            io.verifier,
            io.now,
            &mut recorded,
        );
        if let Some(error) = recorded.journal_error {
            return Err(RecordedProductEvaluationErrorV1::Journal(error));
        }
        result.map_err(RecordedProductEvaluationErrorV1::Evaluation)
    }

    /// Cold recovery decodes persisted values and performs V2/V3 verification
    /// inside learning.eval using the supplied current host trust and clock.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_persisted_qualification<J: DurableProductEvaluationAttemptJournalV1>(
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
            archive::TEMPORAL,
            verifier,
            now,
        )?;
        Self::resume_decided_publication(journal, attempt_id, &decision, sink)
    }
}
