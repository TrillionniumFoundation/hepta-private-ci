//! Separate Cell freeze for the paired on-policy Product mode. The legacy
//! freeze functions and their comparison preimages remain unchanged.

use codex_hepta_intelligence_eval::OnPolicyPairingContractV1;
use codex_hepta_intelligence_eval::freeze_paired_on_policy_product_evaluation_plan_v1;
use super::*;

pub fn freeze_paired_cell_learning_evaluation_plan_v1<
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
>(
    mut registration: CellEvaluationRegistrationV1,
    journals: CellEvaluationJournalsV1<'_, C, F>,
    candidate_temporal: &TemporalEvaluationPlan,
    baseline_temporal: &TemporalEvaluationPlan,
    evaluation_profile: Digest32,
    pairing: OnPolicyPairingContractV1,
) -> Result<CellEvaluationPlanV1, CellEvaluationErrorV1> {
    registration.comparison.validate()?;
    if evaluation_profile.is_zero()
        || registration.product.candidate_id != registration.comparison.candidate.participant_id
        || registration.product.baseline_id != registration.comparison.fixed_expert.participant_id
        || registration.product.estimand_digest.is_zero()
    {
        return Err(CellEvaluationErrorV1::Binding("paired comparison participants, estimand and profile"));
    }
    let candidate = CellEvaluationArmRecordV1::read(
        journals.candidate, &registration.comparison.candidate,
        &registration.comparison.cost_coverage,
    )?;
    let fixed_expert = CellEvaluationArmRecordV1::read(
        journals.fixed_expert, &registration.comparison.fixed_expert,
        &registration.comparison.cost_coverage,
    )?;
    if candidate.cost.identity().task_digest != fixed_expert.cost.identity().task_digest
        || candidate.journal_cut == fixed_expert.journal_cut
    {
        return Err(CellEvaluationErrorV1::Binding("same paired task with distinct original Cell cuts"));
    }
    let candidate_bundle = Digest32::from_array(candidate.manifest.bundle_digest);
    let baseline_bundle = Digest32::from_array(fixed_expert.manifest.bundle_digest);
    if pairing.pairs.is_empty()
        || pairing.pairs.iter().any(|pair|
            pair.candidate.model_digest != candidate_bundle
                || pair.baseline.model_digest != baseline_bundle)
    {
        return Err(CellEvaluationErrorV1::Binding("paired original manifest model identities"));
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
        .map_err(|_| CellEvaluationErrorV1::Binding("paired comparison encoding"))?;
    registration.product.estimand_digest = Digest32::of_parts(&[
        b"hepta.agentd.cell-paired-on-policy-estimand.v1\0", &encoded,
    ]);
    let product = freeze_paired_on_policy_product_evaluation_plan_v1(
        registration.product, registration.metric_roles, registration.metric_sources,
        candidate_temporal, baseline_temporal, pairing,
    ).map_err(CellEvaluationErrorV1::Product)?;
    Ok(CellEvaluationPlanV1 { record, product })
}


/// Realized Cell plan from an already declared V2 policy and the concrete
/// original B cohort. This is after-B assembly, never a new preregistration.
#[cfg(target_os = "linux")]
pub fn freeze_paired_cell_learning_evaluation_plan_v2<
    C: AnchorWitnessStore,
    F: AnchorWitnessStore,
>(
    cohort: &crate::OriginalCircuitOnPolicyCohortV1,
    journals: CellEvaluationJournalsV1<'_, C, F>,
) -> Result<CellEvaluationPlanV1, CellEvaluationErrorV1> {
    let (policy, training) = crate::OriginalCircuitOnPolicyCohortV1::original_pre_b_policy(cohort)
        .map_err(|_| CellEvaluationErrorV1::Binding("original complete V2 declaration"))?;
    let comparison = policy.comparison(
        training,
        journals.candidate.manifest().evolution.structure,
        journals.fixed_expert.manifest().evolution.structure,
    ).map_err(|_| CellEvaluationErrorV1::Binding("fixed V2 comparison and original T"))?;
    let candidate = CellEvaluationArmRecordV1::read(
        journals.candidate, &comparison.candidate, &comparison.cost_coverage,
    )?;
    let fixed_expert = CellEvaluationArmRecordV1::read(
        journals.fixed_expert, &comparison.fixed_expert, &comparison.cost_coverage,
    )?;
    if candidate.cost.identity().task_digest != fixed_expert.cost.identity().task_digest
        || candidate.cost.identity().task_digest != policy.task_digest().into_array()
        || candidate.journal_cut == fixed_expert.journal_cut
    {
        return Err(CellEvaluationErrorV1::Binding("same declared task and distinct actual Cell cuts"));
    }
    let pairing = policy.pairing(training)
        .map_err(|_| CellEvaluationErrorV1::Binding("fixed V2 original pair identities"))?;
    if cohort.observed_pairing_contract()
        .map_err(|_| CellEvaluationErrorV1::Binding("actual original pairing"))? != &pairing
        || pairing.pairs.iter().any(|pair|
            pair.candidate.model_digest.into_array() != candidate.manifest.bundle_digest
                || pair.baseline.model_digest.into_array() != fixed_expert.manifest.bundle_digest)
    {
        return Err(CellEvaluationErrorV1::Binding("same actual V2 arm models and complete pairing"));
    }
    let record = CellEvaluationRecordV1 {
        cost_scope: CellEvaluationCostScopeV1::TaskLedgersBeforeFinalHoldout,
        original_estimand: policy.product().input().base_estimand_digest,
        learning_evaluation_profile: Some(training.request.evaluation_profile.into_array()),
        comparison,
        candidate,
        fixed_expert,
    };
    let encoded = serde_json::to_vec(&record)
        .map_err(|_| CellEvaluationErrorV1::Binding("V2 realized comparison encoding"))?;
    let product = codex_hepta_intelligence_eval::ProductEvaluationPolicyV2::instantiate(
            policy.product(),
        &codex_hepta_intelligence_eval::ProductEvaluationPolicyBindingsV2 {
            candidate_id: record.comparison.candidate.participant_id.clone(),
            dataset_digest: cohort.observed_dataset()
                .map_err(|_| CellEvaluationErrorV1::Binding("actual original B dataset"))?
                .snapshot.dataset_digest,
            final_holdout_digest: cohort.observed_manifest_digest()
                .map_err(|_| CellEvaluationErrorV1::Binding("actual original B manifest"))?,
            cell_estimand_digest: Digest32::of_parts(&[
                b"hepta.agentd.cell-paired-on-policy-estimand.v1\0", &encoded,
            ]),
        },
        &pairing,
    ).map_err(CellEvaluationErrorV1::Product)?;
    let plan = CellEvaluationPlanV1 { record, product };
    crate::OriginalCircuitOnPolicyCohortV1::require_original_pre_b_plan(cohort, &plan)
        .map_err(|_| CellEvaluationErrorV1::Binding("whole V2 policy and realized plan"))?;
    Ok(plan)
}
