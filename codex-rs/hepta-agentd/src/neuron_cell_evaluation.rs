//! Cell/fixed-expert composition over the existing independent product runner.
//! Actual drained journals supply cost evidence. Matching declarations are
//! preregistered, then covered by the existing generator/evaluator signatures;
//! this adapter neither authenticates training counters nor grants adoption.

use std::error::Error;
use std::fmt;

use codex_hepta_intelligence_eval::CrossFoldPlanV1;
use codex_hepta_intelligence_eval::FinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::FinalHoldoutProviderV1;
use codex_hepta_intelligence_eval::IndependentEvaluationBundleV1;
use codex_hepta_intelligence_eval::MetricRoleContractV2;
use codex_hepta_intelligence_eval::ProductEvaluationError;
use codex_hepta_intelligence_eval::ProductEvaluationRunnerV1;
use codex_hepta_intelligence_eval::ProductFrozenEvaluationPlanV1;
use codex_hepta_intelligence_eval::ProductMetricSourceContractV1;
use codex_hepta_intelligence_eval::ProductQualificationContextV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::ProductQualificationReceiptV1;
use codex_hepta_intelligence_eval::ProductTemporalEvaluationReceiptV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::SignedEvaluationEvidenceV1;
use codex_hepta_intelligence_eval::TemporalEvaluationPlan;
use codex_hepta_intelligence_eval::freeze_product_evaluation_plan_v1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Serialize;

#[path = "neuron_cell_evaluation_contract.rs"]
mod contract;
pub use contract::*;

pub struct CellEvaluationJournalsV1<'a, C: AnchorWitnessStore, F: AnchorWitnessStore> {
    pub candidate: &'a CellGenerationJournalV2<C>,
    pub fixed_expert: &'a CellGenerationJournalV2<F>,
}

#[derive(Clone)]
pub struct CellEvaluationRegistrationV1 {
    pub product: CrossFoldPlanV1,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub metric_sources: Vec<ProductMetricSourceContractV1>,
    pub comparison: CellComparisonContractV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CellEvaluationRecordV1 {
    /// The new holdout estimator, signature verification and publication happen
    /// after this cut. Their unmeasured overhead is not claimed by these totals.
    pub cost_scope: CellEvaluationCostScopeV1,
    #[serde(serialize_with = "contract::serialize_digest")]
    pub original_estimand: Digest32,
    pub comparison: CellComparisonContractV1,
    pub candidate: CellEvaluationArmRecordV1,
    pub fixed_expert: CellEvaluationArmRecordV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CellEvaluationCostScopeV1 {
    TaskLedgersBeforeFinalHoldout,
}

/// Private fields and no deserializer preserve the single freeze entry point.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellEvaluationPlanV1 {
    record: CellEvaluationRecordV1,
    product: ProductFrozenEvaluationPlanV1,
}

impl CellEvaluationPlanV1 {
    pub fn record(&self) -> &CellEvaluationRecordV1 {
        &self.record
    }
    pub fn product_plan(&self) -> &ProductFrozenEvaluationPlanV1 {
        &self.product
    }
}

pub fn freeze_cell_evaluation_plan_v1<C: AnchorWitnessStore, F: AnchorWitnessStore>(
    mut registration: CellEvaluationRegistrationV1,
    journals: CellEvaluationJournalsV1<'_, C, F>,
    candidate_temporal: &TemporalEvaluationPlan,
    baseline_temporal: &TemporalEvaluationPlan,
) -> Result<CellEvaluationPlanV1, CellEvaluationErrorV1> {
    registration.comparison.validate()?;
    if registration.product.candidate_id != registration.comparison.candidate.participant_id
        || registration.product.baseline_id != registration.comparison.fixed_expert.participant_id
        || registration.product.estimand_digest.is_zero()
    {
        return Err(CellEvaluationErrorV1::Binding(
            "comparison participants or estimand",
        ));
    }
    let candidate = CellEvaluationArmRecordV1::read(
        journals.candidate,
        &registration.comparison.candidate,
        &registration.comparison.cost_coverage,
    )?;
    let fixed_expert = CellEvaluationArmRecordV1::read(
        journals.fixed_expert,
        &registration.comparison.fixed_expert,
        &registration.comparison.cost_coverage,
    )?;
    if candidate.cost.identity().task_digest != fixed_expert.cost.identity().task_digest {
        return Err(CellEvaluationErrorV1::Binding("comparison task"));
    }
    if candidate.journal_cut == fixed_expert.journal_cut {
        return Err(CellEvaluationErrorV1::Binding(
            "comparison requires distinct Cell owner cuts",
        ));
    }
    let record = CellEvaluationRecordV1 {
        cost_scope: CellEvaluationCostScopeV1::TaskLedgersBeforeFinalHoldout,
        original_estimand: registration.product.estimand_digest,
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
    Ok(CellEvaluationPlanV1 { record, product })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellEvaluationReceiptV1 {
    plan: CellEvaluationPlanV1,
    temporal: ProductTemporalEvaluationReceiptV1,
}

impl CellEvaluationReceiptV1 {
    pub fn plan(&self) -> &CellEvaluationPlanV1 {
        &self.plan
    }
    pub fn temporal(&self) -> &ProductTemporalEvaluationReceiptV1 {
        &self.temporal
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

pub struct CellEvaluationQualificationRequestV1<'a> {
    pub context: &'a ProductQualificationContextV1,
    pub evidence: &'a SignedEvaluationEvidenceV1,
    pub timing: ProductTimingEvidenceV1<'a>,
    pub verifier: &'a LearningEvidenceVerifierV1,
    pub now: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellEvaluationQualificationV1 {
    comparison: CellEvaluationRecordV1,
    product: ProductQualificationReceiptV1,
}

impl CellEvaluationQualificationV1 {
    pub fn comparison(&self) -> &CellEvaluationRecordV1 {
        &self.comparison
    }
    pub fn product(&self) -> &ProductQualificationReceiptV1 {
        &self.product
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

pub struct CellEvaluationRunnerV1<S> {
    product: ProductEvaluationRunnerV1<S>,
}

impl<S: FinalHoldoutCasStoreV1> CellEvaluationRunnerV1<S> {
    /// Consumes the existing runner and its already-owned final-holdout CAS.
    pub fn new(product: ProductEvaluationRunnerV1<S>) -> Self {
        Self { product }
    }

    pub fn evaluate<C: AnchorWitnessStore, F: AnchorWitnessStore, P: FinalHoldoutProviderV1>(
        &mut self,
        plan: &CellEvaluationPlanV1,
        journals: CellEvaluationJournalsV1<'_, C, F>,
        candidate_temporal: &TemporalEvaluationPlan,
        baseline_temporal: &TemporalEvaluationPlan,
        provider: &mut P,
    ) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
        let candidate = CellEvaluationArmRecordV1::read(
            journals.candidate,
            &plan.record.comparison.candidate,
            &plan.record.comparison.cost_coverage,
        )?;
        let fixed_expert = CellEvaluationArmRecordV1::read(
            journals.fixed_expert,
            &plan.record.comparison.fixed_expert,
            &plan.record.comparison.cost_coverage,
        )?;
        if candidate != plan.record.candidate || fixed_expert != plan.record.fixed_expert {
            return Err(CellEvaluationErrorV1::Binding(
                "Cell journal changed after registration",
            ));
        }
        // No provider method or holdout mutation precedes the Cell checks.
        let temporal = self
            .product
            .evaluate_temporal_comparison(
                &plan.product,
                candidate_temporal,
                baseline_temporal,
                provider,
            )
            .map_err(CellEvaluationErrorV1::Product)?;
        Ok(CellEvaluationReceiptV1 {
            plan: plan.clone(),
            temporal,
        })
    }

    pub fn qualification_bundle(
        &self,
        receipt: &CellEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
    ) -> Result<IndependentEvaluationBundleV1, CellEvaluationErrorV1> {
        self.product
            .qualification_bundle(&receipt.temporal, context)
            .map_err(CellEvaluationErrorV1::Product)
    }

    /// Requires the original authenticated evidence and durable publication
    /// sink. No local matching check can mint an independent decision.
    pub fn qualify_and_persist(
        &self,
        receipt: &CellEvaluationReceiptV1,
        request: CellEvaluationQualificationRequestV1<'_>,
        sink: &mut dyn ProductQualificationEvidenceSinkV1,
    ) -> Result<CellEvaluationQualificationV1, CellEvaluationErrorV1> {
        let product = self
            .product
            .qualify_and_persist(
                &receipt.temporal,
                request.context,
                request.evidence,
                request.timing,
                request.verifier,
                request.now,
                sink,
            )
            .map_err(CellEvaluationErrorV1::Product)?;
        Ok(CellEvaluationQualificationV1 {
            comparison: receipt.plan.record.clone(),
            product,
        })
    }
}

#[derive(Debug)]
pub enum CellEvaluationErrorV1 {
    Binding(&'static str),
    Journal(CellGenerationErrorV2),
    Product(ProductEvaluationError),
}

impl fmt::Display for CellEvaluationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for CellEvaluationErrorV1 {}

#[cfg(test)]
#[path = "neuron_cell_evaluation_tests.rs"]
mod tests;
