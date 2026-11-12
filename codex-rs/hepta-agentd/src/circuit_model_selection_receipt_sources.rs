//! Concrete read-only sources for positive Model Selection.
//! Original files and independent witnesses stay held. No cached observation,
//! reconstructed version journal or caller-selected clock satisfies this path.

use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionRequestV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;

use super::*;
use crate::CellEvaluationJournalsV1;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationRunnerV1;
use crate::CellQ24ModelProposalInputsV1;
use crate::CellQ24ModelProposalOwnerV1;
use crate::LearningIterationEvidenceClientV1;
use crate::OriginalCellEvaluationExecutionStoreV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::SourceBoundCellQ24TrainingStageV1;

/// The original host must retain this execution witness before admitting work
/// and advance it with its original store. This reader never creates, repairs
/// or advances a missing witness. Joint rollback remains outside this proof.
pub struct OriginalCircuitModelSelectionEvaluationSourcesV1<
    'a,
    S,
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
    W: AnchorWitnessStore,
> {
    pub runner: &'a mut CellEvaluationRunnerV1<S>,
    pub journals: CellEvaluationJournalsV1<'a, C, F>,
    pub candidate_plan: &'a TemporalEvaluationPlan,
    pub baseline_plan: &'a TemporalEvaluationPlan,
    pub executions: &'a mut OriginalCellEvaluationExecutionStoreV1<W>,
    pub context: &'a ProductQualificationContextV1,
    pub timing: ProductTimingEvidenceV1<'a>,
}

/// The Model is read only through the same original SourceBound trainer lane.
/// The learning Evaluator remains a separately admitted, purpose-bound peer.
/// No original role key, writer descriptor or generic callback is extracted.
pub struct OriginalCircuitModelSelectionReceiptSourcesV1<
    'a,
    C: AnchorWitnessStore,
    TW: AnchorWitnessStore,
    RW: AnchorWitnessStore,
    MW: AnchorWitnessStore,
    S,
    EC: AnchorWitnessStore,
    EF: AnchorWitnessStore,
    EW: AnchorWitnessStore,
> {
    pub snapshot: &'a LearningIterationSnapshotV1,
    pub cell: &'a PublishedCircuitCellOwnerV1<C>,
    pub training_stage: &'a SourceBoundCellQ24TrainingStageV1<TW, RW>,
    pub model: &'a mut CellQ24ModelProposalOwnerV1<MW>,
    pub evaluation: OriginalCircuitModelSelectionEvaluationSourcesV1<'a, S, EC, EF, EW>,
    pub trainer: &'a LearningIterationEvidenceClientV1,
    pub evaluator: &'a LearningIterationEvidenceClientV1,
}

impl<
    C: AnchorWitnessStore,
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
    MW: AnchorWitnessStore,
    S: FinalHoldoutCasStoreV1,
    EC: AnchorWitnessStore,
    EF: AnchorWitnessStore,
    EW: AnchorWitnessStore,
> OriginalCircuitModelSelectionReceiptSourcesV1<'_, C, TW, RW, MW, S, EC, EF, EW>
{
    pub(super) fn prepare(
        &mut self,
        config: &OriginalCircuitModelSelectionReceiptConfigV1,
        training: &LearningIterationSnapshotV1,
        fenced: &mut bool,
    ) -> Result<Prepared, Error> {
        let result = (|| {
            LearningIterationCoordinatorV1::from_snapshot(self.snapshot.clone())?;
            config.scope.validate_snapshot(self.snapshot)?;
            if self.snapshot.request != config.decision.request
                || self.snapshot.owners != config.decision.owners
                || !self
                    .snapshot
                    .receipts
                    .starts_with(&config.decision.receipts)
            {
                return Err(OwnerError::Binding("original Model decision prefix").into());
            }
            self.evaluation.read_original(config)?;
            let request = CellEvaluationQualificationRequestV1 {
                context: self.evaluation.context,
                evidence: &config.product_evidence,
                timing: self.evaluation.timing(),
                verifier: &config.verifier,
                now: binding::now()?,
            };
            let inputs = CellQ24ModelProposalInputsV1 {
                training_cut: training,
                training_attestation: &config.training_evidence,
                runner: &*self.evaluation.runner,
                evaluation: &config.evaluation,
                qualification: &config.qualification,
                request: &request,
            };
            let model = SourceBoundCellQ24TrainingStageV1::read_model_proposal(
                self.training_stage,
                self.model,
                &inputs,
            )?;
            if Some(model.learning_receipt()) != config.decision.receipts.last() {
                return Err(OwnerError::Binding("exact original Model Proposal receipt").into());
            }
            let coordinator =
                LearningIterationCoordinatorV1::from_snapshot(config.decision.clone())?;
            let cell: &PublishedCircuitCellOwnerV1<_> = self.cell;
            let observation = cell.read_learning_selection(&coordinator)?;
            config.scope.validate_observation(&observation)?;
            self.evaluation.read_original(config)?;
            let bundle = self
                .evaluation
                .runner
                .qualification_bundle(&config.evaluation, self.evaluation.context)?;
            Ok(Prepared {
                observation,
                bundle,
            })
        })();
        if result.is_err() {
            *fenced = true;
        }
        result
    }

    pub(super) fn predecessors(
        &self,
        config: &OriginalCircuitModelSelectionReceiptConfigV1,
        runtime: &Handle,
    ) -> Result<(SignedLearningEvidenceV1, SignedLearningEvidenceV1), Error> {
        let training = binding::training_receipt(config)?;
        let evaluation = binding::evaluation_receipt(config)?;
        let trainer: &LearningIterationEvidenceClientV1 = self.trainer;
        let evaluator: &LearningIterationEvidenceClientV1 = self.evaluator;
        // This is the host's bounded blocking lane. No Model or Ledger lock is
        // held while waiting on the two admitted original owner connections.
        runtime.block_on(async {
            let training = trainer.readback(self.snapshot, training).await?;
            let evaluation = evaluator.readback(self.snapshot, evaluation).await?;
            Ok((training, evaluation))
        })
    }
}

impl<S: FinalHoldoutCasStoreV1, C: AnchorWitnessStore, F: AnchorWitnessStore, W: AnchorWitnessStore>
    OriginalCircuitModelSelectionEvaluationSourcesV1<'_, S, C, F, W>
{
    pub(super) fn timing(&self) -> ProductTimingEvidenceV1<'_> {
        match &self.timing {
            ProductTimingEvidenceV1::Qualification => ProductTimingEvidenceV1::Qualification,
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros: *minimum_window_micros,
            },
        }
    }

    fn read_original(
        &mut self,
        config: &OriginalCircuitModelSelectionReceiptConfigV1,
    ) -> Result<(), Error> {
        let clock = || binding::now().map_err(|_| ProductProviderErrorV1::Unavailable);
        let runner: &mut CellEvaluationRunnerV1<S> = self.runner;
        let mut executions = OriginalCellEvaluationExecutionStoreV1::readback_only(
            self.executions,
            config.execution_evidence.key(),
        );
        let (evaluation, execution) = runner.readback_completed_evidence(
            config.evaluation.plan(),
            CellEvaluationJournalsV1 {
                candidate: self.journals.candidate,
                fixed_expert: self.journals.fixed_expert,
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: config.evaluation.plan().product_plan(),
                candidate_plan: self.candidate_plan,
                baseline_plan: self.baseline_plan,
                evaluator: &config.qualification.product().evaluator,
                verifier: &config.verifier,
                clock: &clock,
            },
            &mut executions,
        )?;
        if evaluation != config.evaluation || execution != config.execution_evidence {
            return Err(OwnerError::Binding("exact original completed evaluation evidence").into());
        }
        Ok(())
    }
}
