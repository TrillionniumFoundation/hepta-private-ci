use crate::error::NduError;
use crate::fixed::mul_q32_ties_even;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
const MAX_PORTFOLIO_CANDIDATES: usize = 128;
const MAX_FRONTIER_POINTS: usize = 128;
use crate::output_portfolio_types::*;
/// Selects a bounded output portfolio using deterministic greedy QP/MPC
/// coordinates. The quadratic covariance term is evaluated exactly in Q32;
/// the greedy step is intentional for the bounded Cell budget and is not
/// presented as a closed-form Merton solution.
pub fn select_output_portfolio_v1(
    context: &OutputPortfolioContextV1,
    budget: &OutputPortfolioBudgetV1,
    candidates: &[OutputPortfolioCandidateV1],
) -> Result<OutputPortfolioSelectionReceiptV1, NduError> {
    let original_candidates = candidates;
    let candidates = canonical_candidates(context, original_candidates)?;
    let covariance = canonical_covariance(context, original_candidates, &candidates)?;
    validate_budget(budget)?;
    let count = candidates.len();
    validate_covariance(&covariance, count)?;
    let baseline = candidates
        .iter()
        .position(|candidate| candidate.is_no_change)
        .ok_or(NduError::MissingAbstainCandidate)?;
    for index in 0..count {
        if covariance[baseline * count + index] != FixedQ32::ZERO
            || covariance[index * count + baseline] != FixedQ32::ZERO
        {
            return Err(NduError::InvalidSolverReceipt("no-change covariance"));
        }
    }
    let mut risks = Vec::with_capacity(count);
    let mut scores = Vec::with_capacity(count);
    for candidate in &candidates {
        let risk = scalar_risk(&candidate.risk, budget)?;
        let score = adjusted_score(candidate, risk, budget)?;
        risks.push(risk);
        scores.push(score);
    }
    let mut order: Vec<usize> = (0..count).filter(|index| *index != baseline).collect();
    order.sort_by(|left, right| {
        scores[*right].cmp(&scores[*left]).then_with(|| {
            candidates[*left]
                .candidate_id
                .cmp(&candidates[*right].candidate_id)
        })
    });
    let mut weights = vec![FixedQ32::ZERO; count];
    let mut remaining = FixedQ32::ONE;
    let mut selected = 0_usize;
    // One advisory allocation can only describe one output protocol. A
    // shared FeatureSnapshot does not make logits, flow velocities, audio,
    // video, and discrete unmask plans composable with one another.
    let mut selected_protocol: Option<OutputProtocolV1> = None;
    let mut selected_domain: Option<Digest32> = None;
    for index in order {
        if selected >= budget.max_selected || remaining == FixedQ32::ZERO {
            break;
        }
        if scores[index] <= FixedQ32::ZERO {
            continue;
        }
        if selected_protocol.is_some_and(|protocol| protocol != candidates[index].protocol)
            || selected_domain
                .is_some_and(|domain| domain != candidates[index].composition_domain_digest)
        {
            continue;
        }
        if candidates[index].protocol.requires_whole_candidate()
            && (remaining != FixedQ32::ONE || selected != 0)
        {
            continue;
        }
        let weight = if candidates[index].protocol.requires_whole_candidate() {
            remaining
        } else {
            min_q32(candidates[index].weight_cap, remaining)
        };
        if weight <= FixedQ32::ZERO {
            continue;
        }
        // A fractional Cell direction leaves a nonzero NoChange remainder.
        // That baseline is an emitted allocation and consumes one of the
        // caller's max_selected slots; never hide it outside the count.
        let required_slots = selected + 1 + usize::from(weight < remaining);
        if required_slots > budget.max_selected {
            continue;
        }
        weights[index] = weight;
        let candidate_resource =
            weighted_sum(&weights, &candidates, |candidate| candidate.resource_cost)?;
        let candidate_latency =
            weighted_sum(&weights, &candidates, |candidate| candidate.latency_cost)?;
        let candidate_risk = quadratic_risk(&weights, &risks, &covariance)?;
        if candidate_resource > budget.resource_budget
            || candidate_latency > budget.latency_budget
            || candidate_risk > budget.risk_budget
        {
            weights[index] = FixedQ32::ZERO;
            continue;
        }
        remaining = remaining
            .checked_sub(weight)
            .map_err(|_| NduError::Arithmetic)?;
        selected += 1;
        selected_protocol = Some(candidates[index].protocol);
        selected_domain = Some(candidates[index].composition_domain_digest);
        if candidates[index].protocol.requires_whole_candidate() {
            break;
        }
    }
    weights[baseline] = remaining;
    let total_risk = quadratic_risk(&weights, &risks, &covariance)?;
    let total_resource = weighted_sum(&weights, &candidates, |candidate| candidate.resource_cost)?;
    let total_latency = weighted_sum(&weights, &candidates, |candidate| candidate.latency_cost)?;
    let total_utility = weighted_sum(&weights, &candidates, |candidate| candidate.utility_delta)?;
    let allocations = candidates
        .iter()
        .enumerate()
        .filter(|(index, _)| weights[*index] > FixedQ32::ZERO)
        .map(|(index, candidate)| OutputPortfolioAllocationV1 {
            candidate_id: candidate.candidate_id.clone(),
            protocol: candidate.protocol,
            weight: weights[index],
            adjusted_score: scores[index],
        })
        .collect::<Vec<_>>();
    let disposition = if allocations.len() == 1
        && allocations[0].candidate_id == candidates[baseline].candidate_id
    {
        OutputPortfolioDispositionV1::NoChange
    } else {
        OutputPortfolioDispositionV1::AdvisorySelection
    };
    let frontier = efficient_frontier_from_canonical(&candidates, &risks);
    let selection_digest = digest_selection(
        context,
        budget,
        &candidates,
        &covariance,
        &allocations,
        total_risk,
        total_utility,
    );
    Ok(OutputPortfolioSelectionReceiptV1 {
        objective_digest: context.objective_digest,
        generation: context.generation,
        encoder_digest: context.encoder_digest,
        snapshot_digest: context.snapshot_digest,
        disposition,
        allocations,
        frontier,
        total_utility,
        total_risk,
        total_resource,
        total_latency,
        selection_digest,
    })
}
/// Returns nondominated single-candidate points using utility↑, risk↓ and
/// resource↓. It is useful for visualising the efficient frontier before the
/// budgeted controller commits to one advisory allocation.
pub fn output_efficient_frontier_v1(
    context: &OutputPortfolioContextV1,
    candidates: &[OutputPortfolioCandidateV1],
) -> Result<Vec<OutputPortfolioFrontierPointV1>, NduError> {
    let original_candidates = candidates;
    let canonical = canonical_candidates(context, original_candidates)?;
    let covariance = canonical_covariance(context, original_candidates, &canonical)?;
    let risks = canonical
        .iter()
        .map(|candidate| scalar_risk_unweighted(&candidate.risk))
        .collect::<Result<Vec<_>, _>>()?;
    validate_covariance(&covariance, canonical.len())?;
    Ok(efficient_frontier_from_canonical(&canonical, &risks))
}
fn canonical_candidates(
    context: &OutputPortfolioContextV1,
    candidates: &[OutputPortfolioCandidateV1],
) -> Result<Vec<OutputPortfolioCandidateV1>, NduError> {
    if context.objective_digest.is_zero()
        || context.encoder_digest.is_zero()
        || context.snapshot_digest.is_zero()
        || context.future_window_digest.is_zero()
    {
        return Err(NduError::InvalidSolverReceipt("portfolio context digest"));
    }
    if candidates.is_empty() || candidates.len() > MAX_PORTFOLIO_CANDIDATES {
        return Err(NduError::CandidateLimitExceeded);
    }
    let mut canonical = candidates.to_vec();
    canonical.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    for window in canonical.windows(2) {
        if window[0].candidate_id == window[1].candidate_id {
            return Err(NduError::InvalidSolverReceipt(
                "duplicate portfolio candidate",
            ));
        }
    }
    let mut baseline_count = 0;
    for candidate in &canonical {
        if candidate.candidate_digest.is_zero()
            || candidate.snapshot_digest != context.snapshot_digest
        {
            return Err(NduError::StateDigestMismatch);
        }
        if !candidate.is_no_change && candidate.composition_domain_digest.is_zero() {
            return Err(NduError::InvalidSolverReceipt("composition domain digest"));
        }
        if candidate.weight_cap < FixedQ32::ZERO || candidate.weight_cap > FixedQ32::ONE {
            return Err(NduError::InvalidSolverReceipt("portfolio weight cap"));
        }
        if candidate.protocol.requires_whole_candidate() && candidate.weight_cap != FixedQ32::ONE {
            return Err(NduError::InvalidSolverReceipt("whole-candidate weight cap"));
        }
        // Costs are resource consumption, not signed credits. A negative
        // candidate cost could otherwise bypass the aggregate budget and
        // artificially increase its adjusted score.
        if candidate.resource_cost < FixedQ32::ZERO || candidate.latency_cost < FixedQ32::ZERO {
            return Err(NduError::InvalidSolverReceipt("negative portfolio cost"));
        }
        // NoChange is a unique explicit baseline; an unmarked second
        // NoChange candidate must not claim positive utility or be selected.
        if candidate.protocol == OutputProtocolV1::NoChange && !candidate.is_no_change {
            return Err(NduError::InvalidSolverReceipt("unmarked no-change asset"));
        }
        validate_risk(&candidate.risk)?;
        if candidate.risk.future_window_digest != context.future_window_digest {
            return Err(NduError::InvalidSolverReceipt("future-window digest"));
        }
        if candidate.is_no_change {
            baseline_count += 1;
            if candidate.weight_cap != FixedQ32::ONE {
                return Err(NduError::InvalidSolverReceipt("no-change weight cap"));
            }
            if candidate.protocol != OutputProtocolV1::NoChange
                || candidate.utility_delta != FixedQ32::ZERO
                || candidate.resource_cost != FixedQ32::ZERO
                || candidate.latency_cost != FixedQ32::ZERO
                || !candidate.composition_domain_digest.is_zero()
                || candidate.risk != zero_risk(context.future_window_digest)
            {
                return Err(NduError::InvalidSolverReceipt("invalid no-change asset"));
            }
        }
    }
    if baseline_count != 1 {
        return Err(NduError::MissingAbstainCandidate);
    }
    Ok(canonical)
}
fn canonical_covariance(
    context: &OutputPortfolioContextV1,
    original: &[OutputPortfolioCandidateV1],
    canonical: &[OutputPortfolioCandidateV1],
) -> Result<Vec<FixedQ32>, NduError> {
    let count = canonical.len();
    let expected = count.checked_mul(count).ok_or(NduError::Arithmetic)?;
    if context.semantic_covariance.len() != expected || original.len() != count {
        return Err(NduError::DimensionMismatch);
    }
    let mut permutation = Vec::with_capacity(count);
    for candidate in canonical {
        let original_index = original
            .iter()
            .position(|source| source.candidate_id == candidate.candidate_id)
            .ok_or(NduError::StateDigestMismatch)?;
        permutation.push(original_index);
    }
    let mut covariance = vec![FixedQ32::ZERO; expected];
    for row in 0..count {
        for column in 0..count {
            covariance[row * count + column] =
                context.semantic_covariance[permutation[row] * count + permutation[column]];
        }
    }
    Ok(covariance)
}
fn validate_budget(budget: &OutputPortfolioBudgetV1) -> Result<(), NduError> {
    if budget.max_selected == 0 || budget.max_selected > MAX_PORTFOLIO_CANDIDATES {
        return Err(NduError::InvalidSolverReceipt("portfolio max selected"));
    }
    for value in [
        budget.risk_budget,
        budget.resource_budget,
        budget.latency_budget,
        budget.risk_aversion,
        budget.cvar_aversion,
        budget.failure_aversion,
        budget.inconsistency_aversion,
        budget.resource_price,
        budget.latency_price,
        budget.switch_penalty,
    ] {
        if value < FixedQ32::ZERO {
            return Err(NduError::InvalidSolverReceipt("negative portfolio budget"));
        }
    }
    Ok(())
}
fn validate_risk(risk: &SemanticRiskEstimateV1) -> Result<(), NduError> {
    if risk.future_window_digest.is_zero() {
        return Err(NduError::InvalidSolverReceipt("future-window digest"));
    }
    if risk.mean_loss < FixedQ32::ZERO
        || risk.cvar_loss < FixedQ32::ZERO
        || risk.cross_modal_inconsistency < FixedQ32::ZERO
    {
        return Err(NduError::InvalidSolverReceipt("negative semantic risk"));
    }
    Ok(())
}
fn validate_covariance(covariance: &[FixedQ32], count: usize) -> Result<(), NduError> {
    let expected = count.checked_mul(count).ok_or(NduError::Arithmetic)?;
    if covariance.len() != expected {
        return Err(NduError::DimensionMismatch);
    }
    for row in 0..count {
        let diagonal = covariance[row * count + row];
        if diagonal < FixedQ32::ZERO {
            return Err(NduError::InvalidSolverReceipt(
                "negative covariance diagonal",
            ));
        }
        let mut off_diagonal_abs = FixedQ32::ZERO;
        for column in 0..count {
            if row != column {
                let value = covariance[row * count + column];
                let magnitude = value.raw().checked_abs().ok_or(NduError::Arithmetic)?;
                off_diagonal_abs = off_diagonal_abs
                    .checked_add(FixedQ32::from_raw(magnitude))
                    .map_err(|_| NduError::Arithmetic)?;
            }
            if covariance[row * count + column] != covariance[column * count + row] {
                return Err(NduError::InvalidSolverReceipt(
                    "asymmetric semantic covariance",
                ));
            }
        }
        if diagonal < off_diagonal_abs {
            return Err(NduError::InvalidSolverReceipt(
                "indefinite semantic covariance",
            ));
        }
    }
    Ok(())
}
fn zero_risk(future_window_digest: Digest32) -> SemanticRiskEstimateV1 {
    SemanticRiskEstimateV1 {
        future_window_digest,
        mean_loss: FixedQ32::ZERO,
        cvar_loss: FixedQ32::ZERO,
        failure_probability: ProbabilityQ32::ZERO,
        cross_modal_inconsistency: FixedQ32::ZERO,
    }
}
fn scalar_risk(
    risk: &SemanticRiskEstimateV1,
    budget: &OutputPortfolioBudgetV1,
) -> Result<FixedQ32, NduError> {
    let failure = FixedQ32::from_raw(
        i64::try_from(risk.failure_probability.raw()).map_err(|_| NduError::Arithmetic)?,
    );
    let cvar = mul_q32_ties_even(risk.cvar_loss, budget.cvar_aversion)?;
    let failure = mul_q32_ties_even(failure, budget.failure_aversion)?;
    let inconsistency = mul_q32_ties_even(
        risk.cross_modal_inconsistency,
        budget.inconsistency_aversion,
    )?;
    let weighted = risk
        .mean_loss
        .checked_add(cvar)
        .map_err(|_| NduError::Arithmetic)?
        .checked_add(failure)
        .map_err(|_| NduError::Arithmetic)?
        .checked_add(inconsistency)
        .map_err(|_| NduError::Arithmetic)?;
    mul_q32_ties_even(weighted, budget.risk_aversion)
}
fn scalar_risk_unweighted(risk: &SemanticRiskEstimateV1) -> Result<FixedQ32, NduError> {
    let failure = FixedQ32::from_raw(
        i64::try_from(risk.failure_probability.raw()).map_err(|_| NduError::Arithmetic)?,
    );
    risk.mean_loss
        .checked_add(risk.cvar_loss)
        .map_err(|_| NduError::Arithmetic)?
        .checked_add(failure)
        .map_err(|_| NduError::Arithmetic)?
        .checked_add(risk.cross_modal_inconsistency)
        .map_err(|_| NduError::Arithmetic)
}
fn adjusted_score(
    candidate: &OutputPortfolioCandidateV1,
    risk: FixedQ32,
    budget: &OutputPortfolioBudgetV1,
) -> Result<FixedQ32, NduError> {
    let resource = mul_q32_ties_even(candidate.resource_cost, budget.resource_price)?;
    let latency = mul_q32_ties_even(candidate.latency_cost, budget.latency_price)?;
    candidate
        .utility_delta
        .checked_sub(risk)
        .map_err(|_| NduError::Arithmetic)?
        .checked_sub(resource)
        .map_err(|_| NduError::Arithmetic)?
        .checked_sub(latency)
        .map_err(|_| NduError::Arithmetic)?
        .checked_sub(if candidate.is_no_change {
            FixedQ32::ZERO
        } else {
            budget.switch_penalty
        })
        .map_err(|_| NduError::Arithmetic)
}
fn weighted_sum(
    weights: &[FixedQ32],
    candidates: &[OutputPortfolioCandidateV1],
    value: impl Fn(&OutputPortfolioCandidateV1) -> FixedQ32,
) -> Result<FixedQ32, NduError> {
    let mut total = FixedQ32::ZERO;
    for (weight, candidate) in weights.iter().zip(candidates) {
        total = total
            .checked_add(mul_q32_ties_even(*weight, value(candidate))?)
            .map_err(|_| NduError::Arithmetic)?;
    }
    Ok(total)
}
fn quadratic_risk(
    weights: &[FixedQ32],
    risks: &[FixedQ32],
    covariance: &[FixedQ32],
) -> Result<FixedQ32, NduError> {
    let count = weights.len();
    let mut total = FixedQ32::ZERO;
    for index in 0..count {
        total = total
            .checked_add(mul_q32_ties_even(weights[index], risks[index])?)
            .map_err(|_| NduError::Arithmetic)?;
        for other in 0..count {
            let pair = mul_q32_ties_even(weights[index], weights[other])?;
            let pair = mul_q32_ties_even(pair, covariance[index * count + other])?;
            total = total.checked_add(pair).map_err(|_| NduError::Arithmetic)?;
        }
    }
    Ok(total)
}
fn min_q32(left: FixedQ32, right: FixedQ32) -> FixedQ32 {
    if left < right { left } else { right }
}
fn efficient_frontier_from_canonical(
    candidates: &[OutputPortfolioCandidateV1],
    risks: &[FixedQ32],
) -> Vec<OutputPortfolioFrontierPointV1> {
    let mut points = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        let dominated = candidates.iter().enumerate().any(|(other_index, other)| {
            other_index != index
                && other.utility_delta >= candidate.utility_delta
                && risks[other_index] <= risks[index]
                && other.resource_cost <= candidate.resource_cost
                && (other.utility_delta > candidate.utility_delta
                    || risks[other_index] < risks[index]
                    || other.resource_cost < candidate.resource_cost)
        });
        if !dominated {
            points.push(OutputPortfolioFrontierPointV1 {
                candidate_id: candidate.candidate_id.clone(),
                utility_delta: candidate.utility_delta,
                semantic_risk: risks[index],
                resource_cost: candidate.resource_cost,
            });
        }
    }
    points.sort_by(|left, right| {
        left.semantic_risk
            .cmp(&right.semantic_risk)
            .then_with(|| right.utility_delta.cmp(&left.utility_delta))
            .then_with(|| left.candidate_id.cmp(&right.candidate_id))
    });
    points.truncate(MAX_FRONTIER_POINTS);
    points
}
fn digest_selection(
    context: &OutputPortfolioContextV1,
    budget: &OutputPortfolioBudgetV1,
    candidates: &[OutputPortfolioCandidateV1],
    covariance: &[FixedQ32],
    allocations: &[OutputPortfolioAllocationV1],
    total_risk: FixedQ32,
    total_utility: FixedQ32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(context.objective_digest.as_array());
    bytes.extend_from_slice(&context.generation.get().to_le_bytes());
    bytes.extend_from_slice(context.encoder_digest.as_array());
    bytes.extend_from_slice(context.snapshot_digest.as_array());
    bytes.extend_from_slice(context.future_window_digest.as_array());
    bytes.extend_from_slice(&budget.max_selected.to_le_bytes());
    for value in [
        budget.risk_budget,
        budget.resource_budget,
        budget.latency_budget,
        budget.risk_aversion,
        budget.cvar_aversion,
        budget.failure_aversion,
        budget.inconsistency_aversion,
        budget.resource_price,
        budget.latency_price,
        budget.switch_penalty,
    ] {
        bytes.extend_from_slice(&value.raw().to_le_bytes());
    }
    bytes.extend_from_slice(&(covariance.len() as u64).to_le_bytes());
    for value in covariance {
        bytes.extend_from_slice(&value.raw().to_le_bytes());
    }
    for candidate in candidates {
        bytes.extend_from_slice(candidate.candidate_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(candidate.candidate_digest.as_array());
        bytes.extend_from_slice(candidate.composition_domain_digest.as_array());
        bytes.push(candidate.protocol.tag());
        bytes.extend_from_slice(candidate.risk.future_window_digest.as_array());
        bytes.extend_from_slice(&candidate.utility_delta.raw().to_le_bytes());
        bytes.extend_from_slice(&candidate.risk.mean_loss.raw().to_le_bytes());
        bytes.extend_from_slice(&candidate.risk.cvar_loss.raw().to_le_bytes());
        bytes.extend_from_slice(&candidate.risk.failure_probability.raw().to_le_bytes());
        bytes.extend_from_slice(&candidate.risk.cross_modal_inconsistency.raw().to_le_bytes());
        bytes.extend_from_slice(&candidate.resource_cost.raw().to_le_bytes());
        bytes.extend_from_slice(&candidate.latency_cost.raw().to_le_bytes());
        bytes.extend_from_slice(&candidate.weight_cap.raw().to_le_bytes());
        bytes.push(u8::from(candidate.is_no_change));
    }
    for allocation in allocations {
        bytes.extend_from_slice(allocation.candidate_id.as_str().as_bytes());
        bytes.push(0);
        bytes.push(allocation.protocol.tag());
        bytes.extend_from_slice(&allocation.weight.raw().to_le_bytes());
        bytes.extend_from_slice(&allocation.adjusted_score.raw().to_le_bytes());
    }
    bytes.extend_from_slice(&total_risk.raw().to_le_bytes());
    bytes.extend_from_slice(&total_utility.raw().to_le_bytes());
    Digest32::of_bytes(&bytes)
}
#[cfg(test)]
#[path = "output_portfolio_tests.rs"]
mod tests;
