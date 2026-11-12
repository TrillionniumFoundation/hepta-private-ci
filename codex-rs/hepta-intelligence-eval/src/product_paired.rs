//! Explicit paired on-policy metadata. Original source owners authenticate the
//! two runs and their evidence; this pure domain creates no runtime authority.
//! The v1 initial-state contract is FreshEmpty, checked against each actual
//! checkpoint_before. Pairing retains both real identities and both outcomes.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::ClusterAssignment;
use super::CrossFoldPlanV1;
use super::FinalHoldoutCasStoreV1;
use super::FinalHoldoutProviderV1;
use super::HeldOutTarget;
use super::MetricRoleContractV2;
use super::OpeRow;
use super::OutcomeTrainingSample;
use super::ProductEvaluationError;
use super::ProductEvaluationRunnerV1;
use super::ProductFrozenEvaluationPlanV1;
use super::ProductMetricSourceContractV1;
use super::ProductTemporalEvaluationReceiptV1;
use super::TemporalEvaluationPlan;
use super::freeze_cross_fold_plan_v2;
use super::freeze_product_evaluation_plan_v1;

#[path = "product_paired_inputs.rs"]
mod inputs;
#[path = "product_paired_commitments.rs"]
pub(super) mod commitments;
#[path = "product_paired_evaluation.rs"]
mod evaluation;

pub(super) const MAX_PAIRS: usize = 16_384;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductComparisonModeV1 {
    SharedBehavior,
    PairedOnPolicy(OnPolicyPairingContractV1),
}

/// These are the original identities, not a common replacement decision ID.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OnPolicyArmBindingV1 {
    pub decision_id: StableId,
    pub principal_lineage: StableId,
    pub episode_lineage: StableId,
    pub behavior_run_id: StableId,
    pub model_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OnPolicyPairContractV1 {
    pub pair_id: StableId,
    pub input_digest: Digest32,
    pub protocol_digest: Digest32,
    pub candidate: OnPolicyArmBindingV1,
    pub baseline: OnPolicyArmBindingV1,
}

/// The v1 mode permits only actual empty initial private state. There is no
/// caller-selected state digest or relaxation flag. The original producer must
/// establish that each source's checkpoint_before is the recorded empty value.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OnPolicyPairingContractV1 {
    pub pairs: Vec<OnPolicyPairContractV1>,
}

impl OnPolicyPairingContractV1 {
    /// Pure canonical comparison metadata; neither authenticity nor admission.
    pub fn canonical_commitment_bytes(&self) -> Result<Vec<u8>, ProductEvaluationError> {
        commitments::pair_contract(self)
    }

    pub fn digest(&self) -> Result<Digest32, ProductEvaluationError> {
        Ok(Digest32::of_bytes(&self.canonical_commitment_bytes()?))
    }
}

/// Actual per-arm source and Circuit history evidence. The single holdout
/// consumption remains on the existing fenced Product owner, outside these
/// arm records; this type does not invent a second holdout consumption.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OnPolicyArmProvenanceV1 {
    pub decision_id: StableId,
    pub episode_lineage: StableId,
    pub behavior_run_id: StableId,
    pub model_digest: Digest32,
    pub input_digest: Digest32,
    pub protocol_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub source_evidence_digest: Digest32,
    pub execution_evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OnPolicyEvaluationArmInputsV1 {
    pub targets: Vec<HeldOutTarget>,
    pub observations: Vec<OpeRow>,
    pub assignments: Vec<ClusterAssignment>,
    pub provenance: Vec<OnPolicyArmProvenanceV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OnPolicyTemporalComparisonInputsV1 {
    pub training: Vec<OutcomeTrainingSample>,
    pub candidate: OnPolicyEvaluationArmInputsV1,
    pub baseline: OnPolicyEvaluationArmInputsV1,
    pub snapshot_ids: Vec<StableId>,
    pub future_window_ids: Vec<StableId>,
}

impl ProductFrozenEvaluationPlanV1 {
    pub fn comparison_mode(&self) -> &ProductComparisonModeV1 {
        &self.comparison
    }
}

/// Freeze the complete original metric, temporal, confidence and holdout
/// parameters before either arm is released. Identity-only plan digests may
/// differ between arms; every estimator, timeline and confidence parameter
/// must describe the same comparison protocol.
pub fn freeze_paired_on_policy_product_evaluation_plan_v1(
    mut plan: CrossFoldPlanV1,
    metric_roles: Vec<MetricRoleContractV2>,
    metric_sources: Vec<ProductMetricSourceContractV1>,
    candidate_temporal: &TemporalEvaluationPlan,
    baseline_temporal: &TemporalEvaluationPlan,
    mut pairing: OnPolicyPairingContractV1,
) -> Result<ProductFrozenEvaluationPlanV1, ProductEvaluationError> {
    require_comparable_plans(candidate_temporal, baseline_temporal)?;
    inputs::validate_pair_contract(&pairing)?;
    pairing.pairs.sort_by(|left, right| left.pair_id.cmp(&right.pair_id));
    // Reuse the original freeze validation without invoking any owner, release,
    // estimator or signing effect. All original role and metric values survive.
    let mut frozen = freeze_product_evaluation_plan_v1(
        plan.clone(), metric_roles, metric_sources,
        candidate_temporal, baseline_temporal,
    )?;
    frozen.comparison = ProductComparisonModeV1::PairedOnPolicy(pairing);
    plan.estimand_digest = Digest32::of_bytes(
        &commitments::estimand(&frozen)?,
    );
    frozen.frozen_plan = freeze_cross_fold_plan_v2(plan, frozen.metric_roles.clone())?;
    frozen.receipt_seal = super::product_plan_seal(&frozen)?;
    frozen.validate_integrity()?;
    Ok(frozen)
}

pub(super) fn require_comparable_plans(
    candidate: &TemporalEvaluationPlan,
    baseline: &TemporalEvaluationPlan,
) -> Result<(), ProductEvaluationError> {
    if candidate.evaluation_id == baseline.evaluation_id
        || candidate.objective_digest != baseline.objective_digest
        || candidate.fold.training_watermark != baseline.fold.training_watermark
        || candidate.fold.evaluation_start != baseline.fold.evaluation_start
        || candidate.fold.minimum_per_action != baseline.fold.minimum_per_action
        || candidate.ope.outcome_watermark != baseline.ope.outcome_watermark
        || candidate.ope.minimum_rows != baseline.ope.minimum_rows
        || candidate.ope.minimum_ess != baseline.ope.minimum_ess
        || candidate.ope.maximum_weight != baseline.ope.maximum_weight
        || candidate.confidence.assumptions_digest != baseline.confidence.assumptions_digest
        || candidate.confidence.family_alpha_ppm != baseline.confidence.family_alpha_ppm
        || candidate.confidence.simultaneous_comparisons != baseline.confidence.simultaneous_comparisons
        || candidate.confidence.minimum_clusters != baseline.confidence.minimum_clusters
    {
        return Err(ProductEvaluationError::Binding("paired original comparison protocol"));
    }
    Ok(())
}

impl<S: FinalHoldoutCasStoreV1> ProductEvaluationRunnerV1<S> {
    pub(super) fn evaluate_paired_on_policy_comparison<P: FinalHoldoutProviderV1>(
        &mut self,
        product_plan: &ProductFrozenEvaluationPlanV1,
        candidate_plan: &TemporalEvaluationPlan,
        baseline_plan: &TemporalEvaluationPlan,
        provider: &mut P,
    ) -> Result<ProductTemporalEvaluationReceiptV1, ProductEvaluationError> {
        evaluation::evaluate(
            self, product_plan, candidate_plan, baseline_plan, provider,
        )
    }
}
