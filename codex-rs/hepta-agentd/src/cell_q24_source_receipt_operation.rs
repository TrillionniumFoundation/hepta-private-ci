//! Original Observer journal reads borrowing the same Prepared operation.
//! Source validation still precedes and follows the actual owner journal read;
//! a receipt or a matching digest cannot substitute a different Prepared owner.

use super::*;

impl<W: AnchorWitnessStore> OriginalCellQ24SourceReceiptOwnerV1<W> {
    pub(crate) fn attest_experience_in_operation(
        &mut self,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        if self.config.stage != OriginalCellQ24SourceStageV1::Experience {
            return Err(binding("original Experience owner"));
        }
        let prepared = Arc::clone(&self.prepared);
        self.attest_at(prepared.initial(), read)
    }

    pub(crate) fn attest_dataset_in_operation(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<impl AnchorWitnessStore>,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        self.with_original_experience_in_operation(experience, read, Self::attest_at)
    }

    pub(crate) fn read_experience_in_operation(
        &mut self,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        if self.config.stage != OriginalCellQ24SourceStageV1::Experience {
            return Err(binding("original Experience owner"));
        }
        let prepared = Arc::clone(&self.prepared);
        self.read_at(prepared.initial(), read)
    }

    pub(crate) fn read_dataset_in_operation(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<impl AnchorWitnessStore>,
        read: &OriginalPreparedReadV1<'_>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        self.with_original_experience_in_operation(experience, read, Self::read_at)
    }

    pub(super) fn with_original_experience_in_operation(
        &mut self,
        experience: &mut OriginalCellQ24SourceReceiptOwnerV1<impl AnchorWitnessStore>,
        read: &OriginalPreparedReadV1<'_>,
        operation: impl FnOnce(
            &mut Self,
            &LearningIterationSnapshotV1,
            &OriginalPreparedReadV1<'_>,
        ) -> Result<OriginalCellQ24SourceCompletionV1, Error>,
    ) -> Result<OriginalCellQ24SourceCompletionV1, Error> {
        if self.config.stage != OriginalCellQ24SourceStageV1::Dataset
            || experience.config.stage != OriginalCellQ24SourceStageV1::Experience
            || !Arc::ptr_eq(&self.prepared, &experience.prepared)
        {
            return Err(binding("original Dataset and Experience owners"));
        }
        let prepared = Arc::clone(&self.prepared);
        let before = experience.read_at(prepared.initial(), read)?;
        OriginalPreparedReadV1::require_prepared(read, &self.prepared)?;
        let facts = OriginalPreparedReadV1::read_validated_facts(read)?;
        let initial = self.prepared.initial();
        let receipt = &before.receipt;
        if receipt.operation_id != initial.request.operation_id
            || receipt.predecessor != initial.head_digest
            || receipt.actor_id != initial.owners.experience
            || &receipt.observation != facts.experience()
            || receipt.evidence_digest != facts.experience_evidence_digest()
            || receipt.observed_unix_seconds != before.attestation.issued_at
        {
            return Err(binding("original Experience predecessor"));
        }
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let verified = self.config.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &before.attestation,
            &payload,
            now()?,
        )?;
        if verified.principal().principal_id != initial.owners.experience {
            return Err(binding("original Experience Observer"));
        }
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        self.prepared
            .scope()
            .validate_snapshot(coordinator.snapshot())?;
        if coordinator.snapshot() != &before.snapshot {
            return Err(binding("original Experience checkpoint"));
        }
        let completed = operation(self, &before.snapshot, read)?;
        if experience.read_at(prepared.initial(), read)? != before {
            return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
        }
        Ok(completed)
    }
}
