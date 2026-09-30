//! One selected-host publication adapter for both typed receipt families.
//! Host identity/trust and directory provisioning remain owner inputs. All
//! qualification archive encoding and signature verification are internal.
use std::path::Path;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::LockedQualificationPublicationStoreV1;
use super::map_store_to_recorded;
use crate::DurableProductEvaluationAttemptJournalV1;
use crate::FinalHoldoutCasStoreV1;
use crate::ProductAttemptRecoveryErrorV1;
use crate::ProductEvaluationAttemptReceiptV1;
use crate::ProductOutcomeEvaluationReceiptV1;
use crate::ProductOutcomeQualificationReceiptV1;
use crate::ProductQualificationContextV1;
use crate::ProductQualificationReceiptV1;
use crate::ProductTemporalEvaluationReceiptV1;
use crate::ProductTimingEvidenceV1;
use crate::ReconciledProductQualificationSinkV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::RecordedProductEvaluationRunnerV1;
use crate::SignedEvaluationEvidenceV1;
use crate::reconcile_product_attempt_publication_v1;

fn current_verifier(
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> Result<&LearningEvidenceVerifierV1, RecordedProductEvaluationErrorV1> {
    if !trust.is_current_at(now) {
        return Err(RecordedProductEvaluationErrorV1::Invariant(
            "selected-host root-activated learning trust is not current",
        ));
    }
    Ok(trust.verifier())
}

impl<S: FinalHoldoutCasStoreV1> RecordedProductEvaluationRunnerV1<S> {
    #[allow(clippy::too_many_arguments)]
    pub fn qualify_and_persist_on_selected_host<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        attempt_id: &StableId,
        temporal: &ProductTemporalEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        trust: &ActivatedLearningTrustV1,
        now: u64,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let verifier = current_verifier(trust, now)?;
        let store = LockedQualificationPublicationStoreV1::new(
            publication_root.as_ref(), selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.qualify_and_persist_with_artifacts(
            attempt_id,
            temporal,
            context,
            evidence,
            timing,
            verifier,
            now,
            journal,
            artifact_root,
            selected_host_binding,
            &mut sink,
        )
    }

    /// Cold replay has no callback capable of bypassing current V2/V3 checks.
    #[allow(clippy::too_many_arguments)]
    pub fn recover_selected_host_qualification<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
        trust: &ActivatedLearningTrustV1,
        now: u64,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let verifier = current_verifier(trust, now)?;
        let store = LockedQualificationPublicationStoreV1::open_existing(
            publication_root.as_ref(), selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.recover_persisted_qualification(
            journal,
            attempt_id,
            artifact_root,
            selected_host_binding,
            verifier,
            now,
            &mut sink,
        )
    }

    /// Read-verify an existing publication; only the attempt journal advances.
    pub fn reconcile_selected_host_publication<J: DurableProductEvaluationAttemptJournalV1>(
        journal: &mut J,
        attempt_id: &StableId,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1> {
        let mut store = LockedQualificationPublicationStoreV1::open_existing(
            publication_root.as_ref(), selected_host_binding,
        )
        .map_err(|_| ProductAttemptRecoveryErrorV1::Unresolved)?;
        reconcile_product_attempt_publication_v1(journal, &mut store, attempt_id)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn qualify_outcomes_and_persist_on_selected_host<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        &self,
        attempt_id: &StableId,
        temporal: &ProductOutcomeEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
        evidence: &SignedEvaluationEvidenceV1,
        timing: ProductTimingEvidenceV1<'_>,
        trust: &ActivatedLearningTrustV1,
        now: u64,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductOutcomeQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let verifier = current_verifier(trust, now)?;
        let store = LockedQualificationPublicationStoreV1::new(
            publication_root.as_ref(), selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.qualify_outcomes_and_persist_with_artifacts(
            attempt_id,
            temporal,
            context,
            evidence,
            timing,
            verifier,
            now,
            journal,
            artifact_root,
            selected_host_binding,
            &mut sink,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn recover_selected_host_outcome_qualification<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
        trust: &ActivatedLearningTrustV1,
        now: u64,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let verifier = current_verifier(trust, now)?;
        let store = LockedQualificationPublicationStoreV1::open_existing(
            publication_root.as_ref(), selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        self.recover_persisted_outcome_qualification(
            journal,
            attempt_id,
            artifact_root,
            selected_host_binding,
            verifier,
            now,
            &mut sink,
        )
    }

    pub fn reconcile_selected_host_outcome_publication<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        journal: &mut J,
        attempt_id: &StableId,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1> {
        Self::reconcile_selected_host_publication(
            journal,
            attempt_id,
            publication_root,
            selected_host_binding,
        )
    }
}
