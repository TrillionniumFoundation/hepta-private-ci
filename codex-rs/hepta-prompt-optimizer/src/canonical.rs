//! Canonical, authority-free prompt selection pipeline.
//!
//! This module closes the semantic gap between the registry's authenticated
//! V2 snapshot and the optimizer's local shadow calculator. It remains
//! read-only: every receipt carries DENY_ALL and an exercise decision only
//! states whether a previously selected portfolio is still valid at a named
//! delivery boundary.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_prompt_registry::{
    CompatibleRealizationSetV2, PromptModelTupleV2, PromptRegistry, PromptRegistrySnapshotV2,
    PromptRoleV2,
};
use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

const MAX_CANONICAL_CANDIDATES: usize = 128;
const MAX_CANONICAL_SELECTED: usize = 16;
const MAX_CANONICAL_EDGES: usize = 512;
const MAX_CANONICAL_TOKEN_BUDGET: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub payload_digest: Digest32,
    pub token_cost: u64,
    pub role: PromptRoleV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub generator_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
    pub candidates: Vec<PromptCandidateV1>,
    pub omitted_count: u32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateEvidenceV1 {
    pub candidate_id: StableId,
    pub causal_utility: FixedQ32,
    pub token_shadow_cost: FixedQ32,
    pub latency_cost: FixedQ32,
    pub crowding_cost: FixedQ32,
    pub interference_cost: FixedQ32,
    pub privacy_cost: FixedQ32,
    pub instability_cost: FixedQ32,
    pub future_option_cost: FixedQ32,
    pub resource_cost: FixedQ32,
    pub support_digest: Digest32,
    pub confidence_digest: Digest32,
    pub applicability_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPriceV1 {
    pub candidate: PromptCandidateV1,
    pub causal_utility: FixedQ32,
    pub total_utility_cost: FixedQ32,
    pub net_utility: FixedQ32,
    pub support_digest: Digest32,
    pub confidence_digest: Digest32,
    pub applicability_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub decision_id: StableId,
    pub candidate_set_digest: Digest32,
    pub prices: Vec<PromptPriceV1>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PortfolioRelationV1 {
    Interaction {
        left_candidate_id: StableId,
        right_candidate_id: StableId,
        marginal_utility: FixedQ32,
        support_digest: Digest32,
    },
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortfolioBudgetV1 {
    pub token_budget: u64,
    pub maximum_selected: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub decision_id: StableId,
    pub pricing_receipt_digest: Digest32,
    pub selected_candidate_ids: Vec<StableId>,
    pub selected_factor_ids: Vec<StableId>,
    pub selected_realization_ids: Vec<StableId>,
    pub total_token_cost: u64,
    pub total_net_utility: FixedQ32,
    pub token_budget: u64,
    pub selection_method: StableId,
    pub optimality_certificate: Option<Digest32>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExerciseDispositionV1 {
    Exercise,
    RejectStale,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExerciseBoundaryV1 {
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub decision_id: StableId,
    pub portfolio_receipt_digest: Digest32,
    pub boundary: ExerciseBoundaryV1,
    pub registry_snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub disposition: ExerciseDispositionV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalError {
    EmptyDigest(&'static str),
    CandidateLimitExceeded,
    SelectedLimitExceeded,
    RelationLimitExceeded,
    TokenBudgetExceeded,
    DuplicateCandidate(String),
    DuplicateEvidence(String),
    MissingEvidence(String),
    UnknownRelationEndpoint(String),
    EmptySupport(&'static str),
    NonCanonicalInput(&'static str),
    Registry(String),
    CandidateSetMismatch,
    PricingMismatch,
    DependencyCycle(String),
    Arithmetic,
}

impl fmt::Display for CanonicalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CanonicalError {}

pub fn enumerate_factors(
    decision_id: StableId,
    objective_digest: Digest32,
    registry_snapshot: &PromptRegistrySnapshotV2,
    compatible: &CompatibleRealizationSetV2,
    generator_digest: Digest32,
    hard_filter_digest: Digest32,
    truncation_digest: Digest32,
) -> Result<PromptCandidateSetReceiptV1, CanonicalError> {
    registry_snapshot
        .validate()
        .map_err(|error| CanonicalError::Registry(error.to_string()))?;
    compatible
        .validate()
        .map_err(|error| CanonicalError::Registry(error.to_string()))?;
    for (label, digest) in [
        ("objective", objective_digest),
        ("generator", generator_digest),
        ("hard_filter", hard_filter_digest),
        ("truncation", truncation_digest),
    ] {
        ensure_digest(label, digest)?;
    }
    if compatible.snapshot_digest != registry_snapshot.snapshot_digest
        || compatible.model_tuple_digest != registry_snapshot.model_tuple_digest
    {
        return Err(CanonicalError::CandidateSetMismatch);
    }
    if compatible.bindings.len() > MAX_CANONICAL_CANDIDATES {
        return Err(CanonicalError::CandidateLimitExceeded);
    }

    let mut candidates = Vec::with_capacity(compatible.bindings.len());
    for binding in &compatible.bindings {
        candidates.push(PromptCandidateV1 {
            candidate_id: binding.realization_id.clone(),
            factor_id: binding.factor_id.clone(),
            realization_id: binding.realization_id.clone(),
            payload_digest: binding.payload_digest,
            token_cost: u64::from(binding.token_cost),
            role: binding.role,
        });
    }
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    ensure_unique_candidates(&candidates)?;

    let mut receipt = PromptCandidateSetReceiptV1 {
        decision_id,
        objective_digest,
        registry_snapshot_digest: registry_snapshot.snapshot_digest,
        model_tuple_digest: registry_snapshot.model_tuple_digest,
        generator_digest,
        hard_filter_digest,
        truncation_digest,
        candidates,
        omitted_count: compatible.omitted_count,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_candidate_set(&receipt);
    Ok(receipt)
}

#[must_use]
pub fn candidate_evidence_signing_bytes(evidence: &CandidateEvidenceV1) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.candidate-evidence.v1".to_vec();
    push_id(&mut bytes, &evidence.candidate_id);
    for value in [
        evidence.causal_utility,
        evidence.token_shadow_cost,
        evidence.latency_cost,
        evidence.crowding_cost,
        evidence.interference_cost,
        evidence.privacy_cost,
        evidence.instability_cost,
        evidence.future_option_cost,
        evidence.resource_cost,
    ] {
        push_i64(&mut bytes, value.raw());
    }
    for digest in [
        evidence.support_digest,
        evidence.confidence_digest,
        evidence.applicability_digest,
    ] {
        push_digest(&mut bytes, digest);
    }
    bytes
}

#[must_use]
pub fn candidate_evidence_digest(evidence: &CandidateEvidenceV1) -> Digest32 {
    Digest32::of_bytes(&candidate_evidence_signing_bytes(evidence))
}

pub fn price_factors(
    candidates: &PromptCandidateSetReceiptV1,
    mut evidence: Vec<CandidateEvidenceV1>,
) -> Result<PromptPricingReceiptV1, CanonicalError> {
    validate_candidate_receipt(candidates)?;
    evidence.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    for row in &evidence {
        if !seen.insert(row.candidate_id.clone()) {
            return Err(CanonicalError::DuplicateEvidence(row.candidate_id.to_string()));
        }
        for (label, digest) in [
            ("pricing support", row.support_digest),
            ("pricing confidence", row.confidence_digest),
            ("pricing applicability", row.applicability_digest),
        ] {
            ensure_digest(label, digest)?;
        }
    }

    let evidence_by_id = evidence
        .into_iter()
        .map(|row| (row.candidate_id.clone(), row))
        .collect::<BTreeMap<_, _>>();
    let mut prices = Vec::with_capacity(candidates.candidates.len());
    for candidate in &candidates.candidates {
        let Some(row) = evidence_by_id.get(&candidate.candidate_id) else {
            return Err(CanonicalError::MissingEvidence(candidate.candidate_id.to_string()));
        };
        let mut total_utility_cost = FixedQ32::ZERO;
        for cost in [
            row.token_shadow_cost,
            row.latency_cost,
            row.crowding_cost,
            row.interference_cost,
            row.privacy_cost,
            row.instability_cost,
            row.future_option_cost,
            row.resource_cost,
        ] {
            total_utility_cost = total_utility_cost
                .checked_add(cost)
                .map_err(|_| CanonicalError::Arithmetic)?;
        }
        let net_utility = row
            .causal_utility
            .checked_sub(total_utility_cost)
            .map_err(|_| CanonicalError::Arithmetic)?;
        prices.push(PromptPriceV1 {
            candidate: candidate.clone(),
            causal_utility: row.causal_utility,
            total_utility_cost,
            net_utility,
            support_digest: row.support_digest,
            confidence_digest: row.confidence_digest,
            applicability_digest: row.applicability_digest,
        });
    }
    let mut receipt = PromptPricingReceiptV1 {
        decision_id: candidates.decision_id.clone(),
        candidate_set_digest: candidates.receipt_digest,
        prices,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_pricing(&receipt);
    Ok(receipt)
}

pub fn select_portfolio(
    pricing: &PromptPricingReceiptV1,
    relations: Vec<PortfolioRelationV1>,
    budget: PortfolioBudgetV1,
) -> Result<PromptPortfolioReceiptV1, CanonicalError> {
    validate_pricing_receipt(pricing)?;
    if budget.maximum_selected == 0 || budget.maximum_selected > MAX_CANONICAL_SELECTED {
        return Err(CanonicalError::SelectedLimitExceeded);
    }
    if budget.token_budget == 0 || budget.token_budget > MAX_CANONICAL_TOKEN_BUDGET {
        return Err(CanonicalError::TokenBudgetExceeded);
    }
    if relations.len() > MAX_CANONICAL_EDGES {
        return Err(CanonicalError::RelationLimitExceeded);
    }

    let prices = pricing
        .prices
        .iter()
        .map(|price| (price.candidate.candidate_id.clone(), price))
        .collect::<BTreeMap<_, _>>();
    let graph = validate_relations(&relations, &prices)?;
    let mut selected = BTreeSet::new();
    let mut remaining = budget.token_budget;
    let mut total = FixedQ32::ZERO;

    while selected.len() < budget.maximum_selected {
        let mut best: Option<(Vec<StableId>, FixedQ32, u64)> = None;
        for candidate_id in prices.keys() {
            if selected.contains(candidate_id) {
                continue;
            }
            let closure = prerequisite_closure(candidate_id, &graph.requires)?;
            if closure.iter().any(|id| selected.contains(id)) && closure.iter().all(|id| selected.contains(id)) {
                continue;
            }
            let additions = closure
                .into_iter()
                .filter(|id| !selected.contains(id))
                .collect::<Vec<_>>();
            if additions.is_empty() || selected.len().saturating_add(additions.len()) > budget.maximum_selected {
                continue;
            }
            if factor_collision(&additions, &selected, &prices)
                || conflicts_with_selection(&additions, &selected, &graph.conflicts)
            {
                continue;
            }
            let token_cost = additions.iter().try_fold(0_u64, |sum, id| {
                let Some(price) = prices.get(id) else {
                    return Err(CanonicalError::UnknownRelationEndpoint(id.to_string()));
                };
                sum.checked_add(price.candidate.token_cost)
                    .ok_or(CanonicalError::Arithmetic)
            })?;
            if token_cost > remaining {
                continue;
            }
            let gain = bundle_gain(&additions, &selected, &prices, &graph.interactions)?;
            if gain <= FixedQ32::ZERO {
                continue;
            }
            let is_better = best.as_ref().is_none_or(|(best_ids, best_gain, best_cost)| {
                gain > *best_gain
                    || (gain == *best_gain
                        && (token_cost < *best_cost
                            || (token_cost == *best_cost && additions < *best_ids)))
            });
            if is_better {
                best = Some((additions, gain, token_cost));
            }
        }
        let Some((additions, gain, token_cost)) = best else {
            break;
        };
        remaining = remaining
            .checked_sub(token_cost)
            .ok_or(CanonicalError::Arithmetic)?;
        total = total
            .checked_add(gain)
            .map_err(|_| CanonicalError::Arithmetic)?;
        for candidate_id in additions {
            selected.insert(candidate_id);
        }
    }

    let selected_candidate_ids = selected.into_iter().collect::<Vec<_>>();
    let mut selected_factor_ids = Vec::with_capacity(selected_candidate_ids.len());
    let mut selected_realization_ids = Vec::with_capacity(selected_candidate_ids.len());
    for id in &selected_candidate_ids {
        let Some(price) = prices.get(id) else {
            return Err(CanonicalError::UnknownRelationEndpoint(id.to_string()));
        };
        selected_factor_ids.push(price.candidate.factor_id.clone());
        selected_realization_ids.push(price.candidate.realization_id.clone());
    }
    let total_token_cost = budget
        .token_budget
        .checked_sub(remaining)
        .ok_or(CanonicalError::Arithmetic)?;
    let mut receipt = PromptPortfolioReceiptV1 {
        decision_id: pricing.decision_id.clone(),
        pricing_receipt_digest: pricing.receipt_digest,
        selected_candidate_ids,
        selected_factor_ids,
        selected_realization_ids,
        total_token_cost,
        total_net_utility: total,
        token_budget: budget.token_budget,
        selection_method: stable_id("bundle-greedy-marginal-v1")?,
        optimality_certificate: None,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_portfolio(&receipt);
    Ok(receipt)
}

pub fn exercise(
    portfolio: &PromptPortfolioReceiptV1,
    registry: &PromptRegistry,
    expected_snapshot: &PromptRegistrySnapshotV2,
    generation_vector_digest: Digest32,
    model_tuple: &PromptModelTupleV2,
    now_unix_ms: u64,
    boundary: ExerciseBoundaryV1,
) -> Result<PromptExerciseDecisionV1, CanonicalError> {
    validate_portfolio_receipt(portfolio)?;
    expected_snapshot
        .validate()
        .map_err(|error| CanonicalError::Registry(error.to_string()))?;
    let current = registry
        .snapshot_v2(generation_vector_digest, model_tuple)
        .map_err(|error| CanonicalError::Registry(error.to_string()))?;

    let disposition = if current != *expected_snapshot {
        ExerciseDispositionV1::RejectStale
    } else {
        let compatible = registry.read_compatible_v2(
            expected_snapshot,
            generation_vector_digest,
            model_tuple,
            now_unix_ms,
            portfolio.selected_factor_ids.clone(),
            u32::try_from(MAX_CANONICAL_CANDIDATES).unwrap_or(u32::MAX),
        );
        match compatible {
            Ok(set) => {
                let realized = set
                    .bindings
                    .iter()
                    .map(|binding| binding.realization_id.clone())
                    .collect::<BTreeSet<_>>();
                if portfolio
                    .selected_realization_ids
                    .iter()
                    .all(|id| realized.contains(id))
                {
                    ExerciseDispositionV1::Exercise
                } else {
                    ExerciseDispositionV1::RejectStale
                }
            }
            Err(_) => ExerciseDispositionV1::RejectStale,
        }
    };

    let mut receipt = PromptExerciseDecisionV1 {
        decision_id: portfolio.decision_id.clone(),
        portfolio_receipt_digest: portfolio.receipt_digest,
        boundary,
        registry_snapshot_digest: current.snapshot_digest,
        model_tuple_digest: model_tuple.digest(),
        disposition,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_exercise(&receipt);
    Ok(receipt)
}

struct RelationGraph {
    interactions: BTreeMap<(StableId, StableId), FixedQ32>,
    conflicts: BTreeSet<(StableId, StableId)>,
    requires: BTreeMap<StableId, Vec<StableId>>,
}

fn validate_relations<'a>(
    relations: &[PortfolioRelationV1],
    prices: &BTreeMap<StableId, &'a PromptPriceV1>,
) -> Result<RelationGraph, CanonicalError> {
    let mut graph = RelationGraph {
        interactions: BTreeMap::new(),
        conflicts: BTreeSet::new(),
        requires: BTreeMap::new(),
    };
    let mut seen = BTreeSet::new();
    for relation in relations {
        let (kind, left, right, support) = match relation {
            PortfolioRelationV1::Interaction { left_candidate_id, right_candidate_id, marginal_utility, support_digest } => {
                let (left, right) = ordered_pair(left_candidate_id, right_candidate_id)?;
                let key = (0_u8, left.clone(), right.clone());
                if !seen.insert(key) {
                    return Err(CanonicalError::NonCanonicalInput("duplicate relation"));
                }
                graph.interactions.insert((left, right), *marginal_utility);
                (0_u8, left_candidate_id, right_candidate_id, *support_digest)
            }
            PortfolioRelationV1::Conflict { left_candidate_id, right_candidate_id, support_digest } => {
                let (left, right) = ordered_pair(left_candidate_id, right_candidate_id)?;
                let key = (1_u8, left.clone(), right.clone());
                if !seen.insert(key) {
                    return Err(CanonicalError::NonCanonicalInput("duplicate relation"));
                }
                graph.conflicts.insert((left, right));
                (1_u8, left_candidate_id, right_candidate_id, *support_digest)
            }
            PortfolioRelationV1::Requires { candidate_id, prerequisite_candidate_id, support_digest } => {
                if candidate_id == prerequisite_candidate_id {
                    return Err(CanonicalError::NonCanonicalInput("self prerequisite"));
                }
                let key = (2_u8, candidate_id.clone(), prerequisite_candidate_id.clone());
                if !seen.insert(key) {
                    return Err(CanonicalError::NonCanonicalInput("duplicate relation"));
                }
                graph.requires.entry(candidate_id.clone()).or_default().push(prerequisite_candidate_id.clone());
                (2_u8, candidate_id, prerequisite_candidate_id, *support_digest)
            }
        };
        let _ = kind;
        ensure_digest("relation support", support)?;
        for endpoint in [left, right] {
            if !prices.contains_key(endpoint) {
                return Err(CanonicalError::UnknownRelationEndpoint(endpoint.to_string()));
            }
        }
    }
    for prerequisites in graph.requires.values_mut() {
        prerequisites.sort();
    }
    for id in prices.keys() {
        let _ = prerequisite_closure(id, &graph.requires)?;
    }
    Ok(graph)
}

fn prerequisite_closure(
    root: &StableId,
    requires: &BTreeMap<StableId, Vec<StableId>>,
) -> Result<Vec<StableId>, CanonicalError> {
    fn visit(
        id: &StableId,
        requires: &BTreeMap<StableId, Vec<StableId>>,
        visiting: &mut BTreeSet<StableId>,
        visited: &mut BTreeSet<StableId>,
        output: &mut Vec<StableId>,
    ) -> Result<(), CanonicalError> {
        if visited.contains(id) {
            return Ok(());
        }
        if !visiting.insert(id.clone()) {
            return Err(CanonicalError::DependencyCycle(id.to_string()));
        }
        if let Some(prerequisites) = requires.get(id) {
            for prerequisite in prerequisites {
                visit(prerequisite, requires, visiting, visited, output)?;
            }
        }
        visiting.remove(id);
        visited.insert(id.clone());
        output.push(id.clone());
        Ok(())
    }
    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    let mut output = Vec::new();
    visit(root, requires, &mut visiting, &mut visited, &mut output)?;
    Ok(output)
}

fn factor_collision(
    additions: &[StableId],
    selected: &BTreeSet<StableId>,
    prices: &BTreeMap<StableId, &PromptPriceV1>,
) -> bool {
    let mut factors = BTreeSet::new();
    for candidate_id in selected.iter().chain(additions.iter()) {
        let Some(price) = prices.get(candidate_id) else {
            return true;
        };
        if !factors.insert(price.candidate.factor_id.clone()) {
            return true;
        }
    }
    false
}

fn conflicts_with_selection(
    additions: &[StableId],
    selected: &BTreeSet<StableId>,
    conflicts: &BTreeSet<(StableId, StableId)>,
) -> bool {
    for (index, left) in additions.iter().enumerate() {
        for right in additions.iter().skip(index + 1) {
            if conflicts.contains(&canonical_pair(left, right)) {
                return true;
            }
        }
        for right in selected {
            if conflicts.contains(&canonical_pair(left, right)) {
                return true;
            }
        }
    }
    false
}

fn bundle_gain(
    additions: &[StableId],
    selected: &BTreeSet<StableId>,
    prices: &BTreeMap<StableId, &PromptPriceV1>,
    interactions: &BTreeMap<(StableId, StableId), FixedQ32>,
) -> Result<FixedQ32, CanonicalError> {
    let mut gain = FixedQ32::ZERO;
    for id in additions {
        let Some(price) = prices.get(id) else {
            return Err(CanonicalError::UnknownRelationEndpoint(id.to_string()));
        };
        gain = gain
            .checked_add(price.net_utility)
            .map_err(|_| CanonicalError::Arithmetic)?;
        for peer in selected {
            if let Some(marginal) = interactions.get(&canonical_pair(id, peer)) {
                gain = gain
                    .checked_add(*marginal)
                    .map_err(|_| CanonicalError::Arithmetic)?;
            }
        }
    }
    for (index, left) in additions.iter().enumerate() {
        for right in additions.iter().skip(index + 1) {
            if let Some(marginal) = interactions.get(&canonical_pair(left, right)) {
                gain = gain
                    .checked_add(*marginal)
                    .map_err(|_| CanonicalError::Arithmetic)?;
            }
        }
    }
    Ok(gain)
}

fn validate_candidate_receipt(value: &PromptCandidateSetReceiptV1) -> Result<(), CanonicalError> {
    if value.authority.grants_any() || value.receipt_digest != digest_candidate_set(value) {
        return Err(CanonicalError::CandidateSetMismatch);
    }
    ensure_unique_candidates(&value.candidates)
}

fn validate_pricing_receipt(value: &PromptPricingReceiptV1) -> Result<(), CanonicalError> {
    if value.authority.grants_any() || value.receipt_digest != digest_pricing(value) {
        return Err(CanonicalError::PricingMismatch);
    }
    Ok(())
}

fn validate_portfolio_receipt(value: &PromptPortfolioReceiptV1) -> Result<(), CanonicalError> {
    if value.authority.grants_any() || value.receipt_digest != digest_portfolio(value) {
        return Err(CanonicalError::PricingMismatch);
    }
    Ok(())
}

fn ensure_unique_candidates(candidates: &[PromptCandidateV1]) -> Result<(), CanonicalError> {
    let mut ids = BTreeSet::new();
    let mut realizations = BTreeSet::new();
    for candidate in candidates {
        if !ids.insert(candidate.candidate_id.clone())
            || !realizations.insert(candidate.realization_id.clone())
        {
            return Err(CanonicalError::DuplicateCandidate(candidate.candidate_id.to_string()));
        }
        ensure_digest("payload", candidate.payload_digest)?;
        if candidate.token_cost == 0 {
            return Err(CanonicalError::TokenBudgetExceeded);
        }
    }
    Ok(())
}

fn ordered_pair(left: &StableId, right: &StableId) -> Result<(StableId, StableId), CanonicalError> {
    if left == right {
        return Err(CanonicalError::NonCanonicalInput("self relation"));
    }
    Ok(canonical_pair(left, right))
}

fn canonical_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left < right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

fn stable_id(value: &str) -> Result<StableId, CanonicalError> {
    StableId::new(value).map_err(|_| CanonicalError::NonCanonicalInput("identifier"))
}

fn ensure_digest(label: &'static str, digest: Digest32) -> Result<(), CanonicalError> {
    if digest.is_zero() {
        return Err(CanonicalError::EmptyDigest(label));
    }
    Ok(())
}

fn digest_candidate_set(value: &PromptCandidateSetReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set.v1".to_vec();
    push_id(&mut bytes, &value.decision_id);
    for digest in [
        value.objective_digest,
        value.registry_snapshot_digest,
        value.model_tuple_digest,
        value.generator_digest,
        value.hard_filter_digest,
        value.truncation_digest,
    ] {
        push_digest(&mut bytes, digest);
    }
    push_u64(&mut bytes, u64::try_from(value.candidates.len()).unwrap_or(u64::MAX));
    for candidate in &value.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization_id);
        push_digest(&mut bytes, candidate.payload_digest);
        push_u64(&mut bytes, candidate.token_cost);
        bytes.push(prompt_role_code(candidate.role));
    }
    push_u64(&mut bytes, u64::from(value.omitted_count));
    Digest32::of_bytes(&bytes)
}

fn digest_pricing(value: &PromptPricingReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing.v1".to_vec();
    push_id(&mut bytes, &value.decision_id);
    push_digest(&mut bytes, value.candidate_set_digest);
    for price in &value.prices {
        push_id(&mut bytes, &price.candidate.candidate_id);
        push_id(&mut bytes, &price.candidate.factor_id);
        push_id(&mut bytes, &price.candidate.realization_id);
        push_digest(&mut bytes, price.candidate.payload_digest);
        push_u64(&mut bytes, price.candidate.token_cost);
        bytes.push(prompt_role_code(price.candidate.role));
        push_i64(&mut bytes, price.causal_utility.raw());
        push_i64(&mut bytes, price.total_utility_cost.raw());
        push_i64(&mut bytes, price.net_utility.raw());
        push_digest(&mut bytes, price.support_digest);
        push_digest(&mut bytes, price.confidence_digest);
        push_digest(&mut bytes, price.applicability_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_portfolio(value: &PromptPortfolioReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio.canonical.v1".to_vec();
    push_id(&mut bytes, &value.decision_id);
    push_digest(&mut bytes, value.pricing_receipt_digest);
    push_ids(&mut bytes, &value.selected_candidate_ids);
    push_ids(&mut bytes, &value.selected_factor_ids);
    push_ids(&mut bytes, &value.selected_realization_ids);
    push_u64(&mut bytes, value.total_token_cost);
    push_i64(&mut bytes, value.total_net_utility.raw());
    push_u64(&mut bytes, value.token_budget);
    push_id(&mut bytes, &value.selection_method);
    match value.optimality_certificate {
        Some(digest) => {
            bytes.push(1);
            push_digest(&mut bytes, digest);
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn digest_exercise(value: &PromptExerciseDecisionV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise.v1".to_vec();
    push_id(&mut bytes, &value.decision_id);
    push_digest(&mut bytes, value.portfolio_receipt_digest);
    bytes.push(boundary_code(value.boundary));
    push_digest(&mut bytes, value.registry_snapshot_digest);
    push_digest(&mut bytes, value.model_tuple_digest);
    bytes.push(match value.disposition {
        ExerciseDispositionV1::Exercise => 0,
        ExerciseDispositionV1::RejectStale => 1,
    });
    Digest32::of_bytes(&bytes)
}

fn prompt_role_code(value: PromptRoleV2) -> u8 {
    match value {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}

fn boundary_code(value: ExerciseBoundaryV1) -> u8 {
    match value {
        ExerciseBoundaryV1::BeforePlanning => 0,
        ExerciseBoundaryV1::BeforeCandidateGeneration => 1,
        ExerciseBoundaryV1::BeforeModelOrToolDispatch => 2,
        ExerciseBoundaryV1::AfterObservation => 3,
        ExerciseBoundaryV1::AfterFailureOrUncertaintySpike => 4,
        ExerciseBoundaryV1::BeforeIrreversibleMutation => 5,
        ExerciseBoundaryV1::BeforeVerification => 6,
        ExerciseBoundaryV1::BeforeFinalResponse => 7,
        ExerciseBoundaryV1::BeforeCompactOrHandoff => 8,
    }
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_u64(bytes, u64::try_from(values.len()).unwrap_or(u64::MAX));
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_u64(bytes, u64::try_from(raw.len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "canonical_tests.rs"]
mod tests;
