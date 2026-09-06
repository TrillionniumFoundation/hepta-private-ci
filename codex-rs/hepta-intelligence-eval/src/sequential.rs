//! Finite-horizon, history-conditioned point estimates over complete trajectories.
//!
//! Callers authenticate histories, policy/observer identities and held-out Q
//! predictions. Digests bind those assertions; this core does not establish
//! exchangeability, fit nuisance models, compute intervals or certify efficacy.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ope::scaled_ratio;
use crate::push_id;

const SCALE: i128 = 1_i128 << 32;
const MAX_TRAJECTORIES: usize = 4_096;
const MAX_STEPS: usize = 65_536;

#[path = "sequential_model.rs"]
mod model;
#[path = "sequential_step.rs"]
mod step;

pub use model::DepthSupport;
pub use model::FiniteHorizonEstimand;
pub use model::SequentialError;
pub use model::SequentialEstimate;
pub use model::SequentialEvidenceGap;
pub use model::SequentialPlan;
pub use model::TerminalRewardConvention;
pub use model::Trajectory;
pub use model::TrajectoryAction;
pub use model::TrajectoryBoundary;
pub use model::TrajectoryClaimScope;
pub use model::TrajectoryEstimate;
pub use model::TrajectoryStep;
use step::divide;
use step::fixed;
use step::insufficient;
use step::multiply;
use step::multiply_nonzero;
use step::validate_step;

/// Computes backward DR and per-decision IS with nearest/ties-even Q32 arithmetic.
///
/// V(H) is the evaluation-policy average of supplied Q(H,a), avoiding inconsistent
/// independently supplied V values. Unsupported, censored or low-support data
/// rejects the complete estimate; no rows are silently omitted or weights clipped.
pub fn estimate_sequential(
    plan: &SequentialPlan,
    trajectories: &[Trajectory],
) -> Result<SequentialEstimate, SequentialError> {
    let horizon = usize::from(plan.estimand.horizon);
    if !(1..=128).contains(&horizon)
        || plan.plan_digest.is_zero()
        || plan.behavior_policy.is_zero()
        || plan.evaluation_policy.is_zero()
        || plan.minimum_trajectories == 0
        || plan.minimum_trajectories > MAX_TRAJECTORIES
        || plan.minimum_depth_ess <= FixedQ32::ZERO
        || [plan.maximum_step_ratio, plan.maximum_cumulative_ratio]
            .iter()
            .any(|limit| limit.raw() <= 0 || i128::from(limit.raw()) > 50 * SCALE)
    {
        return Err(SequentialError::InvalidPlan);
    }
    if trajectories.len() > MAX_TRAJECTORIES || trajectories.len() * horizon > MAX_STEPS {
        return Err(SequentialError::ResourceLimit);
    }
    if trajectories.len() < plan.minimum_trajectories {
        return insufficient(SequentialEvidenceGap::InsufficientTrajectories);
    }
    let mut ordered: Vec<_> = trajectories.iter().collect();
    ordered.sort_by(|a, b| a.trajectory_id.cmp(&b.trajectory_id));
    let mut bytes = b"hepta.sequential-dr.q32.v1".to_vec();
    bytes.extend_from_slice(plan.plan_digest.as_array());
    bytes.extend_from_slice(plan.behavior_policy.as_array());
    bytes.extend_from_slice(plan.evaluation_policy.as_array());
    for value in [
        plan.observation_generation.get(),
        plan.outcome_watermark,
        u64::from(plan.estimand.horizon),
        plan.minimum_trajectories as u64,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.push(match plan.estimand.terminal_reward {
        TerminalRewardConvention::IncludedInLastReward => 0,
        TerminalRewardConvention::SeparateTerminalValue => 1,
    });
    bytes.push(match plan.estimand.scope {
        TrajectoryClaimScope::Qualification => 0,
        TrajectoryClaimScope::SystemLongitudinal => 1,
    });
    for value in [
        plan.minimum_depth_ess,
        plan.maximum_step_ratio,
        plan.maximum_cumulative_ratio,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    let mut identities = BTreeSet::new();
    let mut decisions = BTreeSet::new();
    let mut clusters = BTreeSet::new();
    let mut estimates = Vec::with_capacity(ordered.len());
    for trajectory in ordered {
        if !identities.insert(&trajectory.trajectory_id) {
            return Err(SequentialError::DuplicateIdentity);
        }
        clusters.insert(&trajectory.cluster_id);
        let (estimate, digest) = estimate_trajectory(plan, trajectory, &mut decisions)?;
        bytes.extend_from_slice(digest.as_array());
        estimates.push(estimate);
    }
    let count = estimates.len() as i128;
    let floor = match plan.estimand.scope {
        TrajectoryClaimScope::Qualification => i128::from(plan.minimum_depth_ess.raw()),
        TrajectoryClaimScope::SystemLongitudinal => i128::from(plan.minimum_depth_ess.raw())
            .max(400 * SCALE)
            .max(((count + 9) / 10) * SCALE),
    };
    let mut depth_support = Vec::with_capacity(horizon);
    for depth in 0..horizon {
        let weights: Vec<_> = estimates
            .iter()
            .map(|row| i128::from(row.cumulative_weights[depth].raw()))
            .collect();
        let sum: i128 = weights.iter().sum();
        // Keep squares in Q64: tiny nonzero weights must not lose their ESS.
        let squares: i128 = weights.iter().map(|weight| weight * weight).sum();
        if squares == 0 {
            return insufficient(SequentialEvidenceGap::DepthSupport);
        }
        let ess = scaled_ratio(sum * sum, squares).map_err(|_| SequentialError::Arithmetic)?;
        if ess < floor {
            return insufficient(SequentialEvidenceGap::DepthSupport);
        }
        depth_support.push(DepthSupport {
            depth: depth as u16,
            effective_sample_size: fixed(ess)?,
            maximum_cumulative_weight: fixed(weights.iter().copied().max().unwrap_or(0))?,
            positive_weight_trajectories: weights.iter().filter(|weight| **weight > 0).count(),
        });
    }
    let pdis = estimates
        .iter()
        .map(|row| i128::from(row.per_decision_importance_sampling.raw()))
        .sum();
    let dr = estimates
        .iter()
        .map(|row| i128::from(row.doubly_robust.raw()))
        .sum();
    Ok(SequentialEstimate {
        per_decision_importance_sampling: fixed(divide(pdis, count)?)?,
        doubly_robust: fixed(divide(dr, count)?)?,
        trajectories: estimates,
        cluster_count: clusters.len(),
        depth_support,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn estimate_trajectory<'a>(
    plan: &SequentialPlan,
    row: &'a Trajectory,
    decisions: &mut BTreeSet<&'a StableId>,
) -> Result<(TrajectoryEstimate, Digest32), SequentialError> {
    if row.steps.len() != usize::from(plan.estimand.horizon) || row.initial_history.is_zero() {
        return insufficient(SequentialEvidenceGap::IncompleteHistory);
    }
    if row.behavior_policy != plan.behavior_policy
        || row.evaluation_policy != plan.evaluation_policy
    {
        return insufficient(SequentialEvidenceGap::GenerationMismatch);
    }
    if plan.estimand.terminal_reward == TerminalRewardConvention::IncludedInLastReward
        && row.terminal_value != FixedQ32::ZERO
    {
        return Err(SequentialError::TerminalConvention);
    }
    if i128::from(row.terminal_value.raw()).abs() > SCALE {
        return Err(SequentialError::InvalidValue);
    }
    let mut bytes = b"hepta.sequential.trajectory.v1".to_vec();
    push_id(&mut bytes, &row.trajectory_id);
    push_id(&mut bytes, &row.cluster_id);
    bytes.extend_from_slice(row.initial_history.as_array());
    bytes.extend_from_slice(&row.terminal_value.raw().to_be_bytes());
    let mut expected_history = row.initial_history;
    let mut histories = BTreeSet::from([row.initial_history]);
    let mut cumulative = SCALE;
    let mut discount = SCALE;
    let mut pdis = 0_i128;
    let mut values = Vec::with_capacity(row.steps.len());
    let mut weights = Vec::with_capacity(row.steps.len());
    for (depth, step) in row.steps.iter().enumerate() {
        if !decisions.insert(&step.decision_id) {
            return Err(SequentialError::DuplicateIdentity);
        }
        if step.boundary == TrajectoryBoundary::Censored {
            return insufficient(SequentialEvidenceGap::CensoredTrajectory);
        }
        let expected_boundary = if depth + 1 == row.steps.len() {
            TrajectoryBoundary::Terminal
        } else {
            TrajectoryBoundary::Continuing
        };
        if step.history_digest != expected_history
            || step.next_history_digest.is_zero()
            || !histories.insert(step.next_history_digest)
            || step.boundary != expected_boundary
        {
            return insufficient(SequentialEvidenceGap::IncompleteHistory);
        }
        expected_history = step.next_history_digest;
        if step.observation_generation != plan.observation_generation {
            return insufficient(SequentialEvidenceGap::GenerationMismatch);
        }
        let (rho, q, v, reward) = validate_step(plan, step, &mut bytes)?;
        if cumulative * rho > i128::from(plan.maximum_cumulative_ratio.raw()) * SCALE {
            return insufficient(SequentialEvidenceGap::WeightLimit);
        }
        cumulative = multiply_nonzero(cumulative, rho)?;
        let weighted = multiply(cumulative, reward)?;
        pdis = pdis
            .checked_add(multiply(discount, weighted)?)
            .ok_or(SequentialError::Arithmetic)?;
        let gamma = i128::from(step.discount.raw());
        discount = multiply_nonzero(discount, gamma)?;
        weights.push(fixed(cumulative)?);
        values.push((rho, q, v, reward, gamma));
    }
    pdis = pdis
        .checked_add(multiply(
            discount,
            multiply(cumulative, i128::from(row.terminal_value.raw()))?,
        )?)
        .ok_or(SequentialError::Arithmetic)?;
    let mut dr = i128::from(row.terminal_value.raw());
    for (rho, q, v, reward, gamma) in values.into_iter().rev() {
        let residual = reward
            .checked_add(multiply(gamma, dr)?)
            .and_then(|value| value.checked_sub(q))
            .ok_or(SequentialError::Arithmetic)?;
        dr = v
            .checked_add(multiply(rho, residual)?)
            .ok_or(SequentialError::Arithmetic)?;
        fixed(dr)?;
    }
    Ok((
        TrajectoryEstimate {
            trajectory_id: row.trajectory_id.clone(),
            per_decision_importance_sampling: fixed(pdis)?,
            doubly_robust: fixed(dr)?,
            cumulative_weights: weights,
        },
        Digest32::of_bytes(&bytes),
    ))
}
