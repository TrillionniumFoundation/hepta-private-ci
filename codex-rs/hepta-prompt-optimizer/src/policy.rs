//! Registered prompt-selection / optimization policy pipeline.
//!
//! The V1 receipt structs mirror the registered public contracts. Companion
//! audit structs carry information that the V1 wire schemas do not have fields
//! for (completeness, pricing decomposition, solver disclosure, bindings, and
//! per-candidate dispositions). This module never grants execution authority.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

pub const MAX_POLICY_FACTORS: usize = 128;
pub const MAX_POLICY_INTERACTIONS: usize = 512;
pub const MAX_POLICY_CONSTRAINTS: usize = 512;
pub const MAX_POLICY_SELECTED_FACTORS: usize = 16;
pub const MAX_POLICY_TOKEN_BUDGET: u64 = 1_000_000;
const PPM_SCALE: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredPromptCandidateV1 {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub registry_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub support_digest: Digest32,
    pub token_cost_upper_bound: u32,
    pub valid_until_unix_ms: Option<u64>,
    pub admitted: bool,
    pub legal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistrySnapshotInputV1 {
    pub registry_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub candidates: Vec<RegisteredPromptCandidateV1>,
    pub omitted_count: u32,
}

impl PromptRegistrySnapshotInputV1 {
    #[must_use]
    pub fn compute_snapshot_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-optimizer.registry-input.v1".to_vec();
        push_digest(&mut bytes, self.registry_digest);
        push_digest(&mut bytes, self.model_tuple_digest);
        push_u64(&mut bytes, u64::from(self.omitted_count));
        push_len(&mut bytes, self.candidates.len());
        for value in &self.candidates {
            push_id(&mut bytes, &value.candidate_id);
            push_id(&mut bytes, &value.factor_id);
            push_id(&mut bytes, &value.realization_id);
            push_digest(&mut bytes, value.registry_digest);
            push_digest(&mut bytes, value.model_tuple_digest);
            push_digest(&mut bytes, value.support_digest);
            push_u64(&mut bytes, u64::from(value.token_cost_upper_bound));
            match value.valid_until_unix_ms {
                Some(expiry) => {
                    bytes.push(1);
                    push_u64(&mut bytes, expiry);
                }
                None => bytes.push(0),
            }
            bytes.push(u8::from(value.admitted));
            bytes.push(u8::from(value.legal));
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), PolicyError> {
        ensure_digest("registry", self.registry_digest)?;
        ensure_digest("registry snapshot", self.snapshot_digest)?;
        ensure_digest("model tuple", self.model_tuple_digest)?;
        if self.candidates.len() > MAX_POLICY_FACTORS {
            return Err(PolicyError::CandidateLimitExceeded);
        }
        if self.snapshot_digest != self.compute_snapshot_digest() {
            return Err(PolicyError::IntegrityMismatch("registry snapshot"));
        }
        let mut candidate_ids = BTreeSet::new();
        let mut realization_ids = BTreeSet::new();
        for value in &self.candidates {
            if !candidate_ids.insert(value.candidate_id.clone()) {
                return Err(PolicyError::DuplicateCandidate(
                    value.candidate_id.to_string(),
                ));
            }
            if !realization_ids.insert(value.realization_id.clone()) {
                return Err(PolicyError::DuplicateRealization(
                    value.realization_id.to_string(),
                ));
            }
            if value.registry_digest != self.registry_digest {
                return Err(PolicyError::IntegrityMismatch("candidate registry"));
            }
            if value.model_tuple_digest != self.model_tuple_digest {
                return Err(PolicyError::IntegrityMismatch("candidate model tuple"));
            }
            ensure_digest("candidate support", value.support_digest)?;
            if value.token_cost_upper_bound == 0 {
                return Err(PolicyError::ZeroTokenCost(value.factor_id.to_string()));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateEnumerationInputV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub selection_grammar_digest: Digest32,
    pub now_unix_ms: u64,
    pub registry_snapshot: PromptRegistrySnapshotInputV1,
}

/// Registered `PromptCandidateSetReceiptV1` fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetReceiptV1 {
    pub set_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub candidate_factor_ids: Vec<StableId>,
    pub selection_grammar_digest: Digest32,
}

impl PromptCandidateSetReceiptV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-candidate-set-receipt.v1".to_vec();
        push_id(&mut bytes, &self.set_id);
        push_digest(&mut bytes, self.objective_digest);
        push_digest(&mut bytes, self.state_digest);
        push_digest(&mut bytes, self.registry_digest);
        push_len(&mut bytes, self.candidate_factor_ids.len());
        for value in &self.candidate_factor_ids {
            push_id(&mut bytes, value);
        }
        push_digest(&mut bytes, self.selection_grammar_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetAuditV1 {
    pub registry_snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub realization_binding_digest: Digest32,
    pub enumerated_count: u32,
    pub enumerated_at_unix_ms: u64,
    pub omitted_count: u32,
    pub complete: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidateSetDecisionV1 {
    pub receipt: PromptCandidateSetReceiptV1,
    pub audit: PromptCandidateSetAuditV1,
}

impl PromptCandidateSetDecisionV1 {
    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

pub fn enumerate_factors(
    input: CandidateEnumerationInputV1,
) -> Result<PromptCandidateSetReceiptV1, PolicyError> {
    Ok(enumerate_factors_audited(input)?.receipt)
}

pub fn enumerate_factors_audited(
    input: CandidateEnumerationInputV1,
) -> Result<PromptCandidateSetDecisionV1, PolicyError> {
    input.registry_snapshot.validate()?;
    ensure_digest("objective", input.objective_digest)?;
    ensure_digest("state", input.state_digest)?;
    ensure_digest("selection grammar", input.selection_grammar_digest)?;
    if input.registry_snapshot.omitted_count != 0 {
        return Err(PolicyError::CandidateSetIncomplete(
            input.registry_snapshot.omitted_count,
        ));
    }
    let bindings = eligible_bindings(&input.registry_snapshot, input.now_unix_ms);
    let candidate_factor_ids = bindings.keys().cloned().collect::<Vec<_>>();
    let receipt = PromptCandidateSetReceiptV1 {
        set_id: input.set_id,
        objective_digest: input.objective_digest,
        state_digest: input.state_digest,
        registry_digest: input.registry_snapshot.registry_digest,
        candidate_factor_ids,
        selection_grammar_digest: input.selection_grammar_digest,
    };
    Ok(PromptCandidateSetDecisionV1 {
        audit: PromptCandidateSetAuditV1 {
            registry_snapshot_digest: input.registry_snapshot.snapshot_digest,
            model_tuple_digest: input.registry_snapshot.model_tuple_digest,
            realization_binding_digest: digest_bindings(bindings.values().copied()),
            enumerated_count: u32::try_from(receipt.candidate_factor_ids.len())
                .map_err(|_| PolicyError::Arithmetic)?,
            enumerated_at_unix_ms: input.now_unix_ms,
            omitted_count: 0,
            complete: true,
        },
        receipt,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CausalUtilityEstimateV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub gross_utility: FixedQ32,
    pub downside: FixedQ32,
    pub confidence_lower: FixedQ32,
    pub confidence_upper: FixedQ32,
    pub confidence_ppm: u32,
    pub support_digest: Digest32,
    pub scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCostEstimateV1 {
    pub factor_id: StableId,
    pub token_shadow_cost: FixedQ32,
    pub latency_cost_micros: u64,
    pub latency_shadow_cost: FixedQ32,
    pub interference_ppm: u32,
    pub interference_shadow_cost: FixedQ32,
    pub resource_shadow_cost: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptConfidenceIntervalV1 {
    pub lower_q32: i64,
    pub upper_q32: i64,
    pub confidence_ppm: u32,
    pub support_digest: Digest32,
    pub scope_digest: Digest32,
}

/// Registered `PromptPricingReceiptV1` fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingReceiptV1 {
    pub factor_id: StableId,
    pub state_digest: Digest32,
    pub expected_utility_q32: i64,
    pub downside_q32: i64,
    pub token_cost: u32,
    pub latency_cost_micros: u64,
    pub interference_ppm: u32,
    pub confidence_interval: PromptConfidenceIntervalV1,
}

impl PromptPricingReceiptV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-pricing-receipt.v1".to_vec();
        push_id(&mut bytes, &self.factor_id);
        push_digest(&mut bytes, self.state_digest);
        bytes.extend_from_slice(&self.expected_utility_q32.to_be_bytes());
        bytes.extend_from_slice(&self.downside_q32.to_be_bytes());
        push_u64(&mut bytes, u64::from(self.token_cost));
        push_u64(&mut bytes, self.latency_cost_micros);
        push_u64(&mut bytes, u64::from(self.interference_ppm));
        bytes.extend_from_slice(&self.confidence_interval.lower_q32.to_be_bytes());
        bytes.extend_from_slice(&self.confidence_interval.upper_q32.to_be_bytes());
        push_u64(
            &mut bytes,
            u64::from(self.confidence_interval.confidence_ppm),
        );
        push_digest(&mut bytes, self.confidence_interval.support_digest);
        push_digest(&mut bytes, self.confidence_interval.scope_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PricingDispositionV1 {
    Priced,
    MissingCausalEstimate,
    MissingCostEstimate,
    InvalidCausalSupport,
    InvalidCostSupport,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingAuditV1 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub disposition: PricingDispositionV1,
    pub gross_utility_q32: Option<i64>,
    pub token_shadow_cost_q32: Option<i64>,
    pub latency_shadow_cost_q32: Option<i64>,
    pub interference_shadow_cost_q32: Option<i64>,
    pub resource_shadow_cost_q32: Option<i64>,
    pub causal_support_digest: Option<Digest32>,
    pub cost_support_digest: Option<Digest32>,
    pub model_tuple_digest: Digest32,
    pub realization_support_digest: Digest32,
    pub valid_until_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingDecisionV1 {
    pub candidate_set_digest: Digest32,
    pub receipts: Vec<PromptPricingReceiptV1>,
    pub audits: Vec<PromptPricingAuditV1>,
    pub pricing_digest: Digest32,
}

impl PromptPricingDecisionV1 {
    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PricingInputV1 {
    pub candidate_set: PromptCandidateSetDecisionV1,
    pub registry_snapshot: PromptRegistrySnapshotInputV1,
    pub causal_estimates: Vec<CausalUtilityEstimateV1>,
    pub cost_estimates: Vec<PromptCostEstimateV1>,
}

pub fn price_factors(input: PricingInputV1) -> Result<Vec<PromptPricingReceiptV1>, PolicyError> {
    Ok(price_factors_audited(input)?.receipts)
}

pub fn price_factors_audited(
    input: PricingInputV1,
) -> Result<PromptPricingDecisionV1, PolicyError> {
    input.registry_snapshot.validate()?;
    if !input.candidate_set.audit.complete || input.candidate_set.audit.omitted_count != 0 {
        return Err(PolicyError::CandidateSetIncomplete(
            input.candidate_set.audit.omitted_count,
        ));
    }
    if input.candidate_set.receipt.registry_digest != input.registry_snapshot.registry_digest
        || input.candidate_set.audit.registry_snapshot_digest
            != input.registry_snapshot.snapshot_digest
        || input.candidate_set.audit.model_tuple_digest
            != input.registry_snapshot.model_tuple_digest
    {
        return Err(PolicyError::IntegrityMismatch("candidate set binding"));
    }
    let bindings = eligible_bindings(
        &input.registry_snapshot,
        input.candidate_set.audit.enumerated_at_unix_ms,
    );
    if bindings.keys().cloned().collect::<Vec<_>>()
        != input.candidate_set.receipt.candidate_factor_ids
        || digest_bindings(bindings.values().copied())
            != input.candidate_set.audit.realization_binding_digest
    {
        return Err(PolicyError::IntegrityMismatch("candidate set completeness"));
    }
    let causal = unique_causal(&input.causal_estimates)?;
    let costs = unique_costs(&input.cost_estimates)?;
    let mut receipts = Vec::new();
    let mut audits = Vec::new();
    for factor_id in &input.candidate_set.receipt.candidate_factor_ids {
        let Some(binding) = bindings.get(factor_id).copied() else {
            return Err(PolicyError::IntegrityMismatch("enumerated realization"));
        };
        let causal_value = causal.get(factor_id).copied();
        let cost_value = costs.get(factor_id).copied();
        let disposition = match (causal_value, cost_value) {
            (None, _) => PricingDispositionV1::MissingCausalEstimate,
            (_, None) => PricingDispositionV1::MissingCostEstimate,
            (Some(value), _) if value.support_digest.is_zero() || value.scope_digest.is_zero() => {
                PricingDispositionV1::InvalidCausalSupport
            }
            (_, Some(value)) if value.support_digest.is_zero() => {
                PricingDispositionV1::InvalidCostSupport
            }
            _ => PricingDispositionV1::Priced,
        };
        audits.push(PromptPricingAuditV1 {
            factor_id: factor_id.clone(),
            realization_id: binding.realization_id.clone(),
            disposition,
            gross_utility_q32: causal_value.map(|value| value.gross_utility.raw()),
            token_shadow_cost_q32: cost_value.map(|value| value.token_shadow_cost.raw()),
            latency_shadow_cost_q32: cost_value.map(|value| value.latency_shadow_cost.raw()),
            interference_shadow_cost_q32: cost_value
                .map(|value| value.interference_shadow_cost.raw()),
            resource_shadow_cost_q32: cost_value.map(|value| value.resource_shadow_cost.raw()),
            causal_support_digest: causal_value.map(|value| value.support_digest),
            cost_support_digest: cost_value.map(|value| value.support_digest),
            model_tuple_digest: binding.model_tuple_digest,
            realization_support_digest: binding.support_digest,
            valid_until_unix_ms: binding.valid_until_unix_ms,
        });
        if disposition != PricingDispositionV1::Priced {
            continue;
        }
        let (Some(causal_value), Some(cost_value)) = (causal_value, cost_value) else {
            return Err(PolicyError::Arithmetic);
        };
        if causal_value.state_digest != input.candidate_set.receipt.state_digest {
            return Err(PolicyError::IntegrityMismatch("pricing state"));
        }
        if causal_value.confidence_ppm > PPM_SCALE
            || cost_value.interference_ppm > PPM_SCALE
            || causal_value.confidence_lower > causal_value.confidence_upper
            || causal_value.downside.raw() < 0
        {
            return Err(PolicyError::InvalidPricing(factor_id.to_string()));
        }
        let penalties = [
            cost_value.token_shadow_cost,
            cost_value.latency_shadow_cost,
            cost_value.interference_shadow_cost,
            cost_value.resource_shadow_cost,
        ];
        let expected = subtract_costs(causal_value.gross_utility, &penalties)?;
        let lower = subtract_costs(causal_value.confidence_lower, &penalties)?;
        let upper = subtract_costs(causal_value.confidence_upper, &penalties)?;
        receipts.push(PromptPricingReceiptV1 {
            factor_id: factor_id.clone(),
            state_digest: causal_value.state_digest,
            expected_utility_q32: expected.raw(),
            downside_q32: causal_value.downside.raw(),
            token_cost: binding.token_cost_upper_bound,
            latency_cost_micros: cost_value.latency_cost_micros,
            interference_ppm: cost_value.interference_ppm,
            confidence_interval: PromptConfidenceIntervalV1 {
                lower_q32: lower.raw(),
                upper_q32: upper.raw(),
                confidence_ppm: causal_value.confidence_ppm,
                support_digest: causal_value.support_digest,
                scope_digest: causal_value.scope_digest,
            },
        });
    }
    receipts.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    audits.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    let candidate_set_digest = input.candidate_set.receipt.digest();
    let pricing_digest = digest_pricing(candidate_set_digest, &receipts, &audits);
    Ok(PromptPricingDecisionV1 {
        candidate_set_digest,
        receipts,
        audits,
        pricing_digest,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairInteractionV1 {
    pub left_factor_id: StableId,
    pub right_factor_id: StableId,
    pub marginal_utility: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptHardConstraintV1 {
    Conflict {
        left_factor_id: StableId,
        right_factor_id: StableId,
        support_digest: Digest32,
    },
    Requires {
        factor_id: StableId,
        prerequisite_factor_id: StableId,
        support_digest: Digest32,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MissingInteractionPolicyV1 {
    RejectUnknown,
    SupportedZero(Digest32),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioSelectionMethodV1 {
    GreedyClosureDropOneV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioOptimalityV1 {
    HeuristicNoCertificate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PortfolioCandidateDispositionV1 {
    Selected,
    UnavailablePricing,
    Conflict,
    OverBudget,
    SelectionLimit,
    MissingInteractionEvidence,
    NonPositiveMarginal,
    DominatedByChosenPortfolio,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortfolioCandidateAuditV1 {
    pub factor_id: StableId,
    pub disposition: PortfolioCandidateDispositionV1,
    pub pricing_digest: Option<Digest32>,
}

/// Registered `PromptPortfolioReceiptV1` fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceiptV1 {
    pub portfolio_id: StableId,
    pub candidate_set_digest: Digest32,
    pub factor_ids: Vec<StableId>,
    pub interaction_digest: Digest32,
    pub expected_utility_q32: i64,
    pub total_token_upper_bound: u32,
    pub valid_until_unix_ms: u64,
}

impl PromptPortfolioReceiptV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-portfolio-receipt.v1".to_vec();
        push_id(&mut bytes, &self.portfolio_id);
        push_digest(&mut bytes, self.candidate_set_digest);
        push_len(&mut bytes, self.factor_ids.len());
        for value in &self.factor_ids {
            push_id(&mut bytes, value);
        }
        push_digest(&mut bytes, self.interaction_digest);
        bytes.extend_from_slice(&self.expected_utility_q32.to_be_bytes());
        push_u64(&mut bytes, u64::from(self.total_token_upper_bound));
        push_u64(&mut bytes, self.valid_until_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioAuditV1 {
    pub candidate_set_digest: Digest32,
    pub pricing_digest: Digest32,
    pub registry_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub state_digest: Digest32,
    pub interaction_digest: Digest32,
    pub constraint_digest: Digest32,
    pub token_budget: u64,
    pub maximum_selected_factors: u32,
    pub omitted_candidate_count: u32,
    pub selection_method: PortfolioSelectionMethodV1,
    pub optimality: PortfolioOptimalityV1,
    pub candidates: Vec<PortfolioCandidateAuditV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioDecisionV1 {
    pub receipt: PromptPortfolioReceiptV1,
    pub audit: PromptPortfolioAuditV1,
}

impl PromptPortfolioDecisionV1 {
    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PortfolioSelectionInputV1 {
    pub portfolio_id: StableId,
    pub candidate_set: PromptCandidateSetDecisionV1,
    pub pricing: PromptPricingDecisionV1,
    pub interactions: Vec<PromptPairInteractionV1>,
    pub hard_constraints: Vec<PromptHardConstraintV1>,
    pub missing_interaction_policy: MissingInteractionPolicyV1,
    pub token_budget: u64,
    pub maximum_selected_factors: usize,
    pub valid_until_unix_ms: u64,
}

pub fn select_portfolio(
    input: PortfolioSelectionInputV1,
) -> Result<PromptPortfolioReceiptV1, PolicyError> {
    Ok(select_portfolio_audited(input)?.receipt)
}

pub fn select_portfolio_audited(
    input: PortfolioSelectionInputV1,
) -> Result<PromptPortfolioDecisionV1, PolicyError> {
    validate_selection_input(&input)?;
    let nodes = build_nodes(&input)?;
    let interactions = InteractionIndex::build(
        &input.interactions,
        input.missing_interaction_policy,
        &input.candidate_set.receipt.candidate_factor_ids,
    )?;
    let constraints = ConstraintIndex::build(
        &input.hard_constraints,
        &input.candidate_set.receipt.candidate_factor_ids,
    )?;
    constraints.validate_satisfiable()?;
    let mut best = greedy_complete(
        Solution::default(),
        None,
        &nodes,
        &interactions,
        &constraints,
        input.token_budget,
        input.maximum_selected_factors,
    )?;
    // Drop-one restarts fix the legacy "pick the largest item first" knapsack trap
    // without claiming exact optimality.
    for forbidden in best.selected.iter().cloned().collect::<Vec<_>>() {
        let alternative = greedy_complete(
            Solution::default(),
            Some(&forbidden),
            &nodes,
            &interactions,
            &constraints,
            input.token_budget,
            input.maximum_selected_factors,
        )?;
        if better_solution(&alternative, &best) {
            best = alternative;
        }
    }
    let mut factor_ids = best.selected.iter().cloned().collect::<Vec<_>>();
    factor_ids.sort();
    let valid_until_unix_ms = best
        .selected
        .iter()
        .filter_map(|factor_id| {
            nodes
                .get(factor_id)
                .and_then(|node| node.audit.valid_until_unix_ms)
        })
        .min()
        .map_or(input.valid_until_unix_ms, |expiry| {
            expiry.min(input.valid_until_unix_ms)
        });
    if valid_until_unix_ms == 0 {
        return Err(PolicyError::InvalidValidityWindow);
    }
    let receipt = PromptPortfolioReceiptV1 {
        portfolio_id: input.portfolio_id.clone(),
        candidate_set_digest: input.candidate_set.receipt.digest(),
        factor_ids,
        interaction_digest: interactions.digest,
        expected_utility_q32: best.total_gain.raw(),
        total_token_upper_bound: u32::try_from(best.total_cost)
            .map_err(|_| PolicyError::Arithmetic)?,
        valid_until_unix_ms,
    };
    let candidates = audit_candidates(
        &receipt,
        &nodes,
        &interactions,
        &constraints,
        input.token_budget,
        input.maximum_selected_factors,
    )?;
    Ok(PromptPortfolioDecisionV1 {
        audit: PromptPortfolioAuditV1 {
            candidate_set_digest: receipt.candidate_set_digest,
            pricing_digest: input.pricing.pricing_digest,
            registry_digest: input.candidate_set.receipt.registry_digest,
            registry_snapshot_digest: input.candidate_set.audit.registry_snapshot_digest,
            model_tuple_digest: input.candidate_set.audit.model_tuple_digest,
            state_digest: input.candidate_set.receipt.state_digest,
            interaction_digest: interactions.digest,
            constraint_digest: constraints.digest,
            token_budget: input.token_budget,
            maximum_selected_factors: u32::try_from(input.maximum_selected_factors)
                .map_err(|_| PolicyError::Arithmetic)?,
            omitted_candidate_count: input.candidate_set.audit.omitted_count,
            selection_method: PortfolioSelectionMethodV1::GreedyClosureDropOneV1,
            optimality: PortfolioOptimalityV1::HeuristicNoCertificate,
            candidates,
        },
        receipt,
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
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
pub enum PromptExerciseDispositionV1 {
    Exercise,
    Wait,
    Abstain,
}

/// Registered `PromptExerciseDecisionV1` fields.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptExerciseDecisionV1 {
    pub factor_or_portfolio_id: StableId,
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub exercise_now_value_q32: i64,
    pub wait_value_q32: i64,
    pub decision: PromptExerciseDispositionV1,
    pub policy_digest: Digest32,
}

impl PromptExerciseDecisionV1 {
    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExerciseInputV1 {
    pub portfolio: PromptPortfolioDecisionV1,
    pub decision_boundary: PromptDecisionBoundaryV1,
    pub now_unix_ms: u64,
    pub state_digest: Digest32,
    pub registry_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub exercise_now_value: FixedQ32,
    pub wait_value: FixedQ32,
    pub policy_digest: Digest32,
}

pub fn exercise(input: ExerciseInputV1) -> Result<PromptExerciseDecisionV1, PolicyError> {
    ensure_digest("state", input.state_digest)?;
    ensure_digest("registry", input.registry_digest)?;
    ensure_digest("registry snapshot", input.registry_snapshot_digest)?;
    ensure_digest("model tuple", input.model_tuple_digest)?;
    ensure_digest("exercise policy", input.policy_digest)?;
    if input.portfolio.receipt.candidate_set_digest != input.portfolio.audit.candidate_set_digest
        || input.portfolio.receipt.interaction_digest != input.portfolio.audit.interaction_digest
        || input.portfolio.audit.omitted_candidate_count != 0
    {
        return Err(PolicyError::IntegrityMismatch("portfolio audit binding"));
    }
    if input.now_unix_ms >= input.portfolio.receipt.valid_until_unix_ms {
        return Err(PolicyError::PortfolioExpired);
    }
    if input.state_digest != input.portfolio.audit.state_digest {
        return Err(PolicyError::IntegrityMismatch("exercise state"));
    }
    if input.registry_digest != input.portfolio.audit.registry_digest
        || input.registry_snapshot_digest != input.portfolio.audit.registry_snapshot_digest
    {
        return Err(PolicyError::IntegrityMismatch("exercise registry"));
    }
    if input.model_tuple_digest != input.portfolio.audit.model_tuple_digest {
        return Err(PolicyError::IntegrityMismatch("exercise model tuple"));
    }
    let decision = if input.portfolio.receipt.factor_ids.is_empty() {
        PromptExerciseDispositionV1::Abstain
    } else if input.exercise_now_value > input.wait_value {
        PromptExerciseDispositionV1::Exercise
    } else {
        PromptExerciseDispositionV1::Wait
    };
    Ok(PromptExerciseDecisionV1 {
        factor_or_portfolio_id: input.portfolio.receipt.portfolio_id,
        decision_boundary: input.decision_boundary,
        exercise_now_value_q32: input.exercise_now_value.raw(),
        wait_value_q32: input.wait_value.raw(),
        decision,
        policy_digest: input.policy_digest,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PolicyError {
    CandidateLimitExceeded,
    InteractionLimitExceeded,
    ConstraintLimitExceeded,
    SelectionLimitExceeded,
    BudgetLimitExceeded,
    CandidateSetIncomplete(u32),
    DuplicateCandidate(String),
    DuplicateRealization(String),
    DuplicatePricing(String),
    DuplicateInteraction(String, String),
    DuplicateConstraint(String, String, String),
    UnknownInteractionEndpoint(String),
    UnknownConstraintEndpoint(String),
    InvalidInteractionEndpoints,
    InvalidConstraintEndpoints,
    RequiresCycle(String),
    UnsatisfiableRequirementConflict(String),
    EmptyDigest(&'static str),
    ZeroTokenCost(String),
    InvalidPricing(String),
    IntegrityMismatch(&'static str),
    PortfolioExpired,
    InvalidValidityWindow,
    Arithmetic,
}

impl fmt::Display for PolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PolicyError {}

struct Node<'a> {
    pricing: &'a PromptPricingReceiptV1,
    audit: &'a PromptPricingAuditV1,
}

struct InteractionIndex {
    values: BTreeMap<(StableId, StableId), FixedQ32>,
    policy: MissingInteractionPolicyV1,
    digest: Digest32,
}

impl InteractionIndex {
    fn build(
        values: &[PromptPairInteractionV1],
        policy: MissingInteractionPolicyV1,
        known: &[StableId],
    ) -> Result<Self, PolicyError> {
        if values.len() > MAX_POLICY_INTERACTIONS {
            return Err(PolicyError::InteractionLimitExceeded);
        }
        if let MissingInteractionPolicyV1::SupportedZero(support) = policy {
            ensure_digest("zero interaction support", support)?;
        }
        let known = known.iter().cloned().collect::<BTreeSet<_>>();
        let mut map = BTreeMap::new();
        let mut canonical = values.to_vec();
        canonical.sort_by(|left, right| pair_key(left).cmp(&pair_key(right)));
        for value in &canonical {
            if value.left_factor_id == value.right_factor_id {
                return Err(PolicyError::InvalidInteractionEndpoints);
            }
            if !known.contains(&value.left_factor_id) {
                return Err(PolicyError::UnknownInteractionEndpoint(
                    value.left_factor_id.to_string(),
                ));
            }
            if !known.contains(&value.right_factor_id) {
                return Err(PolicyError::UnknownInteractionEndpoint(
                    value.right_factor_id.to_string(),
                ));
            }
            ensure_digest("interaction support", value.support_digest)?;
            let key = ordered_pair(&value.left_factor_id, &value.right_factor_id);
            if map.insert(key.clone(), value.marginal_utility).is_some() {
                return Err(PolicyError::DuplicateInteraction(
                    key.0.to_string(),
                    key.1.to_string(),
                ));
            }
        }
        let digest = digest_interactions(&canonical, policy);
        Ok(Self {
            values: map,
            policy,
            digest,
        })
    }

    fn between(&self, left: &StableId, right: &StableId) -> Option<FixedQ32> {
        self.values
            .get(&ordered_pair(left, right))
            .copied()
            .or_else(|| match self.policy {
                MissingInteractionPolicyV1::RejectUnknown => None,
                MissingInteractionPolicyV1::SupportedZero(_) => Some(FixedQ32::ZERO),
            })
    }
}

struct ConstraintIndex {
    requires: BTreeMap<StableId, Vec<StableId>>,
    conflicts: BTreeSet<(StableId, StableId)>,
    known: BTreeSet<StableId>,
    digest: Digest32,
}

impl ConstraintIndex {
    fn build(values: &[PromptHardConstraintV1], known: &[StableId]) -> Result<Self, PolicyError> {
        if values.len() > MAX_POLICY_CONSTRAINTS {
            return Err(PolicyError::ConstraintLimitExceeded);
        }
        let known = known.iter().cloned().collect::<BTreeSet<_>>();
        let mut requires = BTreeMap::<StableId, Vec<StableId>>::new();
        let mut conflicts = BTreeSet::new();
        let mut seen = BTreeSet::new();
        let mut canonical = values.to_vec();
        canonical.sort_by(|left, right| constraint_key(left).cmp(&constraint_key(right)));
        for value in &canonical {
            match value {
                PromptHardConstraintV1::Conflict {
                    left_factor_id,
                    right_factor_id,
                    support_digest,
                } => {
                    validate_endpoints(left_factor_id, right_factor_id, &known)?;
                    ensure_digest("constraint support", *support_digest)?;
                    let pair = ordered_pair(left_factor_id, right_factor_id);
                    let key = (0_u8, pair.0.clone(), pair.1.clone());
                    if !seen.insert(key) {
                        return Err(PolicyError::DuplicateConstraint(
                            "conflict".to_string(),
                            pair.0.to_string(),
                            pair.1.to_string(),
                        ));
                    }
                    conflicts.insert(pair);
                }
                PromptHardConstraintV1::Requires {
                    factor_id,
                    prerequisite_factor_id,
                    support_digest,
                } => {
                    validate_endpoints(factor_id, prerequisite_factor_id, &known)?;
                    ensure_digest("constraint support", *support_digest)?;
                    let key = (1_u8, factor_id.clone(), prerequisite_factor_id.clone());
                    if !seen.insert(key) {
                        return Err(PolicyError::DuplicateConstraint(
                            "requires".to_string(),
                            factor_id.to_string(),
                            prerequisite_factor_id.to_string(),
                        ));
                    }
                    requires
                        .entry(factor_id.clone())
                        .or_default()
                        .push(prerequisite_factor_id.clone());
                }
            }
        }
        for values in requires.values_mut() {
            values.sort();
            values.dedup();
        }
        Ok(Self {
            requires,
            conflicts,
            known,
            digest: digest_constraints(&canonical),
        })
    }

    fn closure(&self, root: &StableId) -> Result<Vec<StableId>, PolicyError> {
        let mut visiting = BTreeSet::new();
        let mut visited = BTreeSet::new();
        let mut output = Vec::new();
        self.visit(root, &mut visiting, &mut visited, &mut output)?;
        Ok(output)
    }

    fn visit(
        &self,
        value: &StableId,
        visiting: &mut BTreeSet<StableId>,
        visited: &mut BTreeSet<StableId>,
        output: &mut Vec<StableId>,
    ) -> Result<(), PolicyError> {
        if visited.contains(value) {
            return Ok(());
        }
        if !visiting.insert(value.clone()) {
            return Err(PolicyError::RequiresCycle(value.to_string()));
        }
        if let Some(prerequisites) = self.requires.get(value) {
            for prerequisite in prerequisites {
                self.visit(prerequisite, visiting, visited, output)?;
            }
        }
        visiting.remove(value);
        visited.insert(value.clone());
        output.push(value.clone());
        Ok(())
    }

    fn validate_satisfiable(&self) -> Result<(), PolicyError> {
        for value in &self.known {
            let closure = self.closure(value)?;
            if self
                .conflicts
                .iter()
                .any(|(left, right)| closure.contains(left) && closure.contains(right))
            {
                return Err(PolicyError::UnsatisfiableRequirementConflict(
                    value.to_string(),
                ));
            }
        }
        Ok(())
    }

    fn conflicts_with(&self, selected: &BTreeSet<StableId>, additions: &[StableId]) -> bool {
        let additions = additions.iter().cloned().collect::<BTreeSet<_>>();
        self.conflicts.iter().any(|(left, right)| {
            (selected.contains(left) && additions.contains(right))
                || (selected.contains(right) && additions.contains(left))
                || (additions.contains(left) && additions.contains(right))
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Solution {
    selected: BTreeSet<StableId>,
    total_cost: u64,
    total_gain: FixedQ32,
}

impl Default for Solution {
    fn default() -> Self {
        Self {
            selected: BTreeSet::new(),
            total_cost: 0,
            total_gain: FixedQ32::ZERO,
        }
    }
}

fn validate_selection_input(input: &PortfolioSelectionInputV1) -> Result<(), PolicyError> {
    if input.candidate_set.receipt.candidate_factor_ids.len() > MAX_POLICY_FACTORS {
        return Err(PolicyError::CandidateLimitExceeded);
    }
    if input.maximum_selected_factors == 0
        || input.maximum_selected_factors > MAX_POLICY_SELECTED_FACTORS
    {
        return Err(PolicyError::SelectionLimitExceeded);
    }
    if input.token_budget == 0 || input.token_budget > MAX_POLICY_TOKEN_BUDGET {
        return Err(PolicyError::BudgetLimitExceeded);
    }
    if input.valid_until_unix_ms == 0 {
        return Err(PolicyError::InvalidValidityWindow);
    }
    if !input.candidate_set.audit.complete || input.candidate_set.audit.omitted_count != 0 {
        return Err(PolicyError::CandidateSetIncomplete(
            input.candidate_set.audit.omitted_count,
        ));
    }
    if input.pricing.candidate_set_digest != input.candidate_set.receipt.digest() {
        return Err(PolicyError::IntegrityMismatch("pricing candidate set"));
    }
    if input.pricing.pricing_digest
        != digest_pricing(
            input.pricing.candidate_set_digest,
            &input.pricing.receipts,
            &input.pricing.audits,
        )
    {
        return Err(PolicyError::IntegrityMismatch("pricing digest"));
    }
    Ok(())
}

fn build_nodes<'a>(
    input: &'a PortfolioSelectionInputV1,
) -> Result<BTreeMap<StableId, Node<'a>>, PolicyError> {
    let audits = input
        .pricing
        .audits
        .iter()
        .map(|value| (value.factor_id.clone(), value))
        .collect::<BTreeMap<_, _>>();
    let known = input
        .candidate_set
        .receipt
        .candidate_factor_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut output = BTreeMap::new();
    for pricing in &input.pricing.receipts {
        if !known.contains(&pricing.factor_id) {
            return Err(PolicyError::IntegrityMismatch("pricing factor"));
        }
        let Some(audit) = audits.get(&pricing.factor_id).copied() else {
            return Err(PolicyError::IntegrityMismatch("pricing audit"));
        };
        if audit.disposition != PricingDispositionV1::Priced {
            return Err(PolicyError::IntegrityMismatch("pricing disposition"));
        }
        if output
            .insert(pricing.factor_id.clone(), Node { pricing, audit })
            .is_some()
        {
            return Err(PolicyError::DuplicatePricing(pricing.factor_id.to_string()));
        }
    }
    Ok(output)
}

fn greedy_complete(
    mut solution: Solution,
    forbidden: Option<&StableId>,
    nodes: &BTreeMap<StableId, Node<'_>>,
    interactions: &InteractionIndex,
    constraints: &ConstraintIndex,
    token_budget: u64,
    maximum_selected: usize,
) -> Result<Solution, PolicyError> {
    loop {
        let mut best: Option<(StableId, Vec<StableId>, u64, FixedQ32)> = None;
        for factor_id in &constraints.known {
            if solution.selected.contains(factor_id)
                || forbidden.is_some_and(|value| value == factor_id)
                || !nodes.contains_key(factor_id)
            {
                continue;
            }
            let closure = constraints.closure(factor_id)?;
            if forbidden.is_some_and(|value| closure.contains(value)) {
                continue;
            }
            let additions = closure
                .into_iter()
                .filter(|value| !solution.selected.contains(value))
                .collect::<Vec<_>>();
            let Some((cost, gain)) = evaluate_additions(
                &solution,
                &additions,
                nodes,
                interactions,
                constraints,
                token_budget,
                maximum_selected,
            )?
            else {
                continue;
            };
            if gain <= FixedQ32::ZERO {
                continue;
            }
            let better = best
                .as_ref()
                .is_none_or(|(current, _, current_cost, current_gain)| {
                    gain > *current_gain
                        || (gain == *current_gain
                            && (cost < *current_cost
                                || (cost == *current_cost && factor_id < current)))
                });
            if better {
                best = Some((factor_id.clone(), additions, cost, gain));
            }
        }
        let Some((_, additions, cost, gain)) = best else {
            break;
        };
        solution.total_cost = solution
            .total_cost
            .checked_add(cost)
            .ok_or(PolicyError::Arithmetic)?;
        solution.total_gain = solution
            .total_gain
            .checked_add(gain)
            .map_err(|_| PolicyError::Arithmetic)?;
        solution.selected.extend(additions);
    }
    Ok(solution)
}

fn evaluate_additions(
    solution: &Solution,
    additions: &[StableId],
    nodes: &BTreeMap<StableId, Node<'_>>,
    interactions: &InteractionIndex,
    constraints: &ConstraintIndex,
    token_budget: u64,
    maximum_selected: usize,
) -> Result<Option<(u64, FixedQ32)>, PolicyError> {
    if additions.is_empty()
        || solution.selected.len().saturating_add(additions.len()) > maximum_selected
        || constraints.conflicts_with(&solution.selected, additions)
    {
        return Ok(None);
    }
    let mut cost = 0_u64;
    let mut gain = FixedQ32::ZERO;
    for (index, factor_id) in additions.iter().enumerate() {
        let Some(node) = nodes.get(factor_id) else {
            return Ok(None);
        };
        cost = cost
            .checked_add(u64::from(node.pricing.token_cost))
            .ok_or(PolicyError::Arithmetic)?;
        gain = gain
            .checked_add(FixedQ32::from_raw(node.pricing.expected_utility_q32))
            .map_err(|_| PolicyError::Arithmetic)?;
        for selected in &solution.selected {
            let Some(value) = interactions.between(factor_id, selected) else {
                return Ok(None);
            };
            gain = gain
                .checked_add(value)
                .map_err(|_| PolicyError::Arithmetic)?;
        }
        for peer in additions.iter().take(index) {
            let Some(value) = interactions.between(factor_id, peer) else {
                return Ok(None);
            };
            gain = gain
                .checked_add(value)
                .map_err(|_| PolicyError::Arithmetic)?;
        }
    }
    if solution.total_cost.saturating_add(cost) > token_budget {
        return Ok(None);
    }
    Ok(Some((cost, gain)))
}

fn better_solution(candidate: &Solution, current: &Solution) -> bool {
    candidate.total_gain > current.total_gain
        || (candidate.total_gain == current.total_gain
            && (candidate.total_cost < current.total_cost
                || (candidate.total_cost == current.total_cost
                    && candidate
                        .selected
                        .iter()
                        .cmp(current.selected.iter())
                        .is_lt())))
}

fn audit_candidates(
    receipt: &PromptPortfolioReceiptV1,
    nodes: &BTreeMap<StableId, Node<'_>>,
    interactions: &InteractionIndex,
    constraints: &ConstraintIndex,
    token_budget: u64,
    maximum_selected: usize,
) -> Result<Vec<PortfolioCandidateAuditV1>, PolicyError> {
    let selected = receipt.factor_ids.iter().cloned().collect::<BTreeSet<_>>();
    let current = Solution {
        selected: selected.clone(),
        total_cost: u64::from(receipt.total_token_upper_bound),
        total_gain: FixedQ32::from_raw(receipt.expected_utility_q32),
    };
    let mut output = Vec::new();
    for factor_id in &constraints.known {
        let Some(node) = nodes.get(factor_id) else {
            output.push(PortfolioCandidateAuditV1 {
                factor_id: factor_id.clone(),
                disposition: PortfolioCandidateDispositionV1::UnavailablePricing,
                pricing_digest: None,
            });
            continue;
        };
        if selected.contains(factor_id) {
            output.push(PortfolioCandidateAuditV1 {
                factor_id: factor_id.clone(),
                disposition: PortfolioCandidateDispositionV1::Selected,
                pricing_digest: Some(node.pricing.digest()),
            });
            continue;
        }
        let additions = constraints
            .closure(factor_id)?
            .into_iter()
            .filter(|value| !selected.contains(value))
            .collect::<Vec<_>>();
        let disposition = if selected.len().saturating_add(additions.len()) > maximum_selected {
            PortfolioCandidateDispositionV1::SelectionLimit
        } else if constraints.conflicts_with(&selected, &additions) {
            PortfolioCandidateDispositionV1::Conflict
        } else if additions.iter().any(|value| !nodes.contains_key(value)) {
            PortfolioCandidateDispositionV1::UnavailablePricing
        } else if has_missing_interaction(&selected, &additions, interactions) {
            PortfolioCandidateDispositionV1::MissingInteractionEvidence
        } else {
            let cost = additions.iter().try_fold(0_u64, |sum, value| {
                let Some(node) = nodes.get(value) else {
                    return Err(PolicyError::Arithmetic);
                };
                sum.checked_add(u64::from(node.pricing.token_cost))
                    .ok_or(PolicyError::Arithmetic)
            })?;
            if current.total_cost.saturating_add(cost) > token_budget {
                PortfolioCandidateDispositionV1::OverBudget
            } else {
                match evaluate_additions(
                    &current,
                    &additions,
                    nodes,
                    interactions,
                    constraints,
                    token_budget,
                    maximum_selected,
                )? {
                    Some((_, gain)) if gain <= FixedQ32::ZERO => {
                        PortfolioCandidateDispositionV1::NonPositiveMarginal
                    }
                    _ => PortfolioCandidateDispositionV1::DominatedByChosenPortfolio,
                }
            }
        };
        output.push(PortfolioCandidateAuditV1 {
            factor_id: factor_id.clone(),
            disposition,
            pricing_digest: Some(node.pricing.digest()),
        });
    }
    Ok(output)
}

fn has_missing_interaction(
    selected: &BTreeSet<StableId>,
    additions: &[StableId],
    interactions: &InteractionIndex,
) -> bool {
    for addition in additions {
        for existing in selected {
            if interactions.between(addition, existing).is_none() {
                return true;
            }
        }
    }
    for (index, addition) in additions.iter().enumerate() {
        for peer in additions.iter().take(index) {
            if interactions.between(addition, peer).is_none() {
                return true;
            }
        }
    }
    false
}

fn eligible_bindings<'a>(
    snapshot: &'a PromptRegistrySnapshotInputV1,
    now_unix_ms: u64,
) -> BTreeMap<StableId, &'a RegisteredPromptCandidateV1> {
    let mut output = BTreeMap::new();
    for value in &snapshot.candidates {
        if !value.admitted
            || !value.legal
            || value
                .valid_until_unix_ms
                .is_some_and(|expiry| now_unix_ms >= expiry)
        {
            continue;
        }
        output
            .entry(value.factor_id.clone())
            .and_modify(|current: &mut &RegisteredPromptCandidateV1| {
                if value.token_cost_upper_bound < current.token_cost_upper_bound
                    || (value.token_cost_upper_bound == current.token_cost_upper_bound
                        && value.realization_id < current.realization_id)
                {
                    *current = value;
                }
            })
            .or_insert(value);
    }
    output
}

fn unique_causal(
    values: &[CausalUtilityEstimateV1],
) -> Result<BTreeMap<StableId, &CausalUtilityEstimateV1>, PolicyError> {
    let mut output = BTreeMap::new();
    for value in values {
        if output.insert(value.factor_id.clone(), value).is_some() {
            return Err(PolicyError::DuplicatePricing(value.factor_id.to_string()));
        }
    }
    Ok(output)
}

fn unique_costs(
    values: &[PromptCostEstimateV1],
) -> Result<BTreeMap<StableId, &PromptCostEstimateV1>, PolicyError> {
    let mut output = BTreeMap::new();
    for value in values {
        if output.insert(value.factor_id.clone(), value).is_some() {
            return Err(PolicyError::DuplicatePricing(value.factor_id.to_string()));
        }
    }
    Ok(output)
}

fn subtract_costs(base: FixedQ32, costs: &[FixedQ32]) -> Result<FixedQ32, PolicyError> {
    let mut raw = i128::from(base.raw());
    for value in costs {
        raw = raw
            .checked_sub(i128::from(value.raw()))
            .ok_or(PolicyError::Arithmetic)?;
    }
    Ok(FixedQ32::from_raw(
        i64::try_from(raw).map_err(|_| PolicyError::Arithmetic)?,
    ))
}

fn digest_bindings<'a>(values: impl Iterator<Item = &'a RegisteredPromptCandidateV1>) -> Digest32 {
    let mut values = values.collect::<Vec<_>>();
    values.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));
    let mut bytes = b"hepta.prompt-optimizer.bindings.v1".to_vec();
    for value in values {
        push_id(&mut bytes, &value.factor_id);
        push_id(&mut bytes, &value.realization_id);
        push_digest(&mut bytes, value.model_tuple_digest);
        push_digest(&mut bytes, value.support_digest);
        push_u64(&mut bytes, u64::from(value.token_cost_upper_bound));
    }
    Digest32::of_bytes(&bytes)
}

fn digest_pricing(
    candidate_set_digest: Digest32,
    receipts: &[PromptPricingReceiptV1],
    audits: &[PromptPricingAuditV1],
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing.v1".to_vec();
    push_digest(&mut bytes, candidate_set_digest);
    for value in receipts {
        push_digest(&mut bytes, value.digest());
    }
    for value in audits {
        push_id(&mut bytes, &value.factor_id);
        push_id(&mut bytes, &value.realization_id);
        bytes.push(match value.disposition {
            PricingDispositionV1::Priced => 0,
            PricingDispositionV1::MissingCausalEstimate => 1,
            PricingDispositionV1::MissingCostEstimate => 2,
            PricingDispositionV1::InvalidCausalSupport => 3,
            PricingDispositionV1::InvalidCostSupport => 4,
        });
        push_digest(&mut bytes, value.model_tuple_digest);
        push_digest(&mut bytes, value.realization_support_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_interactions(
    values: &[PromptPairInteractionV1],
    policy: MissingInteractionPolicyV1,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.interactions.v1".to_vec();
    match policy {
        MissingInteractionPolicyV1::RejectUnknown => bytes.push(0),
        MissingInteractionPolicyV1::SupportedZero(support) => {
            bytes.push(1);
            push_digest(&mut bytes, support);
        }
    }
    for value in values {
        let pair = ordered_pair(&value.left_factor_id, &value.right_factor_id);
        push_id(&mut bytes, &pair.0);
        push_id(&mut bytes, &pair.1);
        bytes.extend_from_slice(&value.marginal_utility.raw().to_be_bytes());
        push_digest(&mut bytes, value.support_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_constraints(values: &[PromptHardConstraintV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.constraints.v1".to_vec();
    for value in values {
        match value {
            PromptHardConstraintV1::Conflict {
                left_factor_id,
                right_factor_id,
                support_digest,
            } => {
                bytes.push(0);
                let pair = ordered_pair(left_factor_id, right_factor_id);
                push_id(&mut bytes, &pair.0);
                push_id(&mut bytes, &pair.1);
                push_digest(&mut bytes, *support_digest);
            }
            PromptHardConstraintV1::Requires {
                factor_id,
                prerequisite_factor_id,
                support_digest,
            } => {
                bytes.push(1);
                push_id(&mut bytes, factor_id);
                push_id(&mut bytes, prerequisite_factor_id);
                push_digest(&mut bytes, *support_digest);
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

fn pair_key(value: &PromptPairInteractionV1) -> (StableId, StableId) {
    ordered_pair(&value.left_factor_id, &value.right_factor_id)
}

fn constraint_key(value: &PromptHardConstraintV1) -> (u8, StableId, StableId) {
    match value {
        PromptHardConstraintV1::Conflict {
            left_factor_id,
            right_factor_id,
            ..
        } => {
            let pair = ordered_pair(left_factor_id, right_factor_id);
            (0, pair.0, pair.1)
        }
        PromptHardConstraintV1::Requires {
            factor_id,
            prerequisite_factor_id,
            ..
        } => (1, factor_id.clone(), prerequisite_factor_id.clone()),
    }
}

fn validate_endpoints(
    left: &StableId,
    right: &StableId,
    known: &BTreeSet<StableId>,
) -> Result<(), PolicyError> {
    if left == right {
        return Err(PolicyError::InvalidConstraintEndpoints);
    }
    if !known.contains(left) {
        return Err(PolicyError::UnknownConstraintEndpoint(left.to_string()));
    }
    if !known.contains(right) {
        return Err(PolicyError::UnknownConstraintEndpoint(right.to_string()));
    }
    Ok(())
}

fn ordered_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left <= right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

fn ensure_digest(name: &'static str, value: Digest32) -> Result<(), PolicyError> {
    if value.is_zero() {
        return Err(PolicyError::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "policy_tests.rs"]
mod tests;
