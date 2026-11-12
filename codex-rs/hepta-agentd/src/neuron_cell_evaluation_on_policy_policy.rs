//! Independently verify the complete pre-B V2 policy using public metadata.
//! No Cell, frozen plan, execution, Runner or Qualification seal is rebuilt.

use codex_hepta_intelligence_eval::ProductEvaluationPolicyBindingsV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde_json::Value;

use super::*;

pub(super) fn verify_pre_b_policy(
    member: &Member,
    checked: &Checked,
    context: &Context,
    task: &crate::OriginalCellEvaluationPanelTaskV1,
    ledger: Digest32,
    snapshot_id: &StableId,
    outcome_watermark: u64,
    bytes: &[u8],
) -> Result<(), Error> {
    let policy = crate::OriginalCircuitOnPolicyEvaluationPolicyV2::from_canonical_commitment_bytes(bytes)
        .map_err(|_| Error::Binding("full canonical original V2 policy preimage"))?;
    let product = policy.product();
    let training_receipt = context.training.receipts.get(2)
        .ok_or(Error::Binding("actual original T receipt"))?;
    if policy.cohort_rule_digest()
            .map_err(|_| Error::Binding("V2 rule commitment"))? != task.cohort_rule_digest
        || product.context().plan_id != task.plan_id
        || policy.task_digest() != task.task_digest
        || policy.ledger_binding() != ledger
        || policy.snapshot_id() != snapshot_id
        || product.context().objective_digest != context.verifier.objective_digest()
        || product.context().candidate_temporal.ope.outcome_watermark != outcome_watermark
        || product.context().baseline_temporal.ope.outcome_watermark != outcome_watermark
        || training_receipt.observed_unix_seconds
            >= product.context().candidate_temporal.fold.evaluation_start
    {
        return Err(Error::Binding("original T commits the entire V2 policy before actual B"));
    }
    crate::OriginalCircuitOnPolicyEvaluationPolicyV2::require_original_policy_training(&policy, &context.training)
        .map_err(|_| Error::Binding("same original T baseline and policy"))?;
    let pairing = policy.pairing(&context.training)
        .map_err(|_| Error::Binding("complete preregistered original pair identities"))?;
    if paired::pairing(member)? != pairing {
        return Err(Error::Binding("same full real principal, episode and run pairing"));
    }
    let record: Value = serde_json::from_slice(&member.record)?;
    let candidate_structure: [u8; 32] =
        serde_json::from_value(record["candidate"]["manifest"]["evolution"]["structure"].clone())?;
    let baseline_structure: [u8; 32] =
        serde_json::from_value(record["fixed_expert"]["manifest"]["evolution"]["structure"].clone())?;
    let comparison = policy.comparison(&context.training, candidate_structure, baseline_structure)
        .map_err(|_| Error::Binding("complete fixed comparison policy with actual Cell structures"))?;
    if record.as_object().map(|object| object.len()) != Some(6)
        || record["comparison"] != serde_json::to_value(&comparison)?
        || record["original_estimand"] != serde_json::to_value(product.input().base_estimand_digest.into_array())?
        || record["cost_scope"].as_str() != Some("task_ledgers_before_final_holdout")
        || record["learning_evaluation_profile"] != serde_json::to_value(
            context.registration.evaluation_profile().into_array())?
    {
        return Err(Error::Binding("fixed full comparison, original estimand and cost policy"));
    }
    let original = LearningIterationCoordinatorV1::from_snapshot(context.training.clone())?;
    let candidate = original.candidate()
        .ok_or(Error::Binding("unique original signed candidate slot"))?;
    let expected = codex_hepta_intelligence_eval::ProductEvaluationPolicyV2::expected_commitment_bytes(
        product,
        &ProductEvaluationPolicyBindingsV2 {
            candidate_id: candidate.artifact_id.clone(),
            dataset_digest: checked.dataset,
            final_holdout_digest: checked.manifest,
            cell_estimand_digest: Digest32::of_parts(&[
                b"hepta.agentd.cell-paired-on-policy-estimand.v1\0", &member.record,
            ]),
        },
        &pairing,
    ).map_err(|_| Error::Binding("full public V2 Product commitment reconstruction"))?;
    if expected.plan() != member.plan.as_slice()
        || expected.estimand() != member.estimand.as_slice()
        || expected.roles() != member.roles.as_slice()
    {
        return Err(Error::Binding("exact preregistered metrics, roles, margins, sources, folds and holdout"));
    }
    Ok(())
}
