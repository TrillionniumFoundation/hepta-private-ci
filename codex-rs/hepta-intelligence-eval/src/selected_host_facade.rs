//! One selected-host publication adapter for both typed receipt families.
//! Host identity/trust, trusted time and directory provisioning remain owner
//! inputs. All qualification archive encoding and signature verification are
//! internal.
use std::path::Path;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::LockedQualificationPublicationStoreV1;
use super::final_use::SelectedHostFinalUseSinkV1;
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
use crate::product::SelectedHostClockErrorV1;
use crate::product::SelectedHostClockV1;
use crate::reconcile_product_attempt_publication_v1;
use crate::recorded_publication::archive;

fn map_clock(error: SelectedHostClockErrorV1) -> RecordedProductEvaluationErrorV1 {
    match error {
        SelectedHostClockErrorV1::Unavailable => {
            RecordedProductEvaluationErrorV1::Invariant("selected-host trusted clock unavailable")
        }
        SelectedHostClockErrorV1::Indeterminate => {
            RecordedProductEvaluationErrorV1::Invariant("selected-host trusted clock indeterminate")
        }
    }
}

fn current_verifier_at(
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

pub(super) fn sample_current_verifier<'a>(
    trust: &'a ActivatedLearningTrustV1,
    clock: &mut dyn SelectedHostClockV1,
) -> Result<(&'a LearningEvidenceVerifierV1, u64), RecordedProductEvaluationErrorV1> {
    let binding = clock.binding();
    if binding.is_zero() {
        return Err(RecordedProductEvaluationErrorV1::Invariant(
            "selected-host trusted clock binding",
        ));
    }
    let now = clock.sample_current_time().map_err(map_clock)?;
    if clock.binding() != binding {
        return Err(RecordedProductEvaluationErrorV1::Invariant(
            "selected-host trusted clock binding changed",
        ));
    }
    Ok((current_verifier_at(trust, now)?, now))
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
        clock: &mut dyn SelectedHostClockV1,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let clock_binding = clock.binding();
        let (verifier, mut now) = sample_current_verifier(trust, clock)?;
        let artifact_root = artifact_root.as_ref();
        let prepared = self.prepare_temporal_qualification(
            archive::ArchiveAttemptV1 {
                attempt_id,
                host_binding: selected_host_binding,
            },
            temporal,
            context,
            evidence,
            timing,
        )?;
        let store = LockedQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        let mut guarded = SelectedHostFinalUseSinkV1 {
            inner: &mut sink,
            trust,
            clock_binding,
            clock,
            last_now: &mut now,
            artifact_root,
            attempt_id,
            host_binding: selected_host_binding,
            namespace: self.namespace,
            family: archive::TEMPORAL,
            identity: prepared.identity(),
            error: None,
        };
        let initial_now = *guarded.last_now;
        let result = self.qualify_prepared_temporal(
            prepared,
            archive::QualificationPublicationIoV1 {
                journal,
                root: artifact_root,
                verifier,
                now: initial_now,
                sink: &mut guarded,
            },
        );
        if let Some(error) = guarded.error {
            return Err(error);
        }
        result
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
        clock: &mut dyn SelectedHostClockV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let clock_binding = clock.binding();
        let (_, mut now) = sample_current_verifier(trust, clock)?;
        self.recover_selected_host_qualification_at_current_time(
            journal,
            attempt_id,
            artifact_root,
            publication_root,
            selected_host_binding,
            trust,
            clock,
            clock_binding,
            &mut now,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn recover_selected_host_qualification_at_current_time<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
        trust: &ActivatedLearningTrustV1,
        clock: &mut dyn SelectedHostClockV1,
        clock_binding: Digest32,
        now: &mut u64,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let verifier = current_verifier_at(trust, *now)?;
        let artifact_root = artifact_root.as_ref();
        let identity = archive::recovery_publication_identity(journal, attempt_id)?;
        let store = LockedQualificationPublicationStoreV1::open_existing(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        let mut guarded = SelectedHostFinalUseSinkV1 {
            inner: &mut sink,
            trust,
            clock_binding,
            clock,
            last_now: now,
            artifact_root,
            attempt_id,
            host_binding: selected_host_binding,
            namespace: self.namespace,
            family: archive::TEMPORAL,
            identity,
            error: None,
        };
        let initial_now = *guarded.last_now;
        let result = self.recover_persisted_qualification(
            journal,
            attempt_id,
            artifact_root,
            selected_host_binding,
            verifier,
            initial_now,
            &mut guarded,
        );
        if let Some(error) = guarded.error {
            return Err(error);
        }
        result
    }

    /// Read-verify an existing publication; only the attempt journal advances.
    pub fn reconcile_selected_host_publication<J: DurableProductEvaluationAttemptJournalV1>(
        journal: &mut J,
        attempt_id: &StableId,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductAttemptRecoveryErrorV1> {
        let mut store = LockedQualificationPublicationStoreV1::open_existing(
            publication_root.as_ref(),
            selected_host_binding,
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
        clock: &mut dyn SelectedHostClockV1,
        journal: &mut J,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
    ) -> Result<ProductOutcomeQualificationReceiptV1, RecordedProductEvaluationErrorV1> {
        let clock_binding = clock.binding();
        let (verifier, mut now) = sample_current_verifier(trust, clock)?;
        let artifact_root = artifact_root.as_ref();
        let prepared = self.prepare_outcome_qualification(
            archive::ArchiveAttemptV1 {
                attempt_id,
                host_binding: selected_host_binding,
            },
            temporal,
            context,
            evidence,
            timing,
        )?;
        let store = LockedQualificationPublicationStoreV1::new(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        let mut guarded = SelectedHostFinalUseSinkV1 {
            inner: &mut sink,
            trust,
            clock_binding,
            clock,
            last_now: &mut now,
            artifact_root,
            attempt_id,
            host_binding: selected_host_binding,
            namespace: self.namespace,
            family: archive::OUTCOME,
            identity: prepared.identity(),
            error: None,
        };
        let initial_now = *guarded.last_now;
        let result = self.qualify_prepared_outcome(
            prepared,
            archive::QualificationPublicationIoV1 {
                journal,
                root: artifact_root,
                verifier,
                now: initial_now,
                sink: &mut guarded,
            },
        );
        if let Some(error) = guarded.error {
            return Err(error);
        }
        result
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
        clock: &mut dyn SelectedHostClockV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let clock_binding = clock.binding();
        let (_, mut now) = sample_current_verifier(trust, clock)?;
        self.recover_selected_host_outcome_qualification_at_current_time(
            journal,
            attempt_id,
            artifact_root,
            publication_root,
            selected_host_binding,
            trust,
            clock,
            clock_binding,
            &mut now,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn recover_selected_host_outcome_qualification_at_current_time<
        J: DurableProductEvaluationAttemptJournalV1,
    >(
        &self,
        journal: &mut J,
        attempt_id: &StableId,
        artifact_root: impl AsRef<Path>,
        publication_root: impl AsRef<Path>,
        selected_host_binding: Digest32,
        trust: &ActivatedLearningTrustV1,
        clock: &mut dyn SelectedHostClockV1,
        clock_binding: Digest32,
        now: &mut u64,
    ) -> Result<ProductEvaluationAttemptReceiptV1, RecordedProductEvaluationErrorV1> {
        let verifier = current_verifier_at(trust, *now)?;
        let artifact_root = artifact_root.as_ref();
        let identity = archive::recovery_publication_identity(journal, attempt_id)?;
        let store = LockedQualificationPublicationStoreV1::open_existing(
            publication_root.as_ref(),
            selected_host_binding,
        )
        .map_err(map_store_to_recorded)?;
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        let mut guarded = SelectedHostFinalUseSinkV1 {
            inner: &mut sink,
            trust,
            clock_binding,
            clock,
            last_now: now,
            artifact_root,
            attempt_id,
            host_binding: selected_host_binding,
            namespace: self.namespace,
            family: archive::OUTCOME,
            identity,
            error: None,
        };
        let initial_now = *guarded.last_now;
        let result = self.recover_persisted_outcome_qualification(
            journal,
            attempt_id,
            artifact_root,
            selected_host_binding,
            verifier,
            initial_now,
            &mut guarded,
        );
        if let Some(error) = guarded.error {
            return Err(error);
        }
        result
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
