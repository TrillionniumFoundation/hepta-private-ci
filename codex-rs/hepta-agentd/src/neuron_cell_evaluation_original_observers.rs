//! Concrete read-only original Cell files for the private Root B runner.
//! No writable journal, recovered CURRENT, snapshot deserializer or synthetic
//! cost record can be supplied through this boundary. The enclosing Root host
//! retains the original file locks and its durable refusal attempt throughout.

use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellGenerationJournalObserverV1;

use super::*;

pub(crate) struct OriginalCellEvaluationObserversV1 {
    candidate: CellGenerationJournalObserverV1,
    candidate_manifest: CellBackendManifestV2,
    fixed_expert: CellGenerationJournalObserverV1,
    fixed_manifest: CellBackendManifestV2,
    poisoned: AtomicBool,
}

impl OriginalCellEvaluationObserversV1 {
    pub(crate) fn from_original_observers(
        candidate: CellGenerationJournalObserverV1,
        candidate_manifest: CellBackendManifestV2,
        fixed_expert: CellGenerationJournalObserverV1,
        fixed_manifest: CellBackendManifestV2,
    ) -> Result<Self, CellEvaluationErrorV1> {
        if candidate.files_binding() == fixed_expert.files_binding()
            || candidate.owner_binding().manifest_digest()
                != candidate_manifest
                    .digest()
                    .map_err(CellEvaluationErrorV1::Journal)?
            || fixed_expert.owner_binding().manifest_digest()
                != fixed_manifest
                    .digest()
                    .map_err(CellEvaluationErrorV1::Journal)?
        {
            return Err(CellEvaluationErrorV1::Binding(
                "original B Cell observers differ",
            ));
        }
        Ok(Self {
            candidate,
            candidate_manifest,
            fixed_expert,
            fixed_manifest,
            poisoned: AtomicBool::new(false),
        })
    }

    pub(crate) fn freeze_original_learning_plan(
        &self,
        mut registration: CellEvaluationRegistrationV1,
        candidate_temporal: &TemporalEvaluationPlan,
        baseline_temporal: &TemporalEvaluationPlan,
        evaluation_profile: Digest32,
    ) -> Result<CellEvaluationPlanV1, CellEvaluationErrorV1> {
        registration.comparison.validate()?;
        if evaluation_profile.is_zero()
            || registration.product.candidate_id != registration.comparison.candidate.participant_id
            || registration.product.baseline_id
                != registration.comparison.fixed_expert.participant_id
            || registration.product.estimand_digest.is_zero()
        {
            return Err(CellEvaluationErrorV1::Binding(
                "original B learning plan differs",
            ));
        }
        let (candidate, fixed_expert) = self.read_original_arms(&registration.comparison)?;
        if candidate.cost.identity().task_digest != fixed_expert.cost.identity().task_digest
            || candidate.journal_cut == fixed_expert.journal_cut
        {
            return Err(CellEvaluationErrorV1::Binding(
                "original B comparison task or cuts differ",
            ));
        }
        let record = CellEvaluationRecordV1 {
            cost_scope: CellEvaluationCostScopeV1::TaskLedgersBeforeFinalHoldout,
            original_estimand: registration.product.estimand_digest,
            learning_evaluation_profile: Some(evaluation_profile.into_array()),
            comparison: registration.comparison,
            candidate,
            fixed_expert,
        };
        let encoded = serde_json::to_vec(&record)
            .map_err(|_| CellEvaluationErrorV1::Binding("comparison encoding"))?;
        registration.product.estimand_digest =
            Digest32::of_parts(&[b"hepta.agentd.cell-fixed-expert-estimand.v1\0", &encoded]);
        let product = freeze_product_evaluation_plan_v1(
            registration.product,
            registration.metric_roles,
            registration.metric_sources,
            candidate_temporal,
            baseline_temporal,
        )
        .map_err(CellEvaluationErrorV1::Product)?;
        let plan = CellEvaluationPlanV1 { record, product };
        self.require_original_plan(&plan)?;
        Ok(plan)
    }

    pub(crate) fn require_original_plan(
        &self,
        plan: &CellEvaluationPlanV1,
    ) -> Result<(), CellEvaluationErrorV1> {
        let (candidate, fixed_expert) = self.read_original_arms(&plan.record.comparison)?;
        if candidate != plan.record.candidate || fixed_expert != plan.record.fixed_expert {
            self.poisoned.store(true, Ordering::Release);
            return Err(CellEvaluationErrorV1::Binding(
                "original B Cell cut changed",
            ));
        }
        Ok(())
    }

    fn read_original_arms(
        &self,
        comparison: &CellComparisonContractV1,
    ) -> Result<(CellEvaluationArmRecordV1, CellEvaluationArmRecordV1), CellEvaluationErrorV1> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(CellEvaluationErrorV1::Binding(
                "original B Cell observation was refused",
            ));
        }
        let result = (|| {
            let candidate = self
                .candidate
                .observe()
                .map_err(CellEvaluationErrorV1::Journal)?;
            let fixed = self
                .fixed_expert
                .observe()
                .map_err(CellEvaluationErrorV1::Journal)?;
            let mut records = Vec::with_capacity(2);
            for (actual, manifest, declared) in [
                (&candidate, &self.candidate_manifest, &comparison.candidate),
                (&fixed, &self.fixed_manifest, &comparison.fixed_expert),
            ] {
                let observation = actual.observation();
                let cost = observation.cost();
                let summary = cost
                    .summary()
                    .map_err(|_| CellEvaluationErrorV1::Binding("cost ledger"))?;
                if !actual.is_drained()
                    || observation.pending_request_digest().is_some()
                    || observation.pending_output().is_some()
                    || cost.identity().source_digest != manifest.source_digest
                    || declared.structure_after != manifest.evolution.structure
                    || !summary.missing_stages.is_empty()
                    || cost
                        .entries()
                        .iter()
                        .any(|entry| entry.outcome == CellCostOutcomeV2::Unknown)
                {
                    return Err(CellEvaluationErrorV1::Binding(
                        "original B Cell costs are unresolved",
                    ));
                }
                contract::validate_required_metrics(&summary, &comparison.cost_coverage)?;
                records.push(CellEvaluationArmRecordV1 {
                    manifest: manifest.clone(),
                    journal_cut: observation.owner_checkpoint(),
                    snapshot_digest: observation
                        .snapshot()
                        .digest()
                        .map_err(CellEvaluationErrorV1::Journal)?,
                    cost: cost.clone(),
                });
            }
            if self
                .candidate
                .observe()
                .map_err(CellEvaluationErrorV1::Journal)?
                != candidate
                || self
                    .fixed_expert
                    .observe()
                    .map_err(CellEvaluationErrorV1::Journal)?
                    != fixed
            {
                return Err(CellEvaluationErrorV1::Binding(
                    "original B Cell changed during observation",
                ));
            }
            let [candidate, fixed]: [CellEvaluationArmRecordV1; 2] =
                records.try_into().map_err(|_| {
                    CellEvaluationErrorV1::Binding("original comparison requires two arms")
                })?;
            Ok((candidate, fixed))
        })();
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        result
    }

    pub(crate) fn evaluate_original(
        &self,
        runner: &mut CellEvaluationRunnerV1<impl FinalHoldoutCasStoreV1>,
        plan: &CellEvaluationPlanV1,
        request: &ProductEvaluationExecutionRequestV1<'_>,
        provider: &mut impl FinalHoldoutProviderV1,
        executions: &mut impl ProductEvaluationExecutionStoreV1,
        attestor: &mut impl ProductEvaluationExecutionAttestorV1,
    ) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
        self.require_original_plan(plan)?;
        if request.plan != &plan.product {
            return Err(CellEvaluationErrorV1::Binding(
                "original B execution plan differs",
            ));
        }
        let result = runner
            .product
            .evaluate_or_readback_temporal_comparison(request, provider, executions, attestor);
        self.require_original_plan(plan)?;
        let temporal = result.map_err(CellEvaluationErrorV1::Execution)?;
        Ok(CellEvaluationReceiptV1 {
            plan: plan.clone(),
            temporal,
            original_execution_evaluator: Some(request.evaluator.clone()),
        })
    }

    pub(crate) fn read_original_execution(
        &self,
        runner: &mut CellEvaluationRunnerV1<impl FinalHoldoutCasStoreV1>,
        plan: &CellEvaluationPlanV1,
        request: &ProductEvaluationExecutionRequestV1<'_>,
        executions: &mut impl ProductEvaluationExecutionStoreV1,
    ) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
        self.require_original_plan(plan)?;
        if request.plan != &plan.product {
            return Err(CellEvaluationErrorV1::Binding(
                "original B readback plan differs",
            ));
        }
        let result = runner
            .product
            .readback_temporal_comparison(request, executions);
        self.require_original_plan(plan)?;
        let temporal = result.map_err(CellEvaluationErrorV1::Execution)?;
        Ok(CellEvaluationReceiptV1 {
            plan: plan.clone(),
            temporal,
            original_execution_evaluator: Some(request.evaluator.clone()),
        })
    }
}
