//! Preregistered, measured outcome channels. Unit-interval inputs are required;
//! a normalization digest commits to the custodian's transformation, not proof
//! of its correctness or of independently authenticated outcome provenance.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CrossFoldPlanReceiptV1;
use crate::CrossFoldPlanV1;
use crate::MetricRoleContractV2;
use crate::ProductEvaluationError;
use crate::ProductFrozenEvaluationPlanV1;
use crate::ProductMetricSourceContractV1;
use crate::ProductProviderErrorV1;
use crate::TemporalComparisonInputsV1;
use crate::TemporalEvaluationPlan;
use crate::freeze_product_evaluation_plan_v1;
use crate::push_id;

#[path = "outcome_payload.rs"]
mod payload;
pub use payload::product_outcome_inputs_digest_v1;

pub(crate) const MAX_CHANNELS: usize = 32;
pub(crate) const MAX_BATCH_ROWS: usize = 100_000;

/// A single measured result, not an alias for an estimator of another result.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductOutcomeChannelContractV1 {
    pub metric_id: StableId,
    pub channel_id: StableId,
    pub schema_digest: Digest32,
    pub unit_id: StableId,
    pub normalization_digest: Digest32,
    pub subgroup_digest: Digest32,
    pub window_id: StableId,
    pub measurement_start_micros: u64,
    pub measurement_end_micros: u64,
    pub provenance_digest: Digest32,
    pub inputs_digest: Digest32,
    pub candidate_plan: TemporalEvaluationPlan,
    pub baseline_plan: TemporalEvaluationPlan,
}

impl ProductOutcomeChannelContractV1 {
    pub fn canonical_digest(&self) -> Result<Digest32, ProductEvaluationError> {
        let mut bytes = b"hepta.learning-eval.outcome-channel.v1".to_vec();
        for value in [
            &self.metric_id,
            &self.channel_id,
            &self.unit_id,
            &self.window_id,
        ] {
            push_id(&mut bytes, value);
        }
        for value in [
            self.schema_digest,
            self.normalization_digest,
            self.subgroup_digest,
            self.provenance_digest,
            self.inputs_digest,
            self.candidate_plan.canonical_digest()?,
            self.baseline_plan.canonical_digest()?,
        ] {
            if value.is_zero() {
                return Err(ProductEvaluationError::Binding(
                    "empty outcome channel commitment",
                ));
            }
            bytes.extend_from_slice(value.as_array());
        }
        bytes.extend_from_slice(&self.measurement_start_micros.to_be_bytes());
        bytes.extend_from_slice(&self.measurement_end_micros.to_be_bytes());
        if self.measurement_start_micros >= self.measurement_end_micros {
            return Err(ProductEvaluationError::Binding(
                "outcome measurement window",
            ));
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Private fields prevent extracting the internal single-consumption carrier
/// and qualifying its placeholder metrics through the legacy one-stream API.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductFrozenOutcomePlanV1 {
    pub(crate) carrier: ProductFrozenEvaluationPlanV1,
    pub(crate) channels: Vec<ProductOutcomeChannelContractV1>,
    pub(crate) channel_digests: Vec<Digest32>,
}

impl ProductFrozenOutcomePlanV1 {
    #[must_use]
    pub fn frozen_plan(&self) -> &CrossFoldPlanReceiptV1 {
        &self.carrier.frozen_plan
    }

    #[must_use]
    pub fn channels(&self) -> &[ProductOutcomeChannelContractV1] {
        &self.channels
    }
}

pub fn freeze_product_outcome_plan_v1(
    mut plan: CrossFoldPlanV1,
    metric_roles: Vec<MetricRoleContractV2>,
    metric_sources: Vec<ProductMetricSourceContractV1>,
    mut channels: Vec<ProductOutcomeChannelContractV1>,
) -> Result<ProductFrozenOutcomePlanV1, ProductEvaluationError> {
    if channels.is_empty()
        || channels.len() > MAX_CHANNELS
        || channels.len() != plan.metric_contracts.len()
        || plan.simultaneous_comparisons < (channels.len() as u32) * 2
        || plan.estimand_digest.is_zero()
    {
        return Err(ProductEvaluationError::Binding(
            "outcome channel coverage or multiplicity",
        ));
    }
    channels.sort_by(|left, right| left.metric_id.cmp(&right.metric_id));
    let mut metrics: Vec<_> = plan
        .metric_contracts
        .iter()
        .map(|row| &row.metric_id)
        .collect();
    metrics.sort();
    let mut identities = BTreeSet::new();
    let mut inputs = BTreeSet::new();
    let mut channel_digests = Vec::with_capacity(channels.len());
    let mut bytes = b"hepta.learning-eval.outcome-estimand.v1".to_vec();
    bytes.extend_from_slice(plan.estimand_digest.as_array());
    bytes.extend_from_slice(&(channels.len() as u32).to_be_bytes());
    for (channel, metric_id) in channels.iter().zip(metrics) {
        if &channel.metric_id != metric_id
            || !identities.insert(channel.channel_id.clone())
            || !inputs.insert(*channel.inputs_digest.as_array())
            || channel.window_id != plan.final_holdout_window_id
        {
            return Err(ProductEvaluationError::Binding(
                "duplicate or mismatched outcome channel",
            ));
        }
        for temporal in [&channel.candidate_plan, &channel.baseline_plan] {
            if temporal.plan_digest != temporal.canonical_digest()?
                || temporal.objective_digest != plan.objective_digest
                || temporal.confidence.family_alpha_ppm != plan.family_alpha_ppm
                || temporal.confidence.simultaneous_comparisons != plan.simultaneous_comparisons
                || temporal.fold.evaluation_start != channel.measurement_start_micros
                || temporal.ope.outcome_watermark != channel.measurement_end_micros
            {
                return Err(ProductEvaluationError::Binding("outcome temporal plan"));
            }
        }
        let digest = channel.canonical_digest()?;
        bytes.extend_from_slice(digest.as_array());
        channel_digests.push(digest);
    }
    plan.estimand_digest = Digest32::of_bytes(&bytes);
    let primary = &channels[0];
    let carrier = freeze_product_evaluation_plan_v1(
        plan,
        metric_roles,
        metric_sources,
        &primary.candidate_plan,
        &primary.baseline_plan,
    )?;
    Ok(ProductFrozenOutcomePlanV1 {
        carrier,
        channels,
        channel_digests,
    })
}

#[derive(Clone, Debug)]
pub struct ProductOutcomeInputV1 {
    pub channel_id: StableId,
    pub contract_digest: Digest32,
    pub inputs: TemporalComparisonInputsV1,
}

/// The custodian releases one complete, frozen channel batch after consumption.
/// Implementations must not substitute a channel, relabel another result or
/// omit unavailable outcomes. Authentication is a selected-host obligation.
pub trait FinalOutcomeHoldoutProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1>;
    fn release_after_consumption(
        &mut self,
        receipt: &crate::FinalHoldoutJournalReceiptV1,
    ) -> Result<Vec<ProductOutcomeInputV1>, ProductProviderErrorV1>;
}

pub(crate) fn validate_inputs(
    channel: &ProductOutcomeChannelContractV1,
    inputs: &TemporalComparisonInputsV1,
) -> Result<(), ProductEvaluationError> {
    if product_outcome_inputs_digest_v1(inputs)? != channel.inputs_digest
        || inputs.targets.is_empty()
        || inputs.targets.len() != inputs.candidate_observations.len()
        || inputs.targets.len() != inputs.baseline_observations.len()
        || inputs.targets.len() != inputs.assignments.len()
        || inputs.targets.iter().any(|row| {
            row.window_id != channel.window_id
                || row.decision_at < channel.measurement_start_micros
                || row.decision_at > channel.measurement_end_micros
        })
        || inputs.future_window_ids != [channel.window_id.clone()]
    {
        return Err(ProductEvaluationError::Binding("measured outcome payload"));
    }
    let mut candidate: Vec<_> = inputs.candidate_observations.iter().collect();
    let mut baseline: Vec<_> = inputs.baseline_observations.iter().collect();
    candidate.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    baseline.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    for (left, right) in candidate.into_iter().zip(baseline) {
        if left.decision_id != right.decision_id
            || left.chosen_action != right.chosen_action
            || left.complete_candidates != right.complete_candidates
            || left.finalized_outcome != right.finalized_outcome
            || left.outcome_observed_at != right.outcome_observed_at
            || left.outcome_evidence != right.outcome_evidence
            || left.actions.len() != right.actions.len()
            || left.outcome_observed_at < channel.measurement_start_micros
            || left.outcome_observed_at > channel.measurement_end_micros
        {
            return Err(ProductEvaluationError::Binding(
                "paired outcome measurements",
            ));
        }
        let mut la: Vec<_> = left.actions.iter().collect();
        let mut ra: Vec<_> = right.actions.iter().collect();
        la.sort_by(|a, b| a.action_id.cmp(&b.action_id));
        ra.sort_by(|a, b| a.action_id.cmp(&b.action_id));
        if la.into_iter().zip(ra).any(|(a, b)| {
            a.action_id != b.action_id || a.behavior_probability != b.behavior_probability
        }) {
            return Err(ProductEvaluationError::Binding(
                "paired outcome logging policy",
            ));
        }
    }
    Ok(())
}
