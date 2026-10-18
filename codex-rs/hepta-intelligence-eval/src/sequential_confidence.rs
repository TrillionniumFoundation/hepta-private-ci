//! Conservative cluster intervals for finite-horizon sequential point estimates.
//!
//! The underlying PDIS/DR implementation remains unchanged. This layer requires
//! a preregistered absolute contribution envelope covering all legal actions,
//! rewards and the global Q range, and treats cluster labels as supplied
//! evidence, not proof of independence. Future-state validity of the plan's
//! propensity envelope remains an independently justified assumption. It is
//! fixed-analysis only:
//! no anytime-valid, adaptive-stopping or causal-identification claim is added.

use std::collections::BTreeMap;

use super::*;
use crate::ClusterConfidencePlan;
use crate::OpeInterval;

impl SequentialPlan {
    /// Return `(point, PDIS interval, DR interval, confidence evidence digest)`.
    pub fn estimate_cluster_intervals_v1(
        &self,
        confidence: &ClusterConfidencePlan,
        maximum_absolute_trajectory_return: FixedQ32,
        trajectories: &[Trajectory],
    ) -> Result<(SequentialEstimate, OpeInterval, OpeInterval, Digest32), SequentialError> {
        if confidence.plan_digest.is_zero()
            || confidence.assumptions_digest.is_zero()
            || !(1..=100_000).contains(&confidence.family_alpha_ppm)
            || !(1..=1_024).contains(&confidence.simultaneous_comparisons)
            || confidence.minimum_clusters < 2
            || maximum_absolute_trajectory_return <= FixedQ32::ZERO
        {
            return Err(SequentialError::InvalidPlan);
        }
        let point = estimate_sequential(self, trajectories)?;
        let mut cluster_by_trajectory = BTreeMap::new();
        let mut sizes = BTreeMap::<StableId, usize>::new();
        for trajectory in trajectories {
            if cluster_by_trajectory
                .insert(
                    trajectory.trajectory_id.clone(),
                    trajectory.cluster_id.clone(),
                )
                .is_some()
            {
                return Err(SequentialError::DuplicateIdentity);
            }
            *sizes.entry(trajectory.cluster_id.clone()).or_default() += 1;
        }
        if sizes.len() < confidence.minimum_clusters {
            return Err(SequentialError::InsufficientEvidence(
                SequentialEvidenceGap::InsufficientClusters,
            ));
        }
        let envelope = i128::from(maximum_absolute_trajectory_return.raw());
        if envelope < required_contribution_envelope(self)? {
            return Err(SequentialError::InsufficientEvidence(
                SequentialEvidenceGap::ConfidenceEnvelope,
            ));
        }
        if point.trajectories.iter().any(|row| {
            i128::from(row.per_decision_importance_sampling.raw()).abs() > envelope
                || i128::from(row.doubly_robust.raw()).abs() > envelope
        }) {
            return Err(SequentialError::InsufficientEvidence(
                SequentialEvidenceGap::ConfidenceEnvelope,
            ));
        }
        let count = u128::try_from(trajectories.len()).map_err(|_| SequentialError::Arithmetic)?;
        let mut sum_squares = 0_u128;
        for size in sizes.values().copied() {
            let size = u128::try_from(size).map_err(|_| SequentialError::Arithmetic)?;
            sum_squares = sum_squares
                .checked_add(size * size)
                .ok_or(SequentialError::Arithmetic)?;
        }
        let probability_ratio = (4_000_000_u128 * u128::from(confidence.simultaneous_comparisons))
            .div_ceil(u128::from(confidence.family_alpha_ppm));
        let log_upper = u128::from((probability_ratio - 1).ilog2() + 1);
        let range = u128::try_from(envelope)
            .map_err(|_| SequentialError::Arithmetic)?
            .checked_mul(2)
            .ok_or(SequentialError::Arithmetic)?;
        let radius = confidence_radius(range, log_upper, sum_squares, count)?;
        let pdis = confidence_interval(point.per_decision_importance_sampling, radius)?;
        let dr = confidence_interval(point.doubly_robust, radius)?;

        let mut bytes = b"hepta.sequential.cluster-confidence.v1".to_vec();
        for digest in [
            point.evidence_digest,
            confidence.plan_digest,
            confidence.assumptions_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&confidence.family_alpha_ppm.to_be_bytes());
        bytes.extend_from_slice(&confidence.simultaneous_comparisons.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(confidence.minimum_clusters)
                .map_err(|_| SequentialError::Arithmetic)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&maximum_absolute_trajectory_return.raw().to_be_bytes());
        for (trajectory, cluster) in cluster_by_trajectory {
            push_id(&mut bytes, &trajectory);
            push_id(&mut bytes, &cluster);
        }
        for interval in [pdis, dr] {
            bytes.extend_from_slice(&interval.lower.raw().to_be_bytes());
            bytes.extend_from_slice(&interval.upper.raw().to_be_bytes());
        }
        Ok((point, pdis, dr, Digest32::of_bytes(&bytes)))
    }
}

fn required_contribution_envelope(plan: &SequentialPlan) -> Result<i128, SequentialError> {
    let horizon = i128::from(plan.estimand.horizon);
    let weight = i128::from(plan.maximum_cumulative_ratio.raw());
    let terminal =
        if plan.estimand.terminal_reward == TerminalRewardConvention::SeparateTerminalValue {
            weight
        } else {
            0
        };
    let pdis_bound = horizon
        .checked_mul(weight)
        .and_then(|value| value.checked_add(terminal))
        .ok_or(SequentialError::Arithmetic)?;
    // Expand backward DR using cumulative numerical ratios. |Q| and |V|
    // never exceed the GLOBAL input cap, including histories absent from this
    // sample; discounts never exceed one. Each reward/Q residual and each
    // subsequent V is multiplied by a cumulative ratio bounded by the plan.
    let q_bound = MAX_ABSOLUTE_Q_RETURN / SCALE;
    let residuals = horizon
        .checked_mul(weight)
        .and_then(|value| value.checked_mul(1 + q_bound))
        .ok_or(SequentialError::Arithmetic)?;
    let future_values = (horizon - 1)
        .checked_mul(weight)
        .and_then(|value| value.checked_mul(q_bound))
        .ok_or(SequentialError::Arithmetic)?;
    // Each recursion has two nearest-rounded products. After expansion their
    // errors are <= 1/2 raw unit times previous/current cumulative ratios.
    let rounding = divide_upper(
        (2 * horizon - 1)
            .checked_mul(weight)
            .and_then(|value| value.checked_add(SCALE))
            .ok_or(SequentialError::Arithmetic)?,
        2 * SCALE,
    )?;
    let dr_bound = MAX_ABSOLUTE_Q_RETURN
        .checked_add(residuals)
        .and_then(|value| value.checked_add(future_values))
        .and_then(|value| value.checked_add(terminal))
        .and_then(|value| value.checked_add(rounding))
        .ok_or(SequentialError::Arithmetic)?;
    Ok(pdis_bound.max(dr_bound))
}

fn confidence_radius(
    range: u128,
    log_upper: u128,
    sum_squares: u128,
    count: u128,
) -> Result<i128, SequentialError> {
    let denominator = count
        .checked_mul(count)
        .and_then(|value| value.checked_mul(2))
        .filter(|value| *value > 0)
        .ok_or(SequentialError::Arithmetic)?;
    // Retain the exact quotient/remainder after every factor instead of
    // constructing a numerator that can exceed u128 although its quotient
    // (and the final Q32 radius) is representable. Under the trajectory cap,
    // remainder < 2*4096^2 and every factor is <= 2*u64::MAX, so the remainder
    // product is bounded independently of the full numerator's width.
    let mut quotient = 1 / denominator;
    let mut remainder = 1 % denominator;
    for factor in [range, range, log_upper, sum_squares] {
        let remainder_product = remainder
            .checked_mul(factor)
            .ok_or(SequentialError::Arithmetic)?;
        quotient = quotient
            .checked_mul(factor)
            .and_then(|value| value.checked_add(remainder_product / denominator))
            .ok_or(SequentialError::Arithmetic)?;
        remainder = remainder_product % denominator;
    }
    let squared = quotient
        .checked_add(u128::from(remainder != 0))
        .ok_or(SequentialError::Arithmetic)?;
    let floor = squared.isqrt();
    let outward = floor
        .checked_add(u128::from(floor * floor < squared))
        .and_then(|value| value.checked_add(8))
        .ok_or(SequentialError::Arithmetic)?;
    i128::try_from(outward).map_err(|_| SequentialError::Arithmetic)
}

fn confidence_interval(center: FixedQ32, radius: i128) -> Result<OpeInterval, SequentialError> {
    Ok(OpeInterval {
        lower: fixed(i128::from(center.raw()) - radius)?,
        upper: fixed(i128::from(center.raw()) + radius)?,
    })
}

#[cfg(test)]
#[path = "sequential_confidence_tests.rs"]
mod tests;
