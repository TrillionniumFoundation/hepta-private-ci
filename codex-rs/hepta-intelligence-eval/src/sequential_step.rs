//! Validation and deterministic arithmetic for one complete history boundary.

use super::SCALE;
use super::SequentialError;
use super::SequentialEvidenceGap;
use super::SequentialPlan;
use super::TrajectoryStep;
use crate::ope::round_ratio;
use crate::push_id;
use codex_hepta_types::FixedQ32;
use std::collections::BTreeSet;

pub(super) fn validate_step(
    plan: &SequentialPlan,
    step: &TrajectoryStep,
    bytes: &mut Vec<u8>,
) -> Result<(i128, i128, i128, i128), SequentialError> {
    if !step.complete_actions {
        return insufficient(SequentialEvidenceGap::IncompleteActions);
    }
    if step.actions.is_empty() || step.actions.len() > 128 {
        return Err(SequentialError::ResourceLimit);
    }
    let reward = step.reward.ok_or(SequentialError::InsufficientEvidence(
        SequentialEvidenceGap::PendingOutcome,
    ))?;
    if i128::from(reward.raw()).abs() > SCALE {
        return Err(SequentialError::InvalidValue);
    }
    if step.observed_at > plan.outcome_watermark {
        return insufficient(SequentialEvidenceGap::OutcomeAfterWatermark);
    }
    if step.outcome_evidence.is_zero() || step.prediction_evidence.is_zero() {
        return insufficient(SequentialEvidenceGap::MissingEvidence);
    }
    push_id(bytes, &step.decision_id);
    push_id(bytes, &step.chosen_action);
    bytes.extend_from_slice(step.history_digest.as_array());
    bytes.extend_from_slice(step.next_history_digest.as_array());
    bytes.extend_from_slice(step.outcome_evidence.as_array());
    bytes.extend_from_slice(step.prediction_evidence.as_array());
    bytes.extend_from_slice(&step.observed_at.to_be_bytes());
    bytes.extend_from_slice(&reward.raw().to_be_bytes());
    bytes.extend_from_slice(&step.discount.raw().to_be_bytes());
    bytes.extend_from_slice(&(step.actions.len() as u16).to_be_bytes());
    let mut actions: Vec<_> = step.actions.iter().collect();
    actions.sort_by(|a, b| a.action_id.cmp(&b.action_id));
    let mut seen = BTreeSet::new();
    let (mut behavior_sum, mut evaluation_sum, mut direct_sum) = (0_i128, 0_i128, 0_i128);
    let mut chosen = None;
    for action in actions {
        if !seen.insert(&action.action_id) {
            return Err(SequentialError::DuplicateIdentity);
        }
        let (behavior, evaluation, q) = (
            i128::from(action.behavior_probability.raw()),
            i128::from(action.evaluation_probability.raw()),
            i128::from(action.predicted_return.raw()),
        );
        if evaluation > 0 && behavior == 0 {
            return insufficient(SequentialEvidenceGap::UnsupportedAction);
        }
        if behavior > 0 && evaluation * SCALE > behavior * i128::from(plan.maximum_step_ratio.raw())
        {
            return insufficient(SequentialEvidenceGap::WeightLimit);
        }
        if q.abs() > 129 * SCALE {
            return Err(SequentialError::InvalidValue);
        }
        behavior_sum += behavior;
        evaluation_sum += evaluation;
        direct_sum += evaluation * q;
        if action.action_id == step.chosen_action {
            chosen = Some((behavior, evaluation, q));
        }
        push_id(bytes, &action.action_id);
        bytes.extend_from_slice(&action.behavior_probability.raw().to_be_bytes());
        bytes.extend_from_slice(&action.evaluation_probability.raw().to_be_bytes());
        bytes.extend_from_slice(&action.predicted_return.raw().to_be_bytes());
    }
    if behavior_sum != SCALE || evaluation_sum != SCALE {
        return Err(SequentialError::InvalidDistribution);
    }
    let (behavior, evaluation, q) = chosen.ok_or(SequentialError::InsufficientEvidence(
        SequentialEvidenceGap::UnsupportedAction,
    ))?;
    if behavior == 0 {
        return insufficient(SequentialEvidenceGap::UnsupportedAction);
    }
    let rho = divide(evaluation * SCALE, behavior)?;
    if rho == 0 && evaluation != 0 {
        return insufficient(SequentialEvidenceGap::NumericResolution);
    }
    Ok((rho, q, divide(direct_sum, SCALE)?, i128::from(reward.raw())))
}

pub(super) fn divide(numerator: i128, denominator: i128) -> Result<i128, SequentialError> {
    round_ratio(numerator, denominator).map_err(|_| SequentialError::Arithmetic)
}
pub(super) fn multiply(left: i128, right: i128) -> Result<i128, SequentialError> {
    divide(
        left.checked_mul(right).ok_or(SequentialError::Arithmetic)?,
        SCALE,
    )
}
pub(super) fn multiply_nonzero(left: i128, right: i128) -> Result<i128, SequentialError> {
    let result = multiply(left, right)?;
    if left > 0 && right > 0 && result == 0 {
        return insufficient(SequentialEvidenceGap::NumericResolution);
    }
    Ok(result)
}
pub(super) fn fixed(raw: i128) -> Result<FixedQ32, SequentialError> {
    i64::try_from(raw)
        .map(FixedQ32::from_raw)
        .map_err(|_| SequentialError::Arithmetic)
}
pub(super) fn insufficient<T>(gap: SequentialEvidenceGap) -> Result<T, SequentialError> {
    Err(SequentialError::InsufficientEvidence(gap))
}
