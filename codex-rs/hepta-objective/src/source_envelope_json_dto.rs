//! Private remote derives avoid adding a public serde protocol surface to the
//! owner-local models. All nested objects use the object-only adapter.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Deserializer;

use crate::source_envelope_json_shape as shape;
use crate::source_envelope_v1::*;

macro_rules! object_decoder {
    ($dto:ident, $model:ident) => {
        impl $dto {
            pub(super) fn decode<'de, D: Deserializer<'de>>(d: D) -> Result<$model, D::Error> {
                Self::deserialize(shape::ObjectOnly(d))
            }
        }
    };
}

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveSourceEnvelopeV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub(super) struct Envelope {
    request_id: String,
    #[serde(deserialize_with = "shape::digest")]
    principal_scope_digest: Digest32,
    #[serde(deserialize_with = "shape::digest")]
    intent_digest: Digest32,
    #[serde(deserialize_with = "Intent::decode")]
    structured_intent: ObjectiveStructuredIntentV1,
    #[serde(deserialize_with = "shape::trust")]
    source_trust_class: ObjectiveSourceTrustV1,
    locale: String,
    observed_at: String,
    #[serde(default, deserialize_with = "shape::present_deadline")]
    deadline: Option<String>,
    #[serde(deserialize_with = "shape::digest")]
    input_schema_digest: Digest32,
}
object_decoder!(Envelope, ObjectiveSourceEnvelopeV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveStructuredIntentV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Intent {
    #[serde(deserialize_with = "predicates")]
    success_predicates: Vec<ObjectiveSourcePredicateV1>,
    #[serde(deserialize_with = "predicates")]
    terminal_conditions: Vec<ObjectiveSourcePredicateV1>,
    legal_action_classes: Vec<String>,
    forbidden_action_classes: Vec<String>,
    confirmation_action_classes: Vec<String>,
    #[serde(deserialize_with = "constraints")]
    constraints: Vec<ObjectiveSourceConstraintV1>,
    #[serde(deserialize_with = "dimensions")]
    soft_dimensions: Vec<ObjectiveSoftDimensionV1>,
    #[serde(deserialize_with = "requirements")]
    evidence_requirements: Vec<ObjectiveEvidenceRequirementV1>,
    #[serde(deserialize_with = "Resources::decode")]
    resources: ObjectiveResourcesV1,
    #[serde(deserialize_with = "Risk::decode")]
    risk: ObjectiveRiskV1,
    #[serde(deserialize_with = "Provenance::decode")]
    provenance: ObjectiveProvenanceV1,
}
object_decoder!(Intent, ObjectiveStructuredIntentV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveSourcePredicateV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Predicate {
    predicate_id: String,
    unit: String,
    #[serde(deserialize_with = "shape::predicate_comparator")]
    comparator: ObjectivePredicateComparatorV1,
    bound_q32: i64,
    evidence_source_id: String,
    terminal: bool,
}
object_decoder!(Predicate, ObjectiveSourcePredicateV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveSourceConstraintV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Constraint {
    constraint_id: String,
    unit: String,
    #[serde(deserialize_with = "shape::constraint_comparator")]
    comparator: ObjectiveConstraintComparatorV1,
    bound_q32: i64,
    evidence_source_id: String,
    terminal: bool,
}
object_decoder!(Constraint, ObjectiveSourceConstraintV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveSoftDimensionV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Dimension {
    dimension_id: String,
    unit: String,
    #[serde(deserialize_with = "shape::direction")]
    direction: ObjectiveSoftDirectionV1,
    minimum_weight_q32: i64,
    maximum_weight_q32: i64,
}
object_decoder!(Dimension, ObjectiveSoftDimensionV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveEvidenceRequirementV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Requirement {
    requirement_id: String,
    evidence_source_id: String,
    minimum_confidence_ppm: u32,
    terminal: bool,
}
object_decoder!(Requirement, ObjectiveEvidenceRequirementV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveResourcesV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Resources {
    time_micros: u64,
    token_count: u64,
    compute_micros: u64,
    memory_bytes: u64,
    network_bytes: u64,
    external_effect_count: u32,
}
object_decoder!(Resources, ObjectiveResourcesV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveRiskV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Risk {
    #[serde(deserialize_with = "shape::risk")]
    risk_class: ObjectiveRiskClassV1,
    abstention_rule: String,
    #[serde(deserialize_with = "shape::rollback")]
    rollback_class: ObjectiveRollbackClassV1,
    compensation_required: bool,
}
object_decoder!(Risk, ObjectiveRiskV1);

#[derive(Deserialize)]
#[serde(
    remote = "ObjectiveProvenanceV1",
    rename_all = "camelCase",
    deny_unknown_fields
)]
struct Provenance {
    #[serde(deserialize_with = "shape::digest")]
    source_digest: Digest32,
    #[serde(deserialize_with = "shape::digest")]
    normalization_profile_digest: Digest32,
}
object_decoder!(Provenance, ObjectiveProvenanceV1);

// Only these private wrappers implement Deserialize; the source models do not.
macro_rules! object_items {
    ($function:ident, $wrapper:ident, $model:ident, $decode:literal) => {
        #[derive(Deserialize)]
        struct $wrapper(#[serde(deserialize_with = $decode)] $model);

        fn $function<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<$model>, D::Error> {
            Vec::<$wrapper>::deserialize(d)
                .map(|items| items.into_iter().map(|item| item.0).collect())
        }
    };
}
object_items!(
    predicates,
    PredicateItem,
    ObjectiveSourcePredicateV1,
    "Predicate::decode"
);
object_items!(
    constraints,
    ConstraintItem,
    ObjectiveSourceConstraintV1,
    "Constraint::decode"
);
object_items!(
    dimensions,
    DimensionItem,
    ObjectiveSoftDimensionV1,
    "Dimension::decode"
);
object_items!(
    requirements,
    RequirementItem,
    ObjectiveEvidenceRequirementV1,
    "Requirement::decode"
);
