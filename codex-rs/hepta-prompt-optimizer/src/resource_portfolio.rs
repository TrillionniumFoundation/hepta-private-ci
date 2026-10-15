//! Shadow-only NDU/Merton resource portfolio adapter.
//!
//! This module consumes already priced prompt candidates and a separately
//! bound action-risk profile. It performs a deterministic long-only selection
//! with resource limits and pairwise covariance penalties. It does not widen
//! the registered Prompt V1 receipts, authenticate an evaluator, dispatch a
//! model, or grant activation authority.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::PromptPricingReceiptV1;

pub const MAX_ACTIONS_V1: usize = 32;
pub const MAX_COVARIANCE_EDGES_V1: usize = (MAX_ACTIONS_V1 * (MAX_ACTIONS_V1 - 1)) / 2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CovarianceMissingPolicyV1 {
    RejectMissing,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResourceCostBasisV1 {
    /// Prompt pricing has already charged registered token/latency costs. The
    /// resource vector is used for incremental budget admission only.
    IncrementalOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ActionRiskPolicyV1 {
    pub risk_aversion_q32: FixedQ32,
    pub downside_weight_q32: FixedQ32,
    pub max_abs_covariance_q32: FixedQ32,
    pub missing_policy: CovarianceMissingPolicyV1,
    pub cost_basis: ResourceCostBasisV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionRiskEntryV1 {
    pub action_id: StableId,
    pub variance_q32: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionCovarianceEntryV1 {
    pub left_action_id: StableId,
    pub right_action_id: StableId,
    pub covariance_q32: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionRiskProfileV1 {
    pub profile_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub pricing_batch_digest: Digest32,
    pub baseline_id: StableId,
    pub valid_until_unix_ms: u64,
    pub policy: ActionRiskPolicyV1,
    pub entries: Vec<ActionRiskEntryV1>,
    pub covariance: Vec<ActionCovarianceEntryV1>,
    pub source_evidence_digest: Digest32,
    pub profile_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ResourceVectorV1 {
    pub tokens: u64,
    pub latency_micros: u64,
    pub cpu_micros: u64,
    pub gpu_micros: u64,
    pub memory_bytes: u64,
    pub io_bytes: u64,
}

impl ResourceVectorV1 {
    fn checked_add(self, other: Self) -> Result<Self, ResourcePortfolioError> {
        Ok(Self {
            tokens: self.tokens.checked_add(other.tokens).ok_or(ResourcePortfolioError::Arithmetic)?,
            latency_micros: self
                .latency_micros
                .checked_add(other.latency_micros)
                .ok_or(ResourcePortfolioError::Arithmetic)?,
            cpu_micros: self
                .cpu_micros
                .checked_add(other.cpu_micros)
                .ok_or(ResourcePortfolioError::Arithmetic)?,
            gpu_micros: self
                .gpu_micros
                .checked_add(other.gpu_micros)
                .ok_or(ResourcePortfolioError::Arithmetic)?,
            memory_bytes: self
                .memory_bytes
                .checked_add(other.memory_bytes)
                .ok_or(ResourcePortfolioError::Arithmetic)?,
            io_bytes: self
                .io_bytes
                .checked_add(other.io_bytes)
                .ok_or(ResourcePortfolioError::Arithmetic)?,
        })
    }

    fn within(self, limit: Self) -> bool {
        self.tokens <= limit.tokens
            && self.latency_micros <= limit.latency_micros
            && self.cpu_micros <= limit.cpu_micros
            && self.gpu_micros <= limit.gpu_micros
            && self.memory_bytes <= limit.memory_bytes
            && self.io_bytes <= limit.io_bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceBudgetV1 {
    pub budget_id: StableId,
    pub limits: ResourceVectorV1,
    pub maximum_selected: usize,
    pub valid_until_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceActionSpecV1 {
    pub action_id: StableId,
    pub factor_id: StableId,
    pub resources: ResourceVectorV1,
    pub admitted: bool,
    pub legal: bool,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourcePortfolioInputV1 {
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub profile: ActionRiskProfileV1,
    pub pricing_batch_digest: Digest32,
    pub priced_candidates: Vec<PromptPricingReceiptV1>,
    pub actions: Vec<ResourceActionSpecV1>,
    pub budget: ResourceBudgetV1,
    pub now_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResourcePortfolioDispositionV1 {
    NoChange,
    Selected,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourcePortfolioShadowProposalV1 {
    pub profile_digest: Digest32,
    pub budget_id: StableId,
    pub baseline_id: StableId,
    pub selected_action_ids: Vec<StableId>,
    pub aggregate_resources: ResourceVectorV1,
    pub covariance_risk_q32: FixedQ32,
    pub risk_adjusted_utility_q32: FixedQ32,
    pub disposition: ResourcePortfolioDispositionV1,
    pub proposal_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ResourcePortfolioError {
    UnsupportedProfile,
    EmptyDigest(&'static str),
    ProfileDigestMismatch,
    ProfileExpired,
    BudgetExpired,
    ScopeMismatch(&'static str),
    CandidateLimitExceeded,
    SelectionLimitExceeded,
    DuplicateAction(String),
    DuplicateRiskEntry(String),
    DuplicateCovariance(String, String),
    NonCanonicalCovariance,
    MissingRiskEntry(String),
    MissingCovariance(String, String),
    UnknownAction(String),
    UnknownFactor(String),
    PricingBatchMismatch,
    InvalidVariance(String),
    InvalidDownside(String),
    InvalidCovariance(String, String),
    InvalidSupport(&'static str),
    ResourceBudgetExceeded(String),
    Arithmetic,
}

impl fmt::Display for ResourcePortfolioError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ResourcePortfolioError {}

pub fn canonical_action_risk_profile_digest(profile: &ActionRiskProfileV1) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.action-risk-profile.v1\0".to_vec();
    push_id(&mut bytes, &profile.profile_id);
    push_digest(&mut bytes, profile.objective_digest);
    push_digest(&mut bytes, profile.state_digest);
    push_digest(&mut bytes, profile.model_tuple_digest);
    push_digest(&mut bytes, profile.candidate_set_digest);
    push_digest(&mut bytes, profile.pricing_batch_digest);
    push_id(&mut bytes, &profile.baseline_id);
    bytes.extend_from_slice(&profile.valid_until_unix_ms.to_be_bytes());
    bytes.extend_from_slice(&profile.policy.risk_aversion_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.policy.downside_weight_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.policy.max_abs_covariance_q32.raw().to_be_bytes());
    bytes.push(match profile.policy.missing_policy {
        CovarianceMissingPolicyV1::RejectMissing => 0,
    });
    bytes.push(match profile.policy.cost_basis {
        ResourceCostBasisV1::IncrementalOnly => 0,
    });
    for entry in &profile.entries {
        push_id(&mut bytes, &entry.action_id);
        bytes.extend_from_slice(&entry.variance_q32.raw().to_be_bytes());
        push_digest(&mut bytes, entry.support_digest);
    }
    for edge in &profile.covariance {
        push_id(&mut bytes, &edge.left_action_id);
        push_id(&mut bytes, &edge.right_action_id);
        bytes.extend_from_slice(&edge.covariance_q32.raw().to_be_bytes());
        push_digest(&mut bytes, edge.support_digest);
    }
    push_digest(&mut bytes, profile.source_evidence_digest);
    Digest32::of_bytes(&bytes)
}

pub fn validate_action_risk_profile_v1(
    profile: &ActionRiskProfileV1,
    now_unix_ms: u64,
) -> Result<(), ResourcePortfolioError> {
    if profile.valid_until_unix_ms <= now_unix_ms {
        return Err(ResourcePortfolioError::ProfileExpired);
    }
    for (name, digest) in [
        ("objective", profile.objective_digest),
        ("state", profile.state_digest),
        ("model tuple", profile.model_tuple_digest),
        ("candidate set", profile.candidate_set_digest),
        ("pricing batch", profile.pricing_batch_digest),
        ("source evidence", profile.source_evidence_digest),
        ("profile", profile.profile_digest),
    ] {
        if digest.is_zero() {
            return Err(ResourcePortfolioError::EmptyDigest(name));
        }
    }
    if profile.policy.risk_aversion_q32 < FixedQ32::ZERO
        || profile.policy.downside_weight_q32 < FixedQ32::ZERO
        || profile.policy.max_abs_covariance_q32 < FixedQ32::ZERO
    {
        return Err(ResourcePortfolioError::UnsupportedProfile);
    }
    if profile.entries.is_empty() || profile.entries.len() > MAX_ACTIONS_V1 {
        return Err(ResourcePortfolioError::CandidateLimitExceeded);
    }
    if profile.covariance.len() > MAX_COVARIANCE_EDGES_V1 {
        return Err(ResourcePortfolioError::CandidateLimitExceeded);
    }
    let mut previous: Option<&StableId> = None;
    let mut action_ids = BTreeSet::new();
    for entry in &profile.entries {
        if previous.is_some_and(|prior| prior >= &entry.action_id) {
            return Err(ResourcePortfolioError::DuplicateRiskEntry(
                entry.action_id.to_string(),
            ));
        }
        previous = Some(&entry.action_id);
        if !action_ids.insert(entry.action_id.clone()) {
            return Err(ResourcePortfolioError::DuplicateRiskEntry(
                entry.action_id.to_string(),
            ));
        }
        if entry.variance_q32 < FixedQ32::ZERO {
            return Err(ResourcePortfolioError::InvalidVariance(
                entry.action_id.to_string(),
            ));
        }
        if entry.support_digest.is_zero() {
            return Err(ResourcePortfolioError::InvalidSupport("risk entry"));
        }
    }
    let mut previous_edge: Option<(&StableId, &StableId)> = None;
    for edge in &profile.covariance {
        if edge.left_action_id >= edge.right_action_id {
            return Err(ResourcePortfolioError::NonCanonicalCovariance);
        }
        if !action_ids.contains(&edge.left_action_id) || !action_ids.contains(&edge.right_action_id) {
            return Err(ResourcePortfolioError::UnknownAction(
                format!("{}:{}", edge.left_action_id, edge.right_action_id),
            ));
        }
        let pair = (&edge.left_action_id, &edge.right_action_id);
        if previous_edge.is_some_and(|prior| prior >= pair) {
            return Err(ResourcePortfolioError::DuplicateCovariance(
                edge.left_action_id.to_string(),
                edge.right_action_id.to_string(),
            ));
        }
        previous_edge = Some(pair);
        if edge.covariance_q32.raw().unsigned_abs()
            > profile.policy.max_abs_covariance_q32.raw().unsigned_abs()
        {
            return Err(ResourcePortfolioError::InvalidCovariance(
                edge.left_action_id.to_string(),
                edge.right_action_id.to_string(),
            ));
        }
        if edge.support_digest.is_zero() {
            return Err(ResourcePortfolioError::InvalidSupport("covariance"));
        }
    }
    if canonical_action_risk_profile_digest(profile) != profile.profile_digest {
        return Err(ResourcePortfolioError::ProfileDigestMismatch);
    }
    Ok(())
}

pub fn select_resource_portfolio_shadow_v1(
    input: ResourcePortfolioInputV1,
) -> Result<ResourcePortfolioShadowProposalV1, ResourcePortfolioError> {
    validate_action_risk_profile_v1(&input.profile, input.now_unix_ms)?;
    if input.budget.valid_until_unix_ms <= input.now_unix_ms {
        return Err(ResourcePortfolioError::BudgetExpired);
    }
    if input.budget.maximum_selected == 0 || input.budget.maximum_selected > MAX_ACTIONS_V1 {
        return Err(ResourcePortfolioError::SelectionLimitExceeded);
    }
    if input.objective_digest != input.profile.objective_digest {
        return Err(ResourcePortfolioError::ScopeMismatch("objective"));
    }
    if input.state_digest != input.profile.state_digest {
        return Err(ResourcePortfolioError::ScopeMismatch("state"));
    }
    if input.model_tuple_digest != input.profile.model_tuple_digest {
        return Err(ResourcePortfolioError::ScopeMismatch("model tuple"));
    }
    if input.candidate_set_digest != input.profile.candidate_set_digest
        || input.pricing_batch_digest != input.profile.pricing_batch_digest
    {
        return Err(ResourcePortfolioError::PricingBatchMismatch);
    }
    if input.actions.is_empty() || input.actions.len() > MAX_ACTIONS_V1 {
        return Err(ResourcePortfolioError::CandidateLimitExceeded);
    }

    let mut actions = BTreeMap::new();
    for action in input.actions {
        if action.support_digest.is_zero() {
            return Err(ResourcePortfolioError::InvalidSupport("action"));
        }
        let action_id = action.action_id.clone();
        if actions.insert(action_id.clone(), action).is_some() {
            return Err(ResourcePortfolioError::DuplicateAction(action_id.to_string()));
        }
    }
    let mut prices = BTreeMap::new();
    for price in input.priced_candidates {
        if price.state_digest != input.state_digest {
            return Err(ResourcePortfolioError::ScopeMismatch("pricing state"));
        }
        if prices.insert(price.factor_id.clone(), price).is_some() {
            return Err(ResourcePortfolioError::UnknownFactor(
                "duplicate pricing factor".to_string(),
            ));
        }
    }
    if prices.len() != actions.len()
        || actions.values().any(|action| !prices.contains_key(&action.factor_id))
    {
        return Err(ResourcePortfolioError::PricingBatchMismatch);
    }

    let variances: BTreeMap<StableId, FixedQ32> = input
        .profile
        .entries
        .iter()
        .map(|entry| (entry.action_id.clone(), entry.variance_q32))
        .collect();
    let covariance: BTreeMap<(StableId, StableId), FixedQ32> = input
        .profile
        .covariance
        .iter()
        .map(|edge| {
            (
                (edge.left_action_id.clone(), edge.right_action_id.clone()),
                edge.covariance_q32,
            )
        })
        .collect();
    for action in actions.values() {
        if !variances.contains_key(&action.action_id) {
            return Err(ResourcePortfolioError::MissingRiskEntry(
                action.action_id.to_string(),
            ));
        }
        if !prices.contains_key(&action.factor_id) {
            return Err(ResourcePortfolioError::UnknownFactor(
                action.factor_id.to_string(),
            ));
        }
    }
    if input.profile.policy.missing_policy == CovarianceMissingPolicyV1::RejectMissing {
        for left in actions.keys() {
            for right in actions.keys() {
                if left >= right {
                    continue;
                }
                if !covariance.contains_key(&(left.clone(), right.clone())) {
                    return Err(ResourcePortfolioError::MissingCovariance(
                        left.to_string(),
                        right.to_string(),
                    ));
                }
            }
        }
    }

    let risk_aversion = input.profile.policy.risk_aversion_q32;
    let downside_weight = input.profile.policy.downside_weight_q32;
    let mut ranked = Vec::with_capacity(actions.len());
    for action in actions.values() {
        let price = prices
            .get(&action.factor_id)
            .ok_or_else(|| ResourcePortfolioError::UnknownFactor(action.factor_id.to_string()))?;
        let variance = *variances
            .get(&action.action_id)
            .ok_or_else(|| ResourcePortfolioError::MissingRiskEntry(action.action_id.to_string()))?;
        let downside = downside_weight
            .checked_mul(price.downside_q32)
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        let risk = risk_aversion
            .checked_mul(variance)
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        let net = price
            .expected_utility_q32
            .checked_sub(downside)
            .and_then(|value| value.checked_sub(risk))
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        ranked.push((action.action_id.clone(), net));
    }
    ranked.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));

    let mut selected = Vec::new();
    let mut aggregate = ResourceVectorV1::default();
    let mut variance_risk = FixedQ32::ZERO;
    let mut utility = FixedQ32::ZERO;
    for (action_id, base_net) in ranked {
        let action = actions
            .get(&action_id)
            .ok_or_else(|| ResourcePortfolioError::UnknownAction(action_id.to_string()))?;
        if !action.admitted || !action.legal || base_net <= FixedQ32::ZERO {
            continue;
        }
        if selected.len() >= input.budget.maximum_selected {
            break;
        }
        let next_resources = aggregate.checked_add(action.resources)?;
        if !next_resources.within(input.budget.limits) {
            continue;
        }
        let mut pair_covariance = FixedQ32::ZERO;
        for selected_id in &selected {
            let pair = if selected_id < &action_id {
                (selected_id.clone(), action_id.clone())
            } else {
                (action_id.clone(), selected_id.clone())
            };
            let pair_value = covariance
                .get(&pair)
                .copied()
                .ok_or_else(|| ResourcePortfolioError::MissingCovariance(
                    pair.0.to_string(),
                    pair.1.to_string(),
                ))?;
            pair_covariance = pair_covariance
                .checked_add(pair_value)
                .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        }
        let pair_penalty = risk_aversion
            .checked_mul(pair_covariance)
            .and_then(|value| value.checked_mul(FixedQ32::from_raw(2)))
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        let incremental = base_net
            .checked_sub(pair_penalty)
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        if incremental <= FixedQ32::ZERO {
            continue;
        }
        aggregate = next_resources;
        let covariance_increment = pair_covariance
            .checked_mul(FixedQ32::from_raw(2))
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        variance_risk = variance_risk
            .checked_add(*variances.get(&action_id).ok_or_else(|| {
                ResourcePortfolioError::MissingRiskEntry(action_id.to_string())
            })?)
            .and_then(|value| value.checked_add(covariance_increment))
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        utility = utility
            .checked_add(incremental)
            .map_err(|_| ResourcePortfolioError::Arithmetic)?;
        selected.push(action_id);
    }

    let disposition = if selected.is_empty() {
        ResourcePortfolioDispositionV1::NoChange
    } else {
        ResourcePortfolioDispositionV1::Selected
    };
    let proposal_digest = digest_proposal(
        &input.profile,
        &input.budget,
        &selected,
        aggregate,
        variance_risk,
        utility,
        disposition,
    );
    Ok(ResourcePortfolioShadowProposalV1 {
        profile_digest: input.profile.profile_digest,
        budget_id: input.budget.budget_id,
        baseline_id: input.profile.baseline_id,
        selected_action_ids: selected,
        aggregate_resources: aggregate,
        covariance_risk_q32: variance_risk,
        risk_adjusted_utility_q32: utility,
        disposition,
        proposal_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn digest_proposal(
    profile: &ActionRiskProfileV1,
    budget: &ResourceBudgetV1,
    selected: &[StableId],
    resources: ResourceVectorV1,
    covariance_risk: FixedQ32,
    utility: FixedQ32,
    disposition: ResourcePortfolioDispositionV1,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.resource-portfolio-shadow.v1\0".to_vec();
    push_digest(&mut bytes, profile.profile_digest);
    push_id(&mut bytes, &budget.budget_id);
    for id in selected {
        push_id(&mut bytes, id);
    }
    for value in [
        resources.tokens,
        resources.latency_micros,
        resources.cpu_micros,
        resources.gpu_micros,
        resources.memory_bytes,
        resources.io_bytes,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&covariance_risk.raw().to_be_bytes());
    bytes.extend_from_slice(&utility.raw().to_be_bytes());
    bytes.push(match disposition {
        ResourcePortfolioDispositionV1::NoChange => 0,
        ResourcePortfolioDispositionV1::Selected => 1,
    });
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|_| panic!("invalid id"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn profile() -> ActionRiskProfileV1 {
        let mut value = ActionRiskProfileV1 {
            profile_id: id("risk-profile"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            model_tuple_digest: digest("model"),
            candidate_set_digest: digest("candidates"),
            pricing_batch_digest: digest("pricing"),
            baseline_id: id("no-change"),
            valid_until_unix_ms: 100,
            policy: ActionRiskPolicyV1 {
                risk_aversion_q32: FixedQ32::from_raw(1_i64 << 32),
                downside_weight_q32: FixedQ32::from_raw(1_i64 << 32),
                max_abs_covariance_q32: FixedQ32::from_raw(10_i64 << 32),
                missing_policy: CovarianceMissingPolicyV1::RejectMissing,
                cost_basis: ResourceCostBasisV1::IncrementalOnly,
            },
            entries: vec![
                ActionRiskEntryV1 {
                    action_id: id("action:a"),
                    variance_q32: FixedQ32::from_raw(1_i64 << 30),
                    support_digest: digest("risk:a"),
                },
                ActionRiskEntryV1 {
                    action_id: id("action:b"),
                    variance_q32: FixedQ32::from_raw(1_i64 << 30),
                    support_digest: digest("risk:b"),
                },
            ],
            covariance: vec![ActionCovarianceEntryV1 {
                left_action_id: id("action:a"),
                right_action_id: id("action:b"),
                covariance_q32: FixedQ32::from_raw(1_i64 << 29),
                support_digest: digest("cov:a:b"),
            }],
            source_evidence_digest: digest("evidence"),
            profile_digest: Digest32::ZERO,
        };
        value.profile_digest = canonical_action_risk_profile_digest(&value);
        value
    }

    fn input() -> ResourcePortfolioInputV1 {
        ResourcePortfolioInputV1 {
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            model_tuple_digest: digest("model"),
            candidate_set_digest: digest("candidates"),
            pricing_batch_digest: digest("pricing"),
            profile: profile(),
            priced_candidates: vec![
                PromptPricingReceiptV1 {
                    factor_id: id("factor:a"),
                    state_digest: digest("state"),
                    expected_utility_q32: FixedQ32::from_raw(8_i64 << 32),
                    downside_q32: FixedQ32::ZERO,
                    token_cost: 4,
                    latency_cost_micros: 1,
                    interference_ppm: 0,
                    confidence_interval: crate::PromptConfidenceIntervalV1 {
                        lower_q32: FixedQ32::ZERO,
                        upper_q32: FixedQ32::from_raw(8_i64 << 32),
                        confidence_ppm: 900_000,
                        support_digest: digest("ci:a"),
                        scope_digest: digest("scope"),
                    },
                },
                PromptPricingReceiptV1 {
                    factor_id: id("factor:b"),
                    state_digest: digest("state"),
                    expected_utility_q32: FixedQ32::from_raw(7_i64 << 32),
                    downside_q32: FixedQ32::ZERO,
                    token_cost: 4,
                    latency_cost_micros: 1,
                    interference_ppm: 0,
                    confidence_interval: crate::PromptConfidenceIntervalV1 {
                        lower_q32: FixedQ32::ZERO,
                        upper_q32: FixedQ32::from_raw(7_i64 << 32),
                        confidence_ppm: 900_000,
                        support_digest: digest("ci:b"),
                        scope_digest: digest("scope"),
                    },
                },
            ],
            actions: vec![
                ResourceActionSpecV1 {
                    action_id: id("action:a"),
                    factor_id: id("factor:a"),
                    resources: ResourceVectorV1 {
                        tokens: 4,
                        ..ResourceVectorV1::default()
                    },
                    admitted: true,
                    legal: true,
                    support_digest: digest("action:a"),
                },
                ResourceActionSpecV1 {
                    action_id: id("action:b"),
                    factor_id: id("factor:b"),
                    resources: ResourceVectorV1 {
                        tokens: 4,
                        ..ResourceVectorV1::default()
                    },
                    admitted: true,
                    legal: true,
                    support_digest: digest("action:b"),
                },
            ],
            budget: ResourceBudgetV1 {
                budget_id: id("budget"),
                limits: ResourceVectorV1 {
                    tokens: 4,
                    ..ResourceVectorV1::default()
                },
                maximum_selected: 2,
                valid_until_unix_ms: 100,
            },
            now_unix_ms: 1,
        }
    }

    #[test]
    fn selects_one_action_under_incremental_budget_and_denies_authority() {
        let result = select_resource_portfolio_shadow_v1(input()).unwrap();
        assert_eq!(result.selected_action_ids, vec![id("action:a")]);
        assert_eq!(result.aggregate_resources.tokens, 4);
        assert_eq!(result.disposition, ResourcePortfolioDispositionV1::Selected);
        assert!(!result.authority.grants_any());
    }

    #[test]
    fn positive_covariance_prevents_second_action_when_budget_allows_only_one() {
        let mut request = input();
        request.budget.limits.tokens = 8;
        request.profile.covariance[0].covariance_q32 = FixedQ32::from_raw(8_i64 << 32);
        request.profile.profile_digest = canonical_action_risk_profile_digest(&request.profile);
        let result = select_resource_portfolio_shadow_v1(request).unwrap();
        assert_eq!(result.selected_action_ids, vec![id("action:a")]);
    }

    #[test]
    fn no_change_is_explicit_when_all_candidates_are_non_positive() {
        let mut request = input();
        request.priced_candidates[0].expected_utility_q32 = FixedQ32::ZERO;
        request.priced_candidates[1].expected_utility_q32 = FixedQ32::ZERO;
        let result = select_resource_portfolio_shadow_v1(request).unwrap();
        assert!(result.selected_action_ids.is_empty());
        assert_eq!(result.disposition, ResourcePortfolioDispositionV1::NoChange);
        assert_eq!(result.baseline_id, id("no-change"));
    }

    #[test]
    fn profile_digest_drift_is_rejected() {
        let mut request = input();
        request.profile.policy.risk_aversion_q32 = FixedQ32::ZERO;
        assert_eq!(
            select_resource_portfolio_shadow_v1(request),
            Err(ResourcePortfolioError::ProfileDigestMismatch)
        );
    }

    #[test]
    fn missing_covariance_fails_closed() {
        let mut request = input();
        request.profile.covariance.clear();
        request.profile.profile_digest = canonical_action_risk_profile_digest(&request.profile);
        assert!(matches!(
            select_resource_portfolio_shadow_v1(request),
            Err(ResourcePortfolioError::MissingCovariance(_, _))
        ));
    }
}
