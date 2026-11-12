//! Actual Cell cost files and final-holdout CAS for the original data provider.
//! Product declarations remain synthetic mechanism metadata; they are not a
//! claim about independent B deployment or aggregate costs of this cohort.
use super::*;
use crate::OriginalCircuitEvaluationCohortRuleV1;
use crate::OriginalCircuitEvaluationCohortV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use pretty_assertions::assert_eq;

pub(crate) struct ProviderPlanFixture {
    fixture: Fixture,
    pub(crate) plan: CellEvaluationPlanV1,
}
impl ProviderPlanFixture {
    pub(crate) fn new(
        cohort: &OriginalCircuitEvaluationCohortV1,
        rule: &OriginalCircuitEvaluationCohortRuleV1,
        training: &LearningIterationSnapshotV1,
        [candidate_manifest, baseline_manifest]: [CellBackendManifestV2; 2],
    ) -> anyhow::Result<Self> {
        let mut fixture = Fixture::new(Costs::Complete);
        let coordinator = codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
            training.clone(),
        )?;
        let candidate = coordinator.candidate().ok_or_else(|| anyhow::anyhow!("actual Candidate"))?;
        let product = &mut fixture.registration.product;
        product.plan_id = rule.plan_id.clone();
        product.candidate_id = candidate.artifact_id.clone();
        product.baseline_id = training.request.selected_bundle.artifact_id.clone();
        product.objective_digest = rule.objective_digest;
        product.dataset_digest = cohort.observed_dataset()?.snapshot.dataset_digest;
        product.final_holdout_digest = cohort.observed_manifest_digest()?;
        product.final_holdout_window_id = rule.holdout_window_id.clone();
        product.folds[0].holdout_windows = vec![rule.holdout_window_id.clone()];
        let comparison = &mut fixture.registration.comparison;
        comparison.candidate.participant_id = candidate.artifact_id.clone();
        comparison.fixed_expert.participant_id = training.request.selected_bundle.artifact_id.clone();
        comparison.candidate.training_receipt_digest = Digest32::of_bytes(
            &learning_iteration_receipt_signing_bytes_v1(&training.receipts[2])?,
        ).into_array();
        comparison.candidate.structure_before = baseline_manifest.evolution.structure;
        comparison.candidate.structure_after = candidate_manifest.evolution.structure;
        comparison.fixed_expert.structure_before = baseline_manifest.evolution.structure;
        comparison.fixed_expert.structure_after = baseline_manifest.evolution.structure;
        fixture.candidate = journal_with_manifest(
            fixture.directory.path(), "original-B-candidate-cost", Costs::Complete,
            rule.task_digest.into_array(), candidate_manifest,
        );
        fixture.fixed = journal_with_manifest(
            fixture.directory.path(), "original-B-baseline-cost", Costs::Complete,
            rule.task_digest.into_array(), baseline_manifest,
        );
        fixture.candidate_temporal = rule.candidate_plan.clone();
        fixture.baseline_temporal = rule.baseline_plan.clone();
        let plan = crate::freeze_cell_learning_evaluation_plan_v1(
            fixture.registration.clone(), fixture.journals(),
            &fixture.candidate_temporal, &fixture.baseline_temporal,
            training.request.evaluation_profile,
        )?;
        assert_eq!(plan.product_plan().frozen_plan.final_holdout_digest, cohort.observed_manifest_digest()?);
        Ok(Self { fixture, plan })
    }

    pub(crate) fn run(
        &mut self,
        provider: &mut impl FinalHoldoutProviderV1,
    ) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
        self.fixture.runner.evaluate(
            &self.plan,
            CellEvaluationJournalsV1 {
                candidate: &self.fixture.candidate, fixed_expert: &self.fixture.fixed,
            },
            &self.fixture.candidate_temporal, &self.fixture.baseline_temporal, provider,
        )
    }

    pub(crate) fn bytes(&mut self) -> Vec<u8> {
        self.fixture.holdout_bytes()
    }
}
