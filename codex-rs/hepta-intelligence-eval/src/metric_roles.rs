//! Preregistered metric roles for independent evaluation.
//!
//! Freeze roles before consuming the final holdout. Every metric has one role,
//! and at least one primary objective must demonstrate improvement. Directions,
//! absolute bounds, roles and margins all enter the metric and plan digests.
//! Existing plan/holdout receipt types retain their source-compatible shape;
//! their V2 metric digest prevents fallback to the legacy all-superiority gate.
//! These receipts commit to supplied evidence; their local seals do not prove
//! when data was first observed or authenticate the statistical evidence.

use super::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MetricRoleV2 {
    /// The conservative, direction-adjusted improvement must exceed this
    /// nonnegative margin strictly. All registered primary objectives must pass.
    PrimarySuperiority { minimum_improvement: FixedQ32 },
    /// The conservative improvement must be at least minus this nonnegative
    /// margin. Equality passes; no improvement is required for a constraint.
    NonInferiority { maximum_regression: FixedQ32 },
    /// Only the registered `safety_floor` gates this metric: a lower bound for
    /// Maximize and an upper bound for Minimize. The bound must be present.
    AbsoluteConstraint,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MetricRoleContractV2 {
    pub metric_id: StableId,
    pub role: MetricRoleV2,
}

/// Freeze an ordinary cross-fold plan together with its complete metric roles.
/// The returned receipt can use the existing final-holdout registry and journal.
pub fn freeze_cross_fold_plan_v2(
    plan: CrossFoldPlanV1,
    mut metric_roles: Vec<MetricRoleContractV2>,
) -> Result<CrossFoldPlanReceiptV1, EvaluationClosureError> {
    let mut contracts = plan.metric_contracts.clone();
    let contract_digest = digest_role_contracts(&mut contracts, &mut metric_roles)?;
    let mut receipt = freeze_cross_fold_plan(plan)?;
    let mut bytes = b"hepta.intelligence-eval.cross-fold-plan.v3".to_vec();
    bytes.extend_from_slice(receipt.plan_digest.as_array());
    bytes.extend_from_slice(contract_digest.as_array());
    receipt.plan_digest = Digest32::of_bytes(&bytes);
    receipt.metric_contract_digest = contract_digest;
    receipt.receipt_seal = frozen_plan_receipt_seal(&receipt);
    Ok(receipt)
}

/// Evaluate using the exact roles frozen by [`freeze_cross_fold_plan_v2`].
/// All V1 evidence, role-separation, holdout and absolute-bound checks apply.
/// No role or margin can be changed after freezing without a new plan digest.
pub fn decide_independently_v2(
    bundle: IndependentEvaluationBundleV1,
    metric_roles: Vec<MetricRoleContractV2>,
    now: u64,
) -> Result<IndependentEvaluationDecisionV1, EvaluationClosureError> {
    let contract_digest = digest_evaluation_roles(&bundle, &metric_roles)?;
    let roles: BTreeMap<_, _> = metric_roles
        .into_iter()
        .map(|contract| (contract.metric_id, contract.role))
        .collect();
    decide_with_metric_contract(bundle, now, contract_digest, |metric| {
        // Widen before subtraction: both endpoints may span all of Q32.
        let improvement = match metric.direction {
            EvaluationDirectionV1::Maximize => {
                i128::from(metric.candidate.lower.raw()) - i128::from(metric.baseline.upper.raw())
            }
            EvaluationDirectionV1::Minimize => {
                i128::from(metric.baseline.lower.raw()) - i128::from(metric.candidate.upper.raw())
            }
        };
        roles.get(&metric.metric_id).is_some_and(|role| match role {
            MetricRoleV2::PrimarySuperiority {
                minimum_improvement,
            } => improvement > i128::from(minimum_improvement.raw()),
            MetricRoleV2::NonInferiority { maximum_regression } => {
                improvement >= -i128::from(maximum_regression.raw())
            }
            MetricRoleV2::AbsoluteConstraint => true,
        })
    })
}

pub(crate) fn digest_evaluation_roles(
    bundle: &IndependentEvaluationBundleV1,
    metric_roles: &[MetricRoleContractV2],
) -> Result<Digest32, EvaluationClosureError> {
    digest_role_contracts(
        &mut metric_contracts(&bundle.metrics),
        &mut metric_roles.to_vec(),
    )
}

fn digest_role_contracts(
    contracts: &mut [MetricContractV1],
    metric_roles: &mut [MetricRoleContractV2],
) -> Result<Digest32, EvaluationClosureError> {
    let legacy_digest = digest_metric_contracts(contracts)?;
    if metric_roles.len() != contracts.len() {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "metric role coverage",
        ));
    }
    metric_roles.sort_by_key(|contract| contract.metric_id.clone());
    let mut bytes = b"hepta.intelligence-eval.metric-contract.v2".to_vec();
    bytes.extend_from_slice(legacy_digest.as_array());
    let mut primary_count = 0;
    for (contract, role) in contracts.iter().zip(metric_roles.iter()) {
        // Contracts are already unique and sorted, so equality also excludes
        // duplicate role entries, omitted metrics and unknown metrics.
        if contract.metric_id != role.metric_id {
            return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
                "metric role coverage",
            ));
        }
        push_id(&mut bytes, &role.metric_id);
        match role.role {
            MetricRoleV2::PrimarySuperiority {
                minimum_improvement,
            } => {
                if minimum_improvement < FixedQ32::ZERO {
                    return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
                        "negative superiority margin",
                    ));
                }
                primary_count += 1;
                bytes.push(0);
                bytes.extend_from_slice(&minimum_improvement.raw().to_be_bytes());
            }
            MetricRoleV2::NonInferiority { maximum_regression } => {
                if maximum_regression < FixedQ32::ZERO {
                    return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
                        "negative noninferiority margin",
                    ));
                }
                bytes.push(1);
                bytes.extend_from_slice(&maximum_regression.raw().to_be_bytes());
            }
            MetricRoleV2::AbsoluteConstraint => {
                if contract.safety_floor.is_none() {
                    return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
                        "missing absolute constraint bound",
                    ));
                }
                bytes.push(2);
            }
        }
    }
    if primary_count == 0 {
        return Err(EvaluationClosureError::FrozenPlanBindingMismatch(
            "missing primary objective",
        ));
    }
    Ok(Digest32::of_bytes(&bytes))
}
