//! Actual Dataset/Trainer/Evaluator and publication observations in one host.
//! Full signatures are pinned; no observed result substitutes for a later read.
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;

use super::super::super::context::PublicationAccess;
use super::super::Error;
use super::super::OriginalCircuitRetainedVersionReadbackV1;
use super::super::RetainedVersionOriginV1;
use super::super::context::OriginalVersionCut;
use super::super::evaluated_context::OriginalEvaluatedVersionCut;
use super::super::profile::VersionCut;
use super::super::profile::VersionPurpose;
use super::OriginalCircuitRetainedVersionHostV1;
use super::RetainedVersionHostPhaseV1;
use super::RetainedVersionHostStateV1;
use super::SharedEvaluatedReadbacks;
use super::artifact;
use crate::NeuronGenerationCurrentOwnerV1;
use crate::NeuronGenerationUpdateReadbackV1;
use crate::OriginalCellEvaluationCommandClientV1;
use crate::OriginalCellEvaluationCommandConnectionV1;
use crate::OriginalCellQ24DatasetCommandReadbackV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandConnectionV1;

impl OriginalCircuitRetainedVersionHostV1 {
    pub(super) fn bind_original_predecessor(
        &self,
        state: &mut RetainedVersionHostStateV1,
    ) -> Result<(), Error> {
        self.require_lifetime()?;
        if let Some(cut) = state.cut.as_ref() {
            if cut.purpose() != self.purpose || cut.initial_binding() != self.initial_binding {
                return Err(Error::Binding("same original Version bound predecessor"));
            }
            return match cut {
                VersionCut::TrainingNoUpdate(_) => state.require_cut_current(&self.runtime),
                // Binding is not CURRENT. Every evaluated caller immediately
                // performs its own complete before/after owner transaction.
                // Do not spend a third live read before that same transaction.
                VersionCut::Evaluated(_) => {
                    cut.require_fresh(super::super::now()?, PublicationAccess::Readback)
                }
            };
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
            VersionPurpose::TrainingNoUpdate => (
                VersionCut::TrainingNoUpdate(OriginalVersionCut::from_original(
                    self.material.clone(),
                    dataset,
                    &training,
                    self.origin,
                )?),
                None,
            ),
            VersionPurpose::Evaluated => {
                let original = state
                    .initial_evaluator
                    .take()
                    .ok_or(Error::ReadbackRequired)?;
                let evaluator = OriginalCellEvaluationCommandConnectionV1::bind_original_training(
                    original,
                    dataset.snapshot().clone(),
                    &training,
                )?;
                let evaluation = self
                    .runtime
                    .block_on(OriginalCellEvaluationCommandClientV1::readback(&evaluator))?;
                let cut = OriginalEvaluatedVersionCut::from_original(
                    self.material.clone(),
                    dataset,
                    &training,
                    &evaluation,
                    self.origin,
                )?;
                (VersionCut::Evaluated(cut), Some(evaluator))
            }
        };
        if cut.purpose() != self.purpose || cut.initial_binding() != self.initial_binding {
            return Err(Error::Binding(
                "same original Version purpose and initial context",
            ));
        }
        if let Some(expected) = &state.expected {
            let VersionCut::TrainingNoUpdate(cut) = &cut else {
                return Err(Error::Binding("original cold three-cut Version purpose"));
            };
            let mut signatures = cut.dataset.attestations().to_vec();
            signatures.push(cut.training.training_evidence.clone());
            if expected.training != cut.training.training || expected.attestations != signatures {
                return Err(Error::Binding(
                    "same original complete cold E/D/T checkpoint",
                ));
            }
        }
        if let Some(expected) = &state.expected_evaluated {
            let VersionCut::Evaluated(cut) = &cut else {
                return Err(Error::Binding("original cold four-cut Version purpose"));
            };
            if expected.dataset != cut.dataset
                || expected.evaluation.snapshot() != cut.evaluated.snapshot()
                || expected.evaluation.receipt_context_binding()
                    != cut.evaluated.receipt_context_binding()
            {
                return Err(Error::Binding(
                    "same original complete cold E/D/T/B checkpoint",
                ));
            }
        }
        cut.require_fresh(super::super::now()?, PublicationAccess::Readback)?;
        if self.origin == RetainedVersionOriginV1::Recovered
            && matches!(&cut, VersionCut::Evaluated(_))
        {
            if !matches!(state.phase, Some(RetainedVersionHostPhaseV1::Recovered(_))) {
                return Err(Error::ReadbackRequired);
            }
            state.shared_evaluated = Some(SharedEvaluatedReadbacks {
                trainer: std::sync::Arc::new(trainer),
                evaluator: std::sync::Arc::new(evaluator.ok_or(Error::ReadbackRequired)?),
            });
        } else {
            state.trainer = Some(trainer);
            state.evaluator = evaluator;
        }
        state.cut = Some(cut);
        state.install_original_selection_reader()?;
        Ok(())
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
        let original = match self.phase.as_ref() {
            Some(
                RetainedVersionHostPhaseV1::Installed { original, .. }
                | RetainedVersionHostPhaseV1::Recovered(original),
            ) => original,
            _ => return Ok(()),
        };
        let cut = self.cut.as_ref().ok_or(Error::Unavailable)?;
        let reader = match cut {
            VersionCut::TrainingNoUpdate(_) => {
                crate::OriginalCircuitLearningReadOwnerV1::from_original_owners(
                    original.cell.clone(),
                    original.source.as_ref().clone(),
                    original.identity.clone(),
                    cut.legacy_reader()?,
                )
            }
            VersionCut::Evaluated(_) => {
                crate::OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners(
                    original.cell.clone(),
                    original.source.as_ref().clone(),
                    original.identity.clone(),
                    cut.evaluated_reader()?,
                )
            }
        };
        let reader =
            reader.map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))?;
        self.selection_reader = Some(std::sync::Arc::new(reader));
        Ok(())
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
        if &actual != cut.dataset() {
            return Err(Error::Binding(
                "same actual original E/D receipt and signatures",
            ));
        }
        match self.phase.as_ref().ok_or(Error::CommitUncertain)? {
            RetainedVersionHostPhaseV1::Prepared { original, .. } => {
                runtime.block_on(original.require_current(cut))?;
            }
            _ => match cut {
                VersionCut::TrainingNoUpdate(cut) => {
                    runtime.block_on(cut.training.require_training_current(
                        self.trainer.as_ref().ok_or(Error::Unavailable)?,
                        PublicationAccess::Readback,
                    ))?
                }
                VersionCut::Evaluated(cut) => {
                    match self.phase.as_ref().ok_or(Error::CommitUncertain)? {
                        RetainedVersionHostPhaseV1::Awaiting { .. } => {
                            runtime.block_on(cut.evaluated.require_current(
                                self.trainer.as_ref().ok_or(Error::Unavailable)?,
                                self.evaluator.as_ref().ok_or(Error::Unavailable)?,
                                PublicationAccess::Readback,
                            ))?
                        }
                        RetainedVersionHostPhaseV1::Installed { .. }
                        | RetainedVersionHostPhaseV1::Recovered(_) => {
                            let shared =
                                self.shared_evaluated.as_ref().ok_or(Error::Unavailable)?;
                            runtime.block_on(cut.evaluated.require_current(
                                &shared.trainer,
                                &shared.evaluator,
                                PublicationAccess::Readback,
                            ))?;
                        }
                        RetainedVersionHostPhaseV1::Prepared { .. } => {
                            return Err(Error::CommitUncertain);
                        }
                    }
                }
            },
        }
        cut.require_fresh(started, PublicationAccess::Readback)
    }

    fn observe_phase(&self) -> Result<OriginalCircuitRetainedVersionReadbackV1, Error> {
        let cut = self.cut.as_ref().ok_or(Error::Unavailable)?;
        match self.phase.as_ref().ok_or(Error::CommitUncertain)? {
            RetainedVersionHostPhaseV1::Awaiting { .. } => Err(Error::ReadbackRequired),
            RetainedVersionHostPhaseV1::Prepared { original, .. } => {
                let coordinator =
                    LearningIterationCoordinatorV1::from_snapshot(cut.snapshot().clone())?;
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
