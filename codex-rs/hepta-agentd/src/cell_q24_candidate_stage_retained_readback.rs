//! Actual original readback for evaluated S/C. Pins establish equality only;
//! Version, B, retained material and C readiness are observed again each time.

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

use super::*;

impl EvaluatedContinuation {
    pub(super) async fn require_published(&self) -> Result<(), Error> {
        let current = OriginalCircuitRetainedVersionClientV1::readback(
            self.version.as_ref().ok_or(Error::CommitUncertain)?,
        ).await.map_err(|_| Error::CommitUncertain)?;
        if current.publication().is_none() {
            return Err(Error::OwnerUnavailable("original evaluated Version awaits FinalUse"));
        }
        Ok(())
    }

    pub(super) fn pin_selection(&mut self, owners: &Owners, supplied: &LearningIterationSnapshotV1,
        original: &OriginalCircuitSelectionCommandReceiptV1) -> Result<(), Error> {
        let pins = self.pins.as_ref().ok_or(Error::CommitUncertain)?;
        let context = original.evaluated_context().ok_or(Error::WrongScope)?;
        if context.receipt_context_binding() != pins.context.receipt_context_binding()
            || original.snapshot().receipts.len() != 5
            || !original.snapshot().receipts.starts_with(&pins.context.snapshot().receipts)
            || original.training_attestation() != pins.training.attestation()
            || supplied.receipts.get(4).is_some_and(|receipt| receipt != original.receipt())
            || self.selection.as_ref().is_some_and(|previous| previous != original) {
            return Err(Error::WrongScope);
        }
        owners.common.material.scope.validate_snapshot(original.snapshot())?;
        let sealed = original.evaluated_receipt().map_err(auth::selector_failure)?;
        sealed.original_receipt_predecessors(auth::now()?).map_err(|_| Error::WrongScope)?;
        self.selection = Some(original.clone());
        Ok(())
    }

    pub(super) fn pin_completion(&mut self, owners: &Owners, supplied: &LearningIterationSnapshotV1,
        original: &OriginalCircuitNextUseCommandReceiptV1) -> Result<(), Error> {
        let selection = self.selection.as_ref().ok_or(Error::CommitUncertain)?;
        let expected = selection.evaluated_receipt().map_err(auth::selector_failure)?;
        let actual = original.evaluated_selection().ok_or(Error::WrongScope)?;
        if actual.original_receipt_binding() != expected.original_receipt_binding()
            || original.snapshot().receipts.len() != 6
            || !original.snapshot().receipts.starts_with(&selection.snapshot().receipts)
            || original.training_attestation() != selection.training_attestation()
            || original.selection_attestation() != selection.attestation()
            || supplied.receipts.get(5).is_some_and(|receipt| receipt != original.receipt())
            || self.completion.as_ref().is_some_and(|previous| previous != original) {
            return Err(Error::WrongScope);
        }
        owners.common.material.scope.validate_snapshot(original.snapshot())?;
        auth::verify_receipt(&owners.common.material, original.receipt(), original.attestation(), auth::now()?)?;
        self.completion = Some(original.clone());
        Ok(())
    }

    pub(super) async fn read_selection(&mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1)
        -> Result<OriginalCircuitSelectionCommandReceiptV1, Error> {
        self.require_published().await?;
        self.bind_selector(owners)?;
        let original = OriginalCircuitSelectionCommandClientV1::readback(
            self.selector.as_ref().ok_or(Error::CommitUncertain)?,
        ).await.map_err(auth::selector_failure)?;
        self.pin_selection(owners, snapshot, &original)?;
        Ok(original)
    }

    pub(super) async fn read_completion(&mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1)
        -> Result<OriginalCircuitNextUseCommandReceiptV1, Error> {
        self.read_selection(owners, snapshot).await?;
        self.bind_next_use(owners)?;
        let ready = OriginalCircuitCompletionReadinessClientV1::read_current(
            self.readiness.as_ref().ok_or(Error::CommitUncertain)?,
        ).await.map_err(|_| Error::OwnerUnavailable("actual original evaluated C completion"))?
            .ok_or(Error::CommitUncertain)?;
        let original = OriginalCircuitNextUseCommandClientV1::readback(
            self.next_use.as_ref().ok_or(Error::CommitUncertain)?,
        ).await.map_err(auth::next_use_failure)?;
        if ready.observation() != &original.receipt().observation {
            return Err(Error::CommitUncertain);
        }
        self.pin_completion(owners, snapshot, &original)?;
        self.read_selection(owners, snapshot).await?;
        self.require_published().await?;
        Ok(original)
    }
}

impl Owners {
    pub(in super::super) async fn read_evaluated_retained_prefix(&self, snapshot: &LearningIterationSnapshotV1)
        -> Result<(), Error> {
        evaluated_prefix(snapshot)?;
        let mut lane = self.retained.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.failed { return Err(Error::CommitUncertain); }
        lane.failed = true;
        lane.refresh(self, snapshot).await?;
        // A four-cut checkpoint is evidence of completed B only. It does not
        // claim that publication or Selection has already occurred.
        match snapshot.receipts.len() {
            4 => {},
            5 => { lane.read_selection(self, snapshot).await?; },
            6 => { lane.read_completion(self, snapshot).await?; },
            _ => return Err(Error::WrongScope),
        }
        lane.refresh(self, snapshot).await?;
        self.require_live_deadline()?;
        lane.failed = false;
        Ok(())
    }

    pub(in super::super) async fn retained_attestation(&self, snapshot: &LearningIterationSnapshotV1,
        receipt: &LearningIterationReceiptV1) -> Result<SignedLearningEvidenceV1, Error> {
        evaluated_prefix(snapshot)?;
        let mut lane = self.retained.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.failed { return Err(Error::CommitUncertain); }
        lane.failed = true;
        lane.refresh(self, snapshot).await?;
        let (actual, signed) = match receipt.observation.stage() {
            Stage::Selection => {
                let original = lane.read_selection(self, snapshot).await?;
                (original.receipt().clone(), original.attestation().clone())
            },
            Stage::NextUse if snapshot.receipts.len() >= 5 => {
                let original = lane.read_completion(self, snapshot).await?;
                (original.receipt().clone(), original.attestation().clone())
            },
            _ => return Err(Error::WrongScope),
        };
        if actual != *receipt { return Err(Error::WrongScope); }
        lane.refresh(self, snapshot).await?;
        let fresh = auth::require_material(&self.common.material, self.common.initial_binding)?;
        auth::verify_receipt(&self.common.material, &actual, &signed, fresh)?;
        self.require_live_deadline()?;
        lane.failed = false;
        Ok(signed)
    }
}
