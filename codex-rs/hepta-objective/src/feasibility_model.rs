use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::Duration;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ConstraintClass;
use crate::PredicateTerminality;

/// In-process V1 grammar. Registration describes observations, never authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredGrammarV1 {
    pub schema_digest: Digest32,
    pub axes: BTreeMap<StableId, RegisteredAxisV1>,
    pub evidence_sources: BTreeSet<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredAxisV1 {
    pub unit: StableId,
    pub domain: RegisteredDomainV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegisteredDomainV1 {
    Scalar { lower: FixedQ32, upper: FixedQ32 },
    Enumeration(BTreeSet<StableId>),
    Action,
    ImmutableIdentity(IdentityValueV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IdentityValueV1 {
    Scope(StableId),
    Generation(u64),
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum AtomPrecedenceV1 {
    Hard(ConstraintClass),
    Soft,
}

/// Only positive action implications are executable in this version.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AtomPredicateV1 {
    ScalarInterval { lower: FixedQ32, upper: FixedQ32 },
    Include(BTreeSet<StableId>),
    Exclude(BTreeSet<StableId>),
    RequireAction,
    ForbidAction,
    Implies(StableId),
    IdentityEqual(IdentityValueV1),
    Unsupported(StableId),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConstraintAtomV1 {
    pub id: StableId,
    pub precedence: AtomPrecedenceV1,
    pub axis: StableId,
    pub predicate: AtomPredicateV1,
    pub unit: StableId,
    pub evidence_source: StableId,
    pub terminality: PredicateTerminality,
    pub origin_digest: Digest32,
}

/// Legacy availability wrapper. Wall time is interpreted only by the outer
/// runtime adapter; it is never read by the deterministic semantic engine.
/// Call limits above 257 are capped by this compatibility API.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OracleBudgetV1 {
    pub max_calls: u16,
    pub wall_time: Duration,
}

/// Host-independent work budget for deterministic feasibility.
///
/// `max_work_units` counts candidate-atom visits at solver entry. The cache is
/// request-local, bounded, and never evicts, so equal inputs and budgets have
/// equal outcomes regardless of host load or thread scheduling.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DeterministicOracleBudgetV1 {
    pub max_calls: u16,
    pub max_work_units: u64,
    pub max_cache_entries: u16,
}

/// A witness assignment is advisory and grants no effect permission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeasibleAssignmentV1 {
    pub domains: BTreeMap<StableId, RegisteredAxisV1>,
    pub required_actions: BTreeSet<StableId>,
    pub unforced_actions: BTreeSet<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FeasibilityOutcomeV1 {
    Feasible(FeasibleAssignmentV1),
    Infeasible {
        inclusion_minimal_conflicting_ids: Vec<StableId>,
    },
    Unsupported {
        reason: &'static str,
        atom_ids: Vec<StableId>,
    },
    /// Runtime cancellation, wall-clock expiration, or deterministic work
    /// budget exhaustion. This is never a semantic infeasibility proof.
    Exhausted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeasibilityReceiptV1 {
    pub schema_digest: Digest32,
    /// Original order and all hard/soft constraints survive every disposition.
    pub original_constraints: Vec<ConstraintAtomV1>,
    pub outcome: FeasibilityOutcomeV1,
    pub oracle_calls: u16,
    /// Zero for deterministic semantic evaluation. Runtime adapters may project
    /// their measured duration without changing the semantic outcome.
    pub elapsed: Duration,
}
