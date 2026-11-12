//! Independent canonical domains for paired on-policy metadata and evidence.
//! SharedBehavior uses its original byte encoders without a version-tag tail.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::OnPolicyArmBindingV1;
use super::OnPolicyPairingContractV1;
use super::ProductComparisonModeV1;
use super::ProductEvaluationError;
use super::ProductFrozenEvaluationPlanV1;
use super::inputs;
use crate::EvaluationDirectionV1;
use crate::MetricGateV1;
use crate::MetricRoleV2;
use crate::TemporalEvaluationReceipt;

fn count(bytes: &mut Vec<u8>, value: usize) -> Result<(), ProductEvaluationError> {
    let value = u32::try_from(value)
        .map_err(|_| ProductEvaluationError::Binding("paired canonical count"))?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn id(bytes: &mut Vec<u8>, value: &StableId) {
    super::super::push_id(bytes, value);
}

fn arm(bytes: &mut Vec<u8>, original: &OnPolicyArmBindingV1) {
    for value in [&original.decision_id, &original.principal_lineage,
        &original.episode_lineage, &original.behavior_run_id] {
        id(bytes, value);
    }
    bytes.extend_from_slice(original.model_digest.as_array());
}

pub(super) fn pair_contract(
    pairing: &OnPolicyPairingContractV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    inputs::validate_pair_contract(pairing)?;
    let mut bytes = b"hepta.intelligence-eval.on-policy-pair-contract.v1".to_vec();
    bytes.push(0); // Fixed FreshEmpty initial-state contract.
    count(&mut bytes, pairing.pairs.len())?;
    let mut pairs: Vec<_> = pairing.pairs.iter().collect();
    pairs.sort_by(|left, right| left.pair_id.cmp(&right.pair_id));
    for pair in pairs {
        id(&mut bytes, &pair.pair_id);
        bytes.extend_from_slice(pair.input_digest.as_array());
        bytes.extend_from_slice(pair.protocol_digest.as_array());
        bytes.push(0);
        arm(&mut bytes, &pair.candidate);
        bytes.push(1);
        arm(&mut bytes, &pair.baseline);
    }
    Ok(bytes)
}

pub(in super::super) fn plan(
    plan: &ProductFrozenEvaluationPlanV1,
    pairing: &OnPolicyPairingContractV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let paired = pairing.canonical_commitment_bytes()?;
    let mut bytes = b"hepta.intelligence-eval.product-frozen-paired-on-policy.v1".to_vec();
    for digest in [plan.frozen_plan.plan_digest, plan.frozen_plan.metric_contract_digest,
        plan.base_estimand_digest, plan.candidate_temporal_plan_digest,
        plan.baseline_temporal_plan_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    count(&mut bytes, paired.len())?;
    bytes.extend_from_slice(&paired);
    count(&mut bytes, plan.metric_contracts.len())?;
    for contract in &plan.metric_contracts {
        id(&mut bytes, &contract.metric_id);
        bytes.push(match contract.direction {
            EvaluationDirectionV1::Maximize => 0,
            EvaluationDirectionV1::Minimize => 1,
        });
        match contract.safety_floor {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.raw().to_be_bytes());
            }
            None => bytes.push(0),
        }
    }
    count(&mut bytes, plan.metric_roles.len())?;
    for role in &plan.metric_roles {
        id(&mut bytes, &role.metric_id);
        match role.role {
            MetricRoleV2::PrimarySuperiority { minimum_improvement } => {
                bytes.push(0);
                bytes.extend_from_slice(&minimum_improvement.raw().to_be_bytes());
            }
            MetricRoleV2::NonInferiority { maximum_regression } => {
                bytes.push(1);
                bytes.extend_from_slice(&maximum_regression.raw().to_be_bytes());
            }
            MetricRoleV2::AbsoluteConstraint => bytes.push(2),
        }
    }
    count(&mut bytes, plan.metric_sources.len())?;
    for source in &plan.metric_sources {
        id(&mut bytes, &source.metric_id);
        bytes.push(source.source.tag());
    }
    Ok(bytes)
}

pub(in super::super) fn estimand(
    plan: &ProductFrozenEvaluationPlanV1,
) -> Result<Vec<u8>, ProductEvaluationError> {
    let ProductComparisonModeV1::PairedOnPolicy(pairing) = &plan.comparison else {
        return Err(ProductEvaluationError::Binding("paired estimand mode"));
    };
    if plan.base_estimand_digest.is_zero()
        || plan.candidate_temporal_plan_digest.is_zero()
        || plan.baseline_temporal_plan_digest.is_zero()
    {
        return Err(ProductEvaluationError::Binding("paired estimand source"));
    }
    let mut bytes = b"hepta.intelligence-eval.product-paired-on-policy-estimand.v1".to_vec();
    for digest in [plan.base_estimand_digest, plan.candidate_temporal_plan_digest,
        plan.baseline_temporal_plan_digest, pairing.digest()?] {
        bytes.extend_from_slice(digest.as_array());
    }
    count(&mut bytes, plan.metric_sources.len())?;
    for source in &plan.metric_sources {
        id(&mut bytes, &source.metric_id);
        bytes.push(source.source.tag());
    }
    Ok(bytes)
}

pub(in super::super) fn require_receipt_mode(
    plan: &ProductFrozenEvaluationPlanV1,
    paired_input: Option<Digest32>,
) -> Result<(), ProductEvaluationError> {
    match (&plan.comparison, paired_input) {
        (ProductComparisonModeV1::SharedBehavior, None) => Ok(()),
        (ProductComparisonModeV1::PairedOnPolicy(pairing), Some(input)) if !input.is_zero() => {
            inputs::validate_pair_contract(pairing)
        }
        _ => Err(ProductEvaluationError::Integrity("complete original paired input evidence")),
    }
}

pub(in super::super) fn comparison(
    plan: &ProductFrozenEvaluationPlanV1,
    paired_input: Option<Digest32>,
    candidate: &TemporalEvaluationReceipt,
    baseline: &TemporalEvaluationReceipt,
    metrics: &[MetricGateV1],
) -> Result<(Digest32, Digest32, Digest32), ProductEvaluationError> {
    require_receipt_mode(plan, paired_input)?;
    let legacy = super::super::comparison_digests(candidate, baseline, metrics);
    match &plan.comparison {
        ProductComparisonModeV1::SharedBehavior => Ok(legacy),
        ProductComparisonModeV1::PairedOnPolicy(pairing) => {
            let contract = pairing.digest()?;
            let input = paired_input.ok_or(ProductEvaluationError::Integrity("paired input"))?;
            let bind = |domain: &[u8], original: Digest32| {
                let mut bytes = domain.to_vec();
                for digest in [contract, input, original] {
                    bytes.extend_from_slice(digest.as_array());
                }
                Digest32::of_bytes(&bytes)
            };
            Ok((
                bind(b"hepta.intelligence-eval.paired-on-policy-estimate.v1", legacy.0),
                bind(b"hepta.intelligence-eval.paired-on-policy-support.v1", legacy.1),
                bind(b"hepta.intelligence-eval.paired-on-policy-confidence.v1", legacy.2),
            ))
        }
    }
}
