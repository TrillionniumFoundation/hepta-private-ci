//! Conservative cluster intervals for a frozen, single-holdout OPE analysis.
//!
//! Assumptions: independent clusters with prespecified sizes, a fixed evaluation
//! policy and an outcome model trained on a population independent of ALL these
//! clusters, correct propensities, and a prespecified bound on possible weights.
//! Arbitrary K-fold predictions need not meet that independence condition.
//! Caller-supplied digests and cluster IDs do NOT authenticate these assumptions.
//!
//! For bounded row contributions of range R and cluster sizes n_g, Hoeffding's
//! two-sided radius is R*sqrt(log(2/delta)*sum(n_g^2)/(2*n^2)). We replace the log
//! with ceil(log2(ceil(6*m/alpha))), an upper bound, to avoid platform libm drift.
//! Union bounds cover numerator, denominator and DR across m comparisons.
//! Integer division and square roots round OUTWARD, with eight raw Q32 units
//! for arithmetic rounding. These bound conditional contribution expectations;
//! causal value identification, sequential stopping, shared-training leakage
//! and cryptographic observer independence need separate qualification.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::MAX_ROWS;
use super::OpeError;
use super::OpeEstimate;
use super::OpePlan;
use super::OpeRow;
use super::SCALE;
use super::estimate_ope;
use super::estimate_row;
use super::fixed;
use super::round_ratio;
use crate::push_id;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClusterAssignment {
    pub decision_id: StableId,
    pub cluster_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClusterConfidencePlan {
    pub plan_digest: Digest32,
    pub assumptions_digest: Digest32,
    pub family_alpha_ppm: u32,
    pub simultaneous_comparisons: u32,
    pub minimum_clusters: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OpeInterval {
    pub lower: FixedQ32,
    pub upper: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClusterOpeEstimate {
    pub point: OpeEstimate,
    pub cluster_count: usize,
    pub largest_cluster_rows: usize,
    pub ips: OpeInterval,
    pub snips: OpeInterval,
    pub doubly_robust: OpeInterval,
    pub weight_mean: OpeInterval,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ClusterConfidenceError {
    InvalidPlan,
    AssignmentMismatch,
    DuplicateAssignment,
    InsufficientClusters,
    WeightEnvelope,
    Ope(OpeError),
    Arithmetic,
}

impl fmt::Display for ClusterConfidenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ClusterConfidenceError {}

impl From<OpeError> for ClusterConfidenceError {
    fn from(error: OpeError) -> Self {
        Self::Ope(error)
    }
}

/// Compute prespecified fixed-horizon intervals without approving a candidate.
///
/// Each decision must have exactly one cluster assignment. The caller must
/// cluster all dependent observations together; IDs alone cannot prove this.
/// Bounds use the PLAN'S weight ceiling, never a fitted or observed ceiling.
/// The ceiling is checked on unchosen legal actions too. A future-state ceiling
/// still needs external justification. An unresolved SNIPS denominator yields
/// [0, 1], not a discarded resample.
pub fn estimate_cluster_intervals(
    ope_plan: &OpePlan,
    plan: &ClusterConfidencePlan,
    rows: &[OpeRow],
    assignments: &[ClusterAssignment],
) -> Result<ClusterOpeEstimate, ClusterConfidenceError> {
    if plan.plan_digest.is_zero()
        || plan.assumptions_digest.is_zero()
        || !(1..=100_000).contains(&plan.family_alpha_ppm)
        || !(1..=1024).contains(&plan.simultaneous_comparisons)
        || !(2..=MAX_ROWS).contains(&plan.minimum_clusters)
        || ope_plan.maximum_weight < FixedQ32::ONE
    {
        return Err(ClusterConfidenceError::InvalidPlan);
    }
    if assignments.len() != rows.len() || assignments.len() > MAX_ROWS {
        return Err(ClusterConfidenceError::AssignmentMismatch);
    }
    let point = estimate_ope(ope_plan, rows)?;
    let mut assignment_map = BTreeMap::new();
    for assignment in assignments {
        if assignment_map
            .insert(&assignment.decision_id, &assignment.cluster_id)
            .is_some()
        {
            return Err(ClusterConfidenceError::DuplicateAssignment);
        }
    }
    let mut sizes: BTreeMap<&StableId, usize> = BTreeMap::new();
    let mut weight_sum = 0_i128;
    for row in rows {
        let cluster = assignment_map
            .get(&row.decision_id)
            .ok_or(ClusterConfidenceError::AssignmentMismatch)?;
        *sizes.entry(cluster).or_default() += 1;
        for action in &row.actions {
            let target = i128::from(action.evaluation_probability.raw()) * SCALE;
            let limit = i128::from(action.behavior_probability.raw())
                * i128::from(ope_plan.maximum_weight.raw());
            if target > limit {
                return Err(ClusterConfidenceError::WeightEnvelope);
            }
        }
        let (weight, _, _, _) = estimate_row(ope_plan, row)?;
        weight_sum = weight_sum
            .checked_add(weight)
            .ok_or(ClusterConfidenceError::Arithmetic)?;
    }
    if sizes.len() < plan.minimum_clusters {
        return Err(ClusterConfidenceError::InsufficientClusters);
    }
    let count = u128::try_from(rows.len()).map_err(|_| ClusterConfidenceError::Arithmetic)?;
    let mut sum_squares = 0_u128;
    let mut largest_cluster_rows = 0;
    for size in sizes.values().copied() {
        largest_cluster_rows = largest_cluster_rows.max(size);
        let size = u128::try_from(size).map_err(|_| ClusterConfidenceError::Arithmetic)?;
        sum_squares += size * size;
    }
    let probability_ratio = (6_000_000_u128 * u128::from(plan.simultaneous_comparisons))
        .div_ceil(u128::from(plan.family_alpha_ppm));
    let log_upper = u128::from((probability_ratio - 1).ilog2() + 1);
    let weight_range = u128::try_from(ope_plan.maximum_weight.raw())
        .map_err(|_| ClusterConfidenceError::Arithmetic)?;
    let weight_radius = radius(weight_range, log_upper, sum_squares, count)?;
    // Distribution normalization tolerates one Q32 unit; retain a range guard.
    let dr_range = (1_u128 << 32) + 2 * weight_range + 2;
    let dr_radius = radius(dr_range, log_upper, sum_squares, count)?;
    let count = i128::try_from(count).map_err(|_| ClusterConfidenceError::Arithmetic)?;
    let ips = interval(point.ips, weight_radius)?;
    let doubly_robust = interval(point.doubly_robust, dr_radius)?;
    let weight_mean = interval(fixed(round_ratio(weight_sum, count)?)?, weight_radius)?;
    let snips = if weight_mean.lower <= FixedQ32::ZERO {
        OpeInterval {
            lower: FixedQ32::ZERO,
            upper: FixedQ32::ONE,
        }
    } else {
        let numerator_low = u128::try_from(ips.lower.raw().max(0))
            .map_err(|_| ClusterConfidenceError::Arithmetic)?;
        let numerator_high = u128::try_from(ips.upper.raw().max(0))
            .map_err(|_| ClusterConfidenceError::Arithmetic)?;
        let denominator_low = u128::try_from(weight_mean.lower.raw())
            .map_err(|_| ClusterConfidenceError::Arithmetic)?;
        let denominator_high = u128::try_from(weight_mean.upper.raw())
            .map_err(|_| ClusterConfidenceError::Arithmetic)?;
        let lower = ((numerator_low << 32) / denominator_high).min(1_u128 << 32);
        let upper = (numerator_high << 32)
            .div_ceil(denominator_low)
            .min(1_u128 << 32);
        OpeInterval {
            lower: fixed(i128::try_from(lower).map_err(|_| ClusterConfidenceError::Arithmetic)?)?,
            upper: fixed(i128::try_from(upper).map_err(|_| ClusterConfidenceError::Arithmetic)?)?,
        }
    };
    let mut bytes = b"hepta.ope.cluster-hoeffding.v1".to_vec();
    bytes.extend_from_slice(point.evidence_digest.as_array());
    bytes.extend_from_slice(plan.plan_digest.as_array());
    bytes.extend_from_slice(plan.assumptions_digest.as_array());
    bytes.extend_from_slice(&plan.family_alpha_ppm.to_be_bytes());
    bytes.extend_from_slice(&plan.simultaneous_comparisons.to_be_bytes());
    bytes.extend_from_slice(
        &u64::try_from(plan.minimum_clusters)
            .map_err(|_| ClusterConfidenceError::Arithmetic)?
            .to_be_bytes(),
    );
    for (decision, cluster) in assignment_map {
        push_id(&mut bytes, decision);
        push_id(&mut bytes, cluster);
    }
    for bounds in [ips, snips, doubly_robust, weight_mean] {
        bytes.extend_from_slice(&bounds.lower.raw().to_be_bytes());
        bytes.extend_from_slice(&bounds.upper.raw().to_be_bytes());
    }
    Ok(ClusterOpeEstimate {
        point,
        cluster_count: sizes.len(),
        largest_cluster_rows,
        ips,
        snips,
        doubly_robust,
        weight_mean,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn radius(
    range: u128,
    log_upper: u128,
    sum_squares: u128,
    count: u128,
) -> Result<i128, ClusterConfidenceError> {
    let numerator = range
        .checked_mul(range)
        .and_then(|value| value.checked_mul(log_upper))
        .and_then(|value| value.checked_mul(sum_squares))
        .ok_or(ClusterConfidenceError::Arithmetic)?;
    let denominator = count
        .checked_mul(count)
        .and_then(|value| value.checked_mul(2))
        .filter(|value| *value > 0)
        .ok_or(ClusterConfidenceError::Arithmetic)?;
    let squared = numerator.div_ceil(denominator);
    let floor = squared.isqrt();
    let outward = floor + u128::from(floor * floor < squared) + 8;
    i128::try_from(outward).map_err(|_| ClusterConfidenceError::Arithmetic)
}

fn interval(center: FixedQ32, radius: i128) -> Result<OpeInterval, ClusterConfidenceError> {
    Ok(OpeInterval {
        lower: fixed(i128::from(center.raw()) - radius)?,
        upper: fixed(i128::from(center.raw()) + radius)?,
    })
}

#[cfg(test)]
#[path = "ope_confidence_tests.rs"]
mod tests;
