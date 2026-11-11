//! Bind already completed independent B resources to the actual Training cut.
//! The host transfers original files, witness and enrolled evaluator key. This
//! factory never manufactures holdout inputs or signs an execution result.

use std::fs::File;

use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::FileAnchorWitnessStore;
use ed25519_dalek::SigningKey;

use crate::CellEvaluationPlanV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationRunnerV1;
use crate::OriginalCellEvaluationTrainerV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellEvaluationReceiptConfigV1;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::OriginalCellQ24EvaluationStageV1;
use crate::OriginalCellQ24EvaluationTimingV1;
use crate::OriginalCellQ24LearningOpenV1;
use crate::cell_q24_learning_owner_error::owner_error;

pub struct OriginalCellQ24EvaluationInputsV1 {
    pub plan: CellEvaluationPlanV1,
    pub runner: CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    pub candidate: CellGenerationJournalV2<FileAnchorWitnessStore>,
    pub fixed_expert: CellGenerationJournalV2<FileAnchorWitnessStore>,
    pub candidate_plan: TemporalEvaluationPlan,
    pub baseline_plan: TemporalEvaluationPlan,
    pub executions: LockedFileProductEvaluationExecutionStoreV1,
    pub qualification: CellEvaluationQualificationV1,
    pub context: ProductQualificationContextV1,
    pub evidence: SignedEvaluationEvidenceV1,
    pub timing: OriginalCellQ24EvaluationTimingV1,
    pub trainer: OriginalCellEvaluationTrainerV1,
    pub receipt_file: File,
    pub receipt_witness: FileAnchorWitnessStore,
    pub signing: OriginalCellEvaluationSigningConfigV1,
    pub key: SigningKey,
    pub mode: OriginalCellQ24LearningOpenV1,
}

impl OriginalCellQ24EvaluationInputsV1 {
    pub(crate) fn into_stage(
        self,
        training: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
    ) -> Result<OriginalCellQ24EvaluationStageV1, Error> {
        let trainer: &OriginalCellEvaluationTrainerV1 = &self.trainer;
        trainer.require_training(&training, &scope)?;
        let verifier = self.signing.verifier.clone();
        let config = OriginalCellEvaluationReceiptConfigV1 {
            training: training.clone(),
            scope: scope.clone(),
            plan: self.plan.clone(),
            signing: self.signing,
        };
        let receipts = match self.mode {
            OriginalCellQ24LearningOpenV1::Create => OriginalCellEvaluationReceiptOwnerV1::create(
                self.receipt_file,
                self.receipt_witness,
                config,
                self.key,
            ),
            OriginalCellQ24LearningOpenV1::Recover => {
                OriginalCellEvaluationReceiptOwnerV1::recover(
                    self.receipt_file,
                    self.receipt_witness,
                    config,
                    self.key,
                )
            }
        }
        .map_err(owner_error)?;
        Ok(OriginalCellQ24EvaluationStageV1 {
            training,
            scope,
            runner: self.runner,
            candidate: self.candidate,
            fixed_expert: self.fixed_expert,
            candidate_plan: self.candidate_plan,
            baseline_plan: self.baseline_plan,
            executions: self.executions,
            receipts,
            qualification: self.qualification,
            context: self.context,
            evidence: self.evidence,
            timing: self.timing,
            trainer: self.trainer,
            verifier,
        })
    }
}
