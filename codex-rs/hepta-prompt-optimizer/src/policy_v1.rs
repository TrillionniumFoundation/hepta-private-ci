//! Registered V1 prompt-optimization policy surface.
//!
//! This module closes the contract-to-code gap between the V8 prompt optimizer
//! design and the native Rust implementation. It remains authority-free and
//! read-only: every receipt is a deterministic proposal over authenticated,
//! caller-supplied snapshots and grants no dispatch, activation, promotion, or
//! release capability.

use std::collections::{BTreeMap, BTreeSet};

use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

pub const MAX_V1_FACTORS: usize = 128;
pub const MAX_V1_SELECTED_FACTORS: usize = 16;
pub const MAX_V1_INTERACTION_EDGES: usize = 512;
pub const MAX_V1_HARD_CONSTRAINT_EDGES: usize = 512;
pub const MAX_V1_EXACT_FACTORS: usize = 24;
pub const MAX_V1_BEAM_STATES: usize = 4096;
pub const MAX_V1_TOKEN_BUDGET: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactorSnapshotV1 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub admitted: bool,
    pub legal: bool,
    pub registry_digest: Digest32,
    pub support_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub token_cost_upper_bound: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistrySnapshotV1 {
    pub snapshot_digest: Digest32,
    pub owner_attestation_digest: Digest32,
    pub factors: Vec<PromptFactorSnapshotV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptEnumerationRequestV1 {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub registry: PromptRegistrySnapshotV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub registry_digest: Digest32,
    pub support_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub token_cost_upper_bound: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub enumerated_count: u32,
    pub omitted_count: u32,
    pub complete: bool,
    pub candidates: Vec<PromptCandidateV1>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCausalEstimateV1 {
    pub candidate_id: StableId,
    pub incremental_utility: FixedQ32,
    pub confidence_ppm: u32,
    pub support_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCostEstimateV1 {
    pub candidate_id: StableId,
    pub token_cost: FixedQ32,
    pub latency_cost: FixedQ32,
    pub interference_cost: FixedQ32,
    pub resource_cost: FixedQ32,
    pub cost_support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingRequestV1 {
    pub candidate_set: PromptCandidateSetReceiptV1,
    pub causal_estimates: Vec<PromptCausalEstimateV1>,
    pub costs: Vec<PromptCostEstimateV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPricingDispositionV1 {
    Priced,
    MissingCausalSupport,
    MissingCostSupport,
    ScopeMismatch,
    ModelProfileMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidatePriceV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub causal_utility: FixedQ32,
    pub token_cost: FixedQ32,
    pub latency_cost: FixedQ32,
    pub interference_cost: FixedQ32,
    pub resource_cost: FixedQ32,
    pub net_utility: FixedQ32,
    pub confidence_ppm: u32,
    pub causal_support_digest: Digest32,
    pub cost_support_digest: Digest32,
    pub scope_digest: Digest32,
    pub token_cost_upper_bound: u64,
    pub disposition: PromptPricingDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub decision_id: StableId,
    pub candidate_set_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub prices: Vec<PromptCandidatePriceV1>,
    pub priced_count: u32,
    pub unavailable_count: u32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairInteractionV1 {
    pub left_candidate_id: StableId,
    pub right_candidate_id: StableId,
    pub marginal_utility: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptHardConstraintV1 {
    Conflict {
        left_candidate_id: StableId,
        right_candidate_id: StableId,
        support_digest: Digest32,
    },
    Requires {
        candidate_id: StableId,
        prerequisite_candidate_id: StableId,
        support_digest: Digest32,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnknownInteractionPolicyV1 {
    AssumeZero,
    RequireExplicit,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptSolverMethodV1 {
    ExactSubsetV1,
    BoundedBeamV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptOptimalityV1 {
    ExactCertified,
    HeuristicNoCertificate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPortfolioCandidateDispositionV1 {
    Selected,
    UnavailablePrice,
    NonPositiveNetUtility,
    ExcludedByBudget,
    ExcludedBySelectionLimit,
    ExcludedByConstraint,
    NotSelectedBySolver,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioCandidateDecisionV1 {
    pub candidate_id: StableId,
    pub disposition: PromptPortfolioCandidateDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioRequestV1 {
    pub pricing: PromptPricingReceiptV1,
    pub token_budget: u64,
    pub maximum_selected_factors: usize,
    pub interactions: Vec<PromptPairInteractionV1>,
    pub hard_constraints: Vec<PromptHardConstraintV1>,
    pub unknown_interaction_policy: UnknownInteractionPolicyV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub decision_id: StableId,
    pub pricing_digest: Digest32,
    pub selected_candidate_ids: Vec<StableId>,
    pub candidate_decisions: Vec<PromptPortfolioCandidateDecisionV1>,
    pub total_token_cost: u64,
    pub unspent_token_budget: u64,
    pub total_net_utility: FixedQ32,
    pub solver_method: PromptSolverMethodV1,
    pub optimality: PromptOptimalityV1,
    pub interaction_graph_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseRequestV1 {
    pub portfolio: PromptPortfolioReceiptV1,
    pub registered_boundary_id: StableId,
    pub registered_boundary_digest: Digest32,
    pub state_digest: Digest32,
    pub current_registry_snapshot_digest: Digest32,
    pub expected_registry_snapshot_digest: Digest32,
    pub current_model_profile_digest: Digest32,
    pub expected_model_profile_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseDispositionV1 {
    Exercise,
    NoIntervention,
    InvalidatedRegistryDrift,
    InvalidatedModelProfileDrift,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub decision_id: StableId,
    pub portfolio_digest: Digest32,
    pub registered_boundary_id: StableId,
    pub registered_boundary_digest: Digest32,
    pub state_digest: Digest32,
    pub disposition: PromptExerciseDispositionV1,
    pub selected_candidate_ids: Vec<StableId>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPolicyErrorV1 {
    EmptyDigest(&'static str),
    EmptyIdentifier(&'static str),
    CandidateLimitExceeded,
    SelectionLimitExceeded,
    InteractionEdgeLimitExceeded,
    HardConstraintLimitExceeded,
    TokenBudgetLimitExceeded,
    DuplicateCandidate(String),
    DuplicateFactor(String),
    DuplicateRealization(String),
    DuplicateCausalEstimate(String),
    DuplicateCostEstimate(String),
    DuplicateInteraction(String, String),
    DuplicateConstraint(String, String),
    RegistrySnapshotMismatch(String),
    ModelProfileMismatch(String),
    UnknownCandidate(String),
    InvalidInteractionEndpoints,
    InvalidConstraintEndpoints,
    RequiresCycle(Vec<String>),
    UnsatisfiableConstraint(String),
    MissingInteraction(String, String),
    Arithmetic,
}

#[derive(Clone)]
struct SolverState {
    selected: BTreeSet<StableId>,
    token_cost: u64,
    utility_raw: i64,
}

pub fn enumerate_factors(
    mut request: PromptEnumerationRequestV1,
) -> Result<PromptCandidateSetReceiptV1, PromptPolicyErrorV1> {
    require_digest(request.objective_digest, "objective")?;
    require_digest(request.model_profile_digest, "model profile")?;
    require_digest(request.registry.snapshot_digest, "registry snapshot")?;
    require_digest(request.registry.owner_attestation_digest, "registry owner attestation")?;
    require_id(&request.decision_id, "decision")?;

    request.registry.factors.sort_by(|left, right| {
        left.factor_id
            .cmp(&right.factor_id)
            .then_with(|| left.realization_id.cmp(&right.realization_id))
    });
    let total = request.registry.factors.len();
    let mut candidates = Vec::new();
    let mut factor_ids = BTreeSet::new();
    let mut realization_ids = BTreeSet::new();
    for factor in request.registry.factors {
        require_digest(factor.registry_digest, "factor registry")?;
        require_digest(factor.support_digest, "factor support")?;
        require_digest(factor.model_profile_digest, "factor model profile")?;
        if factor.registry_digest != request.registry.snapshot_digest {
            return Err(PromptPolicyErrorV1::RegistrySnapshotMismatch(
                factor.factor_id.to_string(),
            ));
        }
        if !factor_ids.insert(factor.factor_id.clone()) {
            return Err(PromptPolicyErrorV1::DuplicateFactor(factor.factor_id.to_string()));
        }
        if !realization_ids.insert(factor.realization_id.clone()) {
            return Err(PromptPolicyErrorV1::DuplicateRealization(
                factor.realization_id.to_string(),
            ));
        }
        if !factor.admitted || !factor.legal || factor.model_profile_digest != request.model_profile_digest {
            continue;
        }
        if candidates.len() == MAX_V1_FACTORS {
            continue;
        }
        candidates.push(PromptCandidateV1 {
            candidate_id: candidate_id(&factor.factor_id, &factor.realization_id),
            factor_id: factor.factor_id,
            realization_id: factor.realization_id,
            registry_digest: factor.registry_digest,
            support_digest: factor.support_digest,
            model_profile_digest: factor.model_profile_digest,
            token_cost_upper_bound: factor.token_cost_upper_bound,
        });
    }
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let enumerated_count = u32::try_from(candidates.len()).map_err(|_| PromptPolicyErrorV1::Arithmetic)?;
    let omitted = total.saturating_sub(candidates.len());
    let omitted_count = u32::try_from(omitted).map_err(|_| PromptPolicyErrorV1::Arithmetic)?;
    let complete = omitted == 0;
    let receipt_digest = digest_candidate_set(
        &request.decision_id,
        request.objective_digest,
        request.registry.snapshot_digest,
        request.model_profile_digest,
        enumerated_count,
        omitted_count,
        complete,
        &candidates,
    );
    Ok(PromptCandidateSetReceiptV1 {
        decision_id: request.decision_id,
        objective_digest: request.objective_digest,
        registry_snapshot_digest: request.registry.snapshot_digest,
        model_profile_digest: request.model_profile_digest,
        enumerated_count,
        omitted_count,
        complete,
        candidates,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn price_factors(
    request: PromptPricingRequestV1,
) -> Result<PromptPricingReceiptV1, PromptPolicyErrorV1> {
    require_digest(request.candidate_set.receipt_digest, "candidate set receipt")?;
    let causal = unique_causal(&request.causal_estimates)?;
    let costs = unique_costs(&request.costs)?;
    let mut prices = Vec::with_capacity(request.candidate_set.candidates.len());
    for candidate in &request.candidate_set.candidates {
        let causal_estimate = causal.get(&candidate.candidate_id);
        let cost_estimate = costs.get(&candidate.candidate_id);
        let disposition = if candidate.model_profile_digest != request.candidate_set.model_profile_digest {
            PromptPricingDispositionV1::ModelProfileMismatch
        } else if causal_estimate.is_none() {
            PromptPricingDispositionV1::MissingCausalSupport
        } else if cost_estimate.is_none() {
            PromptPricingDispositionV1::MissingCostSupport
        } else {
            PromptPricingDispositionV1::Priced
        };
        let zero_causal = PromptCausalEstimateV1 {
            candidate_id: candidate.candidate_id.clone(),
            incremental_utility: FixedQ32::ZERO,
            confidence_ppm: 0,
            support_digest: Digest32::ZERO,
            scope_digest: Digest32::ZERO,
        };
        let zero_cost = PromptCostEstimateV1 {
            candidate_id: candidate.candidate_id.clone(),
            token_cost: FixedQ32::ZERO,
            latency_cost: FixedQ32::ZERO,
            interference_cost: FixedQ32::ZERO,
            resource_cost: FixedQ32::ZERO,
            cost_support_digest: Digest32::ZERO,
        };
        let causal_estimate = causal_estimate.copied().unwrap_or(&zero_causal);
        let cost_estimate = cost_estimate.copied().unwrap_or(&zero_cost);
        if matches!(disposition, PromptPricingDispositionV1::Priced) {
            require_digest(causal_estimate.support_digest, "causal support")?;
            require_digest(causal_estimate.scope_digest, "causal scope")?;
            require_digest(cost_estimate.cost_support_digest, "cost support")?;
            if causal_estimate.confidence_ppm > 1_000_000 {
                return Err(PromptPolicyErrorV1::Arithmetic);
            }
        }
        let net_raw = checked_net_raw(causal_estimate, cost_estimate)?;
        prices.push(PromptCandidatePriceV1 {
            candidate_id: candidate.candidate_id.clone(),
            factor_id: candidate.factor_id.clone(),
            realization_id: candidate.realization_id.clone(),
            causal_utility: causal_estimate.incremental_utility,
            token_cost: cost_estimate.token_cost,
            latency_cost: cost_estimate.latency_cost,
            interference_cost: cost_estimate.interference_cost,
            resource_cost: cost_estimate.resource_cost,
            net_utility: FixedQ32::from_raw(net_raw),
            confidence_ppm: causal_estimate.confidence_ppm,
            causal_support_digest: causal_estimate.support_digest,
            cost_support_digest: cost_estimate.cost_support_digest,
            scope_digest: causal_estimate.scope_digest,
            token_cost_upper_bound: candidate.token_cost_upper_bound,
            disposition,
        });
    }
    prices.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let priced_count = u32::try_from(
        prices.iter().filter(|price| matches!(price.disposition, PromptPricingDispositionV1::Priced)).count(),
    )
    .map_err(|_| PromptPolicyErrorV1::Arithmetic)?;
    let unavailable_count = u32::try_from(prices.len()).map_err(|_| PromptPolicyErrorV1::Arithmetic)? - priced_count;
    let receipt_digest = digest_pricing(
        &request.candidate_set.decision_id,
        request.candidate_set.receipt_digest,
        request.candidate_set.model_profile_digest,
        &prices,
    );
    Ok(PromptPricingReceiptV1 {
        decision_id: request.candidate_set.decision_id,
        candidate_set_digest: request.candidate_set.receipt_digest,
        model_profile_digest: request.candidate_set.model_profile_digest,
        prices,
        priced_count,
        unavailable_count,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn select_portfolio(
    request: PromptPortfolioRequestV1,
) -> Result<PromptPortfolioReceiptV1, PromptPolicyErrorV1> {
    if request.token_budget > MAX_V1_TOKEN_BUDGET {
        return Err(PromptPolicyErrorV1::TokenBudgetLimitExceeded);
    }
    if request.maximum_selected_factors == 0 || request.maximum_selected_factors > MAX_V1_SELECTED_FACTORS {
        return Err(PromptPolicyErrorV1::SelectionLimitExceeded);
    }
    if request.interactions.len() > MAX_V1_INTERACTION_EDGES {
        return Err(PromptPolicyErrorV1::InteractionEdgeLimitExceeded);
    }
    if request.hard_constraints.len() > MAX_V1_HARD_CONSTRAINT_EDGES {
        return Err(PromptPolicyErrorV1::HardConstraintLimitExceeded);
    }
    let prices = price_map(&request.pricing.prices)?;
    let interactions = interaction_map(&request.interactions, &prices)?;
    let constraints = validate_constraints(&request.hard_constraints, &prices)?;
    let selectable: Vec<StableId> = request
        .pricing
        .prices
        .iter()
        .filter(|price| matches!(price.disposition, PromptPricingDispositionV1::Priced))
        .map(|price| price.candidate_id.clone())
        .collect();

    let (state, solver_method, optimality) = if selectable.len() <= MAX_V1_EXACT_FACTORS {
        (
            exact_solve(&selectable, &prices, &interactions, &constraints, &request)?,
            PromptSolverMethodV1::ExactSubsetV1,
            PromptOptimalityV1::ExactCertified,
        )
    } else {
        (
            beam_solve(&selectable, &prices, &interactions, &constraints, &request)?,
            PromptSolverMethodV1::BoundedBeamV1,
            PromptOptimalityV1::HeuristicNoCertificate,
        )
    };

    let mut selected_candidate_ids: Vec<_> = state.selected.iter().cloned().collect();
    selected_candidate_ids.sort();
    let candidate_decisions = decisions_for(&request, &prices, &state.selected, &constraints);
    let interaction_graph_digest = digest_interactions(&request.interactions, request.unknown_interaction_policy);
    let hard_constraint_digest = digest_constraints(&request.hard_constraints);
    let unspent_token_budget = request.token_budget.checked_sub(state.token_cost).ok_or(PromptPolicyErrorV1::Arithmetic)?;
    let receipt_digest = digest_portfolio(
        &request.pricing.decision_id,
        request.pricing.receipt_digest,
        &selected_candidate_ids,
        state.token_cost,
        unspent_token_budget,
        state.utility_raw,
        solver_method,
        optimality,
        interaction_graph_digest,
        hard_constraint_digest,
    );
    Ok(PromptPortfolioReceiptV1 {
        decision_id: request.pricing.decision_id,
        pricing_digest: request.pricing.receipt_digest,
        selected_candidate_ids,
        candidate_decisions,
        total_token_cost: state.token_cost,
        unspent_token_budget,
        total_net_utility: FixedQ32::from_raw(state.utility_raw),
        solver_method,
        optimality,
        interaction_graph_digest,
        hard_constraint_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn exercise(
    request: PromptExerciseRequestV1,
) -> Result<PromptExerciseDecisionV1, PromptPolicyErrorV1> {
    require_id(&request.registered_boundary_id, "registered boundary")?;
    require_digest(request.registered_boundary_digest, "registered boundary")?;
    require_digest(request.state_digest, "state")?;
    let disposition = if request.current_registry_snapshot_digest != request.expected_registry_snapshot_digest {
        PromptExerciseDispositionV1::InvalidatedRegistryDrift
    } else if request.current_model_profile_digest != request.expected_model_profile_digest {
        PromptExerciseDispositionV1::InvalidatedModelProfileDrift
    } else if request.portfolio.selected_candidate_ids.is_empty() {
        PromptExerciseDispositionV1::NoIntervention
    } else {
        PromptExerciseDispositionV1::Exercise
    };
    let selected_candidate_ids = if matches!(disposition, PromptExerciseDispositionV1::Exercise) {
        request.portfolio.selected_candidate_ids.clone()
    } else {
        Vec::new()
    };
    let receipt_digest = digest_exercise(
        &request.portfolio.decision_id,
        request.portfolio.receipt_digest,
        &request.registered_boundary_id,
        request.registered_boundary_digest,
        request.state_digest,
        disposition,
        &selected_candidate_ids,
    );
    Ok(PromptExerciseDecisionV1 {
        decision_id: request.portfolio.decision_id,
        portfolio_digest: request.portfolio.receipt_digest,
        registered_boundary_id: request.registered_boundary_id,
        registered_boundary_digest: request.registered_boundary_digest,
        state_digest: request.state_digest,
        disposition,
        selected_candidate_ids,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn exact_solve(
    candidates: &[StableId],
    prices: &BTreeMap<StableId, &PromptCandidatePriceV1>,
    interactions: &BTreeMap<(StableId, StableId), FixedQ32>,
    constraints: &ConstraintIndex,
    request: &PromptPortfolioRequestV1,
) -> Result<SolverState, PromptPolicyErrorV1> {
    let mut best = SolverState { selected: BTreeSet::new(), token_cost: 0, utility_raw: 0 };
    exact_walk(0, candidates, prices, interactions, constraints, request, &mut SolverState { selected: BTreeSet::new(), token_cost: 0, utility_raw: 0 }, &mut best)?;
    Ok(best)
}

fn exact_walk(
    index: usize,
    candidates: &[StableId],
    prices: &BTreeMap<StableId, &PromptCandidatePriceV1>,
    interactions: &BTreeMap<(StableId, StableId), FixedQ32>,
    constraints: &ConstraintIndex,
    request: &PromptPortfolioRequestV1,
    state: &mut SolverState,
    best: &mut SolverState,
) -> Result<(), PromptPolicyErrorV1> {
    if index == candidates.len() {
        if state.utility_raw > best.utility_raw || (state.utility_raw == best.utility_raw && better_state(state, best)) {
            *best = state.clone();
        }
        return Ok(());
    }
    exact_walk(index + 1, candidates, prices, interactions, constraints, request, state, best)?;
    let closure = prerequisite_closure(&candidates[index], constraints)?;
    if let Some(next) = add_bundle(state, &closure, prices, interactions, constraints, request)? {
        let old = state.clone();
        *state = next;
        exact_walk(index + 1, candidates, prices, interactions, constraints, request, state, best)?;
        *state = old;
    }
    Ok(())
}

fn beam_solve(
    candidates: &[StableId],
    prices: &BTreeMap<StableId, &PromptCandidatePriceV1>,
    interactions: &BTreeMap<(StableId, StableId), FixedQ32>,
    constraints: &ConstraintIndex,
    request: &PromptPortfolioRequestV1,
) -> Result<SolverState, PromptPolicyErrorV1> {
    let mut beam = vec![SolverState { selected: BTreeSet::new(), token_cost: 0, utility_raw: 0 }];
    for candidate in candidates {
        let closure = prerequisite_closure(candidate, constraints)?;
        let mut expanded = beam.clone();
        for state in &beam {
            if let Some(next) = add_bundle(state, &closure, prices, interactions, constraints, request)? {
                expanded.push(next);
            }
        }
        expanded.sort_by(|left, right| {
            right.utility_raw.cmp(&left.utility_raw)
                .then_with(|| left.token_cost.cmp(&right.token_cost))
                .then_with(|| left.selected.iter().cmp(right.selected.iter()))
        });
        expanded.dedup_by(|left, right| left.selected == right.selected);
        expanded.truncate(MAX_V1_BEAM_STATES);
        beam = expanded;
    }
    beam.into_iter().next().ok_or(PromptPolicyErrorV1::Arithmetic)
}

fn add_bundle(
    state: &SolverState,
    closure: &BTreeSet<StableId>,
    prices: &BTreeMap<StableId, &PromptCandidatePriceV1>,
    interactions: &BTreeMap<(StableId, StableId), FixedQ32>,
    constraints: &ConstraintIndex,
    request: &PromptPortfolioRequestV1,
) -> Result<Option<SolverState>, PromptPolicyErrorV1> {
    let mut selected = state.selected.clone();
    let mut token_cost = state.token_cost;
    let mut utility_raw = state.utility_raw;
    for candidate_id in closure {
        if selected.contains(candidate_id) {
            continue;
        }
        if selected.len() == request.maximum_selected_factors {
            return Ok(None);
        }
        let Some(price) = prices.get(candidate_id) else { return Ok(None); };
        if !matches!(price.disposition, PromptPricingDispositionV1::Priced) {
            return Ok(None);
        }
        if conflicts_with(candidate_id, &selected, constraints) {
            return Ok(None);
        }
        token_cost = token_cost.checked_add(price.token_cost_upper_bound).ok_or(PromptPolicyErrorV1::Arithmetic)?;
        if token_cost > request.token_budget {
            return Ok(None);
        }
        utility_raw = utility_raw.checked_add(price.net_utility.raw()).ok_or(PromptPolicyErrorV1::Arithmetic)?;
        for peer in &selected {
            let key = ordered_pair(candidate_id, peer);
            match interactions.get(&key) {
                Some(value) => utility_raw = utility_raw.checked_add(value.raw()).ok_or(PromptPolicyErrorV1::Arithmetic)?,
                None if matches!(request.unknown_interaction_policy, UnknownInteractionPolicyV1::RequireExplicit) => {
                    return Err(PromptPolicyErrorV1::MissingInteraction(key.0.to_string(), key.1.to_string()));
                }
                None => {}
            }
        }
        selected.insert(candidate_id.clone());
    }
    Ok(Some(SolverState { selected, token_cost, utility_raw }))
}

struct ConstraintIndex {
    requires: BTreeMap<StableId, BTreeSet<StableId>>,
    conflicts: BTreeSet<(StableId, StableId)>,
}

fn validate_constraints(
    constraints: &[PromptHardConstraintV1],
    prices: &BTreeMap<StableId, &PromptCandidatePriceV1>,
) -> Result<ConstraintIndex, PromptPolicyErrorV1> {
    let mut requires: BTreeMap<StableId, BTreeSet<StableId>> = BTreeMap::new();
    let mut conflicts = BTreeSet::new();
    let mut seen = BTreeSet::new();
    for constraint in constraints {
        match constraint {
            PromptHardConstraintV1::Conflict { left_candidate_id, right_candidate_id, support_digest } => {
                require_digest(*support_digest, "conflict support")?;
                if left_candidate_id == right_candidate_id || !prices.contains_key(left_candidate_id) || !prices.contains_key(right_candidate_id) {
                    return Err(PromptPolicyErrorV1::InvalidConstraintEndpoints);
                }
                let pair = ordered_pair(left_candidate_id, right_candidate_id);
                if !seen.insert((0u8, pair.0.clone(), pair.1.clone())) {
                    return Err(PromptPolicyErrorV1::DuplicateConstraint(pair.0.to_string(), pair.1.to_string()));
                }
                conflicts.insert(pair);
            }
            PromptHardConstraintV1::Requires { candidate_id, prerequisite_candidate_id, support_digest } => {
                require_digest(*support_digest, "requires support")?;
                if candidate_id == prerequisite_candidate_id || !prices.contains_key(candidate_id) || !prices.contains_key(prerequisite_candidate_id) {
                    return Err(PromptPolicyErrorV1::InvalidConstraintEndpoints);
                }
                if !seen.insert((1u8, candidate_id.clone(), prerequisite_candidate_id.clone())) {
                    return Err(PromptPolicyErrorV1::DuplicateConstraint(candidate_id.to_string(), prerequisite_candidate_id.to_string()));
                }
                requires.entry(candidate_id.clone()).or_default().insert(prerequisite_candidate_id.clone());
            }
        }
    }
    let index = ConstraintIndex { requires, conflicts };
    for candidate_id in prices.keys() {
        let closure = prerequisite_closure(candidate_id, &index)?;
        for left in &closure {
            for right in &closure {
                if left < right && index.conflicts.contains(&ordered_pair(left, right)) {
                    return Err(PromptPolicyErrorV1::UnsatisfiableConstraint(candidate_id.to_string()));
                }
            }
        }
    }
    Ok(index)
}

fn prerequisite_closure(
    candidate_id: &StableId,
    constraints: &ConstraintIndex,
) -> Result<BTreeSet<StableId>, PromptPolicyErrorV1> {
    let mut closure = BTreeSet::new();
    let mut visiting = BTreeSet::new();
    let mut path = Vec::new();
    collect_prerequisites(candidate_id, constraints, &mut closure, &mut visiting, &mut path)?;
    Ok(closure)
}

fn collect_prerequisites(
    candidate_id: &StableId,
    constraints: &ConstraintIndex,
    closure: &mut BTreeSet<StableId>,
    visiting: &mut BTreeSet<StableId>,
    path: &mut Vec<StableId>,
) -> Result<(), PromptPolicyErrorV1> {
    if closure.contains(candidate_id) {
        return Ok(());
    }
    if !visiting.insert(candidate_id.clone()) {
        let mut cycle: Vec<String> = path.iter().map(ToString::to_string).collect();
        cycle.push(candidate_id.to_string());
        return Err(PromptPolicyErrorV1::RequiresCycle(cycle));
    }
    path.push(candidate_id.clone());
    if let Some(prerequisites) = constraints.requires.get(candidate_id) {
        for prerequisite in prerequisites {
            collect_prerequisites(prerequisite, constraints, closure, visiting, path)?;
        }
    }
    path.pop();
    visiting.remove(candidate_id);
    closure.insert(candidate_id.clone());
    Ok(())
}

fn interaction_map<'a>(
    interactions: &'a [PromptPairInteractionV1],
    prices: &BTreeMap<StableId, &PromptCandidatePriceV1>,
) -> Result<BTreeMap<(StableId, StableId), FixedQ32>, PromptPolicyErrorV1> {
    let mut result = BTreeMap::new();
    for interaction in interactions {
        require_digest(interaction.support_digest, "interaction support")?;
        if interaction.left_candidate_id == interaction.right_candidate_id
            || !prices.contains_key(&interaction.left_candidate_id)
            || !prices.contains_key(&interaction.right_candidate_id)
        {
            return Err(PromptPolicyErrorV1::InvalidInteractionEndpoints);
        }
        let key = ordered_pair(&interaction.left_candidate_id, &interaction.right_candidate_id);
        if result.insert(key.clone(), interaction.marginal_utility).is_some() {
            return Err(PromptPolicyErrorV1::DuplicateInteraction(key.0.to_string(), key.1.to_string()));
        }
    }
    Ok(result)
}

fn price_map(prices: &[PromptCandidatePriceV1]) -> Result<BTreeMap<StableId, &PromptCandidatePriceV1>, PromptPolicyErrorV1> {
    let mut result = BTreeMap::new();
    for price in prices {
        if result.insert(price.candidate_id.clone(), price).is_some() {
            return Err(PromptPolicyErrorV1::DuplicateCandidate(price.candidate_id.to_string()));
        }
    }
    Ok(result)
}

fn unique_causal(estimates: &[PromptCausalEstimateV1]) -> Result<BTreeMap<StableId, &PromptCausalEstimateV1>, PromptPolicyErrorV1> {
    let mut result = BTreeMap::new();
    for estimate in estimates {
        if result.insert(estimate.candidate_id.clone(), estimate).is_some() {
            return Err(PromptPolicyErrorV1::DuplicateCausalEstimate(estimate.candidate_id.to_string()));
        }
    }
    Ok(result)
}

fn unique_costs(estimates: &[PromptCostEstimateV1]) -> Result<BTreeMap<StableId, &PromptCostEstimateV1>, PromptPolicyErrorV1> {
    let mut result = BTreeMap::new();
    for estimate in estimates {
        if result.insert(estimate.candidate_id.clone(), estimate).is_some() {
            return Err(PromptPolicyErrorV1::DuplicateCostEstimate(estimate.candidate_id.to_string()));
        }
    }
    Ok(result)
}

fn checked_net_raw(causal: &PromptCausalEstimateV1, costs: &PromptCostEstimateV1) -> Result<i64, PromptPolicyErrorV1> {
    let total_cost = costs.token_cost.raw()
        .checked_add(costs.latency_cost.raw()).ok_or(PromptPolicyErrorV1::Arithmetic)?
        .checked_add(costs.interference_cost.raw()).ok_or(PromptPolicyErrorV1::Arithmetic)?
        .checked_add(costs.resource_cost.raw()).ok_or(PromptPolicyErrorV1::Arithmetic)?;
    causal.incremental_utility.raw().checked_sub(total_cost).ok_or(PromptPolicyErrorV1::Arithmetic)
}

fn conflicts_with(candidate_id: &StableId, selected: &BTreeSet<StableId>, constraints: &ConstraintIndex) -> bool {
    selected.iter().any(|peer| constraints.conflicts.contains(&ordered_pair(candidate_id, peer)))
}

fn decisions_for(
    request: &PromptPortfolioRequestV1,
    prices: &BTreeMap<StableId, &PromptCandidatePriceV1>,
    selected: &BTreeSet<StableId>,
    constraints: &ConstraintIndex,
) -> Vec<PromptPortfolioCandidateDecisionV1> {
    let mut result = Vec::new();
    for price in &request.pricing.prices {
        let disposition = if selected.contains(&price.candidate_id) {
            PromptPortfolioCandidateDispositionV1::Selected
        } else if !matches!(price.disposition, PromptPricingDispositionV1::Priced) {
            PromptPortfolioCandidateDispositionV1::UnavailablePrice
        } else if price.net_utility <= FixedQ32::ZERO {
            PromptPortfolioCandidateDispositionV1::NonPositiveNetUtility
        } else if price.token_cost_upper_bound > request.token_budget {
            PromptPortfolioCandidateDispositionV1::ExcludedByBudget
        } else if conflicts_with(&price.candidate_id, selected, constraints) {
            PromptPortfolioCandidateDispositionV1::ExcludedByConstraint
        } else if selected.len() == request.maximum_selected_factors {
            PromptPortfolioCandidateDispositionV1::ExcludedBySelectionLimit
        } else {
            PromptPortfolioCandidateDispositionV1::NotSelectedBySolver
        };
        result.push(PromptPortfolioCandidateDecisionV1 { candidate_id: price.candidate_id.clone(), disposition });
    }
    result
}

fn better_state(left: &SolverState, right: &SolverState) -> bool {
    left.token_cost < right.token_cost
        || (left.token_cost == right.token_cost && left.selected.iter().cmp(right.selected.iter()).is_lt())
}

fn candidate_id(factor_id: &StableId, realization_id: &StableId) -> StableId {
    let raw = format!("candidate:{}:{}", factor_id, realization_id);
    StableId::new(&raw).unwrap_or_else(|_| factor_id.clone())
}

fn ordered_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left <= right { (left.clone(), right.clone()) } else { (right.clone(), left.clone()) }
}

fn require_id(value: &StableId, label: &'static str) -> Result<(), PromptPolicyErrorV1> {
    if value.as_str().is_empty() { Err(PromptPolicyErrorV1::EmptyIdentifier(label)) } else { Ok(()) }
}

fn require_digest(value: Digest32, label: &'static str) -> Result<(), PromptPolicyErrorV1> {
    if value.is_zero() { Err(PromptPolicyErrorV1::EmptyDigest(label)) } else { Ok(()) }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn digest_candidate_set(
    decision_id: &StableId,
    objective_digest: Digest32,
    registry_digest: Digest32,
    model_digest: Digest32,
    enumerated_count: u32,
    omitted_count: u32,
    complete: bool,
    candidates: &[PromptCandidateV1],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-candidate-set-receipt.v1");
    push_id(&mut bytes, decision_id);
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(registry_digest.as_array());
    bytes.extend_from_slice(model_digest.as_array());
    bytes.extend_from_slice(&enumerated_count.to_be_bytes());
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    bytes.push(u8::from(complete));
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization_id);
        bytes.extend_from_slice(candidate.support_digest.as_array());
        bytes.extend_from_slice(&candidate.token_cost_upper_bound.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_pricing(decision_id: &StableId, candidate_set_digest: Digest32, model_digest: Digest32, prices: &[PromptCandidatePriceV1]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-pricing-receipt.v1");
    push_id(&mut bytes, decision_id);
    bytes.extend_from_slice(candidate_set_digest.as_array());
    bytes.extend_from_slice(model_digest.as_array());
    for price in prices {
        push_id(&mut bytes, &price.candidate_id);
        bytes.extend_from_slice(&price.causal_utility.raw().to_be_bytes());
        bytes.extend_from_slice(&price.token_cost.raw().to_be_bytes());
        bytes.extend_from_slice(&price.latency_cost.raw().to_be_bytes());
        bytes.extend_from_slice(&price.interference_cost.raw().to_be_bytes());
        bytes.extend_from_slice(&price.resource_cost.raw().to_be_bytes());
        bytes.extend_from_slice(&price.net_utility.raw().to_be_bytes());
        bytes.extend_from_slice(&price.confidence_ppm.to_be_bytes());
        bytes.push(pricing_disposition_code(&price.disposition));
    }
    Digest32::of_bytes(&bytes)
}

fn digest_interactions(interactions: &[PromptPairInteractionV1], policy: UnknownInteractionPolicyV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-interaction-graph.v1");
    bytes.push(match policy { UnknownInteractionPolicyV1::AssumeZero => 0, UnknownInteractionPolicyV1::RequireExplicit => 1 });
    let mut sorted = interactions.to_vec();
    sorted.sort_by(|left, right| ordered_pair(&left.left_candidate_id, &left.right_candidate_id).cmp(&ordered_pair(&right.left_candidate_id, &right.right_candidate_id)));
    for edge in sorted {
        let pair = ordered_pair(&edge.left_candidate_id, &edge.right_candidate_id);
        push_id(&mut bytes, &pair.0);
        push_id(&mut bytes, &pair.1);
        bytes.extend_from_slice(&edge.marginal_utility.raw().to_be_bytes());
        bytes.extend_from_slice(edge.support_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_constraints(constraints: &[PromptHardConstraintV1]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-hard-constraints.v1");
    for constraint in constraints {
        match constraint {
            PromptHardConstraintV1::Conflict { left_candidate_id, right_candidate_id, support_digest } => {
                bytes.push(0);
                let pair = ordered_pair(left_candidate_id, right_candidate_id);
                push_id(&mut bytes, &pair.0);
                push_id(&mut bytes, &pair.1);
                bytes.extend_from_slice(support_digest.as_array());
            }
            PromptHardConstraintV1::Requires { candidate_id, prerequisite_candidate_id, support_digest } => {
                bytes.push(1);
                push_id(&mut bytes, candidate_id);
                push_id(&mut bytes, prerequisite_candidate_id);
                bytes.extend_from_slice(support_digest.as_array());
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

fn digest_portfolio(
    decision_id: &StableId,
    pricing_digest: Digest32,
    selected: &[StableId],
    token_cost: u64,
    unspent: u64,
    utility_raw: i64,
    method: PromptSolverMethodV1,
    optimality: PromptOptimalityV1,
    interaction_digest: Digest32,
    constraint_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-portfolio-receipt.v1");
    push_id(&mut bytes, decision_id);
    bytes.extend_from_slice(pricing_digest.as_array());
    for id in selected { push_id(&mut bytes, id); }
    bytes.extend_from_slice(&token_cost.to_be_bytes());
    bytes.extend_from_slice(&unspent.to_be_bytes());
    bytes.extend_from_slice(&utility_raw.to_be_bytes());
    bytes.push(match method { PromptSolverMethodV1::ExactSubsetV1 => 0, PromptSolverMethodV1::BoundedBeamV1 => 1 });
    bytes.push(match optimality { PromptOptimalityV1::ExactCertified => 0, PromptOptimalityV1::HeuristicNoCertificate => 1 });
    bytes.extend_from_slice(interaction_digest.as_array());
    bytes.extend_from_slice(constraint_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_exercise(
    decision_id: &StableId,
    portfolio_digest: Digest32,
    boundary_id: &StableId,
    boundary_digest: Digest32,
    state_digest: Digest32,
    disposition: PromptExerciseDispositionV1,
    selected: &[StableId],
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-exercise-decision.v1");
    push_id(&mut bytes, decision_id);
    bytes.extend_from_slice(portfolio_digest.as_array());
    push_id(&mut bytes, boundary_id);
    bytes.extend_from_slice(boundary_digest.as_array());
    bytes.extend_from_slice(state_digest.as_array());
    bytes.push(match disposition {
        PromptExerciseDispositionV1::Exercise => 0,
        PromptExerciseDispositionV1::NoIntervention => 1,
        PromptExerciseDispositionV1::InvalidatedRegistryDrift => 2,
        PromptExerciseDispositionV1::InvalidatedModelProfileDrift => 3,
    });
    for id in selected { push_id(&mut bytes, id); }
    Digest32::of_bytes(&bytes)
}

fn pricing_disposition_code(value: &PromptPricingDispositionV1) -> u8 {
    match value {
        PromptPricingDispositionV1::Priced => 0,
        PromptPricingDispositionV1::MissingCausalSupport => 1,
        PromptPricingDispositionV1::MissingCostSupport => 2,
        PromptPricingDispositionV1::ScopeMismatch => 3,
        PromptPricingDispositionV1::ModelProfileMismatch => 4,
    }
}

#[cfg(test)]
#[path = "policy_v1_tests.rs"]
mod tests;
