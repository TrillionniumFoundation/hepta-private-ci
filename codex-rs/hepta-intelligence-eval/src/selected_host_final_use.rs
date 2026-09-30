//! Revalidate selected-host time and signed evidence after write-ahead I/O,
//! immediately before the underlying publication owner is first invoked.
use std::path::Path;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ProductEvaluationError;
use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::SignedEvaluationDecisionV1;
use crate::product::SelectedHostClockV1;
use crate::recorded_publication::archive;

use super::facade::sample_current_verifier;

pub(super) struct SelectedHostFinalUseSinkV1<'a> {
    pub(super) inner: &'a mut dyn ProductQualificationEvidenceSinkV1,
    pub(super) trust: &'a ActivatedLearningTrustV1,
    pub(super) clock: &'a mut dyn SelectedHostClockV1,
    pub(super) clock_binding: Digest32,
    pub(super) last_now: &'a mut u64,
    pub(super) artifact_root: &'a Path,
    pub(super) attempt_id: &'a StableId,
    pub(super) host_binding: Digest32,
    pub(super) namespace: Digest32,
    pub(super) family: u8,
    pub(super) error: Option<RecordedProductEvaluationErrorV1>,
}

impl ProductQualificationEvidenceSinkV1 for SelectedHostFinalUseSinkV1<'_> {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        // PublicationPending is already durable. A final-use failure leaves it
        // unresolved; this guard never makes an unknown publication retryable.
        let admitted = (|| {
            let archive = archive::load_publication_archive(
                self.artifact_root,
                self.attempt_id,
                self.host_binding,
                self.namespace,
                self.family,
                execution_digest,
            )?;
            if self.clock.binding() != self.clock_binding {
                return Err(RecordedProductEvaluationErrorV1::Invariant(
                    "selected-host trusted clock binding changed",
                ));
            }
            let (verifier, now) = sample_current_verifier(self.trust, self.clock)?;
            if now < *self.last_now {
                return Err(RecordedProductEvaluationErrorV1::Invariant(
                    "selected-host trusted clock regressed",
                ));
            }
            *self.last_now = now;
            let current = archive
                .verify(verifier, now)
                .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
            if &current != decision {
                return Err(RecordedProductEvaluationErrorV1::Evaluation(
                    ProductEvaluationError::Integrity("selected-host final-use decision changed"),
                ));
            }
            Ok(())
        })();
        if let Err(error) = admitted {
            self.error = Some(error);
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        self.inner.persist(execution_digest, decision)
    }
}
