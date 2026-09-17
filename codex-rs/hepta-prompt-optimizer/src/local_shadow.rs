//! Authority-free, bounded prompt-portfolio shadow calculations.
//!
//! This is an in-process structural calculator, not a wire codec or registered
//! durable receipt. Gains/costs remain caller supplied. Unlike the legacy v2
//! shadow algorithm, sparse pair graphs are permitted and missing edges are
//! explicitly treated as zero; prerequisite closures are evaluated as packages
//! so a negative standalone prerequisite can be selected when the dependent
//! package has positive aggregate marginal utility.

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, StableId};

use crate::PromptCandidate;

#[path = "local_shadow_digest.rs"]
mod digest;
#[path = "local_shadow_validation.rs"]
mod validation;
use digest::{
    ProposalDigestInput, digest_candidate_input, digest_hard_constraints, digest_interactions,
    digest_proposal,
};
use validation::validate_input_structure;

pub const MAX_TOTAL_CANDIDATES: usize = 128;
pub const MAX_FACTOR_CANDIDATES: usize = MAX_TOTAL_CANDIDATES - 1;
pub const MAX_SELECTED_FACTORS: usize = 16;
pub const MAX_INTERACTION_EDGES: usize = 512;
pub const MAX_HARD_CONSTRAINT_EDGES: usize = 512;
pub const LOCAL_NO_INTERVENTION_ID: &str = "local-no-intervention";
pub(super) const LOCAL_MAX_TOKEN_BUDGET: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalNoInterventionBaseline {
    pub arm_id: StableId,
    pub registry_digest: Digest32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalPairInteraction {
    pub left_candidate_id: StableId,
    pub right_candidate_id: StableId,
    pub caller_supplied_marginal_gain: FixedQ32,
    pub support_reference_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalHardConstraint {
    Conflict {
        left_candidate_id: StableId,
        right_candidate_id: StableId,
        support_reference_digest: Digest32,
    },
    Requires {
        candidate_id: StableId,
        prerequisite_candidate_id: StableId,
        support_reference_digest: Digest32,
    },
}

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalCandidateScope {
    SuppliedCandidatesOnly,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalCandidateCompleteness {
    UnknownCallerSupplied,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalPricingProvenance {
    CallerSuppliedOpaque,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalModelCompatibility {
    Unverified,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalExerciseBoundary {
    Unbound,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalUnknownInteractionPolicy {
    MissingAsZero,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalSelectionMethod {
    PrerequisiteClosureGreedyDensityV2,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalOptimalityDisclosure {
    HeuristicNoCertificate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalShadowSelection {
    pub candidate_id: StableId,
    pub factor_id: StableId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalCandidateDisposition {
    Selected,
    NonPositiveMarginal,
    OverBudget,
    SelectionLimit,
    Conflict,
    HeuristicNotSelected,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalShadowCandidateDecision {
    pub candidate_id: StableId,
    pub disposition: LocalCandidateDisposition,
    pub prerequisite_closure: Vec<StableId>,
}

/// In-process shadow output. This remains deliberately distinct from the
/// registered V1 receipts in `crate::pipeline` but now exposes the audit gaps
/// explicitly instead of leaving them implicit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalShadowProposal {
    pub no_intervention_arm_id: StableId,
    pub candidate_scope: LocalCandidateScope,
    pub candidate_completeness: LocalCandidateCompleteness,
    pub total_candidate_count: u32,
    pub omitted_candidate_count: u32,
    pub selections: Vec<LocalShadowSelection>,
    pub decisions: Vec<LocalShadowCandidateDecision>,
    pub total_token_cost: u64,
    pub unspent_token_budget: u64,
    pub total_caller_supplied_gain: FixedQ32,
    pub candidate_input_digest: Digest32,
    pub interaction_graph_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub pricing_provenance: LocalPricingProvenance,
    pub model_compatibility: LocalModelCompatibility,
    pub exercise_boundary: LocalExerciseBoundary,
    pub interaction_policy: LocalUnknownInteractionPolicy,
    pub selection_method: LocalSelectionMethod,
    pub optimality: LocalOptimalityDisclosure,
    pub proposal_digest: Digest32,
}

impl LocalShadowProposal {
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
    UnsatisfiableConstraintGraph(String),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum InsufficientEvidence {
    EmptySupportReference(&'static str),
    /// Retained for source compatibility; sparse v3 calculation does not emit it.
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
            Self::IntegrityMismatch(reason) => write!(formatter, "integrity mismatch: {reason:?}"),
            Self::ArithmeticInvariant(reason) => {
                write!(formatter, "arithmetic invariant: {reason:?}")
            }
        }
    }
}
impl StdError for LocalShadowError {}

pub fn calculate_local_shadow(
    input: LocalShadowInput,
) -> Result<LocalShadowProposal, LocalShadowError> {
    let total_candidate_count = validate_input_structure(&input)?;
    let candidate_input_digest = digest_candidate_input(&input, total_candidate_count);
    let interaction_graph_digest = digest_interactions(&input.interaction_edges);
    let hard_constraint_digest = digest_hard_constraints(&input.hard_constraints);
    let candidates = input
        .factor_candidates
        .iter()
        .map(|c| (c.candidate_id.clone(), c))
        .collect::<BTreeMap<_, _>>();

    let mut selected = BTreeSet::new();
    let mut ordered_selected = Vec::new();
    let mut remaining = input.token_budget;
    let mut total_gain = FixedQ32::ZERO;

    while ordered_selected.len() < input.maximum_selected_factors {
        let mut best: Option<PackageChoice> = None;
        for candidate in &input.factor_candidates {
            if selected.contains(&candidate.candidate_id) {
                continue;
            }
            let package =
                prerequisite_closure(&candidate.candidate_id, &selected, &input.hard_constraints)?;
            if package.is_empty()
                || ordered_selected.len().saturating_add(package.len())
                    > input.maximum_selected_factors
            {
                continue;
            }
            if package_conflicts(&package, &selected, &input.hard_constraints) {
                continue;
            }
            let package_cost = package_cost(&package, &candidates)?;
            if package_cost > remaining {
                continue;
            }
            let marginal =
                package_gain(&package, &selected, &candidates, &input.interaction_edges)?;
            if marginal <= FixedQ32::ZERO {
                continue;
            }
            let choice = PackageChoice {
                root: candidate.candidate_id.clone(),
                package,
                cost: package_cost,
                marginal,
            };
            if best
                .as_ref()
                .is_none_or(|current| choice_better(&choice, current))
            {
                best = Some(choice);
            }
        }
        let Some(best) = best else {
            break;
        };
        for candidate_id in best.package {
            if selected.insert(candidate_id.clone()) {
                ordered_selected.push(candidate_id);
            }
        }
        remaining = remaining
            .checked_sub(best.cost)
            .ok_or(arithmetic(ArithmeticInvariant::TokenAccounting))?;
        total_gain = total_gain
            .checked_add(best.marginal)
            .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
    }

    let selections = ordered_selected
        .iter()
        .map(|id| {
            let Some(candidate) = candidates.get(id) else {
                return Err(invalid(InvalidInput::UnknownHardConstraintEndpoint(
                    id.to_string(),
                )));
            };
            Ok(LocalShadowSelection {
                candidate_id: id.clone(),
                factor_id: candidate.factor_id.clone(),
            })
        })
        .collect::<Result<Vec<_>, LocalShadowError>>()?;
    let decisions = classify_decisions(&input, &selected, remaining, &candidates)?;
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
        decisions: &decisions,
        total_token_cost,
        unspent_token_budget: remaining,
        total_caller_supplied_gain: total_gain,
    });

    Ok(LocalShadowProposal {
        no_intervention_arm_id: input.no_intervention.arm_id,
        candidate_scope: LocalCandidateScope::SuppliedCandidatesOnly,
        candidate_completeness: LocalCandidateCompleteness::UnknownCallerSupplied,
        total_candidate_count,
        omitted_candidate_count: 0,
        selections,
        decisions,
        total_token_cost,
        unspent_token_budget: remaining,
        total_caller_supplied_gain: total_gain,
        candidate_input_digest,
        interaction_graph_digest,
        hard_constraint_digest,
        pricing_provenance: LocalPricingProvenance::CallerSuppliedOpaque,
        model_compatibility: LocalModelCompatibility::Unverified,
        exercise_boundary: LocalExerciseBoundary::Unbound,
        interaction_policy: LocalUnknownInteractionPolicy::MissingAsZero,
        selection_method: LocalSelectionMethod::PrerequisiteClosureGreedyDensityV2,
        optimality: LocalOptimalityDisclosure::HeuristicNoCertificate,
        proposal_digest,
    })
}

#[derive(Clone)]
struct PackageChoice {
    root: StableId,
    package: Vec<StableId>,
    cost: u64,
    marginal: FixedQ32,
}
fn choice_better(left: &PackageChoice, right: &PackageChoice) -> bool {
    let left_density = i128::from(left.marginal.raw()) * i128::from(right.cost.max(1));
    let right_density = i128::from(right.marginal.raw()) * i128::from(left.cost.max(1));
    left_density > right_density
        || (left_density == right_density
            && (left.marginal > right.marginal
                || (left.marginal == right.marginal
                    && (left.cost < right.cost
                        || (left.cost == right.cost && left.root < right.root)))))
}

fn package_cost(
    package: &[StableId],
    candidates: &BTreeMap<StableId, &PromptCandidate>,
) -> Result<u64, LocalShadowError> {
    package.iter().try_fold(0u64, |total, id| {
        let Some(candidate) = candidates.get(id) else {
            return Err(invalid(InvalidInput::UnknownHardConstraintEndpoint(
                id.to_string(),
            )));
        };
        total
            .checked_add(candidate.cost)
            .ok_or(arithmetic(ArithmeticInvariant::TokenAccounting))
    })
}

fn package_gain(
    package: &[StableId],
    selected: &BTreeSet<StableId>,
    candidates: &BTreeMap<StableId, &PromptCandidate>,
    interactions: &[LocalPairInteraction],
) -> Result<FixedQ32, LocalShadowError> {
    let mut gain = FixedQ32::ZERO;
    for id in package {
        let Some(candidate) = candidates.get(id) else {
            return Err(invalid(InvalidInput::UnknownHardConstraintEndpoint(
                id.to_string(),
            )));
        };
        gain = gain
            .checked_add(candidate.expected_gain)
            .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
    }
    for id in package {
        for peer in selected {
            gain = gain
                .checked_add(interaction_gain(id, peer, interactions))
                .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
        }
    }
    for (index, left) in package.iter().enumerate() {
        for right in package.iter().skip(index + 1) {
            gain = gain
                .checked_add(interaction_gain(left, right, interactions))
                .map_err(|_| arithmetic(ArithmeticInvariant::FixedPointOverflow))?;
        }
    }
    Ok(gain)
}

fn interaction_gain(
    left: &StableId,
    right: &StableId,
    interactions: &[LocalPairInteraction],
) -> FixedQ32 {
    if left == right {
        return FixedQ32::ZERO;
    }
    let (left, right) = if left < right {
        (left, right)
    } else {
        (right, left)
    };
    interactions
        .iter()
        .find(|edge| &edge.left_candidate_id == left && &edge.right_candidate_id == right)
        .map_or(FixedQ32::ZERO, |edge| edge.caller_supplied_marginal_gain)
}

fn prerequisite_closure(
    candidate_id: &StableId,
    selected: &BTreeSet<StableId>,
    constraints: &[LocalHardConstraint],
) -> Result<Vec<StableId>, LocalShadowError> {
    let mut visiting = BTreeSet::new();
    let mut emitted = BTreeSet::new();
    let mut ordered = Vec::new();
    emit_closure(
        candidate_id,
        selected,
        constraints,
        &mut visiting,
        &mut emitted,
        &mut ordered,
    )?;
    Ok(ordered)
}
fn emit_closure(
    node: &StableId,
    selected: &BTreeSet<StableId>,
    constraints: &[LocalHardConstraint],
    visiting: &mut BTreeSet<StableId>,
    emitted: &mut BTreeSet<StableId>,
    ordered: &mut Vec<StableId>,
) -> Result<(), LocalShadowError> {
    if selected.contains(node) || emitted.contains(node) {
        return Ok(());
    }
    if !visiting.insert(node.clone()) {
        return Err(invalid(InvalidInput::RequiresCycle(node.to_string())));
    }
    let mut prerequisites = constraints
        .iter()
        .filter_map(|constraint| match constraint {
            LocalHardConstraint::Requires {
                candidate_id,
                prerequisite_candidate_id,
                ..
            } if candidate_id == node => Some(prerequisite_candidate_id.clone()),
            _ => None,
        })
        .collect::<Vec<_>>();
    prerequisites.sort();
    for prerequisite in prerequisites {
        emit_closure(
            &prerequisite,
            selected,
            constraints,
            visiting,
            emitted,
            ordered,
        )?;
    }
    visiting.remove(node);
    if emitted.insert(node.clone()) {
        ordered.push(node.clone());
    }
    Ok(())
}

fn package_conflicts(
    package: &[StableId],
    selected: &BTreeSet<StableId>,
    constraints: &[LocalHardConstraint],
) -> bool {
    constraints.iter().any(|constraint| match constraint {
        LocalHardConstraint::Conflict {
            left_candidate_id,
            right_candidate_id,
            ..
        } => {
            let left_present =
                selected.contains(left_candidate_id) || package.contains(left_candidate_id);
            let right_present =
                selected.contains(right_candidate_id) || package.contains(right_candidate_id);
            left_present && right_present
        }
        LocalHardConstraint::Requires { .. } => false,
    })
}

fn classify_decisions(
    input: &LocalShadowInput,
    selected: &BTreeSet<StableId>,
    remaining: u64,
    candidates: &BTreeMap<StableId, &PromptCandidate>,
) -> Result<Vec<LocalShadowCandidateDecision>, LocalShadowError> {
    let remaining_slots = input
        .maximum_selected_factors
        .saturating_sub(selected.len());
    input
        .factor_candidates
        .iter()
        .map(|candidate| {
            let full_closure = prerequisite_closure(
                &candidate.candidate_id,
                &BTreeSet::new(),
                &input.hard_constraints,
            )?;
            let remaining_closure =
                prerequisite_closure(&candidate.candidate_id, selected, &input.hard_constraints)?;
            let disposition = if selected.contains(&candidate.candidate_id) {
                LocalCandidateDisposition::Selected
            } else if remaining_closure.len() > remaining_slots {
                LocalCandidateDisposition::SelectionLimit
            } else if package_conflicts(&remaining_closure, selected, &input.hard_constraints) {
                LocalCandidateDisposition::Conflict
            } else if package_cost(&remaining_closure, candidates)? > remaining {
                LocalCandidateDisposition::OverBudget
            } else if package_gain(
                &remaining_closure,
                selected,
                candidates,
                &input.interaction_edges,
            )? <= FixedQ32::ZERO
            {
                LocalCandidateDisposition::NonPositiveMarginal
            } else {
                LocalCandidateDisposition::HeuristicNotSelected
            };
            Ok(LocalShadowCandidateDecision {
                candidate_id: candidate.candidate_id.clone(),
                disposition,
                prerequisite_closure: full_closure,
            })
        })
        .collect()
}

pub(super) fn invalid(reason: InvalidInput) -> LocalShadowError {
    LocalShadowError::InvalidInput(reason)
}
pub(super) fn insufficient(reason: InsufficientEvidence) -> LocalShadowError {
    LocalShadowError::InsufficientEvidence(reason)
}
pub(super) fn integrity(reason: IntegrityMismatch) -> LocalShadowError {
    LocalShadowError::IntegrityMismatch(reason)
}
pub(super) fn arithmetic(reason: ArithmeticInvariant) -> LocalShadowError {
    LocalShadowError::ArithmeticInvariant(reason)
}

#[cfg(test)]
#[path = "local_shadow_tests.rs"]
mod tests;
