//! Owner-local representation of the `ObjectiveSourceEnvelopeV1` field grammar
//! in `docs/readiness/PROTOCOLS.json`. This is not its admitted wire type.
//!
//! The separate `decode_source_envelope_json_v1` entrypoint checks JSON shape;
//! canonical intent digesting and profile-bound admission are provided by
//! `canonical_objective_intent_digest_v1` and `admit_and_compile_objective_v1`.
//! Strings preserve source spelling: identifier/timestamp syntax, NFC, canonical
//! ordering and registered profiles require later admission.

use codex_hepta_types::Digest32;

/// A supplied trust label, not evidence that its source has been authenticated.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveSourceTrustV1 {
    Principal,
    TrustedSystem,
    AuthorizedAdapter,
    UntrustedEvidence,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectivePredicateComparatorV1 {
    Equal,
    NotEqual,
    LessThan,
    LessThanOrEqual,
    GreaterThan,
    GreaterThanOrEqual,
}

/// V1 preserves all protocol comparator spellings so unsupported semantics fail
/// closed at admission rather than being silently rewritten. The V1 constraint
/// row carries only one scalar `bound_q32`; it has no finite-enum set payload.
/// Consequently `In`/`NotInSet`, strict inequalities and `NotEqual` are not a
/// claim that the V1 source-to-objective adapter can represent those operations.
/// Finite-enum intersection is a capability of the general feasibility API and
/// requires a source grammar with an explicit set payload.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveConstraintComparatorV1 {
    Equal,
    NotEqual,
    LessThan,
    LessThanOrEqual,
    GreaterThan,
    GreaterThanOrEqual,
    In,
    NotInSet,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveSoftDirectionV1 {
    Maximize,
    Minimize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveRiskClassV1 {
    Low,
    Medium,
    High,
    Critical,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveRollbackClassV1 {
    None,
    Reversible,
    Compensatable,
    Irreversible,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveSourcePredicateV1 {
    pub predicate_id: String,
    pub unit: String,
    pub comparator: ObjectivePredicateComparatorV1,
    pub bound_q32: i64,
    pub evidence_source_id: String,
    pub terminal: bool,
}

/// Preserves the V1 source grammar without guessing the native compiler's axis
/// or precedence class. Resolving those requires a registered profile. V1 hard
/// constraints are scalar Q32 bounds; enum-set and action-implication atoms are
/// intentionally not synthesized from this row.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveSourceConstraintV1 {
    pub constraint_id: String,
    pub unit: String,
    pub comparator: ObjectiveConstraintComparatorV1,
    pub bound_q32: i64,
    pub evidence_source_id: String,
    pub terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveSoftDimensionV1 {
    pub dimension_id: String,
    pub unit: String,
    pub direction: ObjectiveSoftDirectionV1,
    pub minimum_weight_q32: i64,
    pub maximum_weight_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveEvidenceRequirementV1 {
    pub requirement_id: String,
    pub evidence_source_id: String,
    pub minimum_confidence_ppm: u32,
    pub terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveResourcesV1 {
    pub time_micros: u64,
    pub token_count: u64,
    pub compute_micros: u64,
    pub memory_bytes: u64,
    pub network_bytes: u64,
    pub external_effect_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRiskV1 {
    pub risk_class: ObjectiveRiskClassV1,
    pub abstention_rule: String,
    pub rollback_class: ObjectiveRollbackClassV1,
    pub compensation_required: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveProvenanceV1 {
    pub source_digest: Digest32,
    pub normalization_profile_digest: Digest32,
}

/// All eleven required structured-intent fields. Admission preserves and binds
/// every field, but V1 intentionally lowers only the semantics the native
/// objective model can represent. In particular, the general feasibility
/// engine's finite-enum and positive-action-implication atoms are not exposed by
/// this scalar V1 source grammar.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveStructuredIntentV1 {
    pub success_predicates: Vec<ObjectiveSourcePredicateV1>,
    pub terminal_conditions: Vec<ObjectiveSourcePredicateV1>,
    pub legal_action_classes: Vec<String>,
    pub forbidden_action_classes: Vec<String>,
    pub confirmation_action_classes: Vec<String>,
    pub constraints: Vec<ObjectiveSourceConstraintV1>,
    pub soft_dimensions: Vec<ObjectiveSoftDimensionV1>,
    pub evidence_requirements: Vec<ObjectiveEvidenceRequirementV1>,
    pub resources: ObjectiveResourcesV1,
    pub risk: ObjectiveRiskV1,
    pub provenance: ObjectiveProvenanceV1,
}

/// Native source fields only. Even a structurally valid instance is neither
/// authenticated nor eligible for publication or effect authorization.
///
/// Digest fields retain supplied values until admission verifies their bindings.
/// `observed_at` and `deadline` retain source text; UTC syntax, freshness and
/// deadline enforcement are admission responsibilities.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveSourceEnvelopeV1 {
    pub request_id: String,
    pub principal_scope_digest: Digest32,
    pub intent_digest: Digest32,
    pub structured_intent: ObjectiveStructuredIntentV1,
    pub source_trust_class: ObjectiveSourceTrustV1,
    pub locale: String,
    pub observed_at: String,
    pub deadline: Option<String>,
    pub input_schema_digest: Digest32,
}

#[cfg(test)]
#[path = "source_envelope_v1_tests.rs"]
mod tests;
