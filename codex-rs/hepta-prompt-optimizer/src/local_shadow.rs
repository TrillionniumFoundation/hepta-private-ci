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

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::PromptCandidate;
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
