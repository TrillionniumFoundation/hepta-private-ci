//! One canonical encoding shared by archive acknowledgement and final use.
use std::path::Path;

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProductEvaluationAttemptJournalV1;
use crate::ProductAttemptRecoveryErrorV1;
use crate::ProductEvaluationAttemptPhaseV1;
use crate::ProductEvaluationAttemptTransitionV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::ProductTimingEvidenceV1;
use crate::RecordedProductEvaluationErrorV1;
use crate::SignedEvaluationDecisionV1;
use crate::attempt_recovery::validated_history;

use super::Archive;
use super::store;

pub(crate) struct ArchiveAttemptV1<'a> {
    pub(crate) attempt_id: &'a StableId,
    pub(crate) host_binding: Digest32,
}

#[derive(Clone, Copy)]
pub(crate) struct PublicationArchiveIdentityV1 {
    pub(crate) bytes_digest: Digest32,
    pub(crate) holdout_record_digest: Digest32,
}

pub(crate) struct QualificationPublicationIoV1<'a, J> {
    pub(crate) journal: &'a mut J,
    pub(crate) root: &'a Path,
    pub(crate) verifier: &'a LearningEvidenceVerifierV1,
    pub(crate) now: u64,
    pub(crate) sink: &'a mut dyn ProductQualificationEvidenceSinkV1,
}

pub(crate) struct PreparedArchive {
    archive: Archive,
    bytes: Vec<u8>,
    identity: PublicationArchiveIdentityV1,
}

impl Archive {
    pub(crate) fn prepare(self) -> Result<PreparedArchive, RecordedProductEvaluationErrorV1> {
        let bytes = self
            .encode()
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        if Self::decode(&bytes).map_err(RecordedProductEvaluationErrorV1::Evaluation)? != self {
            return Err(RecordedProductEvaluationErrorV1::Invariant(
                "qualification archive round trip",
            ));
        }
        let identity = PublicationArchiveIdentityV1 {
            bytes_digest: Digest32::of_bytes(&bytes),
            holdout_record_digest: self.holdout_record_digest,
        };
        Ok(PreparedArchive {
            archive: self,
            bytes,
            identity,
        })
    }
}

impl PreparedArchive {
    pub(crate) fn identity(&self) -> PublicationArchiveIdentityV1 {
        self.identity
    }

    pub(crate) fn timing(&self) -> ProductTimingEvidenceV1<'_> {
        self.archive.timing.as_evidence()
    }

    /// Encode from typed native inputs and anchor the exact artifact before a
    /// qualification decision can become durable. A failed append never grants
    /// permission to adopt unanchored disk bytes after restart.
    pub(crate) fn persist<J: DurableProductEvaluationAttemptJournalV1>(
        &self,
        journal: &mut J,
        root: &Path,
        verifier: &LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<SignedEvaluationDecisionV1, RecordedProductEvaluationErrorV1> {
        let reject = || RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
            attempt_id: self.archive.attempt_id.clone(),
        };
        let history = validated_history(journal, &self.archive.attempt_id).map_err(|_| reject())?;
        let latest = history.last().ok_or_else(reject)?;
        if latest.transition.phase != ProductEvaluationAttemptPhaseV1::ComparisonSealed
            || latest.transition.plan_digest != self.archive.bundle.frozen_plan.plan_digest
            || latest.transition.holdout_record_digest != self.archive.holdout_record_digest
            || latest.transition.terminal_digest != self.archive.execution_digest
            || !history.iter().any(|event| {
                event.transition.phase == ProductEvaluationAttemptPhaseV1::IntentPersisted
                    && event.transition.holdout_record_digest == self.archive.namespace
            })
        {
            return Err(reject());
        }
        let decision = self
            .archive
            .verify(verifier, now)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        store::persist(root, &self.archive.attempt_id, &self.bytes)
            .map_err(RecordedProductEvaluationErrorV1::Evaluation)?;
        journal.append(ProductEvaluationAttemptTransitionV1 {
            attempt_id: self.archive.attempt_id.clone(),
            plan_digest: self.archive.bundle.frozen_plan.plan_digest,
            phase: ProductEvaluationAttemptPhaseV1::QualificationArtifactsPersisted,
            holdout_record_digest: self.archive.holdout_record_digest,
            terminal_digest: self.identity.bytes_digest,
        })?;
        Ok(decision)
    }
}

/// Derive the guard identity from authoritative, validated anchored history.
pub(crate) fn recovery_publication_identity<J: DurableProductEvaluationAttemptJournalV1>(
    journal: &mut J,
    attempt_id: &StableId,
) -> Result<PublicationArchiveIdentityV1, RecordedProductEvaluationErrorV1> {
    let reject = || RecordedProductEvaluationErrorV1::AttemptRequiresRecovery {
        attempt_id: attempt_id.clone(),
    };
    let history = validated_history(journal, attempt_id).map_err(|error| match error {
        ProductAttemptRecoveryErrorV1::Journal(error) => {
            RecordedProductEvaluationErrorV1::Journal(error)
        }
        _ => reject(),
    })?;
    let prepared = history
        .iter()
        .find(|event| {
            event.transition.phase
                == ProductEvaluationAttemptPhaseV1::QualificationArtifactsPersisted
        })
        .ok_or_else(reject)?;
    let sealed = history
        .iter()
        .find(|event| event.transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed)
        .ok_or_else(reject)?;
    Ok(PublicationArchiveIdentityV1 {
        bytes_digest: prepared.transition.terminal_digest,
        holdout_record_digest: sealed.transition.holdout_record_digest,
    })
}
