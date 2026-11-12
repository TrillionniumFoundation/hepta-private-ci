//! Actual Dataset/Trainer and original publication observations in one host.
//! Full signatures are pinned; no observed result substitutes for a later read.
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;

use super::super::super::context::PublicationAccess;
use super::super::Error;
use super::super::RetainedVersionPurposeV1;
use super::super::RetainedVersionOriginV1;
use crate::{OriginalCellEvaluationCommandClientV1, OriginalCellEvaluationCommandConnectionV1};
use super::super::OriginalCircuitRetainedVersionReadbackV1;
use super::super::context::OriginalVersionCut;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionHostPhaseV1;
use super::RetainedVersionHostStateV1;
use super::artifact;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::NeuronGenerationUpdateReadbackV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;

impl OriginalCircuitRetainedVersionHostV1 {
    pub(super) fn bind_original_predecessor(
        &self,
        state: &mut RetainedVersionHostStateV1,
    ) -> Result<(), Error> {
        self.require_lifetime()?;
        if state.cut.is_some() {
            return state.require_cut_current(&self.runtime);
        }
        let dataset = self
            .runtime
            .block_on(OriginalCellQ24DatasetCommandReadbackV1::readback(
                &state.dataset,
            ))?;
        OriginalCellQ24DatasetCommandReadbackV1::verify_original_cut(&state.dataset, &dataset)?;
        let original = state
            .initial_trainer
            .take()
            .ok_or(Error::ReadbackRequired)?;
        let trainer = OriginalCellQ24TrainingCommandConnectionV1::bind_original_dataset(
            original,
            dataset.clone(),
        )?;
        let training = self
            .runtime
            .block_on(OriginalCellQ24TrainingCommandClientV1::readback(&trainer))?;
        let (cut, evaluator) = match self.purpose {
            RetainedVersionPurposeV1::TrainingNoUpdate => (
                OriginalVersionCut::from_original(self.material.clone(), dataset, &training, self.origin)?,
                None,
            ),
            RetainedVersionPurposeV1::EvaluatedNoUpdate => {
                let initial = state.initial_evaluator.take().ok_or(Error::ReadbackRequired)?;
                let evaluator = OriginalCellEvaluationCommandConnectionV1::bind_original_training(
                    initial, dataset.snapshot().clone(), &training)?;
                let evaluation = self.runtime.block_on(
                    OriginalCellEvaluationCommandClientV1::readback(&evaluator))?;
                let cut = OriginalVersionCut::from_original_evaluated(
                    self.material.clone(), dataset, &training, &evaluation, self.origin)?;
                (cut, Some(evaluator))
            }
        };
        if let Some(expected) = &state.expected {
            let mut signatures = cut.dataset.attestations().to_vec();
            signatures.push(cut.training.training_evidence.clone());
            if let Some(context) = &cut.evaluated {
                signatures.push(context.evaluation_attestation().clone());
            }
            if expected.training != cut.training.training || expected.attestations != signatures {
                return Err(Error::Binding(
                    "same original complete cold E/D/T checkpoint",
                ));
            }
        }
        cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        state.trainer = Some(trainer);
        state.evaluator = evaluator;
        state.cut = Some(cut);
        Ok(())
    }

    /// A recovered publication is not a ready reader until the actual original
    /// predecessors, Artifact/CURRENT and held C owners agree across its read.
    /// A failed predecessor/publication read removes admission for new
    /// connections. Existing read-only connections keep their own checks.
    pub(super) fn read_original_recovery(
        &self,
        state: &mut RetainedVersionHostStateV1,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        if self.origin != RetainedVersionOriginV1::Recovered {
            return self.read_original(state);
        }
        let retained_reader = state.selection_reader.take();
        let before = self.read_original(state)?;
        let reader = match retained_reader {
            Some(reader) => reader,
            None => state.build_original_selection_reader()?.ok_or(Error::ReadbackRequired)?,
        };
        let after = self.read_original(state)?;
        if before != after || after.publication().is_none() {
            return Err(Error::CommitUncertain);
        }
        state.cut.as_ref().ok_or(Error::Unavailable)?
            .require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        self.require_lifetime()?;
        state.selection_reader = Some(reader);
        self.installed.notify_waiters();
        Ok(after)
    }

    pub(super) fn read_original(
        &self,
        state: &RetainedVersionHostStateV1,
    ) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        let started = super::super::now()?;
        self.require_lifetime()?;
        state.require_cut_current(&self.runtime)?;
        let before = state.artifacts.read_current()?;
        let first = state.observe_phase()?;
        // The second original peer reads cannot turn the first physical
        // publication read into a current one. Re-read the actual owner last.
        state.require_cut_current(&self.runtime)?;
        let last = state.observe_phase()?;
        let after = state.artifacts.read_current()?;
        artifact::require_same(&before, &after)?;
        if first != last {
            return Err(Error::Binding("original retained version changed"));
        }
        self.require_lifetime()?;
        state
            .cut
            .as_ref()
            .ok_or(Error::Unavailable)?
            .require_fresh(started, PublicationAccess::Readback)?;
        Ok(last)
    }
}

impl RetainedVersionHostStateV1 {
    pub(super) fn install_original_selection_reader(&mut self) -> Result<(), Error> {
        if self.selection_reader.is_some() {
            return Ok(());
        }
        self.selection_reader = self.build_original_selection_reader()?;
        Ok(())
    }

    fn build_original_selection_reader(&self) -> Result<Option<std::sync::Arc<
        crate::OriginalCircuitLearningReadOwnerV1<
            codex_hepta_neuron::FileAnchorWitnessStore,
            codex_hepta_neuron::FileAnchorWitnessStore,
        >,
    >>, Error> {
        let original = match self.phase.as_ref() {
            Some(
                RetainedVersionHostPhaseV1::Installed { original, .. }
                | RetainedVersionHostPhaseV1::Recovered(original),
            ) => original,
            _ => return Ok(None),
        };
        let cut = self.cut.as_ref().ok_or(Error::Unavailable)?;
        let reader = match &cut.evaluated {
            None => {
                let context = crate::OriginalCircuitLearningReadContextV1 {
                    prefix: cut.training.training.clone(), scope: cut.training.scope.clone(),
                    verifier: cut.training.verifier.clone(),
                    training_evidence: cut.training.training_evidence.clone(), selection_evidence: None,
                };
                crate::OriginalCircuitLearningReadOwnerV1::from_original_owners(
                    original.cell.clone(), original.source.as_ref().clone(), original.identity.clone(), context)
            }
            Some(evaluated) => {
                let context = crate::OriginalCircuitEvaluatedLearningReadContextV1::for_original_selection(evaluated.clone_for_original_receipt())
                    .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
                crate::OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(
                    original.cell.clone(), original.source.as_ref().clone(), original.identity.clone(), context)
            }
        }.map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        Ok(Some(std::sync::Arc::new(reader)))
    }

    fn original_trainer(&self) -> Result<&OriginalCellQ24TrainingCommandClientV1, Error> {
        match self.phase.as_ref().ok_or(Error::CommitUncertain)? {
            RetainedVersionHostPhaseV1::Prepared { original, .. } => Ok(original.trainer()),
            _ => self.trainer.as_ref().ok_or(Error::Unavailable),
        }
    }

    fn original_evaluator(&self) -> Result<&OriginalCellEvaluationCommandClientV1, Error> {
        match self.phase.as_ref().ok_or(Error::CommitUncertain)? {
            RetainedVersionHostPhaseV1::Prepared { original, .. } => original.evaluator().ok_or(Error::Unavailable),
            _ => self.evaluator.as_ref().ok_or(Error::Unavailable),
        }
    }

    pub(super) fn require_cut_current(
        &self,
        runtime: &tokio::runtime::Handle,
    ) -> Result<(), Error> {
        let started = super::super::now()?;
        let cut = self.cut.as_ref().ok_or(Error::Unavailable)?;
        let actual = runtime.block_on(OriginalCellQ24DatasetCommandReadbackV1::readback(
            &self.dataset,
        ))?;
        OriginalCellQ24DatasetCommandReadbackV1::verify_original_cut(&self.dataset, &actual)?;
        if actual != cut.dataset {
            return Err(Error::Binding(
                "same actual original E/D receipt and signatures",
            ));
        }
        match &cut.evaluated {
            None => runtime.block_on(cut.training.require_training_current(
                self.original_trainer()?, PublicationAccess::Readback))?,
            Some(context) => runtime.block_on(context.require_current(
                self.original_trainer()?, self.original_evaluator()?, PublicationAccess::Readback))?,
        }
        cut.require_fresh(started, PublicationAccess::Readback)
    }

    fn observe_phase(&self) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        let cut = self.cut.as_ref().ok_or(Error::Unavailable)?;
        match self.phase.as_ref().ok_or(Error::CommitUncertain)? {
            RetainedVersionHostPhaseV1::Awaiting { .. } => Err(Error::ReadbackRequired),
            RetainedVersionHostPhaseV1::Prepared { original, .. } => {
                let coordinator =
                    LearningIterationCoordinatorV1::from_snapshot(cut.training.training.clone())?;
                let operation = crate::learning_retained_task_operation_id_v1(&coordinator)?;
                let intent = original.intent_digest();
                let prepared = NeuronGenerationCurrentOwnerV1::recover_operation(
                    &self.control,
                    operation.as_str(),
                    intent,
                )?;
                if !matches!(
                    NeuronGenerationCurrentOwnerV1::read_operation(&self.control, &prepared,)?,
                    NeuronGenerationUpdateReadbackV1::Prepared
                ) {
                    // A published Control record is not an already held C
                    // Source/Cell owner, and never causes factory replay.
                    return Err(Error::CommitUncertain);
                }
                Ok(OriginalCircuitRetainedVersionReadbackV1 {
                    intent,
                    publication: None,
                })
            }
            RetainedVersionHostPhaseV1::Installed { original, .. }
            | RetainedVersionHostPhaseV1::Recovered(original) => original.observe(cut),
        }
    }
}
