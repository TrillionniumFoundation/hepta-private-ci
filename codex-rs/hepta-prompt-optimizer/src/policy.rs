//! Typed prompt-selection policy pipeline.
//!
//! This module closes the contract-to-code gap above the legacy `optimize`
//! primitive. It remains authority-free: callers supply authenticated registry,
//! causal-support, and compatibility facts; the module validates and binds them
//! into deterministic V1 receipts but never mints runtime authority.

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
    pub token_cost: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnumerateFactorsRequestV1 {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub maximum_candidates: usize,
    pub factors: Vec<RegisteredPromptFactorV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub token_cost: u64,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub candidates: Vec<PromptCandidateV1>,
    pub omitted_count: u32,
    pub complete: bool,
    pub candidate_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCausalEstimateV1 {
    pub candidate_id: StableId,
    pub incremental_recursive_utility: FixedQ32,
    pub confidence_ppm: u32,
    pub support_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCostComponentsV1 {
    pub candidate_id: StableId,
    pub token_cost: FixedQ32,
    pub latency_cost: FixedQ32,
    pub interference_cost: FixedQ32,
    pub resource_cost: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PriceFactorsRequestV1 {
    pub candidate_set: PromptCandidateSetReceiptV1,
    pub estimates: Vec<PromptCausalEstimateV1>,
    pub costs: Vec<PromptCostComponentsV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPriceV1 {
    pub candidate: PromptCandidateV1,
    pub causal_utility: FixedQ32,
    pub costs: PromptCostComponentsV1,
    pub net_gain: FixedQ32,
    pub confidence_ppm: u32,
    pub causal_support_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub decision_id: StableId,
    pub candidate_set_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub prices: Vec<PromptPriceV1>,
    pub pricing_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairInteractionV1 {
    pub left_candidate_id: StableId,
    pub right_candidate_id: StableId,
    pub marginal_gain: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptHardConstraintV1 {
    Conflict { left: StableId, right: StableId, support_digest: Digest32 },
    Requires { candidate: StableId, prerequisite: StableId, support_digest: Digest32 },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnknownInteractionPolicyV1 {
    AssumeZero,
    RequireExplicit,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SelectPortfolioRequestV1 {
    pub pricing: PromptPricingReceiptV1,
    pub interactions: Vec<PromptPairInteractionV1>,
    pub hard_constraints: Vec<PromptHardConstraintV1>,
    pub unknown_interaction_policy: UnknownInteractionPolicyV1,
    pub token_budget: u64,
    pub maximum_selected: usize,
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
pub struct PromptPortfolioReceiptV1 {
    pub decision_id: StableId,
    pub candidate_set_digest: Digest32,
    pub pricing_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub selected: Vec<StableId>,
    pub candidate_audit: Vec<PromptCandidateAuditV1>,
    pub omitted_count: u32,
    pub candidate_set_complete: bool,
    pub total_token_cost: u64,
    pub total_net_gain: FixedQ32,
    pub interaction_graph_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub unknown_interaction_policy: UnknownInteractionPolicyV1,
    pub optimality: PromptOptimalityV1,
    pub portfolio_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExerciseRequestV1 {
    pub portfolio: PromptPortfolioReceiptV1,
    pub registered_boundary: StableId,
    pub allowed_boundaries: BTreeSet<StableId>,
    pub state_digest: Digest32,
    pub current_registry_digest: Digest32,
    pub current_model_profile_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptExerciseDispositionV1 {
    Exercise,
    RejectBoundary,
    RejectRegistryDrift,
    RejectModelProfileDrift,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub decision_id: StableId,
    pub portfolio_digest: Digest32,
    pub registered_boundary: StableId,
    pub state_digest: Digest32,
    pub disposition: PromptExerciseDispositionV1,
    pub exercise_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PolicyError {
    InvalidLimit(&'static str),
    EmptyDigest(&'static str),
    DuplicateCandidate(String),
    RegistryMismatch(String),
    ModelProfileMismatch(String),
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
    mut request: EnumerateFactorsRequestV1,
) -> Result<PromptCandidateSetReceiptV1, PolicyError> {
    if request.maximum_candidates == 0 || request.maximum_candidates > MAX_FACTORS {
        return Err(PolicyError::InvalidLimit("maximum_candidates"));
    }
    require_digest(request.objective_digest, "objective")?;
    require_digest(request.registry_snapshot_digest, "registry snapshot")?;
    require_digest(request.model_profile_digest, "model profile")?;
    request.factors.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    let mut candidates = Vec::new();
    for factor in request.factors {
        if !seen.insert(factor.candidate_id.clone()) {
            return Err(PolicyError::DuplicateCandidate(factor.candidate_id.to_string()));
        }
        if factor.registry_digest != request.registry_snapshot_digest {
            return Err(PolicyError::RegistryMismatch(factor.candidate_id.to_string()));
        }
        if factor.model_profile_digest != request.model_profile_digest {
            return Err(PolicyError::ModelProfileMismatch(factor.candidate_id.to_string()));
        }
        if factor.support_digest.is_zero() {
            return Err(PolicyError::MissingSupport(factor.candidate_id.to_string()));
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
    let complete = omitted_count == 0;
    let candidate_set_digest = digest_candidates(
        &request.decision_id,
        request.objective_digest,
        request.registry_snapshot_digest,
        request.model_profile_digest,
        &candidates,
        omitted_count,
    );
    Ok(PromptCandidateSetReceiptV1 {
        decision_id: request.decision_id,
        objective_digest: request.objective_digest,
        registry_snapshot_digest: request.registry_snapshot_digest,
        model_profile_digest: request.model_profile_digest,
        candidates,
        omitted_count,
        complete,
        candidate_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn price_factors(request: PriceFactorsRequestV1) -> Result<PromptPricingReceiptV1, PolicyError> {
    let estimates: BTreeMap<_, _> = request.estimates.into_iter().map(|value| (value.candidate_id.clone(), value)).collect();
    let costs: BTreeMap<_, _> = request.costs.into_iter().map(|value| (value.candidate_id.clone(), value)).collect();
    let mut prices = Vec::with_capacity(request.candidate_set.candidates.len());
    for candidate in &request.candidate_set.candidates {
        let estimate = estimates.get(&candidate.candidate_id).ok_or_else(|| PolicyError::MissingEstimate(candidate.candidate_id.to_string()))?;
        let cost = costs.get(&candidate.candidate_id).ok_or_else(|| PolicyError::MissingCost(candidate.candidate_id.to_string()))?;
        if estimate.confidence_ppm > 1_000_000 {
            return Err(PolicyError::InvalidConfidence(candidate.candidate_id.to_string()));
        }
        if estimate.support_digest.is_zero() || estimate.scope_digest.is_zero() {
            return Err(PolicyError::MissingSupport(candidate.candidate_id.to_string()));
        }
        let total_cost = cost.token_cost.checked_add(cost.latency_cost).and_then(|value| value.checked_add(cost.interference_cost)).and_then(|value| value.checked_add(cost.resource_cost)).map_err(|_| PolicyError::Arithmetic)?;
        let net_gain = estimate.incremental_recursive_utility.checked_sub(total_cost).map_err(|_| PolicyError::Arithmetic)?;
        prices.push(PromptPriceV1 {
            candidate: candidate.clone(),
            causal_utility: estimate.incremental_recursive_utility,
            costs: cost.clone(),
            net_gain,
            confidence_ppm: estimate.confidence_ppm,
            causal_support_digest: estimate.support_digest,
            scope_digest: estimate.scope_digest,
        });
    }
    let pricing_digest = digest_prices(request.candidate_set.candidate_set_digest, &prices);
    Ok(PromptPricingReceiptV1 {
        decision_id: request.candidate_set.decision_id,
        candidate_set_digest: request.candidate_set.candidate_set_digest,
        registry_snapshot_digest: request.candidate_set.registry_snapshot_digest,
        model_profile_digest: request.candidate_set.model_profile_digest,
        prices,
        pricing_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn select_portfolio(request: SelectPortfolioRequestV1) -> Result<PromptPortfolioReceiptV1, PolicyError> {
    if request.maximum_selected == 0 || request.maximum_selected > MAX_SELECTED {
        return Err(PolicyError::InvalidLimit("maximum_selected"));
    }
    if request.token_budget > MAX_TOKEN_BUDGET || request.interactions.len() > MAX_RELATIONS || request.hard_constraints.len() > MAX_RELATIONS {
        return Err(PolicyError::InvalidLimit("portfolio resources"));
    }
    validate_relations(&request)?;
    let gain = solve(&request, SolveOrder::Gain)?;
    let density = solve(&request, SolveOrder::Density)?;
    let chosen = if portfolio_better(&density, &gain) { density } else { gain };
    let selected_set: BTreeSet<_> = chosen.selected.iter().cloned().collect();
    let candidate_audit = request.pricing.prices.iter().map(|price| {
        let disposition = if selected_set.contains(&price.candidate.candidate_id) {
            PromptCandidateDispositionV1::Selected
        } else if price.net_gain <= FixedQ32::ZERO {
            PromptCandidateDispositionV1::NonPositivePortfolioGain
        } else if price.candidate.token_cost > request.token_budget {
            PromptCandidateDispositionV1::OverBudget
        } else if !candidate_can_ever_fit(&price.candidate.candidate_id, &request) {
            PromptCandidateDispositionV1::ConstraintBlocked
        } else {
            PromptCandidateDispositionV1::NotSelectedByHeuristic
        };
        PromptCandidateAuditV1 { candidate_id: price.candidate.candidate_id.clone(), disposition }
    }).collect::<Vec<_>>();
    let interaction_graph_digest = digest_interactions(&request.interactions, request.unknown_interaction_policy);
    let hard_constraint_digest = digest_constraints(&request.hard_constraints);
    let portfolio_digest = digest_portfolio(
        request.pricing.pricing_digest,
        &chosen.selected,
        chosen.total_token_cost,
        chosen.total_gain,
        interaction_graph_digest,
        hard_constraint_digest,
    );
    Ok(PromptPortfolioReceiptV1 {
        decision_id: request.pricing.decision_id,
        candidate_set_digest: request.pricing.candidate_set_digest,
        pricing_digest: request.pricing.pricing_digest,
        registry_snapshot_digest: request.pricing.registry_snapshot_digest,
        model_profile_digest: request.pricing.model_profile_digest,
        selected: chosen.selected,
        candidate_audit,
        omitted_count: 0,
        candidate_set_complete: true,
        total_token_cost: chosen.total_token_cost,
        total_net_gain: chosen.total_gain,
        interaction_graph_digest,
        hard_constraint_digest,
        unknown_interaction_policy: request.unknown_interaction_policy,
        optimality: PromptOptimalityV1::HeuristicBestOfGainAndDensityNoCertificate,
        portfolio_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn exercise(request: ExerciseRequestV1) -> Result<PromptExerciseDecisionV1, PolicyError> {
    require_digest(request.state_digest, "state")?;
    let disposition = if request.current_registry_digest != request.portfolio.registry_snapshot_digest {
        PromptExerciseDispositionV1::RejectRegistryDrift
    } else if request.current_model_profile_digest != request.portfolio.model_profile_digest {
        PromptExerciseDispositionV1::RejectModelProfileDrift
    } else if !request.allowed_boundaries.contains(&request.registered_boundary) {
        PromptExerciseDispositionV1::RejectBoundary
    } else {
        PromptExerciseDispositionV1::Exercise
    };
    let exercise_digest = digest_exercise(request.portfolio.portfolio_digest, &request.registered_boundary, request.state_digest, disposition);
    Ok(PromptExerciseDecisionV1 {
        decision_id: request.portfolio.decision_id,
        portfolio_digest: request.portfolio.portfolio_digest,
        registered_boundary: request.registered_boundary,
        state_digest: request.state_digest,
        disposition,
        exercise_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Copy)]
enum SolveOrder { Gain, Density }

struct SolvedPortfolio { selected: Vec<StableId>, total_token_cost: u64, total_gain: FixedQ32 }

fn solve(request: &SelectPortfolioRequestV1, order: SolveOrder) -> Result<SolvedPortfolio, PolicyError> {
    let price_by_id: BTreeMap<_, _> = request.pricing.prices.iter().map(|price| (price.candidate.candidate_id.clone(), price)).collect();
    let requires = requires_map(&request.hard_constraints);
    let mut selected = BTreeSet::new();
    let mut token_cost = 0_u64;
    let mut total_gain = FixedQ32::ZERO;
    while selected.len() < request.maximum_selected {
        let mut best: Option<(Vec<StableId>, FixedQ32, u64)> = None;
        for candidate_id in price_by_id.keys() {
            if selected.contains(candidate_id) { continue; }
            let bundle = prerequisite_bundle(candidate_id, &requires, &selected);
            if bundle.is_empty() || selected.len() + bundle.len() > request.maximum_selected { continue; }
            let bundle_cost = bundle.iter().try_fold(0_u64, |sum, id| sum.checked_add(price_by_id[id].candidate.token_cost).ok_or(PolicyError::Arithmetic))?;
            if token_cost.checked_add(bundle_cost).ok_or(PolicyError::Arithmetic)? > request.token_budget || bundle_conflicts(&bundle, &selected, &request.hard_constraints) { continue; }
            let bundle_gain = bundle_gain(&bundle, &selected, &price_by_id, request)?;
            if bundle_gain <= FixedQ32::ZERO { continue; }
            let better = best.as_ref().is_none_or(|(best_bundle, best_gain, best_cost)| {
                match order {
                    SolveOrder::Gain => bundle_gain > *best_gain || (bundle_gain == *best_gain && (bundle_cost < *best_cost || (bundle_cost == *best_cost && bundle < *best_bundle))),
                    SolveOrder::Density => density_better(bundle_gain, bundle_cost, *best_gain, *best_cost) || (bundle_gain == *best_gain && bundle_cost == *best_cost && bundle < *best_bundle),
                }
            });
            if better { best = Some((bundle, bundle_gain, bundle_cost)); }
        }
        let Some((bundle, gain, cost)) = best else { break; };
        for id in bundle { selected.insert(id); }
        token_cost = token_cost.checked_add(cost).ok_or(PolicyError::Arithmetic)?;
        total_gain = total_gain.checked_add(gain).map_err(|_| PolicyError::Arithmetic)?;
    }
    Ok(SolvedPortfolio { selected: selected.into_iter().collect(), total_token_cost: token_cost, total_gain })
}

fn density_better(left_gain: FixedQ32, left_cost: u64, right_gain: FixedQ32, right_cost: u64) -> bool {
    i128::from(left_gain.raw()) * i128::from(right_cost) > i128::from(right_gain.raw()) * i128::from(left_cost)
}

fn portfolio_better(left: &SolvedPortfolio, right: &SolvedPortfolio) -> bool {
    left.total_gain > right.total_gain || (left.total_gain == right.total_gain && (left.total_token_cost < right.total_token_cost || (left.total_token_cost == right.total_token_cost && left.selected < right.selected)))
}

fn validate_relations(request: &SelectPortfolioRequestV1) -> Result<(), PolicyError> {
    let ids: BTreeSet<_> = request.pricing.prices.iter().map(|price| price.candidate.candidate_id.clone()).collect();
    let mut interaction_pairs = BTreeSet::new();
    for edge in &request.interactions {
        if edge.left_candidate_id >= edge.right_candidate_id || !ids.contains(&edge.left_candidate_id) || !ids.contains(&edge.right_candidate_id) {
            return Err(PolicyError::UnknownRelationEndpoint(edge.left_candidate_id.to_string()));
        }
        if edge.support_digest.is_zero() || !interaction_pairs.insert((edge.left_candidate_id.clone(), edge.right_candidate_id.clone())) {
            return Err(PolicyError::DuplicateRelation);
        }
    }
    let requires = requires_map(&request.hard_constraints);
    for constraint in &request.hard_constraints {
        let (left, right, support) = match constraint {
            PromptHardConstraintV1::Conflict { left, right, support_digest } => (left, right, support_digest),
            PromptHardConstraintV1::Requires { candidate, prerequisite, support_digest } => (candidate, prerequisite, support_digest),
        };
        if left == right || !ids.contains(left) || !ids.contains(right) { return Err(PolicyError::UnknownRelationEndpoint(left.to_string())); }
        if support.is_zero() { return Err(PolicyError::MissingSupport(left.to_string())); }
    }
    for id in &ids {
        let bundle = prerequisite_bundle_checked(id, &requires)?;
        if bundle_conflicts(&bundle, &BTreeSet::new(), &request.hard_constraints) {
            return Err(PolicyError::UnsatisfiableConstraints(id.to_string()));
        }
    }
    Ok(())
}

fn requires_map(constraints: &[PromptHardConstraintV1]) -> BTreeMap<StableId, Vec<StableId>> {
    let mut result: BTreeMap<StableId, Vec<StableId>> = BTreeMap::new();
    for constraint in constraints {
        if let PromptHardConstraintV1::Requires { candidate, prerequisite, .. } = constraint {
            result.entry(candidate.clone()).or_default().push(prerequisite.clone());
        }
    }
    for values in result.values_mut() { values.sort(); values.dedup(); }
    result
}

fn prerequisite_bundle_checked(candidate: &StableId, requires: &BTreeMap<StableId, Vec<StableId>>) -> Result<Vec<StableId>, PolicyError> {
    fn visit(id: &StableId, requires: &BTreeMap<StableId, Vec<StableId>>, visiting: &mut BTreeSet<StableId>, done: &mut BTreeSet<StableId>) -> Result<(), PolicyError> {
        if done.contains(id) { return Ok(()); }
        if !visiting.insert(id.clone()) { return Err(PolicyError::RequiresCycle); }
        if let Some(prerequisites) = requires.get(id) {
            for prerequisite in prerequisites { visit(prerequisite, requires, visiting, done)?; }
        }
        visiting.remove(id); done.insert(id.clone()); Ok(())
    }
    let mut done = BTreeSet::new();
    visit(candidate, requires, &mut BTreeSet::new(), &mut done)?;
    Ok(done.into_iter().collect())
}

fn prerequisite_bundle(candidate: &StableId, requires: &BTreeMap<StableId, Vec<StableId>>, selected: &BTreeSet<StableId>) -> Vec<StableId> {
    prerequisite_bundle_checked(candidate, requires).unwrap_or_default().into_iter().filter(|id| !selected.contains(id)).collect()
}

fn bundle_conflicts(bundle: &[StableId], selected: &BTreeSet<StableId>, constraints: &[PromptHardConstraintV1]) -> bool {
    let bundle_set: BTreeSet<_> = bundle.iter().cloned().collect();
    constraints.iter().any(|constraint| match constraint {
        PromptHardConstraintV1::Conflict { left, right, .. } => (bundle_set.contains(left) && (bundle_set.contains(right) || selected.contains(right))) || (bundle_set.contains(right) && selected.contains(left)),
        PromptHardConstraintV1::Requires { .. } => false,
    })
}

fn candidate_can_ever_fit(candidate: &StableId, request: &SelectPortfolioRequestV1) -> bool {
    let requires = requires_map(&request.hard_constraints);
    prerequisite_bundle_checked(candidate, &requires).is_ok_and(|bundle| !bundle_conflicts(&bundle, &BTreeSet::new(), &request.hard_constraints))
}

fn bundle_gain(bundle: &[StableId], selected: &BTreeSet<StableId>, prices: &BTreeMap<StableId, &PromptPriceV1>, request: &SelectPortfolioRequestV1) -> Result<FixedQ32, PolicyError> {
    let mut gain = FixedQ32::ZERO;
    for (index, id) in bundle.iter().enumerate() {
        gain = gain.checked_add(prices[id].net_gain).map_err(|_| PolicyError::Arithmetic)?;
        for peer in selected { gain = gain.checked_add(interaction_gain(id, peer, request)?).map_err(|_| PolicyError::Arithmetic)?; }
        for peer in bundle.iter().take(index) { gain = gain.checked_add(interaction_gain(id, peer, request)?).map_err(|_| PolicyError::Arithmetic)?; }
    }
    Ok(gain)
}

fn interaction_gain(left: &StableId, right: &StableId, request: &SelectPortfolioRequestV1) -> Result<FixedQ32, PolicyError> {
    let (a, b) = if left < right { (left, right) } else { (right, left) };
    if let Some(edge) = request.interactions.iter().find(|edge| &edge.left_candidate_id == a && &edge.right_candidate_id == b) { return Ok(edge.marginal_gain); }
    match request.unknown_interaction_policy {
        UnknownInteractionPolicyV1::AssumeZero => Ok(FixedQ32::ZERO),
        UnknownInteractionPolicyV1::RequireExplicit => Err(PolicyError::MissingInteraction(a.to_string(), b.to_string())),
    }
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), PolicyError> { if digest.is_zero() { Err(PolicyError::EmptyDigest(label)) } else { Ok(()) } }
fn push_id(bytes: &mut Vec<u8>, id: &StableId) { let raw = id.as_str().as_bytes(); bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes()); bytes.extend_from_slice(raw); }
fn digest_candidates(decision: &StableId, objective: Digest32, registry: Digest32, model: Digest32, candidates: &[PromptCandidateV1], omitted: u32) -> Digest32 { let mut bytes = b"hepta.prompt-candidate-set.v1".to_vec(); push_id(&mut bytes, decision); bytes.extend_from_slice(objective.as_array()); bytes.extend_from_slice(registry.as_array()); bytes.extend_from_slice(model.as_array()); bytes.extend_from_slice(&omitted.to_be_bytes()); for candidate in candidates { push_id(&mut bytes, &candidate.candidate_id); push_id(&mut bytes, &candidate.factor_id); push_id(&mut bytes, &candidate.realization_id); bytes.extend_from_slice(&candidate.token_cost.to_be_bytes()); bytes.extend_from_slice(candidate.support_digest.as_array()); } Digest32::of_bytes(&bytes) }
fn digest_prices(candidate_set: Digest32, prices: &[PromptPriceV1]) -> Digest32 { let mut bytes = b"hepta.prompt-pricing.v1".to_vec(); bytes.extend_from_slice(candidate_set.as_array()); for price in prices { push_id(&mut bytes, &price.candidate.candidate_id); bytes.extend_from_slice(&price.causal_utility.raw().to_be_bytes()); bytes.extend_from_slice(&price.net_gain.raw().to_be_bytes()); bytes.extend_from_slice(&price.confidence_ppm.to_be_bytes()); bytes.extend_from_slice(price.causal_support_digest.as_array()); bytes.extend_from_slice(price.scope_digest.as_array()); } Digest32::of_bytes(&bytes) }
fn digest_interactions(edges: &[PromptPairInteractionV1], policy: UnknownInteractionPolicyV1) -> Digest32 { let mut bytes = b"hepta.prompt-interactions.v1".to_vec(); bytes.push(match policy { UnknownInteractionPolicyV1::AssumeZero => 0, UnknownInteractionPolicyV1::RequireExplicit => 1 }); for edge in edges { push_id(&mut bytes, &edge.left_candidate_id); push_id(&mut bytes, &edge.right_candidate_id); bytes.extend_from_slice(&edge.marginal_gain.raw().to_be_bytes()); bytes.extend_from_slice(edge.support_digest.as_array()); } Digest32::of_bytes(&bytes) }
fn digest_constraints(constraints: &[PromptHardConstraintV1]) -> Digest32 { let mut bytes = b"hepta.prompt-constraints.v1".to_vec(); for constraint in constraints { match constraint { PromptHardConstraintV1::Conflict { left, right, support_digest } => { bytes.push(0); push_id(&mut bytes, left); push_id(&mut bytes, right); bytes.extend_from_slice(support_digest.as_array()); }, PromptHardConstraintV1::Requires { candidate, prerequisite, support_digest } => { bytes.push(1); push_id(&mut bytes, candidate); push_id(&mut bytes, prerequisite); bytes.extend_from_slice(support_digest.as_array()); } } } Digest32::of_bytes(&bytes) }
fn digest_portfolio(pricing: Digest32, selected: &[StableId], cost: u64, gain: FixedQ32, interactions: Digest32, constraints: Digest32) -> Digest32 { let mut bytes = b"hepta.prompt-portfolio.v1".to_vec(); bytes.extend_from_slice(pricing.as_array()); for id in selected { push_id(&mut bytes, id); } bytes.extend_from_slice(&cost.to_be_bytes()); bytes.extend_from_slice(&gain.raw().to_be_bytes()); bytes.extend_from_slice(interactions.as_array()); bytes.extend_from_slice(constraints.as_array()); Digest32::of_bytes(&bytes) }
fn digest_exercise(portfolio: Digest32, boundary: &StableId, state: Digest32, disposition: PromptExerciseDispositionV1) -> Digest32 { let mut bytes = b"hepta.prompt-exercise.v1".to_vec(); bytes.extend_from_slice(portfolio.as_array()); push_id(&mut bytes, boundary); bytes.extend_from_slice(state.as_array()); bytes.push(match disposition { PromptExerciseDispositionV1::Exercise => 0, PromptExerciseDispositionV1::RejectBoundary => 1, PromptExerciseDispositionV1::RejectRegistryDrift => 2, PromptExerciseDispositionV1::RejectModelProfileDrift => 3 }); Digest32::of_bytes(&bytes) }

#[cfg(test)]
#[path = "policy_tests.rs"]
mod tests;
