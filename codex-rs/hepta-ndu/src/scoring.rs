use std::collections::BTreeMap;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::AxisDirection;
use crate::AxisValue;
use crate::CandidateUtility;
use crate::EvaluationDisposition;
use crate::NduError;
use crate::ScalarizationProfile;
use crate::UtilityProfile;
use crate::evaluator::normalize_axis_values;
use crate::mul_q32_ties_even;

pub(crate) fn pareto_frontier(
    candidates: &[CandidateUtility],
    dimensions: &[(StableId, AxisDirection)],
    tolerances: &BTreeMap<StableId, FixedQ32>,
) -> Vec<CandidateUtility> {
    let mut frontier = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        let dominated = candidates
            .iter()
            .enumerate()
            .filter(|(other_index, _)| *other_index != index)
            .any(|(_, other)| dominates(other, candidate, dimensions, tolerances));
        if !dominated {
            frontier.push(candidate.clone());
        }
    }
    frontier
}

/// Strict partial order: no axis may deteriorate, and at least one must improve
/// by more than its tolerance. A -> B -> C preserves every weak inequality and
/// the strict improvement from A -> B, so A -> C. Finite nonempty candidate sets
/// therefore retain a maximal element, including with nonzero tolerances.
fn dominates(
    left: &CandidateUtility,
    right: &CandidateUtility,
    dimensions: &[(StableId, AxisDirection)],
    tolerances: &BTreeMap<StableId, FixedQ32>,
) -> bool {
    let mut strictly_better = false;
    for (axis, direction) in dimensions {
        let Some(left_value) = axis_value(&left.utility, axis) else {
            return false;
        };
        let Some(right_value) = axis_value(&right.utility, axis) else {
            return false;
        };
        let tolerance = tolerances
            .get(axis)
            .copied()
            .unwrap_or(FixedQ32::ZERO)
            .raw();
        let left_raw = i128::from(left_value.raw());
        let right_raw = i128::from(right_value.raw());
        let tolerance_raw = i128::from(tolerance);
        let (not_worse, better) = match direction {
            AxisDirection::Maximize => {
                (left_raw >= right_raw, left_raw > right_raw + tolerance_raw)
            }
            AxisDirection::Minimize => {
                (left_raw <= right_raw, left_raw + tolerance_raw < right_raw)
            }
        };
        if !not_worse {
            return false;
        }
        strictly_better |= better;
    }
    strictly_better
}

#[cfg(test)]
#[path = "scoring_tests.rs"]
mod tests;

fn axis_value(values: &[AxisValue], axis: &StableId) -> Option<FixedQ32> {
    values
        .binary_search_by(|value| value.axis.cmp(axis))
        .ok()
        .map(|index| values[index].value)
}

pub(crate) fn score_frontier(
    frontier: &mut [CandidateUtility],
    profile: &UtilityProfile,
    mut scalarization: ScalarizationProfile,
) -> Result<(EvaluationDisposition, Option<StableId>), NduError> {
    normalize_axis_values(&mut scalarization.weights)?;
    if scalarization.weights.len() != profile.dimensions.len() {
        return Err(NduError::IncompleteScalarization);
    }
    let weights: BTreeMap<_, _> = scalarization
        .weights
        .into_iter()
        .map(|value| (value.axis, value.value))
        .collect();
    let mut weight_sum = FixedQ32::ZERO;
    for (axis, _) in &profile.dimensions {
        let Some(weight) = weights.get(axis) else {
            return Err(NduError::IncompleteScalarization);
        };
        if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(weight) {
            return Err(NduError::InvalidWeight(axis.to_string()));
        }
        weight_sum = weight_sum
            .checked_add(*weight)
            .map_err(|_| NduError::Arithmetic)?;
    }
    if weight_sum != FixedQ32::ONE {
        return Err(NduError::IncompleteScalarization);
    }

    for candidate in frontier.iter_mut() {
        let mut score = FixedQ32::ZERO;
        for (axis, direction) in &profile.dimensions {
            let value =
                axis_value(&candidate.utility, axis).ok_or_else(|| NduError::MissingAxis {
                    candidate: candidate.candidate_id.to_string(),
                    axis: axis.to_string(),
                })?;
            let weight = weights
                .get(axis)
                .copied()
                .ok_or(NduError::IncompleteScalarization)?;
            let weighted = mul_q32_ties_even(value, weight)?;
            score = match direction {
                AxisDirection::Maximize => score.checked_add(weighted),
                AxisDirection::Minimize => score.checked_sub(weighted),
            }
            .map_err(|_| NduError::Arithmetic)?;
        }
        candidate.scalar_score = Some(score);
    }
    let maximum = frontier
        .iter()
        .filter_map(|candidate| candidate.scalar_score)
        .max()
        .ok_or(NduError::IncompleteScalarization)?;
    let mut winner = None;
    let mut winner_count = 0_usize;
    for candidate in frontier.iter() {
        if candidate.scalar_score == Some(maximum) {
            winner_count += 1;
            winner = Some(candidate.candidate_id.clone());
        }
    }
    if winner_count == 1 {
        Ok((EvaluationDisposition::ScalarizedRecommendation, winner))
    } else {
        Ok((
            EvaluationDisposition::ScalarizationTieRequiresSlowPath,
            None,
        ))
    }
}
