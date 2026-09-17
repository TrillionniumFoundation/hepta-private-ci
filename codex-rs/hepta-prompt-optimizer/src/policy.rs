//! Canonical V1 prompt-selection policy plus richer authority-free audit wrappers.
//!
//! Registered `Prompt*V1` receipt structs mirror `PROTOCOL_SCHEMAS.json`.
//! Extra optimizer diagnostics live in `*AuditV1` wrappers so the V1 wire
//! meaning is not widened in place.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

const MAX_FACTORS: usize = 128;
const MAX_SELECTED: usize = 16;
const MAX_RELATIONS: usize = 512;
const MAX_TOKEN_BUDGET: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredPromptFactorV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub admitted: bool,
    pub legal: bool,
    pub registry_digest: Digest32,
    pub support_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub token_cost: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnumerateFactorsRequestV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub selection_grammar_digest: Digest32,
    pub maximum_candidates: usize,
    pub factors: Vec<RegisteredPromptFactorV1>,
}

/// Canonical `PromptCandidateSetReceiptV1` field shape.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub selection_grammar_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub token_cost: u32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetAuditV1 {
    pub receipt: PromptCandidateSetReceiptV1,
    pub candidates: Vec<PromptCandidateV1>,
    pub omitted_count: u32,
    pub complete: bool,
    pub model_profile_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptConfidenceIntervalV1 {
    pub lower_q32: FixedQ32,
    pub upper_q32: FixedQ32,
    pub confidence_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCausalEstimateV1 {
    pub candidate_id: StableId,
    pub expected_utility_q32: FixedQ32,
    pub confidence_interval: PromptConfidenceIntervalV1,
    pub support_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCostComponentsV1 {
    pub candidate_id: StableId,
    pub downside_q32: FixedQ32,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub token_penalty_q32: FixedQ32,
    pub latency_penalty_q32: FixedQ32,
    pub interference_penalty_q32: FixedQ32,
    pub resource_penalty_q32: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PriceFactorsRequestV1 {
    pub candidate_set: PromptCandidateSetAuditV1,
    pub estimates: Vec<PromptCausalEstimateV1>,
    pub costs: Vec<PromptCostComponentsV1>,
}

/// Canonical `PromptPricingReceiptV1` field shape; one receipt prices one factor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub downside_q32: FixedQ32,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPriceAuditV1 {
    pub candidate: PromptCandidateV1,
    pub receipt: PromptPricingReceiptV1,
    pub net_gain_q32: FixedQ32,
    pub causal_support_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingSetAuditV1 {
    pub set_id: StableId,
    pub candidate_set_digest: Digest32,
    pub registry_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub omitted_count: u32,
    pub candidate_set_complete: bool,
    pub prices: Vec<PromptPriceAuditV1>,
    pub pricing_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairInteractionV1 {
    pub left_candidate_id: StableId,
    pub right_candidate_id: StableId,
    pub marginal_gain_q32: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptHardConstraintV1 {
    Conflict {
        left: StableId,
        right: StableId,
        support_digest: Digest32,
    },
    Requires {
        candidate: StableId,
        prerequisite: StableId,
        support_digest: Digest32,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnknownInteractionPolicyV1 {
    AssumeZero,
    RequireExplicit,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectPortfolioRequestV1 {
    pub portfolio_id: StableId,
    pub pricing: PromptPricingSetAuditV1,
    pub interactions: Vec<PromptPairInteractionV1>,
    pub hard_constraints: Vec<PromptHardConstraintV1>,
    pub unknown_interaction_policy: UnknownInteractionPolicyV1,
    pub token_budget: u64,
    pub maximum_selected: usize,
    pub valid_until_unix_ms: u64,
}

/// Canonical `PromptPortfolioReceiptV1` field shape.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub portfolio_id: StableId,
    pub candidate_set_digest: Digest32,
    pub factor_ids: Vec<StableId>,
    pub interaction_digest: Digest32,
    pub expected_utility_q32: FixedQ32,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptCandidateDispositionV1 {
    Selected,
    NonPositivePortfolioGain,
    OverBudget,
    ConstraintBlocked,
    NotSelectedByHeuristic,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateAuditV1 {
    pub candidate_id: StableId,
    pub disposition: PromptCandidateDispositionV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptOptimalityV1 {
    HeuristicBestOfGainAndDensityNoCertificate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV1 {
    pub receipt: PromptPortfolioReceiptV1,
    pub selected_candidate_ids: Vec<StableId>,
    pub candidate_audit: Vec<PromptCandidateAuditV1>,
    pub omitted_count: u32,
    pub candidate_set_complete: bool,
    pub registry_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub pricing_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub unknown_interaction_policy: UnknownInteractionPolicyV1,
    pub optimality: PromptOptimalityV1,
    pub portfolio_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PromptDecisionBoundaryV1 {
    RequestAccepted,
    ObjectiveCompiled,
    BeforePlanning,
    BeforeCandidateGeneration,
    BeforeModelOrToolDispatch,
    AfterObservation,
    AfterFailureOrUncertaintySpike,
    BeforeIrreversibleMutation,
    BeforeVerification,
    BeforeFinalResponse,
    BeforeCompactOrHandoff,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseActionV1 {
    Exercise,
    Wait,
}

/// Canonical `PromptExerciseDecisionV1` field shape.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub factor_or_portfolio_id: StableId,
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub exercise_now_value_q32: FixedQ32,
    pub wait_value_q32: FixedQ32,
    pub decision: PromptExerciseActionV1,
    pub policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExerciseRequestV1 {
    pub portfolio: PromptPortfolioAuditV1,
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub allowed_boundaries: BTreeSet<PromptDecisionBoundaryV1>,
    pub state_digest: Digest32,
    pub current_registry_digest: Digest32,
    pub current_model_profile_digest: Digest32,
    pub wait_value_q32: FixedQ32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseDispositionV1 {
    Exercise,
    WaitForHigherValue,
    RejectBoundary,
    RejectRegistryDrift,
    RejectModelProfileDrift,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseAuditV1 {
    pub receipt: PromptExerciseDecisionV1,
    pub disposition: PromptExerciseDispositionV1,
    pub state_digest: Digest32,
    pub exercise_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PolicyError {
    InvalidLimit(&'static str),
    EmptyDigest(&'static str),
    DuplicateCandidate(String),
    DuplicateEstimate(String),
    DuplicateCost(String),
    RegistryMismatch(String),
    ModelProfileMismatch(String),
    CandidateSetMismatch,
    MissingEstimate(String),
    MissingCost(String),
    InvalidConfidence(String),
    MissingSupport(String),
    UnknownRelationEndpoint(String),
    DuplicateRelation,
    RequiresCycle,
    UnsatisfiableConstraints(String),
    MissingInteraction(String, String),
    Arithmetic,
}

impl fmt::Display for PolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PolicyError {}

pub fn enumerate_factors(
    request: EnumerateFactorsRequestV1,
) -> Result<PromptCandidateSetReceiptV1, PolicyError> {
    Ok(enumerate_factors_with_audit(request)?.receipt)
}

pub fn enumerate_factors_with_audit(
    mut request: EnumerateFactorsRequestV1,
) -> Result<PromptCandidateSetAuditV1, PolicyError> {
    if request.maximum_candidates == 0 || request.maximum_candidates > MAX_FACTORS {
        return Err(PolicyError::InvalidLimit("maximum_candidates"));
    }
    for (digest, label) in [
        (request.objective_digest, "objective"),
        (request.state_digest, "state"),
        (request.registry_digest, "registry"),
        (request.model_profile_digest, "model profile"),
        (request.selection_grammar_digest, "selection grammar"),
    ] {
        require_digest(digest, label)?;
    }
    request
        .factors
        .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    let mut candidates = Vec::new();
    for factor in request.factors {
        if !seen.insert(factor.candidate_id.clone()) {
            return Err(PolicyError::DuplicateCandidate(
                factor.candidate_id.to_string(),
            ));
        }
        if factor.registry_digest != request.registry_digest {
            return Err(PolicyError::RegistryMismatch(
                factor.candidate_id.to_string(),
            ));
        }
        if factor.model_profile_digest != request.model_profile_digest {
            return Err(PolicyError::ModelProfileMismatch(
                factor.candidate_id.to_string(),
            ));
        }
        if factor.support_digest.is_zero() {
            return Err(PolicyError::MissingSupport(
                factor.candidate_id.to_string(),
            ));
        }
        if factor.admitted && factor.legal && factor.token_cost > 0 {
            candidates.push(PromptCandidateV1 {
                candidate_id: factor.candidate_id,
                factor_id: factor.factor_id,
                realization_id: factor.realization_id,
                token_cost: factor.token_cost,
                support_digest: factor.support_digest,
            });
        }
    }
    let omitted = candidates.len().saturating_sub(request.maximum_candidates);
    candidates.truncate(request.maximum_candidates);
    let omitted_count = u32::try_from(omitted).map_err(|_| PolicyError::Arithmetic)?;
    let receipt = PromptCandidateSetReceiptV1 {
        set_id: request.set_id,
        objective_digest: request.objective_digest,
        state_digest: request.state_digest,
        registry_digest: request.registry_digest,
        candidate_factor_ids: candidates
            .iter()
            .map(|candidate| candidate.factor_id.clone())
            .collect(),
        selection_grammar_digest: request.selection_grammar_digest,
    };
    let candidate_set_digest = digest_candidate_set(&receipt, &candidates, omitted_count);
    Ok(PromptCandidateSetAuditV1 {
        receipt,
        candidates,
        omitted_count,
        complete: omitted_count == 0,
        model_profile_digest: request.model_profile_digest,
        candidate_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn price_factors(
    request: PriceFactorsRequestV1,
) -> Result<Vec<PromptPricingReceiptV1>, PolicyError> {
    Ok(price_factors_with_audit(request)?
        .prices
        .into_iter()
        .map(|price| price.receipt)
        .collect())
}

pub fn price_factors_with_audit(
    request: PriceFactorsRequestV1,
) -> Result<PromptPricingSetAuditV1, PolicyError> {
    let estimates = collect_estimates(request.estimates)?;
    let costs = collect_costs(request.costs)?;
    let mut prices = Vec::with_capacity(request.candidate_set.candidates.len());
    for candidate in &request.candidate_set.candidates {
        let estimate = estimates.get(&candidate.candidate_id).ok_or_else(|| {
            PolicyError::MissingEstimate(candidate.candidate_id.to_string())
        })?;
        let cost = costs
            .get(&candidate.candidate_id)
            .ok_or_else(|| PolicyError::MissingCost(candidate.candidate_id.to_string()))?;
        if estimate.confidence_interval.confidence_ppm > 1_000_000
            || estimate.confidence_interval.lower_q32 > estimate.confidence_interval.upper_q32
        {
            return Err(PolicyError::InvalidConfidence(
                candidate.candidate_id.to_string(),
            ));
        }
        if estimate.support_digest.is_zero() || estimate.scope_digest.is_zero() {
            return Err(PolicyError::MissingSupport(
                candidate.candidate_id.to_string(),
            ));
        }
        let normalized_cost = cost
            .downside_q32
            .checked_add(cost.token_penalty_q32)
            .and_then(|value| value.checked_add(cost.latency_penalty_q32))
            .and_then(|value| value.checked_add(cost.interference_penalty_q32))
            .and_then(|value| value.checked_add(cost.resource_penalty_q32))
            .map_err(|_| PolicyError::Arithmetic)?;
        let net_gain_q32 = estimate
            .expected_utility_q32
            .checked_sub(normalized_cost)
            .map_err(|_| PolicyError::Arithmetic)?;
        let receipt = PromptPricingReceiptV1 {
            factor_id: candidate.factor_id.clone(),
            state_digest: request.candidate_set.receipt.state_digest,
            expected_utility_q32: estimate.expected_utility_q32,
            downside_q32: cost.downside_q32,
            token_cost: cost.token_cost,
            latency_cost_micros: cost.latency_cost_micros,
            interference_ppm: cost.interference_ppm,
            confidence_interval: estimate.confidence_interval.clone(),
        };
        prices.push(PromptPriceAuditV1 {
            candidate: candidate.clone(),
            receipt,
            net_gain_q32,
            causal_support_digest: estimate.support_digest,
            scope_digest: estimate.scope_digest,
        });
    }
    let pricing_digest = digest_pricing(request.candidate_set.candidate_set_digest, &prices);
    Ok(PromptPricingSetAuditV1 {
        set_id: request.candidate_set.receipt.set_id,
        candidate_set_digest: request.candidate_set.candidate_set_digest,
        registry_digest: request.candidate_set.receipt.registry_digest,
        model_profile_digest: request.candidate_set.model_profile_digest,
        omitted_count: request.candidate_set.omitted_count,
        candidate_set_complete: request.candidate_set.complete,
        prices,
        pricing_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn select_portfolio(
    request: SelectPortfolioRequestV1,
) -> Result<PromptPortfolioReceiptV1, PolicyError> {
    Ok(select_portfolio_with_audit(request)?.receipt)
}

pub fn select_portfolio_with_audit(
    request: SelectPortfolioRequestV1,
) -> Result<PromptPortfolioAuditV1, PolicyError> {
    if request.maximum_selected == 0 || request.maximum_selected > MAX_SELECTED {
        return Err(PolicyError::InvalidLimit("maximum_selected"));
    }
    if request.token_budget > MAX_TOKEN_BUDGET
        || request.interactions.len() > MAX_RELATIONS
        || request.hard_constraints.len() > MAX_RELATIONS
    {
        return Err(PolicyError::InvalidLimit("portfolio resources"));
    }
    validate_relations(&request)?;
    let gain = solve(&request, SolveOrder::Gain)?;
    let density = solve(&request, SolveOrder::Density)?;
    let chosen = if portfolio_better(&density, &gain) {
        density
    } else {
        gain
    };
    let selected_set: BTreeSet<_> = chosen.candidate_ids.iter().cloned().collect();
    let interaction_digest =
        digest_interactions(&request.interactions, request.unknown_interaction_policy);
    let hard_constraint_digest = digest_constraints(&request.hard_constraints);
    let total_token_upper_bound =
        u32::try_from(chosen.token_cost).map_err(|_| PolicyError::Arithmetic)?;
    let receipt = PromptPortfolioReceiptV1 {
        portfolio_id: request.portfolio_id,
        candidate_set_digest: request.pricing.candidate_set_digest,
        factor_ids: chosen.factor_ids,
        interaction_digest,
        expected_utility_q32: chosen.total_gain,
        total_token_upper_bound,
        valid_until_unix_ms: request.valid_until_unix_ms,
    };
    let portfolio_digest = digest_portfolio(&receipt, request.pricing.pricing_digest);
    let candidate_audit = request
        .pricing
        .prices
        .iter()
        .map(|price| PromptCandidateAuditV1 {
            candidate_id: price.candidate.candidate_id.clone(),
            disposition: disposition_for(price, &selected_set, &request),
        })
        .collect();
    Ok(PromptPortfolioAuditV1 {
        receipt,
        selected_candidate_ids: chosen.candidate_ids,
        candidate_audit,
        omitted_count: request.pricing.omitted_count,
        candidate_set_complete: request.pricing.candidate_set_complete,
        registry_digest: request.pricing.registry_digest,
        model_profile_digest: request.pricing.model_profile_digest,
        pricing_digest: request.pricing.pricing_digest,
        hard_constraint_digest,
        unknown_interaction_policy: request.unknown_interaction_policy,
        optimality: PromptOptimalityV1::HeuristicBestOfGainAndDensityNoCertificate,
        portfolio_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn exercise(request: ExerciseRequestV1) -> Result<PromptExerciseDecisionV1, PolicyError> {
    Ok(exercise_with_audit(request)?.receipt)
}

pub fn exercise_with_audit(
    request: ExerciseRequestV1,
) -> Result<PromptExerciseAuditV1, PolicyError> {
    require_digest(request.state_digest, "state")?;
    let disposition = if request.current_registry_digest != request.portfolio.registry_digest {
        PromptExerciseDispositionV1::RejectRegistryDrift
    } else if request.current_model_profile_digest != request.portfolio.model_profile_digest {
        PromptExerciseDispositionV1::RejectModelProfileDrift
    } else if !request.allowed_boundaries.contains(&request.decision_boundary) {
        PromptExerciseDispositionV1::RejectBoundary
    } else if request.portfolio.receipt.expected_utility_q32 <= request.wait_value_q32 {
        PromptExerciseDispositionV1::WaitForHigherValue
    } else {
        PromptExerciseDispositionV1::Exercise
    };
    let decision = if disposition == PromptExerciseDispositionV1::Exercise {
        PromptExerciseActionV1::Exercise
    } else {
        PromptExerciseActionV1::Wait
    };
    let policy_digest = digest_exercise_policy(
        request.portfolio.portfolio_digest,
        request.state_digest,
        request.decision_boundary,
        disposition,
    );
    let receipt = PromptExerciseDecisionV1 {
        factor_or_portfolio_id: request.portfolio.receipt.portfolio_id,
        decision_boundary: request.decision_boundary,
        exercise_now_value_q32: request.portfolio.receipt.expected_utility_q32,
        wait_value_q32: request.wait_value_q32,
        decision,
        policy_digest,
    };
    let exercise_digest = digest_exercise(&receipt, request.state_digest);
    Ok(PromptExerciseAuditV1 {
        receipt,
        disposition,
        state_digest: request.state_digest,
        exercise_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Copy)]
enum SolveOrder {
    Gain,
    Density,
}

struct SolvedPortfolio {
    candidate_ids: Vec<StableId>,
    factor_ids: Vec<StableId>,
    token_cost: u64,
    total_gain: FixedQ32,
}

fn solve(
    request: &SelectPortfolioRequestV1,
    order: SolveOrder,
) -> Result<SolvedPortfolio, PolicyError> {
    let price_by_id: BTreeMap<_, _> = request
        .pricing
        .prices
        .iter()
        .map(|price| (price.candidate.candidate_id.clone(), price))
        .collect();
    let requires = requires_map(&request.hard_constraints);
    let mut selected = BTreeSet::new();
    let mut token_cost = 0_u64;
    let mut total_gain = FixedQ32::ZERO;
    while selected.len() < request.maximum_selected {
        let mut best: Option<(Vec<StableId>, FixedQ32, u64)> = None;
        for candidate_id in price_by_id.keys() {
            if selected.contains(candidate_id) {
                continue;
            }
            let bundle = prerequisite_bundle(candidate_id, &requires, &selected);
            if bundle.is_empty() || selected.len() + bundle.len() > request.maximum_selected {
                continue;
            }
            let bundle_cost = bundle.iter().try_fold(0_u64, |sum, id| {
                sum.checked_add(u64::from(price_by_id[id].candidate.token_cost))
                    .ok_or(PolicyError::Arithmetic)
            })?;
            if token_cost
                .checked_add(bundle_cost)
                .ok_or(PolicyError::Arithmetic)?
                > request.token_budget
                || bundle_conflicts(&bundle, &selected, &request.hard_constraints)
            {
                continue;
            }
            let marginal = bundle_gain(&bundle, &selected, &price_by_id, request)?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let better = best
                .as_ref()
                .is_none_or(|(best_bundle, best_gain, best_cost)| match order {
                    SolveOrder::Gain => {
                        marginal > *best_gain
                            || (marginal == *best_gain
                                && (bundle_cost < *best_cost
                                    || (bundle_cost == *best_cost && bundle < *best_bundle)))
                    }
                    SolveOrder::Density => {
                        density_better(marginal, bundle_cost, *best_gain, *best_cost)
                            || (marginal == *best_gain
                                && bundle_cost == *best_cost
                                && bundle < *best_bundle)
                    }
                });
            if better {
                best = Some((bundle, marginal, bundle_cost));
            }
        }
        let Some((bundle, marginal, cost)) = best else {
            break;
        };
        for id in bundle {
            selected.insert(id);
        }
        token_cost = token_cost
            .checked_add(cost)
            .ok_or(PolicyError::Arithmetic)?;
        total_gain = total_gain
            .checked_add(marginal)
            .map_err(|_| PolicyError::Arithmetic)?;
    }
    let candidate_ids: Vec<_> = selected.into_iter().collect();
    let factor_ids = candidate_ids
        .iter()
        .map(|id| price_by_id[id].candidate.factor_id.clone())
        .collect();
    Ok(SolvedPortfolio {
        candidate_ids,
        factor_ids,
        token_cost,
        total_gain,
    })
}

fn validate_relations(request: &SelectPortfolioRequestV1) -> Result<(), PolicyError> {
    let ids: BTreeSet<_> = request
        .pricing
        .prices
        .iter()
        .map(|price| price.candidate.candidate_id.clone())
        .collect();
    let mut pairs = BTreeSet::new();
    for edge in &request.interactions {
        if edge.left_candidate_id >= edge.right_candidate_id
            || !ids.contains(&edge.left_candidate_id)
            || !ids.contains(&edge.right_candidate_id)
        {
            return Err(PolicyError::UnknownRelationEndpoint(
                edge.left_candidate_id.to_string(),
            ));
        }
        if edge.support_digest.is_zero() {
            return Err(PolicyError::MissingSupport(
                edge.left_candidate_id.to_string(),
            ));
        }
        if !pairs.insert((edge.left_candidate_id.clone(), edge.right_candidate_id.clone())) {
            return Err(PolicyError::DuplicateRelation);
        }
    }
    let mut hard_keys = BTreeSet::new();
    for constraint in &request.hard_constraints {
        let (kind, left, right, support) = match constraint {
            PromptHardConstraintV1::Conflict {
                left,
                right,
                support_digest,
            } => (0_u8, left, right, support_digest),
            PromptHardConstraintV1::Requires {
                candidate,
                prerequisite,
                support_digest,
            } => (1_u8, candidate, prerequisite, support_digest),
        };
        if left == right || !ids.contains(left) || !ids.contains(right) {
            return Err(PolicyError::UnknownRelationEndpoint(left.to_string()));
        }
        if support.is_zero() {
            return Err(PolicyError::MissingSupport(left.to_string()));
        }
        if !hard_keys.insert((kind, left.clone(), right.clone())) {
            return Err(PolicyError::DuplicateRelation);
        }
    }
    let requires = requires_map(&request.hard_constraints);
    for id in &ids {
        let bundle = prerequisite_bundle_checked(id, &requires)?;
        if bundle_conflicts(&bundle, &BTreeSet::new(), &request.hard_constraints) {
            return Err(PolicyError::UnsatisfiableConstraints(id.to_string()));
        }
    }
    Ok(())
}

fn collect_estimates(
    values: Vec<PromptCausalEstimateV1>,
) -> Result<BTreeMap<StableId, PromptCausalEstimateV1>, PolicyError> {
    let mut result = BTreeMap::new();
    for value in values {
        let id = value.candidate_id.clone();
        if result.insert(id.clone(), value).is_some() {
            return Err(PolicyError::DuplicateEstimate(id.to_string()));
        }
    }
    Ok(result)
}

fn collect_costs(
    values: Vec<PromptCostComponentsV1>,
) -> Result<BTreeMap<StableId, PromptCostComponentsV1>, PolicyError> {
    let mut result = BTreeMap::new();
    for value in values {
        let id = value.candidate_id.clone();
        if result.insert(id.clone(), value).is_some() {
            return Err(PolicyError::DuplicateCost(id.to_string()));
        }
    }
    Ok(result)
}

fn requires_map(
    constraints: &[PromptHardConstraintV1],
) -> BTreeMap<StableId, Vec<StableId>> {
    let mut result: BTreeMap<StableId, Vec<StableId>> = BTreeMap::new();
    for constraint in constraints {
        if let PromptHardConstraintV1::Requires {
            candidate,
            prerequisite,
            ..
        } = constraint
        {
            result
                .entry(candidate.clone())
                .or_default()
                .push(prerequisite.clone());
        }
    }
    for prerequisites in result.values_mut() {
        prerequisites.sort();
        prerequisites.dedup();
    }
    result
}

fn prerequisite_bundle_checked(
    candidate: &StableId,
    requires: &BTreeMap<StableId, Vec<StableId>>,
) -> Result<Vec<StableId>, PolicyError> {
    fn visit(
        id: &StableId,
        requires: &BTreeMap<StableId, Vec<StableId>>,
        visiting: &mut BTreeSet<StableId>,
        done: &mut BTreeSet<StableId>,
    ) -> Result<(), PolicyError> {
        if done.contains(id) {
            return Ok(());
        }
        if !visiting.insert(id.clone()) {
            return Err(PolicyError::RequiresCycle);
        }
        if let Some(prerequisites) = requires.get(id) {
            for prerequisite in prerequisites {
                visit(prerequisite, requires, visiting, done)?;
            }
        }
        visiting.remove(id);
        done.insert(id.clone());
        Ok(())
    }
    let mut done = BTreeSet::new();
    visit(candidate, requires, &mut BTreeSet::new(), &mut done)?;
    Ok(done.into_iter().collect())
}

fn prerequisite_bundle(
    candidate: &StableId,
    requires: &BTreeMap<StableId, Vec<StableId>>,
    selected: &BTreeSet<StableId>,
) -> Vec<StableId> {
    prerequisite_bundle_checked(candidate, requires)
        .unwrap_or_default()
        .into_iter()
        .filter(|id| !selected.contains(id))
        .collect()
}

fn bundle_conflicts(
    bundle: &[StableId],
    selected: &BTreeSet<StableId>,
    constraints: &[PromptHardConstraintV1],
) -> bool {
    let bundle_set: BTreeSet<_> = bundle.iter().cloned().collect();
    constraints.iter().any(|constraint| match constraint {
        PromptHardConstraintV1::Conflict { left, right, .. } => {
            (bundle_set.contains(left)
                && (bundle_set.contains(right) || selected.contains(right)))
                || (bundle_set.contains(right) && selected.contains(left))
        }
        PromptHardConstraintV1::Requires { .. } => false,
    })
}

fn bundle_gain(
    bundle: &[StableId],
    selected: &BTreeSet<StableId>,
    prices: &BTreeMap<StableId, &PromptPriceAuditV1>,
    request: &SelectPortfolioRequestV1,
) -> Result<FixedQ32, PolicyError> {
    let mut gain = FixedQ32::ZERO;
    for (index, id) in bundle.iter().enumerate() {
        gain = gain
            .checked_add(prices[id].net_gain_q32)
            .map_err(|_| PolicyError::Arithmetic)?;
        for peer in selected {
            gain = gain
                .checked_add(interaction_gain(id, peer, request)?)
                .map_err(|_| PolicyError::Arithmetic)?;
        }
        for peer in bundle.iter().take(index) {
            gain = gain
                .checked_add(interaction_gain(id, peer, request)?)
                .map_err(|_| PolicyError::Arithmetic)?;
        }
    }
    Ok(gain)
}

fn interaction_gain(
    left: &StableId,
    right: &StableId,
    request: &SelectPortfolioRequestV1,
) -> Result<FixedQ32, PolicyError> {
    let (a, b) = if left < right {
        (left, right)
    } else {
        (right, left)
    };
    if let Some(edge) = request.interactions.iter().find(|edge| {
        &edge.left_candidate_id == a && &edge.right_candidate_id == b
    }) {
        return Ok(edge.marginal_gain_q32);
    }
    match request.unknown_interaction_policy {
        UnknownInteractionPolicyV1::AssumeZero => Ok(FixedQ32::ZERO),
        UnknownInteractionPolicyV1::RequireExplicit => Err(PolicyError::MissingInteraction(
            a.to_string(),
            b.to_string(),
        )),
    }
}

fn disposition_for(
    price: &PromptPriceAuditV1,
    selected: &BTreeSet<StableId>,
    request: &SelectPortfolioRequestV1,
) -> PromptCandidateDispositionV1 {
    if selected.contains(&price.candidate.candidate_id) {
        PromptCandidateDispositionV1::Selected
    } else if price.net_gain_q32 <= FixedQ32::ZERO {
        PromptCandidateDispositionV1::NonPositivePortfolioGain
    } else if u64::from(price.candidate.token_cost) > request.token_budget {
        PromptCandidateDispositionV1::OverBudget
    } else if !candidate_can_ever_fit(&price.candidate.candidate_id, request) {
        PromptCandidateDispositionV1::ConstraintBlocked
    } else {
        PromptCandidateDispositionV1::NotSelectedByHeuristic
    }
}

fn candidate_can_ever_fit(candidate: &StableId, request: &SelectPortfolioRequestV1) -> bool {
    let requires = requires_map(&request.hard_constraints);
    prerequisite_bundle_checked(candidate, &requires).is_ok_and(|bundle| {
        !bundle_conflicts(&bundle, &BTreeSet::new(), &request.hard_constraints)
    })
}

fn density_better(
    left_gain: FixedQ32,
    left_cost: u64,
    right_gain: FixedQ32,
    right_cost: u64,
) -> bool {
    i128::from(left_gain.raw()) * i128::from(right_cost)
        > i128::from(right_gain.raw()) * i128::from(left_cost)
}

fn portfolio_better(left: &SolvedPortfolio, right: &SolvedPortfolio) -> bool {
    left.total_gain > right.total_gain
        || (left.total_gain == right.total_gain
            && (left.token_cost < right.token_cost
                || (left.token_cost == right.token_cost
                    && left.candidate_ids < right.candidate_ids)))
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), PolicyError> {
    if digest.is_zero() {
        Err(PolicyError::EmptyDigest(label))
    } else {
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn digest_candidate_set(
    receipt: &PromptCandidateSetReceiptV1,
    candidates: &[PromptCandidateV1],
    omitted: u32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-candidate-set.audit.v1".to_vec();
    push_id(&mut bytes, &receipt.set_id);
    bytes.extend_from_slice(receipt.objective_digest.as_array());
    bytes.extend_from_slice(receipt.state_digest.as_array());
    bytes.extend_from_slice(receipt.registry_digest.as_array());
    bytes.extend_from_slice(receipt.selection_grammar_digest.as_array());
    bytes.extend_from_slice(&omitted.to_be_bytes());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization_id);
        bytes.extend_from_slice(&candidate.token_cost.to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_pricing(candidate_set: Digest32, prices: &[PromptPriceAuditV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-pricing-set.audit.v1".to_vec();
    bytes.extend_from_slice(candidate_set.as_array());
    for price in prices {
        push_id(&mut bytes, &price.candidate.candidate_id);
        push_id(&mut bytes, &price.receipt.factor_id);
        bytes.extend_from_slice(&price.receipt.expected_utility_q32.raw().to_be_bytes());
        bytes.extend_from_slice(&price.receipt.downside_q32.raw().to_be_bytes());
        bytes.extend_from_slice(&price.net_gain_q32.raw().to_be_bytes());
        bytes.extend_from_slice(price.causal_support_digest.as_array());
        bytes.extend_from_slice(price.scope_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_interactions(
    edges: &[PromptPairInteractionV1],
    policy: UnknownInteractionPolicyV1,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-interactions.v1".to_vec();
    bytes.push(match policy {
        UnknownInteractionPolicyV1::AssumeZero => 0,
        UnknownInteractionPolicyV1::RequireExplicit => 1,
    });
    for edge in edges {
        push_id(&mut bytes, &edge.left_candidate_id);
        push_id(&mut bytes, &edge.right_candidate_id);
        bytes.extend_from_slice(&edge.marginal_gain_q32.raw().to_be_bytes());
        bytes.extend_from_slice(edge.support_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_constraints(constraints: &[PromptHardConstraintV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-constraints.v1".to_vec();
    for constraint in constraints {
        match constraint {
            PromptHardConstraintV1::Conflict {
                left,
                right,
                support_digest,
            } => {
                bytes.push(0);
                push_id(&mut bytes, left);
                push_id(&mut bytes, right);
                bytes.extend_from_slice(support_digest.as_array());
            }
            PromptHardConstraintV1::Requires {
                candidate,
                prerequisite,
                support_digest,
            } => {
                bytes.push(1);
                push_id(&mut bytes, candidate);
                push_id(&mut bytes, prerequisite);
                bytes.extend_from_slice(support_digest.as_array());
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_portfolio(receipt: &PromptPortfolioReceiptV1, pricing: Digest32) -> Digest32 {
    let mut bytes = b"hepta.prompt-portfolio.audit.v1".to_vec();
    push_id(&mut bytes, &receipt.portfolio_id);
    bytes.extend_from_slice(receipt.candidate_set_digest.as_array());
    bytes.extend_from_slice(pricing.as_array());
    bytes.extend_from_slice(receipt.interaction_digest.as_array());
    bytes.extend_from_slice(&receipt.expected_utility_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&receipt.total_token_upper_bound.to_be_bytes());
    bytes.extend_from_slice(&receipt.valid_until_unix_ms.to_be_bytes());
    for factor_id in &receipt.factor_ids {
        push_id(&mut bytes, factor_id);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_exercise_policy(
    portfolio: Digest32,
    state: Digest32,
    boundary: PromptDecisionBoundaryV1,
    disposition: PromptExerciseDispositionV1,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-exercise-policy.v1".to_vec();
    bytes.extend_from_slice(portfolio.as_array());
    bytes.extend_from_slice(state.as_array());
    bytes.push(boundary as u8);
    bytes.push(disposition as u8);
    Digest32::of_bytes(&bytes)
}

fn digest_exercise(receipt: &PromptExerciseDecisionV1, state: Digest32) -> Digest32 {
    let mut bytes = b"hepta.prompt-exercise.audit.v1".to_vec();
    push_id(&mut bytes, &receipt.factor_or_portfolio_id);
    bytes.push(receipt.decision_boundary as u8);
    bytes.extend_from_slice(&receipt.exercise_now_value_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&receipt.wait_value_q32.raw().to_be_bytes());
    bytes.push(receipt.decision as u8);
    bytes.extend_from_slice(receipt.policy_digest.as_array());
    bytes.extend_from_slice(state.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "policy_tests.rs"]
mod tests;
