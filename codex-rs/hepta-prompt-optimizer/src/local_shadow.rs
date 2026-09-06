//! Authority-free, bounded prompt-portfolio shadow calculations.
//!
//! This module is an in-process structural calculator, not a wire codec,
//! durable receipt, owner attestation, or candidate-completeness mechanism.
//! All gains, costs, admission flags, relations, and support-reference digests
//! remain supplied by the caller. A successful result therefore describes only
//! the supplied local input. It does not authenticate registry, graph, or
//! ledger owners; establish realization-context compatibility or causal
//! support; authorize selection or activation; or represent the learning-ledger
//! canonical abstain arm.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::PromptCandidate;

#[path = "local_shadow_digest.rs"]
mod digest;
#[path = "local_shadow_validation.rs"]
mod validation;
use digest::ProposalDigestInput;
use digest::digest_candidate_input;
use digest::digest_hard_constraints;
use digest::digest_interactions;
use digest::digest_proposal;
use validation::validate_input_structure;

/// Maximum total local candidates, including the one local baseline.
pub const MAX_TOTAL_CANDIDATES: usize = 128;
/// Maximum factor candidates after reserving one slot for the local baseline.
pub const MAX_FACTOR_CANDIDATES: usize = MAX_TOTAL_CANDIDATES - 1;
/// Maximum factor candidates in one shadow portfolio.
pub const MAX_SELECTED_FACTORS: usize = 16;
/// Maximum caller-supplied pairwise interaction edges.
///
/// A request permitting multi-factor selection is therefore limited to 32
/// factor candidates by the pair-completeness rule (33 would require 528
/// edges). Single-factor shadow selection can still use all 127 factor slots.
pub const MAX_INTERACTION_EDGES: usize = 512;
/// Maximum caller-supplied hard constraint edges.
pub const MAX_HARD_CONSTRAINT_EDGES: usize = 512;

/// Reserved identity for this calculator's baseline.
///
/// This identity is deliberately distinct from the learning ledger's
/// canonical `abstain` candidate. Mapping between them requires an owner-bound
/// protocol adapter outside this authority-free module.
pub const LOCAL_NO_INTERVENTION_ID: &str = "local-no-intervention";

// Retain the legacy implementation's local budget safety ceiling. This is a
// token-budget bound and is intentionally unrelated to graph-edge ceilings.
const LOCAL_MAX_TOKEN_BUDGET: u64 = 1_000_000;

/// The calculator-local baseline, supplied separately from factor candidates.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalNoInterventionBaseline {
    pub arm_id: StableId,
    pub registry_digest: Digest32,
    pub support_reference_digest: Digest32,
}

/// An explicit caller-supplied marginal term for one unordered factor pair.
///
/// A zero marginal is still represented by an edge. When selection can contain
/// more than one factor, every unordered factor pair must have exactly one edge.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalPairInteraction {
    pub left_candidate_id: StableId,
    pub right_candidate_id: StableId,
    pub caller_supplied_marginal_gain: FixedQ32,
    pub support_reference_digest: Digest32,
}

/// Non-tradable portfolio constraints, independent of numeric utility.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalHardConstraint {
    /// The two factors cannot coexist in the shadow portfolio.
    Conflict {
        left_candidate_id: StableId,
        right_candidate_id: StableId,
        support_reference_digest: Digest32,
    },
    /// `candidate_id` is unavailable until `prerequisite_candidate_id` is selected.
    Requires {
        candidate_id: StableId,
        prerequisite_candidate_id: StableId,
        support_reference_digest: Digest32,
    },
}

/// Untrusted, caller-owned input to the local structural calculator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalShadowInput {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub state_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub token_budget: u64,
    pub maximum_selected_factors: usize,
    pub no_intervention: LocalNoInterventionBaseline,
    pub factor_candidates: Vec<PromptCandidate>,
    pub interaction_edges: Vec<LocalPairInteraction>,
    pub hard_constraints: Vec<LocalHardConstraint>,
}

/// Scope disclosure carried by every local result.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalCandidateScope {
    /// Only the caller's supplied candidates were considered; completeness is unknown.
    SuppliedCandidatesOnly,
}

/// Deterministic local selection method.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalSelectionMethod {
    GreedyMarginalV1,
}

/// Explicit absence of an optimality guarantee.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalOptimalityDisclosure {
    HeuristicNoCertificate,
}

/// One selected candidate-to-factor binding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalShadowSelection {
    pub candidate_id: StableId,
    pub factor_id: StableId,
}

/// In-process shadow output. This is not a registered prompt receipt schema.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalShadowProposal {
    pub no_intervention_arm_id: StableId,
    pub candidate_scope: LocalCandidateScope,
    /// Count of the local baseline plus caller-supplied factor candidates.
    pub total_candidate_count: u32,
    pub selections: Vec<LocalShadowSelection>,
    pub total_token_cost: u64,
    pub unspent_token_budget: u64,
    pub total_caller_supplied_gain: FixedQ32,
    pub candidate_input_digest: Digest32,
    pub interaction_graph_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub selection_method: LocalSelectionMethod,
    pub optimality: LocalOptimalityDisclosure,
    pub proposal_digest: Digest32,
}

impl LocalShadowProposal {
    /// Shadow calculations never carry runtime, selection, or activation authority.
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InvalidInput {
    TotalCandidateLimitExceeded,
    SelectedFactorLimitExceeded,
    InteractionEdgeLimitExceeded,
    HardConstraintLimitExceeded,
    TokenBudgetLimitExceeded,
    EmptyIdentifier(&'static str),
    EmptyDigest(&'static str),
    InvalidNoInterventionIdentity(String),
    DuplicateCandidate(String),
    DuplicateFactor(String),
    DuplicateRealization(String),
    NonCanonicalCandidateOrder,
    UnadmittedFactor(String),
    IllegalFactor(String),
    InvalidFactorCost(String),
    InvalidInteractionEndpoints,
    UnknownInteractionEndpoint(String),
    DuplicateInteractionEdge(String, String),
    NonCanonicalInteractionOrder,
    InvalidHardConstraintEndpoints,
    UnknownHardConstraintEndpoint(String),
    DuplicateHardConstraint(&'static str, String, String),
    NonCanonicalHardConstraintOrder,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InsufficientEvidence {
    EmptySupportReference(&'static str),
    MissingPairInteraction(String, String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntegrityMismatch {
    RegistrySnapshot(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArithmeticInvariant {
    CandidateCount,
    TokenAccounting,
    FixedPointOverflow,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalShadowError {
    InvalidInput(InvalidInput),
    InsufficientEvidence(InsufficientEvidence),
    IntegrityMismatch(IntegrityMismatch),
    ArithmeticInvariant(ArithmeticInvariant),
}

impl fmt::Display for LocalShadowError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidInput(reason) => write!(formatter, "invalid input: {reason:?}"),
            Self::InsufficientEvidence(reason) => {
                write!(formatter, "insufficient evidence: {reason:?}")
            }
            Self::IntegrityMismatch(reason) => {
                write!(formatter, "integrity mismatch: {reason:?}")
            }
            Self::ArithmeticInvariant(reason) => {
                write!(formatter, "arithmetic invariant: {reason:?}")
            }
        }
    }
}

impl StdError for LocalShadowError {}

/// Calculate a deterministic, authority-free proposal over the supplied input.
///
/// Factor candidates, interactions, and hard constraints must already be in
/// canonical order. If `maximum_selected_factors` is greater than one, every
/// unordered factor pair needs an explicit interaction edge, including pairs
/// whose caller-supplied marginal is zero.
pub fn calculate_local_shadow(
    input: LocalShadowInput,
) -> Result<LocalShadowProposal, LocalShadowError> {
    let total_candidate_count = validate_input_structure(&input)?;
    let candidate_input_digest = digest_candidate_input(&input, total_candidate_count);
    let interaction_graph_digest = digest_interactions(&input.interaction_edges);
    let hard_constraint_digest = digest_hard_constraints(&input.hard_constraints);

    let mut selections = Vec::new();
    let mut selected_candidate_ids = BTreeSet::new();
    let mut remaining = input.token_budget;
    let mut total_caller_supplied_gain = FixedQ32::ZERO;

    while selections.len() < input.maximum_selected_factors {
        let mut best: Option<(&PromptCandidate, FixedQ32)> = None;
        for candidate in &input.factor_candidates {
            if selected_candidate_ids.contains(&candidate.candidate_id)
                || candidate.cost > remaining
                || !hard_constraints_allow(
                    &candidate.candidate_id,
                    &selected_candidate_ids,
                    &input.hard_constraints,
                )
            {
                continue;
            }
            let marginal = marginal_gain(
                candidate,
                &selected_candidate_ids,
                &input.interaction_edges,
            )?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let is_better = best.as_ref().is_none_or(|(current, current_gain)| {
                marginal > *current_gain
                    || (marginal == *current_gain
                        && (candidate.cost < current.cost
                            || (candidate.cost == current.cost
                                && candidate.candidate_id < current.candidate_id)))
            });
            if is_better {
                best = Some((candidate, marginal));
            }
        }
        let Some((candidate, marginal)) = best else {
            break;
        };
        remaining = remaining
            .checked_sub(candidate.cost)
            .ok_or(arithmetic(ArithmeticInvariant::TokenAccounting))?;
        total_caller_supplied_gain = total_caller_supplied_gain
            .checked_add(marginal)
            .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
        selected_candidate_ids.insert(candidate.candidate_id.clone());
        selections.push(LocalShadowSelection {
            candidate_id: candidate.candidate_id.clone(),
            factor_id: candidate.factor_id.clone(),
        });
    }

    let total_token_cost = input
        .token_budget
        .checked_sub(remaining)
        .ok_or(arithmetic(ArithmeticInvariant::TokenAccounting))?;
    let proposal_digest = digest_proposal(ProposalDigestInput {
        input: &input,
        total_candidate_count,
        candidate_input_digest,
        interaction_graph_digest,
        hard_constraint_digest,
        selections: &selections,
        total_token_cost,
        unspent_token_budget: remaining,
        total_caller_supplied_gain,
    });

    Ok(LocalShadowProposal {
        no_intervention_arm_id: input.no_intervention.arm_id,
        candidate_scope: LocalCandidateScope::SuppliedCandidatesOnly,
        total_candidate_count,
        selections,
        total_token_cost,
        unspent_token_budget: remaining,
        total_caller_supplied_gain,
        candidate_input_digest,
        interaction_graph_digest,
        hard_constraint_digest,
        selection_method: LocalSelectionMethod::GreedyMarginalV1,
        optimality: LocalOptimalityDisclosure::HeuristicNoCertificate,
        proposal_digest,
    })
}

fn marginal_gain(
    candidate: &PromptCandidate,
    selected: &BTreeSet<StableId>,
    interactions: &[LocalPairInteraction],
) -> Result<FixedQ32, LocalShadowError> {
    let mut marginal = candidate.expected_gain;
    for selected_peer in selected {
        let (left, right) = if candidate.candidate_id.as_str() < selected_peer.as_str() {
            (&candidate.candidate_id, selected_peer)
        } else {
            (selected_peer, &candidate.candidate_id)
        };
        let Some(edge) = interactions.iter().find(|edge| {
            edge.left_candidate_id.as_str() == left.as_str()
                && edge.right_candidate_id.as_str() == right.as_str()
        }) else {
            return Err(insufficient(InsufficientEvidence::MissingPairInteraction(
                left.to_string(),
                right.to_string(),
            )));
        };
        marginal = marginal
            .checked_add(edge.caller_supplied_marginal_gain)
            .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
    }
    Ok(marginal)
}

fn hard_constraints_allow(
    candidate_id: &StableId,
    selected: &BTreeSet<StableId>,
    constraints: &[LocalHardConstraint],
) -> bool {
    constraints.iter().all(|constraint| match constraint {
        LocalHardConstraint::Conflict {
            left_candidate_id,
            right_candidate_id,
            ..
        } => {
            !((candidate_id == left_candidate_id && selected.contains(right_candidate_id))
                || (candidate_id == right_candidate_id && selected.contains(left_candidate_id)))
        }
        LocalHardConstraint::Requires {
            candidate_id: constrained_candidate_id,
            prerequisite_candidate_id,
            ..
        } => {
            candidate_id != constrained_candidate_id
                || selected.contains(prerequisite_candidate_id)
        }
    })
}

fn invalid(reason: InvalidInput) -> LocalShadowError {
    LocalShadowError::InvalidInput(reason)
}

fn insufficient(reason: InsufficientEvidence) -> LocalShadowError {
    LocalShadowError::InsufficientEvidence(reason)
}

fn integrity(reason: IntegrityMismatch) -> LocalShadowError {
    LocalShadowError::IntegrityMismatch(reason)
}

fn arithmetic(reason: ArithmeticInvariant) -> LocalShadowError {
    LocalShadowError::ArithmeticInvariant(reason)
}
