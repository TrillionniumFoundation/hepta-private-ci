//! The original fenced Product owner releases one complete paired cohort.
//! The same two original temporal estimators and metric gates remain in use.
//! Paired identities support comparability; no new paired-difference interval
//! or statistical independence is inferred from a pair identifier.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::FinalHoldoutCasStoreV1;
use super::FinalHoldoutProviderV1;
use super::ProductComparisonModeV1;
use super::ProductEvaluationError;
use super::ProductEvaluationRunnerV1;
use super::ProductFrozenEvaluationPlanV1;
use super::ProductTemporalEvaluationReceiptV1;
use super::TemporalEvaluationPlan;
use super::commitments;
use super::inputs;
use super::require_comparable_plans;
use crate::HoldoutUseDispositionV1;
use crate::evaluate_temporal_holdout;

pub(super) fn evaluate<S: FinalHoldoutCasStoreV1, P: FinalHoldoutProviderV1>(
    runner: &mut ProductEvaluationRunnerV1<S>,
    product_plan: &ProductFrozenEvaluationPlanV1,
    candidate_plan: &TemporalEvaluationPlan,
    baseline_plan: &TemporalEvaluationPlan,
    provider: &mut P,
) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
    product_plan.validate_integrity()?;
    let ProductComparisonModeV1::PairedOnPolicy(pairing) = &product_plan.comparison else {
        return Err(ProductEvaluationError::Binding("paired execution mode"));
    };
    require_comparable_plans(candidate_plan, baseline_plan)?;
    if candidate_plan.plan_digest != product_plan.candidate_temporal_plan_digest
        || baseline_plan.plan_digest != product_plan.baseline_temporal_plan_digest
        || candidate_plan.plan_digest != candidate_plan.canonical_digest()?
        || baseline_plan.plan_digest != baseline_plan.canonical_digest()?
        || candidate_plan.objective_digest != product_plan.frozen_plan.objective_digest
        || baseline_plan.objective_digest != product_plan.frozen_plan.objective_digest
    {
        return Err(ProductEvaluationError::Binding("paired temporal execution plan"));
    }
    let manifest = provider.manifest_digest()?;
    if manifest.is_zero() || manifest != product_plan.frozen_plan.final_holdout_digest {
        return Err(ProductEvaluationError::Binding("paired final holdout manifest"));
    }
    let holdout = runner.holdout.consume(&product_plan.frozen_plan)?;
    match holdout.disposition {
        HoldoutUseDispositionV1::Recorded => {}
        HoldoutUseDispositionV1::IdempotentReplay => {
            return Err(ProductEvaluationError::Binding("final holdout already consumed"));
        }
    }
    let mut released = provider.release_paired_after_consumption(&holdout, pairing)?;
    super::super::normalize_unique_ids(&mut released.snapshot_ids)?;
    super::super::normalize_unique_ids(&mut released.future_window_ids)?;
    let paired_input = inputs::validate_released_inputs(
        &product_plan.frozen_plan, pairing, &released,
    )?;
    let candidate = evaluate_temporal_holdout(
        candidate_plan, &released.training,
        &released.candidate.targets, &released.candidate.observations,
        &released.candidate.assignments,
    )?;
    let baseline = evaluate_temporal_holdout(
        baseline_plan, &released.training,
        &released.baseline.targets, &released.baseline.observations,
        &released.baseline.assignments,
    )?;
    candidate.validate_integrity()?;
    baseline.validate_integrity()?;
    let metrics = super::super::derive_metric_gates(
        product_plan, &candidate.estimate, &baseline.estimate,
    )?;
    let (estimate_receipt_digest, support_audit_digest, confidence_receipt_digest) =
        commitments::comparison(
            product_plan, Some(paired_input), &candidate, &baseline, &metrics,
        )?;
    let execution_digest = super::super::execution_digest(
        &holdout, product_plan, &candidate, &baseline, &metrics,
        &released.snapshot_ids, &released.future_window_ids,
        estimate_receipt_digest, support_audit_digest, confidence_receipt_digest,
    );
    let mut receipt = ProductTemporalEvaluationReceiptV1 {
        holdout,
        product_plan: product_plan.clone(),
        candidate,
        baseline,
        metrics,
        estimate_receipt_digest,
        support_audit_digest,
        confidence_receipt_digest,
        snapshot_ids: released.snapshot_ids,
        future_window_ids: released.future_window_ids,
        execution_digest,
        authority: AuthorityPosture::DENY_ALL,
        receipt_seal: Digest32::ZERO,
        execution_evaluator: None,
        paired_input_digest: Some(paired_input),
    };
    receipt.receipt_seal = super::super::product_evaluation_seal(&receipt)?;
    receipt.validate_integrity()?;
    Ok(receipt)
}
