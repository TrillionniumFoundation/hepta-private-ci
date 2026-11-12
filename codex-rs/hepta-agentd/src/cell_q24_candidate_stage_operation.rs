//! One borrowed original-owner observation, never a retained CURRENT cache.
//! Its private guard fences cancellation and errors. All original E/D/T reads
//! bracket the work; Root consumes the result only after its own final I/O.

use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use tokio::sync::MutexGuard;

use super::super::auth;
use super::Error;
use super::OriginalCellQ24CandidateStageOwnersV1 as Owners;
use crate::OriginalCellEvaluationCommandReceiptV1;
use crate::OriginalCellQ24CandidateMaterialV1;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use crate::OriginalCellQ24ModelReadCompletionV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;
use crate::OriginalCircuitModelSelectionCommandReceiptV1;
use crate::OriginalCircuitCandidateNextUseCommandReceiptV1;
use crate::OriginalCircuitModelVersionPublicationV1;
use crate::OriginalCircuitCandidateLearningReadbackV1;

#[path = "cell_q24_candidate_stage_suffix.rs"]
mod suffix;

#[derive(Default)]
pub(super) struct OperationLane {
    failed: bool,
}

pub(super) struct CandidateOriginalOperation<'a> {
    owners: &'a Owners,
    lane: MutexGuard<'a, OperationLane>,
    pub(super) supplied: LearningIterationSnapshotV1,
    pub(super) training_cut: LearningIterationSnapshotV1,
    pub(super) dataset: OriginalCellQ24MaterialCommandReceiptV1,
    pub(super) training: OriginalCellQ24TrainingCommandReceiptV1,
    records: Vec<(LearningIterationReceiptV1, SignedLearningEvidenceV1)>,
    started: u64,
}

pub(super) struct ClosedCandidateOriginalOperation<'a>(CandidateOriginalOperation<'a>);

/// Only concrete original Candidate work constructs this borrowed, non-Clone
/// result. It is never serialized, stored on an owner, or accepted from a DTO.
pub(crate) struct OriginalCandidateOperationEvidence<'a> {
    operation: ClosedCandidateOriginalOperation<'a>,
    snapshot: LearningIterationSnapshotV1,
    evaluation: OriginalCellEvaluationCommandReceiptV1,
    model: Option<OriginalCellQ24ModelCommandReceiptV1>,
    model_completion: Option<OriginalCellQ24ModelReadCompletionV1>,
    selection: Option<OriginalCircuitModelSelectionCommandReceiptV1>,
    next_use: Option<OriginalCircuitCandidateNextUseCommandReceiptV1>,
    publication: Option<OriginalCircuitModelVersionPublicationV1>,
    completion_read: Option<OriginalCircuitCandidateLearningReadbackV1>,
}

impl<'a> CandidateOriginalOperation<'a> {
    pub(super) async fn begin(
        owners: &'a Owners,
        supplied: &LearningIterationSnapshotV1,
    ) -> Result<Self, Error> {
        let started = auth::now()?;
        owners.require_live_deadline()?;
        let training_cut = owners.training_prefix(supplied)?;
        let mut lane = owners.operation.try_lock().map_err(|_| Error::QueueFull)?;
        if lane.failed {
            return Err(Error::CommitUncertain);
        }
        // No error, cancelled await or dropped evidence can reopen this lane.
        lane.failed = true;
        let mut common = owners.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
        common.read_prefix(&owners.common, &training_cut).await?;
        let dataset = common.original_dataset.as_ref().ok_or(Error::CommitUncertain)?.clone();
        let training = common.original_training.as_ref().ok_or(Error::CommitUncertain)?.clone();
        let records = common.records[..3].to_vec();
        let fresh = auth::require_material(&owners.common.material, owners.common.initial_binding)?;
        auth::require_clock(started, fresh)?;
        auth::verify_prefix(&owners.common.material, &training_cut, &common, fresh)?;
        Ok(Self { owners, lane, supplied: supplied.clone(), training_cut, dataset, training, records, started })
    }

    pub(super) fn require_owner(&self, owners: &Owners) -> Result<(), Error> {
        if !std::ptr::eq(self.owners, owners) {
            return Err(Error::WrongScope);
        }
        owners.require_live_deadline()
    }

    pub(super) async fn close(self) -> Result<ClosedCandidateOriginalOperation<'a>, Error> {
        let mut common = self.owners.common.continuation.try_lock().map_err(|_| Error::QueueFull)?;
        common.read_prefix(&self.owners.common, &self.training_cut).await?;
        if common.original_dataset.as_ref() != Some(&self.dataset)
            || common.original_training.as_ref() != Some(&self.training)
            || common.records.get(..3) != Some(self.records.as_slice())
        {
            return Err(Error::CommitUncertain);
        }
        let fresh = auth::require_material(&self.owners.common.material, self.owners.common.initial_binding)?;
        auth::require_clock(self.started, fresh)?;
        auth::verify_prefix(&self.owners.common.material, &self.training_cut, &common, fresh)?;
        drop(common);
        Ok(ClosedCandidateOriginalOperation(self))
    }

    fn authenticate_prefix(&self, observed: u64) -> Result<u64, Error> {
        let fresh = auth::require_material(&self.owners.common.material, self.owners.common.initial_binding)?;
        auth::require_clock(self.started, observed)?;
        auth::require_clock(observed, fresh)?;
        self.owners.require_live_deadline()?;
        for (receipt, signature) in &self.records {
            auth::verify_receipt(&self.owners.common.material, receipt, signature, fresh)?;
        }
        Ok(fresh)
    }
}

impl<'a> ClosedCandidateOriginalOperation<'a> {
    pub(super) fn candidate(mut self, material: OriginalCellQ24CandidateMaterialV1) -> Result<OriginalCellQ24CandidateMaterialV1, Error> {
        let fresh = self.0.authenticate_prefix(auth::now()?)?;
        if material.receipt() != self.0.training.receipt()
            || material.attestation() != self.0.training.attestation()
        {
            return Err(Error::WrongScope);
        }
        auth::verify_receipt(&self.0.owners.common.material, material.receipt(), material.attestation(), fresh)?;
        self.0.lane.failed = false;
        Ok(material)
    }

    pub(super) fn evaluation(self, evaluation: OriginalCellEvaluationCommandReceiptV1) -> Result<OriginalCandidateOperationEvidence<'a>, Error> {
        let result = OriginalCandidateOperationEvidence { snapshot: evaluation.snapshot().clone(), operation: self, evaluation, model: None, model_completion: None, selection: None, next_use: None, publication: None, completion_read: None };
        result.authenticate_result(result.snapshot(), auth::now()?)?;
        Ok(result)
    }

    pub(super) fn model(
        self,
        completed: OriginalCellQ24ModelReadCompletionV1,
    ) -> Result<OriginalCandidateOperationEvidence<'a>, Error> {
        let model = completed.model().clone();
        let evaluation = completed.material().original_evaluation().clone();
        let result = OriginalCandidateOperationEvidence {
            snapshot: model.snapshot().clone(), operation: self, evaluation,
            model: Some(model), model_completion: Some(completed), selection: None, next_use: None,
            publication: None, completion_read: None,
        };
        result.authenticate_result(result.snapshot(), auth::now()?)?;
        Ok(result)
    }
    pub(super) fn selection(
        self,
        completed: OriginalCellQ24ModelReadCompletionV1,
        selection: OriginalCircuitModelSelectionCommandReceiptV1,
        publication: OriginalCircuitModelVersionPublicationV1,
    ) -> Result<OriginalCandidateOperationEvidence<'a>, Error> {
        let result = OriginalCandidateOperationEvidence {
            snapshot: selection.snapshot().clone(),
            evaluation: completed.material().original_evaluation().clone(),
            model: Some(completed.model().clone()),
            model_completion: Some(completed),
            selection: Some(selection),
            next_use: None,
            publication: Some(publication),
            completion_read: None,
            operation: self,
        };
        result.authenticate_result(result.snapshot(), auth::now()?)?;
        Ok(result)
    }

    pub(super) fn next_use(
        self,
        completed: OriginalCellQ24ModelReadCompletionV1,
        selection: OriginalCircuitModelSelectionCommandReceiptV1,
        next_use: OriginalCircuitCandidateNextUseCommandReceiptV1,
        publication: OriginalCircuitModelVersionPublicationV1,
        completion_read: OriginalCircuitCandidateLearningReadbackV1,
    ) -> Result<OriginalCandidateOperationEvidence<'a>, Error> {
        let result = OriginalCandidateOperationEvidence {
            snapshot: next_use.snapshot().clone(),
            evaluation: completed.material().original_evaluation().clone(),
            model: Some(completed.model().clone()),
            model_completion: Some(completed),
            selection: Some(selection),
            next_use: Some(next_use),
            publication: Some(publication),
            completion_read: Some(completion_read),
            operation: self,
        };
        result.authenticate_result(result.snapshot(), auth::now()?)?;
        Ok(result)
    }

}

impl OriginalCandidateOperationEvidence<'_> {
    pub(crate) fn snapshot(&self) -> &LearningIterationSnapshotV1 { &self.snapshot }

    pub(crate) fn receipt(&self) -> &LearningIterationReceiptV1 {
        if let Some(next_use) = &self.next_use { return next_use.receipt(); }
        if let Some(selection) = &self.selection { return selection.receipt(); }
        match &self.model { Some(model) => model.receipt(), None => self.evaluation.receipt() }
    }

    fn authenticate_result(&self, snapshot: &LearningIterationSnapshotV1, observed: u64) -> Result<Vec<SignedLearningEvidenceV1>, Error> {
        let operation = &self.operation.0;
        if snapshot != &self.snapshot { return Err(Error::WrongScope); }
        let fresh = operation.authenticate_prefix(observed)?;
        operation.owners.verify_original_evaluation(&operation.supplied, &operation.training_cut, &operation.training, &self.evaluation, fresh)?;
        let mut signatures: Vec<_> = operation.records.iter().map(|(_, signature)| signature.clone()).collect();
        signatures.push(self.evaluation.attestation().clone());
        if let Some(model) = &self.model {
            let completed: &OriginalCellQ24ModelReadCompletionV1 =
                self.model_completion.as_ref().ok_or(Error::CommitUncertain)?;
            if completed.model() != model
                || completed.material().original_evaluation() != &self.evaluation
            {
                return Err(Error::CommitUncertain);
            }
            // This includes every nested B/retention window after Root's last
            // actual I/O. The opaque completion lives only in this continuation.
            completed.material().authenticate_current(fresh)
                .map_err(|_| Error::CommitUncertain)?;
            let input = completed.material().require_original_model_input(
                &operation.training_cut, operation.training.attestation(), fresh,
            ).map_err(|_| Error::CommitUncertain)?;
            if input.material_digest() != model.material_digest() {
                return Err(Error::CommitUncertain);
            }
            if model.snapshot().request != snapshot.request
                || model.snapshot().owners != snapshot.owners
                || snapshot.receipts.get(..5) != Some(model.snapshot().receipts.as_slice())
                || model.snapshot().receipts.len() != 5
                || !model.snapshot().receipts.starts_with(&self.evaluation.snapshot().receipts)
                || operation.supplied.receipts.get(4).is_some_and(|expected| expected != model.receipt())
            { return Err(Error::WrongScope); }
            operation.owners.common.material.scope.validate_snapshot(model.snapshot())?;
            OriginalCellQ24ModelCommandReceiptV1::original_record_for_root(model, &signatures).map_err(|_| Error::WrongScope)?;
            self.authenticate_original_suffix(model, &mut signatures, fresh)?;
        } else if self.model_completion.is_some() || self.selection.is_some() || self.next_use.is_some()
            || self.publication.is_some() || self.completion_read.is_some()
            || self.evaluation.snapshot() != snapshot
        { return Err(Error::WrongScope); }
        Ok(signatures)
    }

    pub(crate) fn into_original_parts(mut self, owners: &Owners, snapshot: &LearningIterationSnapshotV1, observed: u64) -> Result<(Vec<SignedLearningEvidenceV1>, Option<OriginalCellQ24ModelCommandReceiptV1>), Error> {
        self.operation.0.require_owner(owners)?;
        let signatures = self.authenticate_result(snapshot, observed)?;
        self.operation.0.lane.failed = false;
        Ok((signatures, self.model))
    }

    pub(super) fn into_evaluation(self) -> Result<OriginalCellEvaluationCommandReceiptV1, Error> {
        let snapshot = self.snapshot.clone();
        let original = self.evaluation.clone();
        let owners = self.operation.0.owners;
        self.into_original_parts(owners, &snapshot, auth::now()?)?;
        Ok(original)
    }

    pub(super) fn into_model(self) -> Result<OriginalCellQ24ModelCommandReceiptV1, Error> {
        let snapshot = self.snapshot.clone();
        let owners = self.operation.0.owners;
        self.into_original_parts(owners, &snapshot, auth::now()?)?.1.ok_or(Error::WrongScope)
    }
}
