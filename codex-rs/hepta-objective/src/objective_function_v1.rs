//! Canonical ObjectiveFunctionV1 protocol projection.
//!
//! The compiler keeps a compact owner-native semantic identity for deterministic
//! execution. This adapter separately materializes the registered canonical JSON
//! protocol from the admitted source, frozen profile, admission receipt and
//! compiled native objective. The two digests are deliberately distinct.

use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveAdmissionReceiptV1;
use crate::ObjectiveCompileReceipt;
use crate::ObjectiveSourceEnvelopeV1;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SuccessPredicate;
use crate::canonical_native_objective_semantic_bytes_v1;

pub const MAX_OBJECTIVE_FUNCTION_V1_BYTES: usize = 256 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveFunctionV1Artifact {
    canonical_bytes: Vec<u8>,
    protocol_digest: Digest32,
    native_semantic_digest: Digest32,
}

impl ObjectiveFunctionV1Artifact {
    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    #[must_use]
    pub const fn protocol_digest(&self) -> Digest32 {
        self.protocol_digest
    }

    #[must_use]
    pub const fn native_semantic_digest(&self) -> Digest32 {
        self.native_semantic_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecodedObjectiveFunctionV1 {
    canonical_bytes: Vec<u8>,
    protocol_digest: Digest32,
}

impl DecodedObjectiveFunctionV1 {
    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    #[must_use]
    pub const fn protocol_digest(&self) -> Digest32 {
        self.protocol_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveFunctionV1Error {
    Json,
    NonCanonicalEncoding,
    Capacity,
    InvalidField(&'static str),
    ProjectionMismatch(&'static str),
}

impl fmt::Display for ObjectiveFunctionV1Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ObjectiveFunctionV1Error {}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ObjectiveFunctionWireV1 {
    objective_id: String,
    request_digest: String,
    principal_scope: PrincipalScopeWireV1,
    success_predicates: Vec<PredicateWireV1>,
    terminal_conditions: Vec<PredicateWireV1>,
    hard_constraints: Vec<ConstraintWireV1>,
    evidence_requirements: Vec<EvidenceRequirementWireV1>,
    allowed_action_classes: Vec<ActionWireV1>,
    forbidden_action_classes: Vec<String>,
    soft_utility_dimensions: Vec<SoftDimensionWireV1>,
    resource_endowment: ResourceEndowmentWireV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    deadline_unix_ms: Option<u64>,
    revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PrincipalScopeWireV1 {
    scope_id: String,
    scope_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PredicateWireV1 {
    id: String,
    axis: String,
    relation: String,
    bound_q32: i64,
    evidence_source: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ConstraintWireV1 {
    id: String,
    class: String,
    axis: String,
    relation: String,
    bound_q32: i64,
    evidence_source: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceRequirementWireV1 {
    id: String,
    axis: String,
    minimum_confidence_ppm: u32,
    evidence_source: String,
    terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ActionWireV1 {
    id: String,
    confirmation: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SoftDimensionWireV1 {
    dimension: String,
    direction: String,
    weight_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourceEndowmentWireV1 {
    time_micros: u64,
    token_count: u64,
    compute_micros: u64,
    memory_bytes: u64,
    network_bytes: u64,
    external_effect_count: u32,
}

pub fn encode_objective_function_v1(
    compiled: &ObjectiveCompileReceipt,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    source
        .validate_structure()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("source structure"))?;
    let profile_digest = profile
        .digest()
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("profile"))?;
    if profile_digest != admission.profile_digest
        || source.intent_digest != admission.intent_digest
        || source.principal_scope_digest != profile.principal_scope_digest
    {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "admission binding",
        ));
    }

    let objective = &compiled.objective;
    if objective.request_id.as_str() != source.request_id
        || objective.principal_scope != profile.principal_scope
        || objective.source_digest != admission.admitted_source_digest
        || objective.schema_digest != source.input_schema_digest
    {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "native objective identity",
        ));
    }
    let native_bytes = canonical_native_objective_semantic_bytes_v1(objective);
    if Digest32::of_bytes(&native_bytes) != objective.semantic_digest {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "native semantic digest",
        ));
    }

    let evidence_ids = source
        .structured_intent
        .evidence_requirements
        .iter()
        .map(|value| value.requirement_id.as_str())
        .collect::<BTreeSet<_>>();
    let mut success_predicates = Vec::new();
    let mut terminal_conditions = Vec::new();
    for predicate in &objective.success_predicates {
        if evidence_ids.contains(predicate.id.as_str()) {
            continue;
        }
        let value = predicate_wire(predicate);
        match predicate.terminality {
            PredicateTerminality::Intermediate => success_predicates.push(value),
            PredicateTerminality::Terminal => terminal_conditions.push(value),
        }
    }

    let mut evidence_requirements = Vec::new();
    for source_requirement in &source.structured_intent.evidence_requirements {
        let predicate = objective
            .success_predicates
            .iter()
            .find(|value| value.id.as_str() == source_requirement.requirement_id)
            .ok_or(ObjectiveFunctionV1Error::ProjectionMismatch(
                "evidence requirement",
            ))?;
        let raw = (i128::from(source_requirement.minimum_confidence_ppm)
            * i128::from(FixedQ32::ONE.raw()))
            / 1_000_000_i128;
        let expected = i64::try_from(raw)
            .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("evidence bound"))?;
        let terminality = if source_requirement.terminal {
            PredicateTerminality::Terminal
        } else {
            PredicateTerminality::Intermediate
        };
        if predicate.bound.raw() != expected
            || predicate.evidence_source.as_str() != source_requirement.evidence_source_id
            || predicate.terminality != terminality
        {
            return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
                "evidence lowering",
            ));
        }
        evidence_requirements.push(EvidenceRequirementWireV1 {
            id: predicate.id.to_string(),
            axis: predicate.axis.to_string(),
            minimum_confidence_ppm: source_requirement.minimum_confidence_ppm,
            evidence_source: predicate.evidence_source.to_string(),
            terminal: source_requirement.terminal,
        });
    }
    evidence_requirements.sort_by(|left, right| left.id.cmp(&right.id));

    let mut forbidden_action_classes = Vec::new();
    for source_action in &source.structured_intent.forbidden_action_classes {
        let mapping = profile
            .actions
            .iter()
            .find(|value| value.source_action_class == *source_action)
            .ok_or(ObjectiveFunctionV1Error::ProjectionMismatch(
                "forbidden action mapping",
            ))?;
        forbidden_action_classes.push(mapping.action_id.to_string());
    }
    forbidden_action_classes.sort();
    forbidden_action_classes.dedup();

    let deadline_unix_ms = match admission.deadline_unix_micros {
        Some(value) if value % 1_000 == 0 => Some(value / 1_000),
        Some(_) => {
            return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
                "deadline precision",
            ));
        }
        None => None,
    };

    let wire = ObjectiveFunctionWireV1 {
        objective_id: objective.request_id.to_string(),
        request_digest: admission.intent_digest.to_string(),
        principal_scope: PrincipalScopeWireV1 {
            scope_id: objective.principal_scope.to_string(),
            scope_digest: source.principal_scope_digest.to_string(),
        },
        success_predicates,
        terminal_conditions,
        hard_constraints: objective.constraints.iter().map(constraint_wire).collect(),
        evidence_requirements,
        allowed_action_classes: objective
            .legal_actions
            .iter()
            .map(|value| ActionWireV1 {
                id: value.id.to_string(),
                confirmation: match value.confirmation {
                    ConfirmationPolicy::NotRequired => "not_required",
                    ConfirmationPolicy::Required => "required",
                }
                .to_string(),
            })
            .collect(),
        forbidden_action_classes,
        soft_utility_dimensions: objective
            .soft_preferences
            .iter()
            .map(|value| SoftDimensionWireV1 {
                dimension: value.dimension.to_string(),
                direction: match value.direction {
                    SoftDirection::Maximize => "maximize",
                    SoftDirection::Minimize => "minimize",
                }
                .to_string(),
                weight_q32: value.weight.raw(),
            })
            .collect(),
        resource_endowment: ResourceEndowmentWireV1 {
            time_micros: source.structured_intent.resources.time_micros,
            token_count: source.structured_intent.resources.token_count,
            compute_micros: source.structured_intent.resources.compute_micros,
            memory_bytes: source.structured_intent.resources.memory_bytes,
            network_bytes: source.structured_intent.resources.network_bytes,
            external_effect_count: source.structured_intent.resources.external_effect_count,
        },
        deadline_unix_ms,
        revision: objective.revision.get(),
    };
    validate_wire(&wire)?;
    let canonical_bytes = serde_json::to_vec(&wire).map_err(|_| ObjectiveFunctionV1Error::Json)?;
    if canonical_bytes.len() > MAX_OBJECTIVE_FUNCTION_V1_BYTES {
        return Err(ObjectiveFunctionV1Error::Capacity);
    }
    let protocol_digest = Digest32::of_bytes(&canonical_bytes);
    let decoded = decode_objective_function_v1(&canonical_bytes)?;
    if decoded.protocol_digest != protocol_digest || decoded.canonical_bytes != canonical_bytes {
        return Err(ObjectiveFunctionV1Error::NonCanonicalEncoding);
    }
    Ok(ObjectiveFunctionV1Artifact {
        canonical_bytes,
        protocol_digest,
        native_semantic_digest: objective.semantic_digest,
    })
}

pub fn decode_objective_function_v1(
    input: &[u8],
) -> Result<DecodedObjectiveFunctionV1, ObjectiveFunctionV1Error> {
    if input.is_empty() || input.len() > MAX_OBJECTIVE_FUNCTION_V1_BYTES {
        return Err(ObjectiveFunctionV1Error::Capacity);
    }
    let value: ObjectiveFunctionWireV1 =
        serde_json::from_slice(input).map_err(|_| ObjectiveFunctionV1Error::Json)?;
    validate_wire(&value)?;
    let canonical = serde_json::to_vec(&value).map_err(|_| ObjectiveFunctionV1Error::Json)?;
    if canonical != input {
        return Err(ObjectiveFunctionV1Error::NonCanonicalEncoding);
    }
    Ok(DecodedObjectiveFunctionV1 {
        protocol_digest: Digest32::of_bytes(&canonical),
        canonical_bytes: canonical,
    })
}

fn validate_wire(value: &ObjectiveFunctionWireV1) -> Result<(), ObjectiveFunctionV1Error> {
    stable_id(&value.objective_id, "objectiveId")?;
    digest(&value.request_digest, "requestDigest")?;
    stable_id(&value.principal_scope.scope_id, "principalScope.scopeId")?;
    digest(
        &value.principal_scope.scope_digest,
        "principalScope.scopeDigest",
    )?;
    if value.hard_constraints.len() > 256
        || value.success_predicates.len()
            + value.terminal_conditions.len()
            + value.evidence_requirements.len()
            > 128
        || value.allowed_action_classes.len() > 128
        || value.forbidden_action_classes.len() > 128
        || value.soft_utility_dimensions.len() > 64
    {
        return Err(ObjectiveFunctionV1Error::Capacity);
    }
    for predicate in value
        .success_predicates
        .iter()
        .chain(value.terminal_conditions.iter())
    {
        stable_id(&predicate.id, "predicate.id")?;
        stable_id(&predicate.axis, "predicate.axis")?;
        stable_id(&predicate.evidence_source, "predicate.evidenceSource")?;
        relation(&predicate.relation)?;
    }
    for constraint in &value.hard_constraints {
        stable_id(&constraint.id, "constraint.id")?;
        stable_id(&constraint.axis, "constraint.axis")?;
        stable_id(&constraint.evidence_source, "constraint.evidenceSource")?;
        relation(&constraint.relation)?;
        match constraint.class.as_str() {
            "constitutional" | "principal" | "environment" | "task" => {}
            _ => return Err(ObjectiveFunctionV1Error::InvalidField("constraint.class")),
        }
    }
    for evidence in &value.evidence_requirements {
        stable_id(&evidence.id, "evidence.id")?;
        stable_id(&evidence.axis, "evidence.axis")?;
        stable_id(&evidence.evidence_source, "evidence.evidenceSource")?;
        if evidence.minimum_confidence_ppm > 1_000_000 {
            return Err(ObjectiveFunctionV1Error::InvalidField(
                "evidence.minimumConfidencePpm",
            ));
        }
    }
    for action in &value.allowed_action_classes {
        stable_id(&action.id, "action.id")?;
        match action.confirmation.as_str() {
            "not_required" | "required" => {}
            _ => {
                return Err(ObjectiveFunctionV1Error::InvalidField(
                    "action.confirmation",
                ));
            }
        }
    }
    for action in &value.forbidden_action_classes {
        stable_id(action, "forbiddenActionClasses")?;
    }
    for dimension in &value.soft_utility_dimensions {
        stable_id(&dimension.dimension, "soft.dimension")?;
        match dimension.direction.as_str() {
            "maximize" | "minimize" => {}
            _ => return Err(ObjectiveFunctionV1Error::InvalidField("soft.direction")),
        }
    }
    if value.revision == 0 || value.deadline_unix_ms == Some(0) {
        return Err(ObjectiveFunctionV1Error::InvalidField("revision/deadline"));
    }
    Ok(())
}

fn predicate_wire(value: &SuccessPredicate) -> PredicateWireV1 {
    PredicateWireV1 {
        id: value.id.to_string(),
        axis: value.axis.to_string(),
        relation: relation_name(value.relation).to_string(),
        bound_q32: value.bound.raw(),
        evidence_source: value.evidence_source.to_string(),
    }
}

fn constraint_wire(value: &Constraint) -> ConstraintWireV1 {
    ConstraintWireV1 {
        id: value.id.to_string(),
        class: match value.class {
            ConstraintClass::Constitutional => "constitutional",
            ConstraintClass::Principal => "principal",
            ConstraintClass::Environment => "environment",
            ConstraintClass::Task => "task",
        }
        .to_string(),
        axis: value.axis.to_string(),
        relation: relation_name(value.relation).to_string(),
        bound_q32: value.bound.raw(),
        evidence_source: value.evidence_source.to_string(),
    }
}

const fn relation_name(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "gte",
        ConstraintRelation::AtMost => "lte",
        ConstraintRelation::Equal => "eq",
    }
}

fn relation(value: &str) -> Result<(), ObjectiveFunctionV1Error> {
    match value {
        "gte" | "lte" | "eq" => Ok(()),
        _ => Err(ObjectiveFunctionV1Error::InvalidField("relation")),
    }
}

fn stable_id(value: &str, field: &'static str) -> Result<(), ObjectiveFunctionV1Error> {
    StableId::new(value)
        .map(|_| ())
        .map_err(|_| ObjectiveFunctionV1Error::InvalidField(field))
}

fn digest(value: &str, field: &'static str) -> Result<(), ObjectiveFunctionV1Error> {
    Digest32::from_str(value)
        .map(|_| ())
        .map_err(|_| ObjectiveFunctionV1Error::InvalidField(field))
}
