use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

/// Non-compensable constraint precedence, highest authority first.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ConstraintClass {
    Constitutional,
    Principal,
    Environment,
    Task,
}

impl ConstraintClass {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Constitutional => 0,
            Self::Principal => 1,
            Self::Environment => 2,
            Self::Task => 3,
        }
    }
}

/// Supported deterministic numeric relations.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ConstraintRelation {
    AtLeast,
    AtMost,
    Equal,
}

impl ConstraintRelation {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::AtLeast => 0,
            Self::AtMost => 1,
            Self::Equal => 2,
        }
    }
}

/// Trust class of the source adapter. Untrusted evidence never creates authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceTrust {
    PrincipalStructured,
    RegisteredAdapter,
    UntrustedEvidence,
}

impl SourceTrust {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::PrincipalStructured => 0,
            Self::RegisteredAdapter => 1,
            Self::UntrustedEvidence => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum SoftDirection {
    Maximize,
    Minimize,
}

impl SoftDirection {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Maximize => 0,
            Self::Minimize => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Constraint {
    pub id: StableId,
    pub class: ConstraintClass,
    pub axis: StableId,
    pub relation: ConstraintRelation,
    pub bound: FixedQ32,
    pub evidence_source: StableId,
}

/// Whether a success predicate is an advisory intermediate signal or a
/// terminal outcome observed outside the policy being evaluated.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PredicateTerminality {
    Intermediate,
    Terminal,
}

impl PredicateTerminality {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::Intermediate => 0,
            Self::Terminal => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SuccessPredicate {
    pub id: StableId,
    pub axis: StableId,
    pub relation: ConstraintRelation,
    pub bound: FixedQ32,
    pub evidence_source: StableId,
    pub terminality: PredicateTerminality,
}

/// Explicit confirmation posture for an otherwise legal action class.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ConfirmationPolicy {
    NotRequired,
    Required,
}

impl ConfirmationPolicy {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::NotRequired => 0,
            Self::Required => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionClass {
    pub id: StableId,
    pub confirmation: ConfirmationPolicy,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SoftPreference {
    pub dimension: StableId,
    pub direction: SoftDirection,
    pub weight: FixedQ32,
}

/// Fully structured source envelope. Raw free text is represented only by its
/// source digest and remains outside the authority-bearing IR.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveSourceEnvelope {
    pub request_id: StableId,
    pub principal_scope: StableId,
    pub revision: Revision,
    pub source_trust: SourceTrust,
    pub source_digest: Digest32,
    pub schema_digest: Digest32,
    pub constraints: Vec<Constraint>,
    pub success_predicates: Vec<SuccessPredicate>,
    pub allowed_actions: Vec<ActionClass>,
    pub forbidden_actions: Vec<StableId>,
    pub soft_preferences: Vec<SoftPreference>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveFunction {
    pub request_id: StableId,
    pub principal_scope: StableId,
    pub revision: Revision,
    pub source_digest: Digest32,
    pub schema_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub semantic_digest: Digest32,
    pub constraints: Vec<Constraint>,
    pub success_predicates: Vec<SuccessPredicate>,
    pub legal_actions: Vec<ActionClass>,
    pub soft_preferences: Vec<SoftPreference>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompileDisposition {
    Compiled,
    ExplicitAbstain,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveCompileReceipt {
    pub objective: ObjectiveFunction,
    pub disposition: CompileDisposition,
    pub removed_action_ids: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveConflictReceipt {
    pub request_id: StableId,
    pub revision: Revision,
    pub source_digest: Digest32,
    pub conflicting_ids: Vec<StableId>,
    pub conflict_digest: Digest32,
}
