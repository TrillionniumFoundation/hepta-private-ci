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
//!
//! The strict shadow surface deliberately requires complete pair evidence when
//! more than one factor may be selected. The registered `policy` surface owns
//! the scalable sparse-interaction semantics for the full 128-factor target.

use std::collections::BTreeMap;
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
/// The strict shadow calculator requires pair completeness whenever multi-factor
/// selection is enabled, so this surface reaches 32 factor candidates at most
/// in that mode. The registered policy surface supports the 128-factor target
/// through an explicit sparse missing-interaction policy instead of silently
/// treating unknown pair effects as zero.
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
    /// Selecting `candidate_id` requires selecting `prerequisite_candidate_id`.
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
    /// Greedy marginal selection where each root is evaluated together with its
    /// transitive prerequisite closure.
    GreedyRequirementClosureV2,
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
    RequiresCycle(String),
    UnsatisfiableRequirementConflict(String),
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
/// whose caller-supplied marginal is zero. A candidate with prerequisites is
/// evaluated as one transitive requirement package, so a negative prerequisite
/// may be selected when the complete package has positive marginal gain.
pub fn calculate_local_shadow(
    input: LocalShadowInput,
) -> Result<LocalShadowProposal, LocalShadowError> {
    let total_candidate_count = validate_input_structure(&input)?;
    let candidate_input_digest = digest_candidate_input(&input, total_candidate_count);
    let interaction_graph_digest = digest_interactions(&input.interaction_edges);
    let hard_constraint_digest = digest_hard_constraints(&input.hard_constraints);

    let candidates_by_id = input
        .factor_candidates
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate))
        .collect::<BTreeMap<_, _>>();
    let mut selections = Vec::new();
    let mut selected_candidate_ids = BTreeSet::new();
    let mut remaining = input.token_budget;
    let mut total_caller_supplied_gain = FixedQ32::ZERO;

    while selections.len() < input.maximum_selected_factors {
        let mut best: Option<(&PromptCandidate, Vec<&PromptCandidate>, u64, FixedQ32)> = None;
        for root in &input.factor_candidates {
            if selected_candidate_ids.contains(&root.candidate_id) {
                continue;
            }
            let package = requirement_package(
                &root.candidate_id,
                &candidates_by_id,
                &input.hard_constraints,
            )?;
            let additions = package
                .into_iter()
                .filter(|candidate| !selected_candidate_ids.contains(&candidate.candidate_id))
                .collect::<Vec<_>>();
            if additions.is_empty()
                || selections.len().saturating_add(additions.len()) > input.maximum_selected_factors
                || package_conflicts(&selected_candidate_ids, &additions, &input.hard_constraints)
            {
                continue;
            }
            let package_cost = additions.iter().try_fold(0_u64, |sum, candidate| {
                sum.checked_add(candidate.cost)
                    .ok_or(arithmetic(ArithmeticInvariant::TokenAccounting))
            })?;
            if package_cost > remaining {
                continue;
            }
            let marginal = package_marginal_gain(
                &additions,
                &selected_candidate_ids,
                &input.interaction_edges,
            )?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let is_better =
                best.as_ref()
                    .is_none_or(|(current_root, _, current_cost, current_gain)| {
                        marginal > *current_gain
                            || (marginal == *current_gain
                                && (package_cost < *current_cost
                                    || (package_cost == *current_cost
                                        && root.candidate_id < current_root.candidate_id)))
                    });
            if is_better {
                best = Some((root, additions, package_cost, marginal));
            }
        }
        let Some((_, additions, package_cost, marginal)) = best else {
            break;
        };
        remaining = remaining
            .checked_sub(package_cost)
            .ok_or(arithmetic(ArithmeticInvariant::TokenAccounting))?;
        total_caller_supplied_gain = total_caller_supplied_gain
            .checked_add(marginal)
            .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
        for candidate in additions {
            if selected_candidate_ids.insert(candidate.candidate_id.clone()) {
                selections.push(LocalShadowSelection {
                    candidate_id: candidate.candidate_id.clone(),
                    factor_id: candidate.factor_id.clone(),
                });
            }
        }
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
        selection_method: LocalSelectionMethod::GreedyRequirementClosureV2,
        optimality: LocalOptimalityDisclosure::HeuristicNoCertificate,
        proposal_digest,
    })
}

fn requirement_package<'a>(
    root: &StableId,
    candidates: &BTreeMap<StableId, &'a PromptCandidate>,
    constraints: &[LocalHardConstraint],
) -> Result<Vec<&'a PromptCandidate>, LocalShadowError> {
    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    let mut output = Vec::new();
    collect_requirement_package(
        root,
        candidates,
        constraints,
        &mut visiting,
        &mut visited,
        &mut output,
    )?;
    Ok(output)
}

fn collect_requirement_package<'a>(
    candidate_id: &StableId,
    candidates: &BTreeMap<StableId, &'a PromptCandidate>,
    constraints: &[LocalHardConstraint],
    visiting: &mut BTreeSet<StableId>,
    visited: &mut BTreeSet<StableId>,
    output: &mut Vec<&'a PromptCandidate>,
) -> Result<(), LocalShadowError> {
    if visited.contains(candidate_id) {
        return Ok(());
    }
    if !visiting.insert(candidate_id.clone()) {
        return Err(invalid(InvalidInput::RequiresCycle(
            candidate_id.to_string(),
        )));
    }
    let mut prerequisites = constraints
        .iter()
        .filter_map(|constraint| match constraint {
            LocalHardConstraint::Requires {
                candidate_id: constrained_candidate_id,
                prerequisite_candidate_id,
                ..
            } if constrained_candidate_id == candidate_id => Some(prerequisite_candidate_id),
            _ => None,
        })
        .collect::<Vec<_>>();
    prerequisites.sort();
    for prerequisite in prerequisites {
        collect_requirement_package(
            prerequisite,
            candidates,
            constraints,
            visiting,
            visited,
            output,
        )?;
    }
    visiting.remove(candidate_id);
    visited.insert(candidate_id.clone());
    let Some(candidate) = candidates.get(candidate_id).copied() else {
        return Err(invalid(InvalidInput::UnknownHardConstraintEndpoint(
            candidate_id.to_string(),
        )));
    };
    output.push(candidate);
    Ok(())
}

fn package_conflicts(
    selected: &BTreeSet<StableId>,
    additions: &[&PromptCandidate],
    constraints: &[LocalHardConstraint],
) -> bool {
    let additions = additions
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<BTreeSet<_>>();
    constraints.iter().any(|constraint| match constraint {
        LocalHardConstraint::Conflict {
            left_candidate_id,
            right_candidate_id,
            ..
        } => {
            (selected.contains(left_candidate_id) && additions.contains(right_candidate_id))
                || (selected.contains(right_candidate_id) && additions.contains(left_candidate_id))
                || (additions.contains(left_candidate_id) && additions.contains(right_candidate_id))
        }
        LocalHardConstraint::Requires { .. } => false,
    })
}

fn package_marginal_gain(
    additions: &[&PromptCandidate],
    selected: &BTreeSet<StableId>,
    interactions: &[LocalPairInteraction],
) -> Result<FixedQ32, LocalShadowError> {
    let mut marginal = FixedQ32::ZERO;
    let mut package_selected = selected.clone();
    for candidate in additions {
        marginal = marginal
            .checked_add(candidate.expected_gain)
            .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
        for selected_peer in &package_selected {
            let edge_gain = interaction_gain(&candidate.candidate_id, selected_peer, interactions)?;
            marginal = marginal
                .checked_add(edge_gain)
                .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
        }
        package_selected.insert(candidate.candidate_id.clone());
    }
    Ok(marginal)
}

fn interaction_gain(
    left_candidate_id: &StableId,
    right_candidate_id: &StableId,
    interactions: &[LocalPairInteraction],
) -> Result<FixedQ32, LocalShadowError> {
    let (left, right) = if left_candidate_id < right_candidate_id {
        (left_candidate_id, right_candidate_id)
    } else {
        (right_candidate_id, left_candidate_id)
    };
    let Some(edge) = interactions
        .iter()
        .find(|edge| edge.left_candidate_id == *left && edge.right_candidate_id == *right)
    else {
        return Err(insufficient(InsufficientEvidence::MissingPairInteraction(
            left.to_string(),
            right.to_string(),
        )));
    };
    Ok(edge.caller_supplied_marginal_gain)
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

#[cfg(test)]
#[path = "local_shadow_tests.rs"]
mod tests;
