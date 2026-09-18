//! Canonical ObjectiveFunctionV1 projection.
//!
//! The native compiler IR deliberately stays owner-local.  This module is the
//! single wire projection from an admitted V1 source plus its successful
//! compile outcome.  It preserves source semantics that are not represented as
//! first-class native compiler rows (terminal conditions, evidence requirements,
//! resources and risk) instead of inventing a second objective definition.

use std::fmt;

use serde::Serialize;

use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveEvidenceRequirementV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceConstraintV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourcePredicateV1;
use crate::ObjectiveSourceTrustV1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveFunctionV1 {
    pub objective_id: String,
    pub request_id: String,
    pub request_digest: String,
    pub principal_scope: String,
    pub revision: u64,
    pub source_trust_class: &'static str,
    pub locale: String,
    pub observed_at_unix_micros: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deadline_unix_micros: Option<u64>,
    pub success_predicates: Vec<ObjectivePredicateWireV1>,
    pub terminal_conditions: Vec<ObjectivePredicateWireV1>,
    pub hard_constraints: Vec<ObjectiveConstraintWireV1>,
    pub evidence_requirements: Vec<ObjectiveEvidenceRequirementWireV1>,
    pub allowed_action_classes: Vec<String>,
    pub forbidden_action_classes: Vec<String>,
    pub confirmation_action_classes: Vec<String>,
    pub soft_utility_dimensions: Vec<ObjectiveSoftDimensionWireV1>,
    pub resource_endowment: ObjectiveResourcesWireV1,
    pub risk_profile: ObjectiveRiskWireV1,
    pub source_digest: String,
    pub input_schema_digest: String,
    pub normalization_profile_digest: String,
    pub hard_constraint_digest: String,
    pub semantic_digest: String,
}

impl ObjectiveFunctionV1 {
    /// Struct field order is the registered V1 canonical JSON field order.
    /// Every nested value is an object/array/scalar; no map ordering is left to
    /// a caller.
    pub fn canonical_json(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(self)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectivePredicateWireV1 {
    pub predicate_id: String,
    pub unit: String,
    pub comparator: &'static str,
    pub bound_q32: i64,
    pub evidence_source_id: String,
    pub terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveConstraintWireV1 {
    pub constraint_id: String,
    pub unit: String,
    pub comparator: &'static str,
    pub bound_q32: i64,
    pub evidence_source_id: String,
    pub terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveEvidenceRequirementWireV1 {
    pub requirement_id: String,
    pub evidence_source_id: String,
    pub minimum_confidence_ppm: u32,
    pub terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveSoftDimensionWireV1 {
    pub dimension_id: String,
    pub unit: String,
    pub direction: &'static str,
    pub minimum_weight_q32: i64,
    pub maximum_weight_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveResourcesWireV1 {
    pub time_micros: u64,
    pub token_count: u64,
    pub compute_micros: u64,
    pub memory_bytes: u64,
    pub network_bytes: u64,
    pub external_effect_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveRiskWireV1 {
    pub risk_class: &'static str,
    pub abstention_rule: String,
    pub rollback_class: &'static str,
    pub compensation_required: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveProjectionError {
    Conflict,
    BindingMismatch(&'static str),
}

impl fmt::Display for ObjectiveProjectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Conflict => formatter.write_str("objective conflict has no ObjectiveFunctionV1"),
            Self::BindingMismatch(field) => write!(formatter, "objective projection binding mismatch: {field}"),
        }
    }
}

impl std::error::Error for ObjectiveProjectionError {}

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
    if outcome.receipt.supplied_source_digest != envelope.structured_intent.provenance.source_digest {
        return Err(ObjectiveProjectionError::BindingMismatch("sourceDigest"));
    }
    if outcome.receipt.admitted_source_digest != objective.source_digest {
        return Err(ObjectiveProjectionError::BindingMismatch("admittedSourceDigest"));
    }

    let intent = &envelope.structured_intent;
    Ok(ObjectiveFunctionV1 {
        objective_id: format!("objective.{}", objective.semantic_digest),
        request_id: envelope.request_id.clone(),
        request_digest: outcome.receipt.intent_digest.to_string(),
        principal_scope: objective.principal_scope.to_string(),
        revision: objective.revision.get(),
        source_trust_class: source_trust(envelope.source_trust_class),
        locale: envelope.locale.clone(),
        observed_at_unix_micros: outcome.receipt.observed_at_unix_micros,
        deadline_unix_micros: outcome.receipt.deadline_unix_micros,
        success_predicates: intent.success_predicates.iter().map(predicate).collect(),
        terminal_conditions: intent.terminal_conditions.iter().map(predicate).collect(),
        hard_constraints: intent.constraints.iter().map(constraint).collect(),
        evidence_requirements: intent.evidence_requirements.iter().map(requirement).collect(),
        allowed_action_classes: intent.legal_action_classes.clone(),
        forbidden_action_classes: intent.forbidden_action_classes.clone(),
        confirmation_action_classes: intent.confirmation_action_classes.clone(),
        soft_utility_dimensions: intent
            .soft_dimensions
            .iter()
            .map(|value| ObjectiveSoftDimensionWireV1 {
                dimension_id: value.dimension_id.clone(),
                unit: value.unit.clone(),
                direction: soft_direction(value.direction),
                minimum_weight_q32: value.minimum_weight_q32,
                maximum_weight_q32: value.maximum_weight_q32,
            })
            .collect(),
        resource_endowment: ObjectiveResourcesWireV1 {
            time_micros: intent.resources.time_micros,
            token_count: intent.resources.token_count,
            compute_micros: intent.resources.compute_micros,
            memory_bytes: intent.resources.memory_bytes,
            network_bytes: intent.resources.network_bytes,
            external_effect_count: intent.resources.external_effect_count,
        },
        risk_profile: ObjectiveRiskWireV1 {
            risk_class: risk_class(intent.risk.risk_class),
            abstention_rule: intent.risk.abstention_rule.clone(),
            rollback_class: rollback_class(intent.risk.rollback_class),
            compensation_required: intent.risk.compensation_required,
        },
        source_digest: outcome.receipt.admitted_source_digest.to_string(),
        input_schema_digest: envelope.input_schema_digest.to_string(),
        normalization_profile_digest: intent.provenance.normalization_profile_digest.to_string(),
        hard_constraint_digest: objective.hard_constraint_digest.to_string(),
        semantic_digest: objective.semantic_digest.to_string(),
    })
}

fn predicate(value: &ObjectiveSourcePredicateV1) -> ObjectivePredicateWireV1 {
    ObjectivePredicateWireV1 {
        predicate_id: value.predicate_id.clone(),
        unit: value.unit.clone(),
        comparator: predicate_comparator(value.comparator),
        bound_q32: value.bound_q32,
        evidence_source_id: value.evidence_source_id.clone(),
        terminal: value.terminal,
    }
}

fn constraint(value: &ObjectiveSourceConstraintV1) -> ObjectiveConstraintWireV1 {
    ObjectiveConstraintWireV1 {
        constraint_id: value.constraint_id.clone(),
        unit: value.unit.clone(),
        comparator: constraint_comparator(value.comparator),
        bound_q32: value.bound_q32,
        evidence_source_id: value.evidence_source_id.clone(),
        terminal: value.terminal,
    }
}

fn requirement(value: &ObjectiveEvidenceRequirementV1) -> ObjectiveEvidenceRequirementWireV1 {
    ObjectiveEvidenceRequirementWireV1 {
        requirement_id: value.requirement_id.clone(),
        evidence_source_id: value.evidence_source_id.clone(),
        minimum_confidence_ppm: value.minimum_confidence_ppm,
        terminal: value.terminal,
    }
}

const fn predicate_comparator(value: ObjectivePredicateComparatorV1) -> &'static str {
    match value {
        ObjectivePredicateComparatorV1::Equal => "eq",
        ObjectivePredicateComparatorV1::NotEqual => "ne",
        ObjectivePredicateComparatorV1::LessThan => "lt",
        ObjectivePredicateComparatorV1::LessThanOrEqual => "lte",
        ObjectivePredicateComparatorV1::GreaterThan => "gt",
        ObjectivePredicateComparatorV1::GreaterThanOrEqual => "gte",
    }
}

const fn constraint_comparator(value: ObjectiveConstraintComparatorV1) -> &'static str {
    match value {
        ObjectiveConstraintComparatorV1::Equal => "eq",
        ObjectiveConstraintComparatorV1::NotEqual => "ne",
        ObjectiveConstraintComparatorV1::LessThan => "lt",
        ObjectiveConstraintComparatorV1::LessThanOrEqual => "lte",
        ObjectiveConstraintComparatorV1::GreaterThan => "gt",
        ObjectiveConstraintComparatorV1::GreaterThanOrEqual => "gte",
        ObjectiveConstraintComparatorV1::In => "in",
        ObjectiveConstraintComparatorV1::NotInSet => "not_in",
    }
}

const fn soft_direction(value: ObjectiveSoftDirectionV1) -> &'static str {
    match value {
        ObjectiveSoftDirectionV1::Maximize => "maximize",
        ObjectiveSoftDirectionV1::Minimize => "minimize",
    }
}

const fn risk_class(value: ObjectiveRiskClassV1) -> &'static str {
    match value {
        ObjectiveRiskClassV1::Low => "low",
        ObjectiveRiskClassV1::Medium => "medium",
        ObjectiveRiskClassV1::High => "high",
        ObjectiveRiskClassV1::Critical => "critical",
    }
}

const fn rollback_class(value: ObjectiveRollbackClassV1) -> &'static str {
    match value {
        ObjectiveRollbackClassV1::None => "none",
        ObjectiveRollbackClassV1::Reversible => "reversible",
        ObjectiveRollbackClassV1::Compensatable => "compensatable",
        ObjectiveRollbackClassV1::Irreversible => "irreversible",
    }
}

const fn source_trust(value: ObjectiveSourceTrustV1) -> &'static str {
    match value {
        ObjectiveSourceTrustV1::Principal => "principal",
        ObjectiveSourceTrustV1::TrustedSystem => "trusted_system",
        ObjectiveSourceTrustV1::AuthorizedAdapter => "authorized_adapter",
        ObjectiveSourceTrustV1::UntrustedEvidence => "untrusted_evidence",
    }
}
