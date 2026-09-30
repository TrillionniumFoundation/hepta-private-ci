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
        let bundle = self
            .qualification_bundle(temporal, context)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        let artifact = archive::Archive::new(
            archive::TEMPORAL,
            attempt_id,
            artifact_host_binding,
            self.namespace,
            temporal.execution_digest,
            temporal.holdout.record_digest,
            bundle,
            temporal.product_plan.metric_roles.clone(),
            evidence,
            timing,
        );
        artifact.persist(journal, artifact_root.as_ref(), verifier, now)?;
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: attempt_id.clone(),
            plan_digest: temporal.product_plan.frozen_plan.plan_digest,
            holdout_record_digest: temporal.holdout.record_digest,
            journal,
            inner: sink,
            journal_error: None,
        };
        let result = self.inner.qualify_and_persist(
            temporal,
            context,
            evidence,
            artifact.timing.as_evidence(),
            verifier,
            now,
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
