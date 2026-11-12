//! Complete pre-B Product policy metadata. Freezing this value establishes no
//! time, source observation, training result, execution or qualification authority.
//! The original producer must bind its digest before T/B and authenticate every
//! late binding. Declared fold digests are not evidence of a future actual fit.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::OnPolicyPairingContractV1;
use super::ProductEvaluationError;
use super::ProductFrozenEvaluationPlanV1;
use super::ProductMetricSourceContractV1;
use super::freeze_paired_on_policy_product_evaluation_plan_v1;
use super::normalize_product_plan_inputs;
use super::paired;
use crate::CrossFoldPartitionV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationClosureError;
use crate::MetricContractV1;
use crate::MetricRoleContractV2;
use crate::TemporalEvaluationPlan;
use crate::closure::cross_fold_plan_v2_commitments;
use crate::closure::normalize_cross_fold_metadata;
use crate::closure::role_contract_commitment_bytes;

#[path = "product_policy_codec.rs"]
mod codec;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationPolicyContextV2 {
    pub plan_id: StableId,
    pub objective_digest: Digest32,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub final_holdout_window_id: StableId,
    pub candidate_temporal: TemporalEvaluationPlan,
    pub baseline_temporal: TemporalEvaluationPlan,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationPolicyInputV2 {
    pub claim_scope: EvaluationClaimScopeV1,
    pub base_estimand_digest: Digest32,
    pub baseline_id: StableId,
    pub metric_contracts: Vec<MetricContractV1>,
    pub metric_roles: Vec<MetricRoleContractV2>,
    pub metric_sources: Vec<ProductMetricSourceContractV1>,
    pub folds: Vec<CrossFoldPartitionV1>,
}

/// Only these values are late. Their authenticity remains the original owner's
/// responsibility; this metadata does not derive a candidate from a policy name.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationPolicyBindingsV2 {
    pub candidate_id: StableId,
    pub dataset_digest: Digest32,
    pub final_holdout_digest: Digest32,
    pub cell_estimand_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationPolicyV2 {
    context: ProductEvaluationPolicyContextV2,
    input: ProductEvaluationPolicyInputV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductEvaluationPolicyCommitmentsV2 {
    plan: Vec<u8>,
    estimand: Vec<u8>,
    roles: Vec<u8>,
}

impl ProductEvaluationPolicyCommitmentsV2 {
    pub fn plan(&self) -> &[u8] {
        &self.plan
    }

    pub fn estimand(&self) -> &[u8] {
        &self.estimand
    }

    pub fn roles(&self) -> &[u8] {
        &self.roles
    }
}

impl ProductEvaluationPolicyV2 {
    pub fn freeze(
        context: ProductEvaluationPolicyContextV2,
        mut input: ProductEvaluationPolicyInputV2,
    ) -> Result<Self, ProductEvaluationError> {
        // Bound the complete input before sorting or copying any collections.
        codec::encode(&context, &input)?;
        if context.objective_digest.is_zero() || input.base_estimand_digest.is_zero() {
            return Err(ProductEvaluationError::Binding("policy objective or estimand"));
        }
        if !(1..=100_000).contains(&context.family_alpha_ppm)
            || !(1..=1_024).contains(&context.simultaneous_comparisons)
        {
            return Err(EvaluationClosureError::MultiplicityProfile.into());
        }
        paired::require_comparable_plans(
            &context.candidate_temporal, &context.baseline_temporal,
        )?;
        input.metric_contracts = normalize_product_plan_inputs(
            context.objective_digest, context.family_alpha_ppm,
            context.simultaneous_comparisons, input.base_estimand_digest,
            &input.metric_contracts, &mut input.metric_roles, &mut input.metric_sources,
            &context.candidate_temporal, &context.baseline_temporal,
        )?;
        normalize_cross_fold_metadata(
            &mut input.metric_contracts, &mut input.folds,
            &context.final_holdout_window_id,
        )?;
        role_contract_commitment_bytes(
            &mut input.metric_contracts, &mut input.metric_roles,
        )?;
        let policy = Self { context, input };
        policy.canonical_commitment_bytes()?;
        Ok(policy)
    }

    /// Strict metadata decoding only; no old plan, execution or qualification
    /// receipt seal is accepted or recreated by this operation.
    pub fn from_canonical_commitment_bytes(
        bytes: &[u8],
    ) -> Result<Self, ProductEvaluationError> {
        let (context, input) = codec::decode(bytes)?;
        let policy = Self::freeze(context, input)?;
        if policy.canonical_commitment_bytes()? != bytes {
            return Err(ProductEvaluationError::Binding("canonical policy bytes"));
        }
        Ok(policy)
    }

    pub fn canonical_commitment_bytes(&self) -> Result<Vec<u8>, ProductEvaluationError> {
        codec::encode(&self.context, &self.input)
    }

    pub fn digest(&self) -> Result<Digest32, ProductEvaluationError> {
        Ok(Digest32::of_bytes(&self.canonical_commitment_bytes()?))
    }

    pub fn context(&self) -> &ProductEvaluationPolicyContextV2 {
        &self.context
    }

    pub fn input(&self) -> &ProductEvaluationPolicyInputV2 {
        &self.input
    }

    /// Local original-owner path. It uses the existing paired freezer, with
    /// unchanged metric roles, margins, estimators and confidence parameters.
    pub fn instantiate(
        &self,
        bindings: &ProductEvaluationPolicyBindingsV2,
        pairing: &OnPolicyPairingContractV1,
    ) -> Result<ProductFrozenEvaluationPlanV1, ProductEvaluationError> {
        freeze_paired_on_policy_product_evaluation_plan_v1(
            self.bound_plan(bindings), self.input.metric_roles.clone(),
            self.input.metric_sources.clone(), &self.context.candidate_temporal,
            &self.context.baseline_temporal, pairing.clone(),
        )
    }

    /// Remote comparison path. Only original pure normalization, hashes and
    /// canonical encoders are shared; no freezer or receipt-seal constructor is
    /// called. The returned bytes cannot be used as execution or qualification.
    pub fn expected_commitment_bytes(
        &self,
        bindings: &ProductEvaluationPolicyBindingsV2,
        pairing: &OnPolicyPairingContractV1,
    ) -> Result<ProductEvaluationPolicyCommitmentsV2, ProductEvaluationError> {
        let estimand = paired::commitments::estimand_fields(
            bindings.cell_estimand_digest, self.context.candidate_temporal.plan_digest,
            self.context.baseline_temporal.plan_digest, pairing, &self.input.metric_sources,
        )?;
        let mut bound = self.bound_plan(bindings);
        bound.estimand_digest = Digest32::of_bytes(&estimand);
        let mut metric_roles = self.input.metric_roles.clone();
        let commitments = cross_fold_plan_v2_commitments(&mut bound, &mut metric_roles)?;
        let plan = paired::commitments::plan_fields(
            commitments.plan_digest, commitments.metric_contract_digest,
            bindings.cell_estimand_digest, self.context.candidate_temporal.plan_digest,
            self.context.baseline_temporal.plan_digest, pairing, &bound.metric_contracts,
            &metric_roles, &self.input.metric_sources,
        )?;
        let roles = role_contract_commitment_bytes(
            &mut bound.metric_contracts, &mut metric_roles,
        )?;
        Ok(ProductEvaluationPolicyCommitmentsV2 { plan, estimand, roles })
    }

    fn bound_plan(&self, bindings: &ProductEvaluationPolicyBindingsV2) -> CrossFoldPlanV1 {
        CrossFoldPlanV1 {
            plan_id: self.context.plan_id.clone(),
            claim_scope: self.input.claim_scope,
            candidate_id: bindings.candidate_id.clone(),
            baseline_id: self.input.baseline_id.clone(),
            objective_digest: self.context.objective_digest,
            dataset_digest: bindings.dataset_digest,
            estimand_digest: bindings.cell_estimand_digest,
            metric_contracts: self.input.metric_contracts.clone(),
            family_alpha_ppm: self.context.family_alpha_ppm,
            simultaneous_comparisons: self.context.simultaneous_comparisons,
            folds: self.input.folds.clone(),
            final_holdout_window_id: self.context.final_holdout_window_id.clone(),
            final_holdout_digest: bindings.final_holdout_digest,
        }
    }
}

#[cfg(test)]
#[path = "product_policy_tests.rs"]
mod tests;
