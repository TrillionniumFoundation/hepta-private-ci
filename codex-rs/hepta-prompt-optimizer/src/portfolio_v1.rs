//! Constraint-aware canonical prompt portfolio selection.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::canonical_v1::CanonicalPromptErrorV1;
use crate::canonical_v1::PromptCandidateBindingV1;
use crate::canonical_v1::PromptCandidateSetReceiptV1;
use crate::canonical_v1::push_id;
use crate::canonical_v1::push_len;
use crate::canonical_v1::require_digest;
use crate::pricing_v1::PromptPriceAvailabilityV1;
use crate::pricing_v1::PromptPriceV1;
use crate::pricing_v1::PromptPricingReceiptV1;
use crate::relations_v1::PromptRelationErrorV1;
use crate::relations_v1::PromptRelationSourceAuthenticatorV1;
use crate::relations_v1::PromptRelationSourceV1;
use crate::relations_v1::ValidatedPromptRelationsV1;

pub const MAX_CANONICAL_SELECTED_FACTORS_V1: usize = 16;
pub const MAX_CANONICAL_SELECTION_STEPS_V1: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioSelectionRequestV1 {
    pub selection_id: StableId,
    pub token_budget: u64,
    pub maximum_selected_factors: usize,
    pub maximum_steps: usize,
    pub now_unix_ms: u64,
    pub relations: PromptRelationSourceV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptPortfolioCandidateDispositionV1 {
    Selected,
    Unavailable,
    NonPositiveStandalone,
    HeuristicExcluded,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioCandidateDecisionV1 {
    pub candidate_id: StableId,
    pub disposition: PromptPortfolioCandidateDispositionV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptOptimalityDisclosureV1 {
    HeuristicNoCertificate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub selection_id: StableId,
    pub candidate_set_receipt_digest: Digest32,
    pub pricing_receipt_digest: Digest32,
    pub relation_source_digest: Digest32,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_profile_digest: Digest32,
    pub no_intervention_arm_id: StableId,
    pub token_budget: u64,
    pub used_tokens: u64,
    pub maximum_selected_factors: usize,
    pub maximum_steps: usize,
    pub selection_steps: usize,
    pub selected_candidate_ids: Vec<StableId>,
    pub decisions: Vec<PromptPortfolioCandidateDecisionV1>,
    pub total_net_utility: FixedQ32,
    pub solver_id: StableId,
    pub optimality: PromptOptimalityDisclosureV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn select_portfolio_v1<A: PromptRelationSourceAuthenticatorV1>(
    candidate_set: &PromptCandidateSetReceiptV1,
    pricing: &PromptPricingReceiptV1,
    request: PromptPortfolioSelectionRequestV1,
    authenticator: &A,
) -> Result<PromptPortfolioReceiptV1, PromptPortfolioErrorV1> {
    candidate_set.validate(request.now_unix_ms)?;
    pricing.validate_for(candidate_set, request.now_unix_ms)?;
    validate_selection_bounds(&request)?;
    let graph = ValidatedPromptRelationsV1::new(candidate_set, &request.relations)?;
    authenticator
        .authenticate_relation_source(
            &request.relations,
            candidate_set.objective_digest,
            request.now_unix_ms,
        )
        .map_err(|_| PromptPortfolioErrorV1::RelationAuthenticationRejected)?;

    let bindings = binding_map(candidate_set);
    let prices = price_map(pricing);
    let mut selected = BTreeSet::new();
    let mut used_tokens = 0_u64;
    let mut total_net_utility = FixedQ32::ZERO;
    let mut selection_steps = 0_usize;
    while selected.len() < request.maximum_selected_factors
        && selection_steps < request.maximum_steps
    {
        let mut best: Option<BundleCandidate> = None;
        for candidate in &candidate_set.candidates {
            if selected.contains(&candidate.candidate_id) {
                continue;
            }
            let closure =
                prerequisite_closure(&candidate.candidate_id, &graph.requires, &selected);
            let Some(bundle) = evaluate_bundle(
                &candidate.candidate_id,
                &closure,
                &selected,
                &bindings,
                &prices,
                &graph,
                request.token_budget.saturating_sub(used_tokens),
                request.maximum_selected_factors,
            )? else {
                continue;
            };
            if best
                .as_ref()
                .is_none_or(|current| bundle.is_better_than(current))
            {
                best = Some(bundle);
            }
        }
        let Some(best) = best else {
            break;
        };
        for candidate_id in best.new_candidate_ids {
            selected.insert(candidate_id);
        }
        used_tokens = used_tokens
            .checked_add(best.token_cost)
            .ok_or(PromptPortfolioErrorV1::Arithmetic)?;
        total_net_utility = total_net_utility
            .checked_add(best.marginal_net_utility)
            .map_err(|_| PromptPortfolioErrorV1::Arithmetic)?;
        selection_steps += 1;
    }

    let selected_candidate_ids = selected.iter().cloned().collect::<Vec<_>>();
    let decisions = candidate_set
        .candidates
        .iter()
        .zip(&pricing.prices)
        .map(|(candidate, price)| PromptPortfolioCandidateDecisionV1 {
            candidate_id: candidate.candidate_id.clone(),
            disposition: disposition(&selected, price),
        })
        .collect::<Vec<_>>();
    let solver_id = StableId::new("prompt-greedy-prerequisite-closure-v1")
        .map_err(|_| PromptPortfolioErrorV1::InternalInvariant)?;
    let mut receipt = PromptPortfolioReceiptV1 {
        selection_id: request.selection_id,
        candidate_set_receipt_digest: candidate_set.receipt_digest,
        pricing_receipt_digest: pricing.receipt_digest,
        relation_source_digest: request.relations.source_digest,
        objective_digest: candidate_set.objective_digest,
        state_digest: candidate_set.state_digest,
        generation_vector_digest: candidate_set.generation_vector_digest,
        model_profile_digest: candidate_set.model_profile_digest,
        no_intervention_arm_id: candidate_set.no_intervention_arm_id.clone(),
        token_budget: request.token_budget,
        used_tokens,
        maximum_selected_factors: request.maximum_selected_factors,
        maximum_steps: request.maximum_steps,
        selection_steps,
        selected_candidate_ids,
        decisions,
        total_net_utility,
        solver_id,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = compute_receipt_digest(&receipt);
    receipt.validate_for(
        candidate_set,
        pricing,
        &request.relations,
        request.now_unix_ms,
    )?;
    Ok(receipt)
}

impl PromptPortfolioReceiptV1 {
    pub fn validate_for(
        &self,
        candidate_set: &PromptCandidateSetReceiptV1,
        pricing: &PromptPricingReceiptV1,
        relations: &PromptRelationSourceV1,
        now_unix_ms: u64,
    ) -> Result<(), PromptPortfolioErrorV1> {
        candidate_set.validate(now_unix_ms)?;
        pricing.validate_for(candidate_set, now_unix_ms)?;
        let graph = ValidatedPromptRelationsV1::new(candidate_set, relations)?;
        if self.authority.grants_any()
            || self.candidate_set_receipt_digest != candidate_set.receipt_digest
            || self.pricing_receipt_digest != pricing.receipt_digest
            || self.relation_source_digest != relations.source_digest
            || self.objective_digest != candidate_set.objective_digest
            || self.state_digest != candidate_set.state_digest
            || self.generation_vector_digest != candidate_set.generation_vector_digest
            || self.model_profile_digest != candidate_set.model_profile_digest
            || self.no_intervention_arm_id != candidate_set.no_intervention_arm_id
            || self.used_tokens > self.token_budget
            || self.maximum_selected_factors == 0
            || self.maximum_selected_factors > MAX_CANONICAL_SELECTED_FACTORS_V1
            || self.maximum_steps == 0
            || self.maximum_steps > MAX_CANONICAL_SELECTION_STEPS_V1
            || self.selection_steps > self.maximum_steps
            || self.selected_candidate_ids.len() > self.maximum_selected_factors
            || self.optimality != PromptOptimalityDisclosureV1::HeuristicNoCertificate
            || self.solver_id.as_str() != "prompt-greedy-prerequisite-closure-v1"
        {
            return Err(PromptPortfolioErrorV1::InvalidReceipt);
        }
        if self
            .selected_candidate_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        {
            return Err(PromptPortfolioErrorV1::InvalidReceipt);
        }
        let selected = self
            .selected_candidate_ids
            .iter()
            .cloned()
            .collect::<BTreeSet<_>>();
        let (expected_tokens, expected_utility) =
            evaluate_selected_portfolio(&selected, candidate_set, pricing, &graph)?;
        if expected_tokens != self.used_tokens || expected_utility != self.total_net_utility {
            return Err(PromptPortfolioErrorV1::InvalidReceipt);
        }
        if self.decisions.len() != candidate_set.candidates.len()
            || self
                .decisions
                .iter()
                .zip(candidate_set.candidates.iter().zip(&pricing.prices))
                .any(|(decision, (candidate, price))| {
                    decision.candidate_id != candidate.candidate_id
                        || decision.disposition != disposition(&selected, price)
                })
        {
            return Err(PromptPortfolioErrorV1::InvalidReceipt);
        }
        require_digest(self.receipt_digest, "portfolio receipt")?;
        if self.receipt_digest != compute_receipt_digest(self) {
            return Err(PromptPortfolioErrorV1::DigestMismatch("portfolio receipt"));
        }
        Ok(())
    }
}

#[derive(Clone)]
struct BundleCandidate {
    root_candidate_id: StableId,
    new_candidate_ids: Vec<StableId>,
    token_cost: u64,
    marginal_net_utility: FixedQ32,
}

impl BundleCandidate {
    fn is_better_than(&self, other: &Self) -> bool {
        self.marginal_net_utility > other.marginal_net_utility
            || (self.marginal_net_utility == other.marginal_net_utility
                && (self.token_cost < other.token_cost
                    || (self.token_cost == other.token_cost
                        && self.root_candidate_id < other.root_candidate_id)))
    }
}

fn evaluate_bundle(
    root_candidate_id: &StableId,
    closure: &BTreeSet<StableId>,
    selected: &BTreeSet<StableId>,
    bindings: &BTreeMap<StableId, &PromptCandidateBindingV1>,
    prices: &BTreeMap<StableId, &PromptPriceV1>,
    graph: &ValidatedPromptRelationsV1,
    remaining_budget: u64,
    maximum_selected_factors: usize,
) -> Result<Option<BundleCandidate>, PromptPortfolioErrorV1> {
    let new_candidate_ids = closure
        .difference(selected)
        .cloned()
        .collect::<Vec<_>>();
    if new_candidate_ids.is_empty()
        || selected.len().saturating_add(new_candidate_ids.len()) > maximum_selected_factors
    {
        return Ok(None);
    }
    let mut factor_ids = selected
        .iter()
        .filter_map(|candidate_id| {
            bindings
                .get(candidate_id)
                .map(|binding| binding.factor_id.clone())
        })
        .collect::<BTreeSet<_>>();
    let mut token_cost = 0_u64;
    let mut marginal = FixedQ32::ZERO;
    for candidate_id in &new_candidate_ids {
        let binding = bindings
            .get(candidate_id)
            .ok_or(PromptPortfolioErrorV1::InternalInvariant)?;
        if !factor_ids.insert(binding.factor_id.clone()) {
            return Ok(None);
        }
        let price = prices
            .get(candidate_id)
            .ok_or(PromptPortfolioErrorV1::InternalInvariant)?;
        if price.availability != PromptPriceAvailabilityV1::Available {
            return Ok(None);
        }
        token_cost = token_cost
            .checked_add(binding.token_cost)
            .ok_or(PromptPortfolioErrorV1::Arithmetic)?;
        if token_cost > remaining_budget {
            return Ok(None);
        }
        marginal = marginal
            .checked_add(price.net_utility)
            .map_err(|_| PromptPortfolioErrorV1::Arithmetic)?;
    }
    let final_selection = selected
        .union(closure)
        .cloned()
        .collect::<BTreeSet<_>>();
    if has_conflict(&final_selection, &graph.conflicts) {
        return Ok(None);
    }
    let final_ids = final_selection.iter().collect::<Vec<_>>();
    for (index, left) in final_ids.iter().enumerate() {
        for right in final_ids.iter().skip(index + 1) {
            if selected.contains(*left) && selected.contains(*right) {
                continue;
            }
            let key = ((*left).clone(), (*right).clone());
            let Some(pair_gain) = graph.interactions.get(&key) else {
                return Ok(None);
            };
            marginal = marginal
                .checked_add(*pair_gain)
                .map_err(|_| PromptPortfolioErrorV1::Arithmetic)?;
        }
    }
    if marginal <= FixedQ32::ZERO {
        return Ok(None);
    }
    Ok(Some(BundleCandidate {
        root_candidate_id: root_candidate_id.clone(),
        new_candidate_ids,
        token_cost,
        marginal_net_utility: marginal,
    }))
}

fn prerequisite_closure(
    candidate_id: &StableId,
    requires: &BTreeMap<StableId, Vec<StableId>>,
    selected: &BTreeSet<StableId>,
) -> BTreeSet<StableId> {
    fn visit(
        candidate_id: &StableId,
        requires: &BTreeMap<StableId, Vec<StableId>>,
        selected: &BTreeSet<StableId>,
        closure: &mut BTreeSet<StableId>,
    ) {
        if selected.contains(candidate_id) || closure.contains(candidate_id) {
            return;
        }
        if let Some(prerequisites) = requires.get(candidate_id) {
            for prerequisite in prerequisites {
                visit(prerequisite, requires, selected, closure);
            }
        }
        closure.insert(candidate_id.clone());
    }

    let mut closure = BTreeSet::new();
    visit(candidate_id, requires, selected, &mut closure);
    closure
}

fn evaluate_selected_portfolio(
    selected: &BTreeSet<StableId>,
    candidate_set: &PromptCandidateSetReceiptV1,
    pricing: &PromptPricingReceiptV1,
    graph: &ValidatedPromptRelationsV1,
) -> Result<(u64, FixedQ32), PromptPortfolioErrorV1> {
    let bindings = binding_map(candidate_set);
    let prices = price_map(pricing);
    if has_conflict(selected, &graph.conflicts) {
        return Err(PromptPortfolioErrorV1::InvalidReceipt);
    }
    let mut factor_ids = BTreeSet::new();
    let mut tokens = 0_u64;
    let mut utility = FixedQ32::ZERO;
    for candidate_id in selected {
        let binding = bindings
            .get(candidate_id)
            .ok_or(PromptPortfolioErrorV1::InvalidReceipt)?;
        if !factor_ids.insert(binding.factor_id.clone()) {
            return Err(PromptPortfolioErrorV1::InvalidReceipt);
        }
        let price = prices
            .get(candidate_id)
            .ok_or(PromptPortfolioErrorV1::InvalidReceipt)?;
        if price.availability != PromptPriceAvailabilityV1::Available {
            return Err(PromptPortfolioErrorV1::InvalidReceipt);
        }
        if let Some(prerequisites) = graph.requires.get(candidate_id)
            && prerequisites
                .iter()
                .any(|prerequisite| !selected.contains(prerequisite))
        {
            return Err(PromptPortfolioErrorV1::InvalidReceipt);
        }
        tokens = tokens
            .checked_add(binding.token_cost)
            .ok_or(PromptPortfolioErrorV1::Arithmetic)?;
        utility = utility
            .checked_add(price.net_utility)
            .map_err(|_| PromptPortfolioErrorV1::Arithmetic)?;
    }
    let ids = selected.iter().collect::<Vec<_>>();
    for (index, left) in ids.iter().enumerate() {
        for right in ids.iter().skip(index + 1) {
            let key = ((*left).clone(), (*right).clone());
            let pair_gain = graph.interactions.get(&key).ok_or_else(|| {
                PromptPortfolioErrorV1::MissingPairSupport(left.to_string(), right.to_string())
            })?;
            utility = utility
                .checked_add(*pair_gain)
                .map_err(|_| PromptPortfolioErrorV1::Arithmetic)?;
        }
    }
    Ok((tokens, utility))
}

fn binding_map(
    candidate_set: &PromptCandidateSetReceiptV1,
) -> BTreeMap<StableId, &PromptCandidateBindingV1> {
    candidate_set
        .candidates
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate))
        .collect()
}

fn price_map(pricing: &PromptPricingReceiptV1) -> BTreeMap<StableId, &PromptPriceV1> {
    pricing
        .prices
        .iter()
        .map(|price| (price.candidate_id.clone(), price))
        .collect()
}

fn has_conflict(
    selected: &BTreeSet<StableId>,
    conflicts: &BTreeSet<(StableId, StableId)>,
) -> bool {
    conflicts
        .iter()
        .any(|(left, right)| selected.contains(left) && selected.contains(right))
}

fn disposition(
    selected: &BTreeSet<StableId>,
    price: &PromptPriceV1,
) -> PromptPortfolioCandidateDispositionV1 {
    if selected.contains(&price.candidate_id) {
        PromptPortfolioCandidateDispositionV1::Selected
    } else if price.availability != PromptPriceAvailabilityV1::Available {
        PromptPortfolioCandidateDispositionV1::Unavailable
    } else if price.net_utility <= FixedQ32::ZERO {
        PromptPortfolioCandidateDispositionV1::NonPositiveStandalone
    } else {
        PromptPortfolioCandidateDispositionV1::HeuristicExcluded
    }
}

fn validate_selection_bounds(
    request: &PromptPortfolioSelectionRequestV1,
) -> Result<(), PromptPortfolioErrorV1> {
    if request.token_budget == 0
        || request.now_unix_ms == 0
        || request.maximum_selected_factors == 0
        || request.maximum_selected_factors > MAX_CANONICAL_SELECTED_FACTORS_V1
        || request.maximum_steps == 0
        || request.maximum_steps > MAX_CANONICAL_SELECTION_STEPS_V1
    {
        return Err(PromptPortfolioErrorV1::InvalidSelectionBound);
    }
    Ok(())
}

fn compute_receipt_digest(receipt: &PromptPortfolioReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio-receipt.v1".to_vec();
    push_id(&mut bytes, &receipt.selection_id);
    for digest in [
        receipt.candidate_set_receipt_digest,
        receipt.pricing_receipt_digest,
        receipt.relation_source_digest,
        receipt.objective_digest,
        receipt.state_digest,
        receipt.generation_vector_digest,
        receipt.model_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &receipt.no_intervention_arm_id);
    bytes.extend_from_slice(&receipt.token_budget.to_be_bytes());
    bytes.extend_from_slice(&receipt.used_tokens.to_be_bytes());
    push_len(&mut bytes, receipt.maximum_selected_factors);
    push_len(&mut bytes, receipt.maximum_steps);
    push_len(&mut bytes, receipt.selection_steps);
    push_len(&mut bytes, receipt.selected_candidate_ids.len());
    for candidate_id in &receipt.selected_candidate_ids {
        push_id(&mut bytes, candidate_id);
    }
    push_len(&mut bytes, receipt.decisions.len());
    for decision in &receipt.decisions {
        push_id(&mut bytes, &decision.candidate_id);
        bytes.push(match decision.disposition {
            PromptPortfolioCandidateDispositionV1::Selected => 0,
            PromptPortfolioCandidateDispositionV1::Unavailable => 1,
            PromptPortfolioCandidateDispositionV1::NonPositiveStandalone => 2,
            PromptPortfolioCandidateDispositionV1::HeuristicExcluded => 3,
        });
    }
    bytes.extend_from_slice(&receipt.total_net_utility.raw().to_be_bytes());
    push_id(&mut bytes, &receipt.solver_id);
    bytes.push(0); // HeuristicNoCertificate.
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptPortfolioErrorV1 {
    Canonical(CanonicalPromptErrorV1),
    Relation(PromptRelationErrorV1),
    RelationAuthenticationRejected,
    MissingPairSupport(String, String),
    InvalidSelectionBound,
    InvalidReceipt,
    DigestMismatch(&'static str),
    Arithmetic,
    InternalInvariant,
}

impl From<CanonicalPromptErrorV1> for PromptPortfolioErrorV1 {
    fn from(value: CanonicalPromptErrorV1) -> Self {
        Self::Canonical(value)
    }
}

impl From<PromptRelationErrorV1> for PromptPortfolioErrorV1 {
    fn from(value: PromptRelationErrorV1) -> Self {
        Self::Relation(value)
    }
}

impl fmt::Display for PromptPortfolioErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptPortfolioErrorV1 {}

#[cfg(test)]
#[path = "portfolio_v1_tests.rs"]
mod tests;
