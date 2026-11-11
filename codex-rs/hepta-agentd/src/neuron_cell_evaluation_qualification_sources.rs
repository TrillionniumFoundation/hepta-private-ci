//! The concrete original owners required for Qualification, borrowed per call.
//! This never accepts a cached receipt, arbitrary sink, caller clock or provider.
use codex_hepta_intelligence_eval::ProductEvaluationExecutionRequestV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;

use super::*;
use crate::CellEvaluationJournalsV1;
use crate::LearningIterationEvidenceClientV1;

pub struct OriginalCellEvaluationQualificationSourcesV1<
    'a, C: AnchorWitnessStore, F: AnchorWitnessStore, X: AnchorWitnessStore,
> {
    pub runner: &'a mut CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    pub journals: CellEvaluationJournalsV1<'a, C, F>,
    pub candidate_plan: &'a TemporalEvaluationPlan,
    pub baseline_plan: &'a TemporalEvaluationPlan,
    pub executions: &'a mut OriginalCellEvaluationExecutionStoreV1<X>,
    pub trainer: &'a LearningIterationEvidenceClientV1,
}

impl<C: AnchorWitnessStore, F: AnchorWitnessStore, X: AnchorWitnessStore>
    OriginalCellEvaluationQualificationSourcesV1<'_, C, F, X>
{
    fn read_original(
        &mut self,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<Prepared, Error> {
        let clock = || binding::now().map_err(|_| ProductProviderErrorV1::Unavailable);
        let mut executions = OriginalCellEvaluationExecutionStoreV1::readback_only(
            self.executions, config.execution_evidence.key(),
        );
        let runner: &mut CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> = self.runner;
        let (evaluation, execution) = runner.readback_completed_evidence(
            &config.plan,
            CellEvaluationJournalsV1 {
                candidate: self.journals.candidate,
                fixed_expert: self.journals.fixed_expert,
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: config.plan.product_plan(),
                candidate_plan: self.candidate_plan,
                baseline_plan: self.baseline_plan,
                evaluator: &config.context.evaluator,
                verifier: &config.verifier,
                clock: &clock,
            },
            &mut executions,
        )?;
        if execution != config.execution_evidence || evaluation.plan() != &config.plan {
            return Err(Error::Binding("exact original Qualification execution evidence"));
        }
        evaluation.require_original_signed_execution(&config.context.evaluator)?;
        let bundle = runner.qualification_bundle(&evaluation, &config.context)?;
        Ok(Prepared { evaluation, bundle })
    }

    pub(super) async fn read_trainer(
        &self,
        config: &OriginalCellEvaluationQualificationConfigV1,
    ) -> Result<(), Error> {
        let trainer: &LearningIterationEvidenceClientV1 = self.trainer;
        let original = trainer.readback(
            &config.training, binding::training_receipt(config)?,
        ).await?;
        if original != config.training_evidence {
            return Err(Error::Binding("changed original Qualification Training signature"));
        }
        Ok(())
    }

    pub(super) async fn prepare(
        &mut self,
        config: &OriginalCellEvaluationQualificationConfigV1,
        started_at: u64,
    ) -> Result<Prepared, Error> {
        let before = self.read_original(config)?;
        self.read_trainer(config).await?;
        let after = self.read_original(config)?;
        if before != after {
            return Err(Error::CommitUncertain);
        }
        let current = binding::now()?;
        binding::clock_time(started_at, current)?;
        binding::authenticate(config, &after, current)?;
        Ok(after)
    }

    pub(super) fn verify_current(
        &mut self,
        config: &OriginalCellEvaluationQualificationConfigV1,
        prepared: &Prepared,
    ) -> Result<(), Error> {
        if self.read_original(config)? != *prepared {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }
}
