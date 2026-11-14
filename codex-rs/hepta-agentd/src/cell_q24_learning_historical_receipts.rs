//! Original receipt readback and current signature checks on the same borrowed
//! stage. No cached signature or caller-provided receipt supplies authority.

use super::*;
use crate::learning_iteration_auth::OriginalReceiptVerificationV1;
use crate::learning_iteration_auth::independent_receipt_stages;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;

impl OriginalQ24StageOperationV1<'_, '_, '_, '_> {
    pub(super) fn source_receipt(
        &mut self,
        stage: LearningIterationStageV1,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let observed = match stage {
            LearningIterationStageV1::Experience => {
                OriginalCellQ24SourceReceiptOwnerV1::read_experience_in_operation(
                    &mut self.owners.experience,
                    self.read,
                )
            }
            LearningIterationStageV1::Dataset => {
                OriginalCellQ24SourceReceiptOwnerV1::read_dataset_in_operation(
                    &mut self.owners.dataset,
                    &mut self.owners.experience,
                    self.read,
                )
            }
            _ => return Err(Error::WrongScope),
        }
        .map_err(unavailable)?;
        Ok((observed.receipt().clone(), observed.attestation().clone()))
    }

    fn read_receipt(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        expected: &LearningIterationReceiptV1,
    ) -> Result<Option<SignedLearningEvidenceV1>, Error> {
        let (receipt, signed) = match expected.observation.stage() {
            LearningIterationStageV1::Experience | LearningIterationStageV1::Dataset => {
                let (receipt, signed) = self.source_receipt(expected.observation.stage())?;
                (receipt, Some(signed))
            }
            LearningIterationStageV1::Training => {
                let original =
                    OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?;
                if snapshot != &self.inner.dataset_cut
                    && !snapshot.receipts.starts_with(&original.snapshot().receipts)
                {
                    return Err(Error::WrongScope);
                }
                (
                    original.receipt().clone(),
                    Some(original.attestation().clone()),
                )
            }
            LearningIterationStageV1::Evaluation => {
                let original =
                    OriginalQ24TrainingOperationV1::read_original_training_evidence(self.training)?;
                if !snapshot.receipts.starts_with(&original.snapshot().receipts) {
                    return Err(Error::WrongScope);
                }
                self.require_original_b_read()?;
                let observed = self.original_b.as_ref().ok_or(Error::CommitUncertain)?;
                (
                    observed.receipt().clone(),
                    Some(observed.attestation().clone()),
                )
            }
            LearningIterationStageV1::Proposal => {
                self.model_root_action(snapshot, model::Action::ReadProposal)?
            }
            LearningIterationStageV1::Selection
                if matches!(
                    expected.observation,
                    LearningIterationObservationV1::LocalDecisionV2(_)
                ) =>
            {
                self.model_root_action(snapshot, model::Action::ReadDecision)?
            }
            LearningIterationStageV1::Selection | LearningIterationStageV1::NextUse => {
                let (selection, next_use) = self
                    .owners
                    .generation
                    .as_mut()
                    .ok_or(Error::OwnerUnavailable("original C handoff"))?;
                let original: &mut OriginalGenerationLearningReceiptOwnerV1<
                    FileAnchorWitnessStore,
                > = if expected.observation.stage() == LearningIterationStageV1::Selection {
                    selection
                } else {
                    next_use
                };
                let (receipt, signed) = self
                    .runtime
                    .block_on(original.readback(snapshot))
                    .map_err(unavailable)?;
                (receipt, Some(signed))
            }
        };
        if &receipt != expected {
            return Err(Error::WrongScope);
        }
        Ok(signed)
    }

    fn verify_receipt(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        receipt: &LearningIterationReceiptV1,
    ) -> Result<VerifiedLearningEvidenceV1, Error> {
        let signed = self
            .read_receipt(snapshot, receipt)?
            .ok_or(Error::Evidence(SignedEvidenceError::RoleMismatch))?;
        let verification = OriginalReceiptVerificationV1::new(self.verifier(), snapshot, receipt)?;
        OriginalReceiptVerificationV1::verify(&verification, &signed, self.current_time()?)
    }

    pub(in super::super) fn authenticate_receipt(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        receipt: &LearningIterationReceiptV1,
    ) -> Result<(), Error> {
        if receipt.observation.stage() == LearningIterationStageV1::Proposal {
            if self.read_receipt(snapshot, receipt)?.is_some() {
                return Err(Error::WrongScope);
            }
            return Ok(());
        }
        let current = self.verify_receipt(snapshot, receipt)?;
        if let Some(decision) = snapshot.receipts.iter().find(|earlier| {
            matches!(
                earlier.observation,
                LearningIterationObservationV1::LocalDecisionV2(_)
            )
        }) {
            self.verify_receipt(snapshot, decision)?;
        }
        for stage in independent_receipt_stages(snapshot, receipt) {
            let earlier = snapshot
                .receipts
                .iter()
                .rev()
                .find(|earlier| earlier.observation.stage() == *stage)
                .ok_or(Error::Evidence(SignedEvidenceError::ContextMismatch))?;
            let prior = self.verify_receipt(snapshot, earlier)?;
            verify_signed_actor_separation(&prior, &current, self.current_time()?)
                .map_err(Error::Evidence)?;
        }
        Ok(())
    }
}
