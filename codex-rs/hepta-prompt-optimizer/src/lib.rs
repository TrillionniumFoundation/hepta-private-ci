//! Bounded prompt-intervention portfolio optimizer for shadow evaluation.
//!
//! The optimizer is read-only with respect to registries and objectives. Its
//! receipt is a proposal and grants no activation, dispatch or promotion power.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub mod local_shadow;

const MAX_CANDIDATES: usize = 4_096;
const MAX_SELECTED: usize = 128;
const MAX_BUDGET: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptCandidate {
    pub candidate_id: StableId,
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub admitted: bool,
    pub legal: bool,
    pub expected_gain: FixedQ32,
    pub cost: u64,
    pub registry_digest: Digest32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OptimizationRequest {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub budget: u64,
    pub maximum_selected: usize,
    pub candidates: Vec<PromptCandidate>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CandidateDisposition {
    Selected,
    NotAdmitted,
    Illegal,
    NonPositiveGain,
    OverBudget,
    SelectionLimit,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateDecision {
    pub candidate_id: StableId,
    pub disposition: CandidateDisposition,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPortfolioReceipt {
    pub decision_id: StableId,
    pub selected: Vec<StableId>,
    pub decisions: Vec<CandidateDecision>,
    pub total_cost: u64,
    pub total_expected_gain: FixedQ32,
    pub unspent_budget: u64,
    pub marginal_excluded_gain: FixedQ32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    CandidateLimitExceeded,
    SelectionLimitExceeded,
    BudgetLimitExceeded,
    DuplicateCandidate(String),
    EmptyDigest(&'static str),
    ZeroCost(String),
    RegistrySnapshotMismatch(String),
    Arithmetic,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn optimize(mut request: OptimizationRequest) -> Result<PromptPortfolioReceipt, Error> {
    validate_request(&request)?;
    request.candidates.sort_by(|left, right| {
        right
            .expected_gain
            .cmp(&left.expected_gain)
            .then_with(|| left.cost.cmp(&right.cost))
            .then_with(|| left.candidate_id.cmp(&right.candidate_id))
    });

    let mut seen = BTreeSet::new();
    for candidate in &request.candidates {
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(Error::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.registry_digest != request.registry_snapshot_digest {
            return Err(Error::RegistrySnapshotMismatch(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.support_digest.is_zero() {
            return Err(Error::EmptyDigest("candidate support"));
        }
        if candidate.cost == 0 {
            return Err(Error::ZeroCost(candidate.candidate_id.to_string()));
        }
    }

    let mut selected = Vec::new();
    let mut decisions = Vec::with_capacity(request.candidates.len());
    let mut remaining = request.budget;
    let mut total_gain = FixedQ32::ZERO;
    let mut marginal_excluded_gain = FixedQ32::ZERO;

    for candidate in &request.candidates {
        let disposition = if !candidate.admitted {
            CandidateDisposition::NotAdmitted
        } else if !candidate.legal {
            CandidateDisposition::Illegal
        } else if candidate.expected_gain <= FixedQ32::ZERO {
            CandidateDisposition::NonPositiveGain
        } else if selected.len() >= request.maximum_selected {
            marginal_excluded_gain = marginal_excluded_gain.max(candidate.expected_gain);
            CandidateDisposition::SelectionLimit
        } else if candidate.cost > remaining {
            marginal_excluded_gain = marginal_excluded_gain.max(candidate.expected_gain);
            CandidateDisposition::OverBudget
        } else {
            remaining = remaining
                .checked_sub(candidate.cost)
                .ok_or(Error::Arithmetic)?;
            total_gain = total_gain
                .checked_add(candidate.expected_gain)
                .map_err(|_| Error::Arithmetic)?;
            selected.push(candidate.candidate_id.clone());
            CandidateDisposition::Selected
        };
        decisions.push(CandidateDecision {
            candidate_id: candidate.candidate_id.clone(),
            disposition,
        });
    }

    let total_cost = request
        .budget
        .checked_sub(remaining)
        .ok_or(Error::Arithmetic)?;
    let receipt_digest = digest_receipt(
        &request,
        &selected,
        &decisions,
        total_cost,
        total_gain,
        marginal_excluded_gain,
    );

    Ok(PromptPortfolioReceipt {
        decision_id: request.decision_id,
        selected,
        decisions,
        total_cost,
        total_expected_gain: total_gain,
        unspent_budget: remaining,
        marginal_excluded_gain,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_request(request: &OptimizationRequest) -> Result<(), Error> {
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(Error::CandidateLimitExceeded);
    }
    if request.maximum_selected == 0 || request.maximum_selected > MAX_SELECTED {
        return Err(Error::SelectionLimitExceeded);
    }
    if request.budget > MAX_BUDGET {
        return Err(Error::BudgetLimitExceeded);
    }
    if request.objective_digest.is_zero() {
        return Err(Error::EmptyDigest("objective"));
    }
    if request.registry_snapshot_digest.is_zero() {
        return Err(Error::EmptyDigest("registry snapshot"));
    }
    Ok(())
}

fn digest_receipt(
    request: &OptimizationRequest,
    selected: &[StableId],
    decisions: &[CandidateDecision],
    total_cost: u64,
    total_gain: FixedQ32,
    marginal_excluded_gain: FixedQ32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.prompt-optimizer.portfolio.v1");
    push_id(&mut bytes, &request.decision_id);
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.registry_snapshot_digest.as_array());
    bytes.extend_from_slice(&request.budget.to_be_bytes());
    bytes.extend_from_slice(
        &u64::try_from(request.maximum_selected)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization_id);
        bytes.push(u8::from(candidate.admitted));
        bytes.push(u8::from(candidate.legal));
        bytes.extend_from_slice(&candidate.expected_gain.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.cost.to_be_bytes());
        bytes.extend_from_slice(candidate.registry_digest.as_array());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    for candidate_id in selected {
        push_id(&mut bytes, candidate_id);
    }
    for decision in decisions {
        push_id(&mut bytes, &decision.candidate_id);
        bytes.push(disposition_code(decision.disposition));
    }
    bytes.extend_from_slice(&total_cost.to_be_bytes());
    bytes.extend_from_slice(&total_gain.raw().to_be_bytes());
    bytes.extend_from_slice(&marginal_excluded_gain.raw().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn disposition_code(value: CandidateDisposition) -> u8 {
    match value {
        CandidateDisposition::Selected => 0,
        CandidateDisposition::NotAdmitted => 1,
        CandidateDisposition::Illegal => 2,
        CandidateDisposition::NonPositiveGain => 3,
        CandidateDisposition::OverBudget => 4,
        CandidateDisposition::SelectionLimit => 5,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
