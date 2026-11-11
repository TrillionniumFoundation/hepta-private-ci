//! Identity pins and one-way channel moves. Stored originals are compared with
//! new original-owner reads; none of these values substitutes for CURRENT.

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1 as Stage;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::Error;
use super::OriginalCellQ24NoUpdateStageOwnersV1 as Owners;
use super::auth;
use crate::OriginalCellQ24MaterialCommandClientV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitCompletionReadinessClientV1;
use crate::OriginalCircuitNextUseCommandClientV1;
use crate::OriginalCircuitNextUseCommandReceiptV1;
use crate::OriginalCircuitSelectionCommandClientV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;

pub(super) struct Continuation {
    pub(super) experience: OriginalCellQ24MaterialCommandClientV1,
    pub(super) dataset: OriginalCellQ24MaterialCommandClientV1,
    trainer_initial: Option<OriginalCellQ24TrainingCommandConnectionV1>,
    pub(super) trainer: Option<OriginalCellQ24TrainingCommandClientV1>,
    selector_initial: Option<HostAuthorityPeerChannel>,
    pub(super) selector: Option<OriginalCircuitSelectionCommandClientV1>,
    next_use_initial: Option<HostAuthorityPeerChannel>,
    pub(super) next_use: Option<OriginalCircuitNextUseCommandClientV1>,
    readiness_initial: Option<HostAuthorityPeerChannel>,
    pub(super) readiness: Option<OriginalCircuitCompletionReadinessClientV1>,
    pub(super) records: Vec<(LearningIterationReceiptV1, SignedLearningEvidenceV1)>,
    pub(super) original_dataset: Option<OriginalCellQ24MaterialCommandReceiptV1>,
    pub(super) original_training: Option<OriginalCellQ24TrainingCommandReceiptV1>,
    pub(super) original_selection: Option<OriginalCircuitSelectionCommandReceiptV1>,
}

impl Continuation {
    pub(super) fn new(
        experience: OriginalCellQ24MaterialCommandClientV1,
        dataset: OriginalCellQ24MaterialCommandClientV1,
        trainer: OriginalCellQ24TrainingCommandConnectionV1,
        selector: HostAuthorityPeerChannel,
        next_use: HostAuthorityPeerChannel,
        readiness: HostAuthorityPeerChannel,
    ) -> Self {
        Self {
            experience, dataset,
            trainer_initial: Some(trainer), trainer: None,
            selector_initial: Some(selector), selector: None,
            next_use_initial: Some(next_use), next_use: None,
            readiness_initial: Some(readiness), readiness: None,
            records: Vec::with_capacity(5),
            original_dataset: None, original_training: None, original_selection: None,
        }
    }

    pub(super) async fn read_prefix(
        &mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), Error> {
        if snapshot.receipts.is_empty() {
            // An unconfirmed/empty checkpoint is never evidence of absence.
            // Observe the original journal, but do not complete or advance it.
            let _ = OriginalCellQ24MaterialCommandClientV1::readback(&self.experience)
                .await.map_err(auth::material_failure)?;
            return Err(Error::CommitUncertain);
        }
        for expected in &snapshot.receipts {
            let actual = self.read_stage(owners, expected.observation.stage()).await?;
            if &actual != expected {
                return Err(Error::WrongScope);
            }
        }
        auth::verify_prefix(&owners.material, snapshot, self, auth::now()?)
    }

    pub(super) async fn read_stage(&mut self, owners: &Owners, stage: Stage)
        -> Result<LearningIterationReceiptV1, Error>
    {
        match stage {
            Stage::Experience => {
                let original = OriginalCellQ24MaterialCommandClientV1::readback(&self.experience)
                    .await.map_err(auth::material_failure)?;
                self.record_material(owners, &original)?;
                Ok(original.receipt().clone())
            }
            Stage::Dataset => {
                let original = OriginalCellQ24MaterialCommandClientV1::readback(&self.dataset)
                    .await.map_err(auth::material_failure)?;
                self.record_material(owners, &original)?;
                Ok(original.receipt().clone())
            }
            Stage::Training => {
                self.ensure_trainer(owners).await?;
                let client = self.trainer.as_ref().ok_or(Error::CommitUncertain)?;
                let original = OriginalCellQ24TrainingCommandClientV1::readback(client)
                    .await.map_err(auth::trainer_failure)?;
                self.record_training(owners, &original)?;
                Ok(original.receipt().clone())
            }
            Stage::Selection => {
                self.ensure_selector(owners).await?;
                let client = self.selector.as_ref().ok_or(Error::CommitUncertain)?;
                let original = OriginalCircuitSelectionCommandClientV1::readback(client)
                    .await.map_err(auth::selector_failure)?;
                self.record_selection(owners, &original)?;
                Ok(original.receipt().clone())
            }
            Stage::NextUse => {
                self.ensure_next_use(owners).await?;
                let client = self.next_use.as_ref().ok_or(Error::CommitUncertain)?;
                let original = OriginalCircuitNextUseCommandClientV1::readback(client)
                    .await.map_err(auth::next_use_failure)?;
                self.record_next_use(owners, &original)?;
                Ok(original.receipt().clone())
            }
            Stage::Evaluation | Stage::Proposal =>
                Err(Error::OwnerUnavailable("original Candidate requires its separate route")),
        }
    }

    pub(super) async fn read_attestation(
        &mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1,
        receipt: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        auth::require_receipt_position(snapshot, receipt)?;
        let actual = self.read_stage(owners, receipt.observation.stage()).await?;
        if &actual != receipt {
            return Err(Error::WrongScope);
        }
        // Reconcile every already observed identity against the full supplied
        // checkpoint, including later receipts. Current proof for each role is
        // still obtained only from that role's actual read above.
        for (expected, (original, _)) in snapshot.receipts.iter().zip(&self.records) {
            if expected != original {
                return Err(Error::WrongScope);
            }
        }
        let index = auth::stage_index(receipt.observation.stage())?;
        Ok(self.records.get(index).ok_or(Error::CommitUncertain)?.1.clone())
    }

    pub(super) async fn ensure_trainer(&mut self, owners: &Owners) -> Result<(), Error> {
        if self.trainer.is_none() {
            let dataset = OriginalCellQ24MaterialCommandClientV1::readback(&self.dataset)
                .await.map_err(auth::material_failure)?;
            self.record_material(owners, &dataset)?;
            let initial = self.trainer_initial.take().ok_or(Error::CommitUncertain)?;
            self.trainer = Some(OriginalCellQ24TrainingCommandConnectionV1::bind_original_dataset(
                initial, dataset,
            ).map_err(|_| Error::OwnerUnavailable("original Trainer late Dataset binding"))?);
        }
        Ok(())
    }

    pub(super) async fn ensure_selector(&mut self, owners: &Owners) -> Result<(), Error> {
        if self.selector.is_none() {
            self.ensure_trainer(owners).await?;
            let trainer = self.trainer.as_ref().ok_or(Error::CommitUncertain)?;
            let training = OriginalCellQ24TrainingCommandClientV1::readback(trainer)
                .await.map_err(auth::trainer_failure)?;
            self.record_training(owners, &training)?;
            let dataset = self.original_dataset.as_ref().ok_or(Error::CommitUncertain)?;
            let channel = self.selector_initial.take().ok_or(Error::CommitUncertain)?;
            self.selector = Some(OriginalCircuitSelectionCommandClientV1::bind_original_stage_channel(
                channel, &owners.material, dataset, &training, owners.origin,
            ).map_err(auth::selector_failure)?);
        }
        Ok(())
    }

    pub(super) async fn ensure_next_use(&mut self, owners: &Owners) -> Result<(), Error> {
        if self.next_use.is_none() {
            self.ensure_selector(owners).await?;
            let selector = self.selector.as_ref().ok_or(Error::CommitUncertain)?;
            let selection = OriginalCircuitSelectionCommandClientV1::readback(selector)
                .await.map_err(auth::selector_failure)?;
            self.record_selection(owners, &selection)?;
            let dataset = self.original_dataset.as_ref().ok_or(Error::CommitUncertain)?;
            let channel = self.next_use_initial.take().ok_or(Error::CommitUncertain)?;
            self.next_use = Some(OriginalCircuitNextUseCommandClientV1::bind_original_stage_channel(
                channel, &owners.material, dataset, &selection, owners.origin,
            ).map_err(auth::next_use_failure)?);
        }
        Ok(())
    }

    pub(super) fn ensure_readiness(&mut self, owners: &Owners) -> Result<(), Error> {
        if self.readiness.is_none() {
            let dataset = self.original_dataset.as_ref().ok_or(Error::CommitUncertain)?;
            let selection = self.original_selection.as_ref().ok_or(Error::CommitUncertain)?;
            let channel = self.readiness_initial.take().ok_or(Error::CommitUncertain)?;
            self.readiness = Some(OriginalCircuitCompletionReadinessClientV1::bind_original_stage_channel(
                channel, &owners.material, dataset, selection,
            ).map_err(|_| Error::OwnerUnavailable("original C readiness binding"))?);
        }
        Ok(())
    }

    pub(super) fn record_material(
        &mut self, owners: &Owners, original: &OriginalCellQ24MaterialCommandReceiptV1,
    ) -> Result<(), Error> {
        auth::require_snapshot(&owners.material, original.snapshot())?;
        let count = original.snapshot().receipts.len();
        if !(1..=2).contains(&count) || original.attestations().len() != count {
            return Err(Error::WrongScope);
        }
        if count == 2 {
            OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
                original, &owners.material,
            ).map_err(|_| Error::WrongScope)?;
        }
        for (receipt, signature) in original.snapshot().receipts.iter().zip(original.attestations()) {
            self.pin(owners, receipt, signature)?;
        }
        if count == 2 {
            self.original_dataset = Some(original.clone());
        }
        Ok(())
    }

    pub(super) fn record_training(
        &mut self, owners: &Owners, original: &OriginalCellQ24TrainingCommandReceiptV1,
    ) -> Result<(), Error> {
        let dataset = self.original_dataset.as_ref().ok_or(Error::CommitUncertain)?;
        auth::require_receipt_position(dataset.snapshot(), original.receipt())?;
        self.pin(owners, original.receipt(), original.attestation())?;
        // Candidate remains the actual result. It is not converted to NoUpdate.
        self.original_training = Some(original.clone());
        Ok(())
    }

    pub(super) fn record_selection(
        &mut self, owners: &Owners, original: &OriginalCircuitSelectionCommandReceiptV1,
    ) -> Result<(), Error> {
        let training = self.original_training.as_ref().ok_or(Error::CommitUncertain)?;
        if original.training_attestation() != training.attestation() {
            return Err(Error::WrongScope);
        }
        auth::require_snapshot(&owners.material, original.snapshot())?;
        if original.snapshot().receipts.len() != 4
            || original.snapshot().training_no_update_v2().is_none()
        {
            return Err(Error::WrongScope);
        }
        for (index, expected) in original.snapshot().receipts[..3].iter().enumerate() {
            if self.records.get(index).map(|record| &record.0) != Some(expected) {
                return Err(Error::WrongScope);
            }
        }
        self.pin(owners, original.receipt(), original.attestation())?;
        self.original_selection = Some(original.clone());
        Ok(())
    }

    pub(super) fn record_next_use(
        &mut self, owners: &Owners, original: &OriginalCircuitNextUseCommandReceiptV1,
    ) -> Result<(), Error> {
        let selection = self.original_selection.as_ref().ok_or(Error::CommitUncertain)?;
        if original.training_attestation() != selection.training_attestation()
            || original.selection_attestation() != selection.attestation()
            || original.snapshot().receipts.len() != 5
        {
            return Err(Error::WrongScope);
        }
        auth::require_snapshot(&owners.material, original.snapshot())?;
        for (index, expected) in original.snapshot().receipts[..4].iter().enumerate() {
            if self.records.get(index).map(|record| &record.0) != Some(expected) {
                return Err(Error::WrongScope);
            }
        }
        self.pin(owners, original.receipt(), original.attestation())
    }

    fn pin(
        &mut self, owners: &Owners, receipt: &LearningIterationReceiptV1,
        signature: &SignedLearningEvidenceV1,
    ) -> Result<(), Error> {
        let index = auth::stage_index(receipt.observation.stage())?;
        auth::verify_receipt(&owners.material, receipt, signature, auth::now()?)?;
        match self.records.get(index) {
            Some(prior) if prior != &(receipt.clone(), signature.clone()) => return Err(Error::WrongScope),
            Some(_) => return Ok(()),
            None => {}
        }
        if self.records.len() != index || self.records.len() >= 5 {
            return Err(Error::WrongScope);
        }
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(owners.material.initial.clone())?;
        for (prior, _) in &self.records {
            coordinator.record(prior.clone(), prior.observed_unix_seconds)?;
        }
        coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
        owners.material.scope.validate_snapshot(coordinator.snapshot())?;
        self.records.push((receipt.clone(), signature.clone()));
        Ok(())
    }
}
