//! Same original Model file/witness and claim bytes, with closed current
//! Evaluation material. All capability verification here is pure; no Evaluator
//! RPC is allowed while the original Trainer lane is held.
use super::*;
use crate::OriginalCellEvaluationModelMaterialV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;

impl<W: AnchorWitnessStore> CellQ24ModelProposalOwnerV1<W> {
    pub(crate) fn create_from_current_material<T: AnchorWitnessStore>(
        file: File,
        mut witness: W,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset: LearningIterationSnapshotV1,
        training_cut: &LearningIterationSnapshotV1,
        training_attestation: &SignedLearningEvidenceV1,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<Self, Error> {
        let started = current_time()?;
        let (scope, binding) = admission::owner_binding(trainer, &dataset)?;
        if witness.current()?.is_some() {
            return Err(Error::Binding("proposal witness already initialized"));
        }
        admission::validate_current_material(
            trainer,
            &dataset,
            scope,
            binding,
            training_cut,
            training_attestation,
            material,
            started,
        )?;
        let fresh = current_time()?;
        require_material(material, started, fresh)?;
        if fresh >= dataset.request.envelope.expiry_unix_seconds {
            return Err(Error::Binding("original proposal deadline"));
        }
        // No writer exists before all actual Native/witness I/O and fresh full
        // material authentication. The host has already consumed shared once.
        Self::create_empty_original(file, witness, dataset, scope, binding)
    }

    /// Explicit deployment recovery only. The existing implementation may
    /// acknowledge an already persisted suffix. No command calls this method.
    pub(crate) fn recover_from_current_material<T: AnchorWitnessStore>(
        file: File,
        mut witness: W,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        dataset: LearningIterationSnapshotV1,
        training_cut: &LearningIterationSnapshotV1,
        training_attestation: &SignedLearningEvidenceV1,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<Self, Error> {
        let started = current_time()?;
        let (scope, binding) = admission::owner_binding(trainer, &dataset)?;
        let minimum = witness
            .current()?
            .ok_or(Error::Binding("original proposal witness"))?;
        admission::validate_current_material(
            trainer,
            &dataset,
            scope,
            binding,
            training_cut,
            training_attestation,
            material,
            started,
        )?;
        require_material(material, started, current_time()?)?;
        Self::recover_existing_original(file, witness, dataset, scope, binding, minimum)
    }

    pub(crate) fn commit_current_material_or_readback<T: AnchorWitnessStore>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        training_cut: &LearningIterationSnapshotV1,
        training_attestation: &SignedLearningEvidenceV1,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let started = self.now()?;
        let admission = self.admit_current_material(
            trainer,
            training_cut,
            training_attestation,
            material,
            started,
        )?;
        match ProductEvaluationExecutionStoreV1::readback(
            &mut self.journal,
            &admission.key(self.binding),
        ) {
            Ok(state) => {
                let receipt = self.decode_current(&admission, state)?;
                require_material(material, started, self.now()?)?;
                return Ok(receipt);
            }
            Err(ProductEvaluationExecutionStoreErrorV1::Missing) => {}
            Err(error) => return Err(error.into()),
        }
        self.require_current()?;
        let fresh = self.now()?;
        require_material(material, started, fresh)?;
        let payload = admission.encode(fresh)?;
        let receipt = self.complete_admitted(&admission, &admission.key(self.binding), &payload)?;
        // A late expiry is an uncertain committed proposal, never permission
        // to recreate its owner or rewrite the original timestamp.
        if require_material(material, started, self.now()?).is_err() {
            self.fenced = true;
            return Err(Error::CommitUncertain);
        }
        Ok(receipt)
    }

    pub(crate) fn read_current_material<T: AnchorWitnessStore>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        training_cut: &LearningIterationSnapshotV1,
        training_attestation: &SignedLearningEvidenceV1,
        material: &OriginalCellEvaluationModelMaterialV1,
    ) -> Result<CellQ24ModelProposalReceiptV1, Error> {
        let started = self.now()?;
        let admission = self.admit_current_material(
            trainer,
            training_cut,
            training_attestation,
            material,
            started,
        )?;
        let state = ProductEvaluationExecutionStoreV1::readback(
            &mut self.journal,
            &admission.key(self.binding),
        )?;
        let receipt = self.decode_current(&admission, state)?;
        require_material(material, started, self.now()?)?;
        Ok(receipt)
    }

    fn admit_current_material<T: AnchorWitnessStore>(
        &mut self,
        trainer: &mut CellQ24TrainingOwnerV1<T>,
        training_cut: &LearningIterationSnapshotV1,
        training_attestation: &SignedLearningEvidenceV1,
        material: &OriginalCellEvaluationModelMaterialV1,
        started: u64,
    ) -> Result<Admission, Error> {
        self.require_current()?;
        let admission = admission::validate_current_material(
            trainer,
            &self.dataset_cut,
            self.scope,
            self.binding,
            training_cut,
            training_attestation,
            material,
            started,
        )?;
        self.require_current()?;
        require_material(material, started, self.now()?)?;
        Ok(admission)
    }
}

fn current_time() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original Model clock before Unix epoch"))
}
fn require_material(
    material: &OriginalCellEvaluationModelMaterialV1,
    started: u64,
    fresh: u64,
) -> Result<(), Error> {
    if fresh < started {
        return Err(Error::Binding("original Model clock moved backwards"));
    }
    material
        .authenticate_current(fresh)
        .map_err(|error| Error::OriginalEvaluationMaterial(Box::new(error)))
}
