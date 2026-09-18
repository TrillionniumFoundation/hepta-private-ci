//! Exact canonical JSON projection for the registered ObjectiveFunctionV1.
//!
//! The native compiler IR remains owner-local and may contain additional
//! semantics. This projection publishes only the ten fields registered by
//! docs/contracts/PROTOCOL_SCHEMAS.json. Full native semantics remain bound by
//! requestDigest/objectiveId and are persisted alongside this wire object.

use serde::Deserialize;
use serde::Serialize;

use codex_hepta_types::Digest32;

use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::PredicateTerminality;
use crate::SoftDirection;

const MAX_OBJECTIVE_BYTES: usize = 262_144;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveFunctionV1 {
    pub objective_id: String,
    pub request_digest: String,
    pub principal_scope: ObjectivePrincipalScopeWireV1,
    pub success_predicates: Vec<ObjectivePredicateWireV1>,
    pub terminal_conditions: Vec<ObjectivePredicateWireV1>,
    pub hard_constraints: Vec<ObjectiveConstraintWireV1>,
    pub soft_utility_dimensions: Vec<ObjectiveSoftDimensionWireV1>,
    pub resource_endowment: ObjectiveResourcesWireV1,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deadline_unix_ms: Option<u64>,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectivePrincipalScopeWireV1 {
    pub scope_id: String,
    pub source_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectivePredicateWireV1 {
    pub predicate_id: String,
    pub axis: String,
    pub relation: String,
    pub bound_q32: i64,
    pub evidence_source_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveConstraintWireV1 {
    pub constraint_id: String,
    pub class: String,
    pub axis: String,
    pub relation: String,
    pub bound_q32: i64,
    pub evidence_source_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveSoftDimensionWireV1 {
    pub dimension_id: String,
    pub direction: String,
    pub weight_q32: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveResourcesWireV1 {
    pub time_micros: u64,
    pub token_count: u64,
    pub compute_micros: u64,
    pub memory_bytes: u64,
    pub network_bytes: u64,
    pub external_effect_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveProjectionError {
    Conflict,
    BindingMismatch(&'static str),
    DeadlinePrecision,
    InvalidDigest(&'static str),
    FieldTooLarge(&'static str),
    EncodedTooLarge,
    Encoding,
    NonCanonicalEncoding,
}

impl std::fmt::Display for ObjectiveProjectionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Conflict => formatter.write_str("objective conflict has no ObjectiveFunctionV1"),
            Self::BindingMismatch(field) => {
                write!(formatter, "objective projection binding mismatch: {field}")
            }
            Self::DeadlinePrecision => {
                formatter.write_str("V1 deadlineUnixMs cannot represent sub-millisecond deadline")
            }
            Self::InvalidDigest(field) => write!(formatter, "invalid {field} digest"),
            Self::FieldTooLarge(field) => write!(formatter, "{field} exceeds V1 encoded bound"),
            Self::EncodedTooLarge => formatter.write_str("ObjectiveFunctionV1 exceeds 262144 bytes"),
            Self::Encoding => formatter.write_str("ObjectiveFunctionV1 JSON encoding failed"),
            Self::NonCanonicalEncoding => {
                formatter.write_str("ObjectiveFunctionV1 bytes are not canonical")
            }
        }
    }
}

impl std::error::Error for ObjectiveProjectionError {}

impl ObjectiveFunctionV1 {
    pub fn canonical_json(&self) -> Result<Vec<u8>, ObjectiveProjectionError> {
        self.validate_bounds()?;
        let bytes = serde_json::to_vec(self).map_err(|_| ObjectiveProjectionError::Encoding)?;
        if bytes.len() > MAX_OBJECTIVE_BYTES {
            return Err(ObjectiveProjectionError::EncodedTooLarge);
        }
        Ok(bytes)
    }

    pub fn digest(&self) -> Result<Digest32, ObjectiveProjectionError> {
        Ok(Digest32::of_bytes(&self.canonical_json()?))
    }

    pub fn from_canonical_json(input: &[u8]) -> Result<Self, ObjectiveProjectionError> {
        if input.len() > MAX_OBJECTIVE_BYTES {
            return Err(ObjectiveProjectionError::EncodedTooLarge);
        }
        let value: Self =
            serde_json::from_slice(input).map_err(|_| ObjectiveProjectionError::Encoding)?;
        let canonical = value.canonical_json()?;
        if canonical != input {
            return Err(ObjectiveProjectionError::NonCanonicalEncoding);
        }
        Ok(value)
    }

    fn validate_bounds(&self) -> Result<(), ObjectiveProjectionError> {
        if self.objective_id.as_bytes().len() > 128 {
            return Err(ObjectiveProjectionError::FieldTooLarge("objectiveId"));
        }
        if !sha256_text(&self.request_digest) {
            return Err(ObjectiveProjectionError::InvalidDigest("request"));
        }
        if !sha256_text(&self.principal_scope.source_digest) {
            return Err(ObjectiveProjectionError::InvalidDigest("principal scope"));
        }
        bounded_json("principalScope", &self.principal_scope, 4_096)?;
        bounded_json("successPredicates", &self.success_predicates, 32_768)?;
        bounded_json("terminalConditions", &self.terminal_conditions, 16_384)?;
        bounded_json("hardConstraints", &self.hard_constraints, 32_768)?;
        bounded_json(
            "softUtilityDimensions",
            &self.soft_utility_dimensions,
            16_384,
        )?;
        bounded_json("resourceEndowment", &self.resource_endowment, 8_192)?;
        Ok(())
    }
}

pub fn project_objective_function_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    outcome: &ObjectiveAdmissionOutcomeV1,
) -> Result<ObjectiveFunctionV1, ObjectiveProjectionError> {
    let compile = outcome
        .compile_result
        .as_ref()
        .map_err(|_| ObjectiveProjectionError::Conflict)?;
    let objective = &compile.objective;
    if objective.request_id.as_str() != envelope.request_id {
        return Err(ObjectiveProjectionError::BindingMismatch("requestId"));
    }
    if outcome.receipt.intent_digest != envelope.intent_digest {
        return Err(ObjectiveProjectionError::BindingMismatch("requestDigest"));
    }
    if outcome.receipt.admitted_source_digest != objective.source_digest {
        return Err(ObjectiveProjectionError::BindingMismatch(
            "admittedSourceDigest",
        ));
    }
    let deadline_unix_ms = match outcome.receipt.deadline_unix_micros {
        Some(value) if value % 1_000 != 0 => {
            return Err(ObjectiveProjectionError::DeadlinePrecision);
        }
        Some(value) => Some(value / 1_000),
        None => None,
    };

    let mut success_predicates = Vec::new();
    let mut terminal_conditions = Vec::new();
    for value in &objective.success_predicates {
        let projected = ObjectivePredicateWireV1 {
            predicate_id: value.id.to_string(),
            axis: value.axis.to_string(),
            relation: relation(value.relation).to_string(),
            bound_q32: value.bound.raw(),
            evidence_source_id: value.evidence_source.to_string(),
        };
        match value.terminality {
            PredicateTerminality::Intermediate => success_predicates.push(projected),
            PredicateTerminality::Terminal => terminal_conditions.push(projected),
        }
    }

    let value = ObjectiveFunctionV1 {
        objective_id: format!("objective.{}", objective.semantic_digest),
        request_digest: outcome.receipt.intent_digest.to_string(),
        principal_scope: ObjectivePrincipalScopeWireV1 {
            scope_id: objective.principal_scope.to_string(),
            source_digest: envelope.principal_scope_digest.to_string(),
        },
        success_predicates,
        terminal_conditions,
        hard_constraints: objective
            .constraints
            .iter()
            .map(|value| ObjectiveConstraintWireV1 {
                constraint_id: value.id.to_string(),
                class: constraint_class(value.class).to_string(),
                axis: value.axis.to_string(),
                relation: relation(value.relation).to_string(),
                bound_q32: value.bound.raw(),
                evidence_source_id: value.evidence_source.to_string(),
            })
            .collect(),
        soft_utility_dimensions: objective
            .soft_preferences
            .iter()
            .map(|value| ObjectiveSoftDimensionWireV1 {
                dimension_id: value.dimension.to_string(),
                direction: soft_direction(value.direction).to_string(),
                weight_q32: value.weight.raw(),
            })
            .collect(),
        resource_endowment: ObjectiveResourcesWireV1 {
            time_micros: envelope.structured_intent.resources.time_micros,
            token_count: envelope.structured_intent.resources.token_count,
            compute_micros: envelope.structured_intent.resources.compute_micros,
            memory_bytes: envelope.structured_intent.resources.memory_bytes,
            network_bytes: envelope.structured_intent.resources.network_bytes,
            external_effect_count: envelope.structured_intent.resources.external_effect_count,
        },
        deadline_unix_ms,
        revision: objective.revision.get(),
    };
    value.validate_bounds()?;
    Ok(value)
}

fn bounded_json<T: Serialize>(
    field: &'static str,
    value: &T,
    maximum: usize,
) -> Result<(), ObjectiveProjectionError> {
    let encoded = serde_json::to_vec(value).map_err(|_| ObjectiveProjectionError::Encoding)?;
    if encoded.len() > maximum {
        return Err(ObjectiveProjectionError::FieldTooLarge(field));
    }
    Ok(())
}

fn sha256_text(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

const fn relation(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "at_least",
        ConstraintRelation::AtMost => "at_most",
        ConstraintRelation::Equal => "equal",
    }
}

const fn constraint_class(value: ConstraintClass) -> &'static str {
    match value {
        ConstraintClass::Constitutional => "constitutional",
        ConstraintClass::Principal => "principal",
        ConstraintClass::Environment => "environment",
        ConstraintClass::Task => "task",
    }
}

const fn soft_direction(value: SoftDirection) -> &'static str {
    match value {
        SoftDirection::Maximize => "maximize",
        SoftDirection::Minimize => "minimize",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_decode_rejects_reformatted_or_unknown_json() {
        let value = ObjectiveFunctionV1 {
            objective_id: "objective.example".to_string(),
            request_digest: "a".repeat(64),
            principal_scope: ObjectivePrincipalScopeWireV1 {
                scope_id: "scope".to_string(),
                source_digest: "b".repeat(64),
            },
            success_predicates: Vec::new(),
            terminal_conditions: Vec::new(),
            hard_constraints: Vec::new(),
            soft_utility_dimensions: Vec::new(),
            resource_endowment: ObjectiveResourcesWireV1 {
                time_micros: 1,
                token_count: 1,
                compute_micros: 1,
                memory_bytes: 1,
                network_bytes: 1,
                external_effect_count: 0,
            },
            deadline_unix_ms: None,
            revision: 1,
        };
        let canonical = value.canonical_json().expect("canonical");
        assert_eq!(
            ObjectiveFunctionV1::from_canonical_json(&canonical).expect("decode"),
            value
        );
        let mut reformatted = canonical.clone();
        reformatted.insert(1, b' ');
        assert_eq!(
            ObjectiveFunctionV1::from_canonical_json(&reformatted),
            Err(ObjectiveProjectionError::NonCanonicalEncoding)
        );
    }
}
