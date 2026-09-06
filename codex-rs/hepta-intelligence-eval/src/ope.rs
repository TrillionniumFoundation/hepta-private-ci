//! Bounded deterministic OPE point estimates, not an efficacy or promotion gate.
//!
//! Callers supply independently observed finalized outcomes and already verified
//! held-out outcome-model predictions. This core checks support and numeric
//! integrity; it does not authenticate receipts or manufacture confidence bounds.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::push_id;

#[path = "ope_confidence.rs"]
mod confidence;

pub use confidence::ClusterAssignment;
pub use confidence::ClusterConfidenceError;
pub use confidence::ClusterConfidencePlan;
pub use confidence::ClusterOpeEstimate;
pub use confidence::OpeInterval;
pub use confidence::estimate_cluster_intervals;

const SCALE: i128 = 1_i128 << 32;
const MAX_ROWS: usize = 1_000_000;
const MAX_ACTIONS: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpeAction {
    pub action_id: StableId,
    pub behavior_probability: ProbabilityQ32,
    pub evaluation_probability: ProbabilityQ32,
    pub predicted_outcome: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpeRow {
    pub decision_id: StableId,
    pub chosen_action: StableId,
    pub complete_candidates: bool,
    pub actions: Vec<OpeAction>,
    pub finalized_outcome: Option<FixedQ32>,
    pub outcome_observed_at: u64,
    pub outcome_evidence: Digest32,
    pub outcome_model_evidence: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpePlan {
    pub plan_digest: Digest32,
    pub outcome_watermark: u64,
    pub minimum_rows: usize,
    pub minimum_ess: FixedQ32,
    pub maximum_weight: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpeEstimate {
    pub rows: usize,
    pub ips: FixedQ32,
    pub snips: FixedQ32,
    pub doubly_robust: FixedQ32,
    pub effective_sample_size: FixedQ32,
    pub maximum_observed_weight: FixedQ32,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OpeError {
    InvalidPlan,
    RowLimit,
    InsufficientRows,
    DuplicateDecision,
    IncompleteCandidates,
    ActionLimit,
    DuplicateAction,
    InvalidDistribution,
    UnsupportedAction,
    UnknownChosenAction,
    PendingOutcome,
    OutcomeAfterWatermark,
    MissingEvidence,
    InvalidOutcome,
    WeightLimit,
    InsufficientSupport,
    Arithmetic,
}

impl fmt::Display for OpeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for OpeError {}

/// Compute IPS, SNIPS, DR, ESS and maximum weight without selecting a policy.
///
/// Rewards and predictions are normalized to [0, 1]. All fixed-point division
/// rounds to nearest, ties to even. Weights are not silently clipped. Pending
/// outcomes and unsupported actions are rejected rather than converted to zero.
pub fn estimate_ope(plan: &OpePlan, rows: &[OpeRow]) -> Result<OpeEstimate, OpeError> {
    if plan.plan_digest.is_zero()
        || plan.minimum_rows == 0
        || plan.minimum_rows > MAX_ROWS
        || plan.minimum_ess <= FixedQ32::ZERO
        || plan.maximum_weight <= FixedQ32::ZERO
        || i128::from(plan.maximum_weight.raw()) > 50 * SCALE
    {
        return Err(OpeError::InvalidPlan);
    }
    if rows.len() > MAX_ROWS {
        return Err(OpeError::RowLimit);
    }
    if rows.len() < plan.minimum_rows {
        return Err(OpeError::InsufficientRows);
    }
    let mut ordered: Vec<_> = rows.iter().collect();
    ordered.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    let mut prior = None;
    let mut weight_sum = 0_i128;
    let mut weight_square_sum = 0_i128;
    let mut weighted_outcome_sum = 0_i128;
    let mut dr_sum = 0_i128;
    let mut max_weight = 0_i128;
    let mut digest_bytes = b"hepta.ope.point-estimate.v1".to_vec();
    digest_bytes.extend_from_slice(plan.plan_digest.as_array());
    digest_bytes.extend_from_slice(&plan.outcome_watermark.to_be_bytes());
    digest_bytes.extend_from_slice(
        &u64::try_from(plan.minimum_rows)
            .map_err(|_| OpeError::Arithmetic)?
            .to_be_bytes(),
    );
    digest_bytes.extend_from_slice(&plan.minimum_ess.raw().to_be_bytes());
    digest_bytes.extend_from_slice(&plan.maximum_weight.raw().to_be_bytes());
    // Hash each row separately so retained receipt input is O(n), not O(n*k).
    for row in ordered {
        if prior == Some(&row.decision_id) {
            return Err(OpeError::DuplicateDecision);
        }
        prior = Some(&row.decision_id);
        let (weight, weighted_outcome, dr, row_digest) = estimate_row(plan, row)?;
        weight_sum = checked_add(weight_sum, weight)?;
        weight_square_sum = checked_add(
            weight_square_sum,
            weight.checked_mul(weight).ok_or(OpeError::Arithmetic)?,
        )?;
        weighted_outcome_sum = checked_add(weighted_outcome_sum, weighted_outcome)?;
        dr_sum = checked_add(dr_sum, dr)?;
        max_weight = max_weight.max(weight);
        digest_bytes.extend_from_slice(row_digest.as_array());
    }
    if weight_sum == 0 || weight_square_sum == 0 {
        return Err(OpeError::InsufficientSupport);
    }
    let ess = scaled_ratio(
        weight_sum
            .checked_mul(weight_sum)
            .ok_or(OpeError::Arithmetic)?,
        weight_square_sum,
    )?;
    if ess < i128::from(plan.minimum_ess.raw()) {
        return Err(OpeError::InsufficientSupport);
    }
    let count = i128::try_from(rows.len()).map_err(|_| OpeError::Arithmetic)?;
    let ips = fixed(round_ratio(weighted_outcome_sum, count)?)?;
    let snips = fixed(round_ratio(
        weighted_outcome_sum
            .checked_mul(SCALE)
            .ok_or(OpeError::Arithmetic)?,
        weight_sum,
    )?)?;
    let doubly_robust = fixed(round_ratio(dr_sum, count)?)?;
    let effective_sample_size = fixed(ess)?;
    let maximum_observed_weight = fixed(max_weight)?;
    for value in [
        ips,
        snips,
        doubly_robust,
        effective_sample_size,
        maximum_observed_weight,
    ] {
        digest_bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    Ok(OpeEstimate {
        rows: rows.len(),
        ips,
        snips,
        doubly_robust,
        effective_sample_size,
        maximum_observed_weight,
        evidence_digest: Digest32::of_bytes(&digest_bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn estimate_row(plan: &OpePlan, row: &OpeRow) -> Result<(i128, i128, i128, Digest32), OpeError> {
    if !row.complete_candidates {
        return Err(OpeError::IncompleteCandidates);
    }
    if row.actions.is_empty() || row.actions.len() > MAX_ACTIONS {
        return Err(OpeError::ActionLimit);
    }
    let outcome = row.finalized_outcome.ok_or(OpeError::PendingOutcome)?;
    if row.outcome_observed_at > plan.outcome_watermark {
        return Err(OpeError::OutcomeAfterWatermark);
    }
    if row.outcome_evidence.is_zero() || row.outcome_model_evidence.is_zero() {
        return Err(OpeError::MissingEvidence);
    }
    if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&outcome) {
        return Err(OpeError::InvalidOutcome);
    }
    let mut actions: Vec<_> = row.actions.iter().collect();
    actions.sort_by(|left, right| left.action_id.cmp(&right.action_id));
    let mut seen = BTreeSet::new();
    let mut behavior_sum = 0_i128;
    let mut evaluation_sum = 0_i128;
    let mut direct_sum = 0_i128;
    let mut chosen = None;
    let mut bytes = b"hepta.ope.row.v1".to_vec();
    push_id(&mut bytes, &row.decision_id);
    push_id(&mut bytes, &row.chosen_action);
    bytes.extend_from_slice(&outcome.raw().to_be_bytes());
    bytes.extend_from_slice(&row.outcome_observed_at.to_be_bytes());
    bytes.extend_from_slice(row.outcome_evidence.as_array());
    bytes.extend_from_slice(row.outcome_model_evidence.as_array());
    for action in actions {
        if !seen.insert(&action.action_id) {
            return Err(OpeError::DuplicateAction);
        }
        let behavior = i128::from(action.behavior_probability.raw());
        let evaluation = i128::from(action.evaluation_probability.raw());
        if evaluation > 0 && behavior == 0 {
            return Err(OpeError::UnsupportedAction);
        }
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&action.predicted_outcome) {
            return Err(OpeError::InvalidOutcome);
        }
        behavior_sum += behavior;
        evaluation_sum += evaluation;
        direct_sum += evaluation * i128::from(action.predicted_outcome.raw());
        if action.action_id == row.chosen_action {
            chosen = Some(action);
        }
        push_id(&mut bytes, &action.action_id);
        bytes.extend_from_slice(&action.behavior_probability.raw().to_be_bytes());
        bytes.extend_from_slice(&action.evaluation_probability.raw().to_be_bytes());
        bytes.extend_from_slice(&action.predicted_outcome.raw().to_be_bytes());
    }
    if (behavior_sum - SCALE).abs() > 1 || (evaluation_sum - SCALE).abs() > 1 {
        return Err(OpeError::InvalidDistribution);
    }
    let chosen = chosen.ok_or(OpeError::UnknownChosenAction)?;
    let behavior = i128::from(chosen.behavior_probability.raw());
    if behavior == 0 {
        return Err(OpeError::UnsupportedAction);
    }
    let weight = round_ratio(
        i128::from(chosen.evaluation_probability.raw()) * SCALE,
        behavior,
    )?;
    if weight > i128::from(plan.maximum_weight.raw()) {
        return Err(OpeError::WeightLimit);
    }
    let weighted_outcome = round_ratio(weight * i128::from(outcome.raw()), SCALE)?;
    let residual = i128::from(outcome.raw()) - i128::from(chosen.predicted_outcome.raw());
    let dr = checked_add(
        round_ratio(direct_sum, SCALE)?,
        round_ratio(weight * residual, SCALE)?,
    )?;
    Ok((weight, weighted_outcome, dr, Digest32::of_bytes(&bytes)))
}

fn checked_add(left: i128, right: i128) -> Result<i128, OpeError> {
    left.checked_add(right).ok_or(OpeError::Arithmetic)
}

fn fixed(raw: i128) -> Result<FixedQ32, OpeError> {
    i64::try_from(raw)
        .map(FixedQ32::from_raw)
        .map_err(|_| OpeError::Arithmetic)
}

// Compute a nonnegative rational in Q32 without overflowing a Q96 numerator.
// Keep squared weights in Q64: rounding every square to Q32 loses tiny weights
// and can turn a supported policy into a false zero-ESS rejection.
pub(super) fn scaled_ratio(numerator: i128, denominator: i128) -> Result<i128, OpeError> {
    if numerator < 0 || denominator <= 0 {
        return Err(OpeError::Arithmetic);
    }
    let mut result = (numerator / denominator)
        .checked_mul(SCALE)
        .ok_or(OpeError::Arithmetic)?;
    let mut remainder = numerator % denominator;
    let mut fraction = 0_i128;
    for _ in 0..32 {
        remainder = remainder.checked_mul(2).ok_or(OpeError::Arithmetic)?;
        fraction = fraction.checked_mul(2).ok_or(OpeError::Arithmetic)?;
        if remainder >= denominator {
            remainder -= denominator;
            fraction += 1;
        }
    }
    result = checked_add(result, fraction)?;
    let twice = remainder.checked_mul(2).ok_or(OpeError::Arithmetic)?;
    if twice > denominator || (twice == denominator && result % 2 != 0) {
        checked_add(result, 1)
    } else {
        Ok(result)
    }
}

pub(super) fn round_ratio(numerator: i128, denominator: i128) -> Result<i128, OpeError> {
    if denominator <= 0 {
        return Err(OpeError::Arithmetic);
    }
    let quotient = numerator / denominator;
    let remainder = numerator % denominator;
    let twice = remainder
        .checked_abs()
        .and_then(|value| value.checked_mul(2))
        .ok_or(OpeError::Arithmetic)?;
    if twice > denominator || (twice == denominator && quotient % 2 != 0) {
        checked_add(quotient, numerator.signum())
    } else {
        Ok(quotient)
    }
}

#[cfg(test)]
#[path = "ope_tests.rs"]
mod tests;
