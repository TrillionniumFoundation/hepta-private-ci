//! Concrete original B resources retained for learning and Model readback.
//! These are already admitted, independently completed evaluation owners. This
//! handoff neither manufactures B inputs nor reruns the final holdout.

use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationExecutionStoreV1;
use codex_hepta_intelligence_eval::LongitudinalTimeEvidenceV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::FileAnchorWitnessStore;

use crate::CellEvaluationJournalsV1;
use crate::CellEvaluationQualificationRequestV1;
use crate::CellEvaluationQualificationV1;
use crate::CellEvaluationReceiptV1;
use crate::CellEvaluationRunnerV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationTrainerV1;
use crate::cell_q24_learning_owner_error::owner_error;
use crate::neuron_cell_evaluation_receipt_owner::ReceiptSources;
use crate::neuron_cell_evaluation_training_source::OriginalCellEvaluationTrainerReadbackV1;

pub enum OriginalCellQ24EvaluationTimingV1 {
    Qualification,
    SystemLongitudinal {
        timing: LongitudinalTimeEvidenceV1,
        minimum_window_micros: u64,
    },
}

impl OriginalCellQ24EvaluationTimingV1 {
    fn borrow(&self) -> ProductTimingEvidenceV1<'_> {
        match self {
            Self::Qualification => ProductTimingEvidenceV1::Qualification,
            Self::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros: *minimum_window_micros,
            },
        }
    }
}

/// Original concrete resources, not arbitrary callbacks or an unsigned result.
/// Trainer evidence uses the pinned original peer or the same original Q24
/// owner's sealed readback handle; both retain independent B verification.
pub struct OriginalCellQ24EvaluationStageV1 {
    pub training: LearningIterationSnapshotV1,
    pub scope: FrozenLearningScopeV2,
    pub runner: CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    pub candidate: CellGenerationJournalV2<FileAnchorWitnessStore>,
    pub fixed_expert: CellGenerationJournalV2<FileAnchorWitnessStore>,
    pub candidate_plan: TemporalEvaluationPlan,
    pub baseline_plan: TemporalEvaluationPlan,
    pub executions: LockedFileProductEvaluationExecutionStoreV1,
    pub receipts: OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore>,
    pub qualification: CellEvaluationQualificationV1,
    pub context: ProductQualificationContextV1,
    pub evidence: SignedEvaluationEvidenceV1,
    pub timing: OriginalCellQ24EvaluationTimingV1,
    pub trainer: OriginalCellEvaluationTrainerV1,
    pub verifier: LearningEvidenceVerifierV1,
}

impl OriginalCellQ24EvaluationStageV1 {
    pub(crate) fn require_training(
        &mut self,
        training: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        if &self.training != training
            || &self.scope != scope
            || training.owners.evidence_trust_digest != self.verifier.trust_digest()
        {
            return Err(Error::WrongScope);
        }
        let trainer: &OriginalCellEvaluationTrainerV1 = &self.trainer;
        trainer.require_training(training, scope)?;
        self.receipts
            .require_original_training(training, scope)
            .map_err(owner_error)?;
        self.read_execution()?;
        Ok(())
    }

    pub(crate) async fn require_original_training_evidence(
        &self,
        original: &SignedLearningEvidenceV1,
    ) -> Result<(), Error> {
        let receipt = self.training.receipts.last().ok_or(Error::WrongScope)?;
        let trainer: OriginalCellEvaluationTrainerReadbackV1<'_> = self.trainer.borrow();
        if &trainer.readback(&self.training, receipt).await? != original {
            return Err(Error::WrongScope);
        }
        Ok(())
    }

    pub(crate) fn read_execution(&mut self) -> Result<CellEvaluationReceiptV1, Error> {
        let Self {
            training,
            runner,
            candidate,
            fixed_expert,
            candidate_plan,
            baseline_plan,
            executions,
            receipts,
            qualification,
            context,
            evidence,
            timing,
            trainer,
            ..
        } = self;
        let receipts: &mut OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore> = receipts;
        let trainer: &OriginalCellEvaluationTrainerV1 = trainer;
        receipts
            .read_original_execution(ReceiptSources {
                snapshot: training,
                runner,
                journals: CellEvaluationJournalsV1 {
                    candidate,
                    fixed_expert,
                },
                candidate_plan,
                baseline_plan,
                executions,
                qualification,
                context,
                evidence,
                timing: timing.borrow(),
                trainer: trainer.borrow(),
            })
            .map_err(owner_error)
    }

    pub(crate) fn qualification_request(
        &self,
    ) -> Result<CellEvaluationQualificationRequestV1<'_>, Error> {
        Ok(CellEvaluationQualificationRequestV1 {
            context: &self.context,
            evidence: &self.evidence,
            timing: self.timing.borrow(),
            verifier: &self.verifier,
            now: now()?,
        })
    }

    pub(crate) async fn complete(
        &mut self,
        snapshot: &LearningIterationSnapshotV1,
        read_only: bool,
    ) -> Result<(LearningIterationReceiptV1, SignedLearningEvidenceV1), Error> {
        let Self {
            runner,
            candidate,
            fixed_expert,
            candidate_plan,
            baseline_plan,
            executions,
            receipts,
            qualification,
            context,
            evidence,
            timing,
            trainer,
            ..
        } = self;
        let receipts: &mut OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore> = receipts;
        let trainer: &OriginalCellEvaluationTrainerV1 = trainer;
        let source = ReceiptSources {
            snapshot,
            runner,
            journals: CellEvaluationJournalsV1 {
                candidate,
                fixed_expert,
            },
            candidate_plan,
            baseline_plan,
            executions,
            qualification,
            context,
            evidence,
            timing: timing.borrow(),
            trainer: trainer.borrow(),
        };
        if read_only {
            receipts.readback_sources(source).await.map_err(owner_error)
        } else {
            receipts
                .attest_original_sources(source)
                .await
                .map_err(owner_error)
        }
    }
}

fn now() -> Result<u64, Error> {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| Error::OwnerUnavailable("original owner clock"))
}
