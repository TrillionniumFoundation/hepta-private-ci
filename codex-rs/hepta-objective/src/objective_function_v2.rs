//! Canonical objective publication contract.
//!
//! V1 remains readable for historical compatibility, but it cannot encode the
//! complete immutable objective core. V2 publishes every security-relevant
//! source semantic explicitly and binds it to the deterministic compiled IR.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::ActionClass;
use crate::CompileDisposition;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectiveEvidenceRequirementV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SuccessPredicate;

pub const OBJECTIVE_FUNCTION_WIRE_SCHEMA_V2: &str = "ObjectiveFunctionV2";
pub const OBJECTIVE_SOURCE_WIRE_SCHEMA_V2: &str = "ObjectiveSourceEnvelopeV2";

/// V2 intentionally keeps the V1 field grammar while correcting its published
/// capacity semantics. New product callers must use the V2 entrypoint/name.
pub type ObjectiveSourceEnvelopeV2 = ObjectiveSourceEnvelopeV1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectivePrincipalScopeV2 {
    pub scope_id: String,
    pub scope_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectivePredicateWireV2 {
    pub predicate_id: String,
    pub unit: String,
    pub comparator: String,
    pub bound_q32: i64,
    pub evidence_source_id: String,
    pub terminal: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveHardConstraintWireV2 {
    pub constraint_id: String,
    pub class: String,
    pub axis: String,
    pub relation: String,
    pub bound_q32: i64,
    pub evidence_source_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveEvidenceRequirementWireV2 {
    pub requirement_id: String,
    pub evidence_source_id: String,
    pub minimum_confidence_ppm: u32,
    pub terminal: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveActionWireV2 {
    pub action_id: String,
    pub confirmation_required: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveSoftDimensionWireV2 {
    pub dimension_id: String,
    pub unit: String,
    pub direction: String,
    pub minimum_weight_q32: i64,
    pub maximum_weight_q32: i64,
    pub selected_weight_q32: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveResourcesWireV2 {
    pub time_micros: u64,
    pub token_count: u64,
    pub compute_micros: u64,
    pub memory_bytes: u64,
    pub network_bytes: u64,
    pub external_effect_count: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveRiskWireV2 {
    pub risk_class: String,
    pub abstention_rule: String,
    pub rollback_class: String,
    pub compensation_required: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ObjectiveFunctionV2 {
    pub schema: String,
    pub objective_id: String,
    pub request_id: String,
    pub intent_digest: String,
    pub admitted_source_digest: String,
    pub principal_scope: ObjectivePrincipalScopeV2,
    pub success_predicates: Vec<ObjectivePredicateWireV2>,
    pub terminal_conditions: Vec<ObjectivePredicateWireV2>,
    pub hard_constraints: Vec<ObjectiveHardConstraintWireV2>,
    pub evidence_requirements: Vec<ObjectiveEvidenceRequirementWireV2>,
    pub allowed_action_classes: Vec<ObjectiveActionWireV2>,
    pub forbidden_action_classes: Vec<String>,
    pub soft_utility_dimensions: Vec<ObjectiveSoftDimensionWireV2>,
    pub resource_endowment: ObjectiveResourcesWireV2,
    pub risk: ObjectiveRiskWireV2,
    pub deadline_unix_micros: Option<u64>,
    pub revision: u64,
    pub compiled_hard_constraint_digest: String,
    pub compiled_semantic_digest: String,
    pub disposition: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveProjectionErrorV2 {
    ConflictOutcome,
    SourceCompileIdentityMismatch,
    MissingSelectedSoftDimension(String),
}

impl std::fmt::Display for ObjectiveProjectionErrorV2 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ObjectiveProjectionErrorV2 {}

pub fn project_objective_function_v2(
    envelope: &ObjectiveSourceEnvelopeV2,
    outcome: &ObjectiveAdmissionOutcomeV1,
) -> Result<ObjectiveFunctionV2, ObjectiveProjectionErrorV2> {
    let compile = outcome
        .compile_result
        .as_ref()
        .map_err(|_| ObjectiveProjectionErrorV2::ConflictOutcome)?;
    let objective = &compile.objective;
    if objective.request_id.as_str() != envelope.request_id
        || objective.source_digest != outcome.receipt.admitted_source_digest
    {
        return Err(ObjectiveProjectionErrorV2::SourceCompileIdentityMismatch);
    }

    let mut soft_utility_dimensions = Vec::with_capacity(envelope.structured_intent.soft_dimensions.len());
    for source in &envelope.structured_intent.soft_dimensions {
        let selected = objective
            .soft_preferences
            .iter()
            .find(|value| value.dimension.as_str() == source.dimension_id)
            .ok_or_else(|| ObjectiveProjectionErrorV2::MissingSelectedSoftDimension(source.dimension_id.clone()))?;
        soft_utility_dimensions.push(ObjectiveSoftDimensionWireV2 {
            dimension_id: source.dimension_id.clone(),
            unit: source.unit.clone(),
            direction: soft_direction(source.direction).to_string(),
            minimum_weight_q32: source.minimum_weight_q32,
            maximum_weight_q32: source.maximum_weight_q32,
            selected_weight_q32: selected.weight.raw(),
        });
    }

    let objective_id = format!("objective.{}", objective.semantic_digest);
    Ok(ObjectiveFunctionV2 {
        schema: OBJECTIVE_FUNCTION_WIRE_SCHEMA_V2.to_string(),
        objective_id,
        request_id: envelope.request_id.clone(),
        intent_digest: outcome.receipt.intent_digest.to_string(),
        admitted_source_digest: outcome.receipt.admitted_source_digest.to_string(),
        principal_scope: ObjectivePrincipalScopeV2 {
            scope_id: objective.principal_scope.as_str().to_string(),
            scope_digest: envelope.principal_scope_digest.to_string(),
        },
        success_predicates: envelope
            .structured_intent
            .success_predicates
            .iter()
            .map(predicate_wire)
            .collect(),
        terminal_conditions: envelope
            .structured_intent
            .terminal_conditions
            .iter()
            .map(predicate_wire)
            .collect(),
        hard_constraints: objective.constraints.iter().map(constraint_wire).collect(),
        evidence_requirements: envelope
            .structured_intent
            .evidence_requirements
            .iter()
            .map(evidence_wire)
            .collect(),
        allowed_action_classes: objective.legal_actions.iter().map(action_wire).collect(),
        forbidden_action_classes: envelope.structured_intent.forbidden_action_classes.clone(),
        soft_utility_dimensions,
        resource_endowment: ObjectiveResourcesWireV2 {
            time_micros: envelope.structured_intent.resources.time_micros,
            token_count: envelope.structured_intent.resources.token_count,
            compute_micros: envelope.structured_intent.resources.compute_micros,
            memory_bytes: envelope.structured_intent.resources.memory_bytes,
            network_bytes: envelope.structured_intent.resources.network_bytes,
            external_effect_count: envelope.structured_intent.resources.external_effect_count,
        },
        risk: ObjectiveRiskWireV2 {
            risk_class: risk_class(envelope.structured_intent.risk.risk_class).to_string(),
            abstention_rule: envelope.structured_intent.risk.abstention_rule.clone(),
            rollback_class: rollback_class(envelope.structured_intent.risk.rollback_class).to_string(),
            compensation_required: envelope.structured_intent.risk.compensation_required,
        },
        deadline_unix_micros: outcome.receipt.deadline_unix_micros,
        revision: objective.revision.get(),
        compiled_hard_constraint_digest: objective.hard_constraint_digest.to_string(),
        compiled_semantic_digest: objective.semantic_digest.to_string(),
        disposition: match compile.disposition {
            CompileDisposition::Compiled => "compiled",
            CompileDisposition::ExplicitAbstain => "explicit_abstain",
        }
        .to_string(),
    })
}

pub fn objective_function_v2_digest(
    value: &ObjectiveFunctionV2,
) -> Result<Digest32, serde_json::Error> {
    serde_json::to_vec(value).map(|bytes| Digest32::of_bytes(&bytes))
}

fn predicate_wire(value: &crate::ObjectiveSourcePredicateV1) -> ObjectivePredicateWireV2 {
    ObjectivePredicateWireV2 {
        predicate_id: value.predicate_id.clone(),
        unit: value.unit.clone(),
        comparator: predicate_comparator(value.comparator).to_string(),
        bound_q32: value.bound_q32,
        evidence_source_id: value.evidence_source_id.clone(),
        terminal: value.terminal,
    }
}

fn evidence_wire(value: &ObjectiveEvidenceRequirementV1) -> ObjectiveEvidenceRequirementWireV2 {
    ObjectiveEvidenceRequirementWireV2 {
        requirement_id: value.requirement_id.clone(),
        evidence_source_id: value.evidence_source_id.clone(),
        minimum_confidence_ppm: value.minimum_confidence_ppm,
        terminal: value.terminal,
    }
}

fn constraint_wire(value: &Constraint) -> ObjectiveHardConstraintWireV2 {
    ObjectiveHardConstraintWireV2 {
        constraint_id: value.id.as_str().to_string(),
        class: constraint_class(value.class).to_string(),
        axis: value.axis.as_str().to_string(),
        relation: constraint_relation(value.relation).to_string(),
        bound_q32: value.bound.raw(),
        evidence_source_id: value.evidence_source.as_str().to_string(),
    }
}

fn action_wire(value: &ActionClass) -> ObjectiveActionWireV2 {
    ObjectiveActionWireV2 {
        action_id: value.id.as_str().to_string(),
        confirmation_required: value.confirmation == ConfirmationPolicy::Required,
    }
}

fn predicate_comparator(value: ObjectivePredicateComparatorV1) -> &'static str {
    match value {
        ObjectivePredicateComparatorV1::Equal => "eq",
        ObjectivePredicateComparatorV1::NotEqual => "ne",
        ObjectivePredicateComparatorV1::LessThan => "lt",
        ObjectivePredicateComparatorV1::LessThanOrEqual => "lte",
        ObjectivePredicateComparatorV1::GreaterThan => "gt",
        ObjectivePredicateComparatorV1::GreaterThanOrEqual => "gte",
    }
}

fn constraint_comparator(value: ObjectiveConstraintComparatorV1) -> &'static str {
    match value {
        ObjectiveConstraintComparatorV1::Equal => "eq",
        ObjectiveConstraintComparatorV1::NotEqual => "ne",
        ObjectiveConstraintComparatorV1::LessThan => "lt",
        ObjectiveConstraintComparatorV1::LessThanOrEqual => "lte",
        ObjectiveConstraintComparatorV1::GreaterThan => "gt",
        ObjectiveConstraintComparatorV1::GreaterThanOrEqual => "gte",
        ObjectiveConstraintComparatorV1::In => "in",
        ObjectiveConstraintComparatorV1::NotInSet => "not_in_set",
    }
}

fn soft_direction(value: ObjectiveSoftDirectionV1) -> &'static str {
    match value {
        ObjectiveSoftDirectionV1::Maximize => "maximize",
        ObjectiveSoftDirectionV1::Minimize => "minimize",
    }
}

fn risk_class(value: ObjectiveRiskClassV1) -> &'static str {
    match value {
        ObjectiveRiskClassV1::Low => "low",
        ObjectiveRiskClassV1::Medium => "medium",
        ObjectiveRiskClassV1::High => "high",
        ObjectiveRiskClassV1::Critical => "critical",
    }
}

fn rollback_class(value: ObjectiveRollbackClassV1) -> &'static str {
    match value {
        ObjectiveRollbackClassV1::None => "none",
        ObjectiveRollbackClassV1::Reversible => "reversible",
        ObjectiveRollbackClassV1::Compensatable => "compensatable",
        ObjectiveRollbackClassV1::Irreversible => "irreversible",
    }
}

fn constraint_class(value: ConstraintClass) -> &'static str {
    match value {
        ConstraintClass::Constitutional => "constitutional",
        ConstraintClass::Principal => "principal",
        ConstraintClass::Environment => "environment",
        ConstraintClass::Task => "task",
    }
}

fn constraint_relation(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "at_least",
        ConstraintRelation::AtMost => "at_most",
        ConstraintRelation::Equal => "equal",
    }
}

#[allow(dead_code)]
fn _native_predicate_terminal(value: PredicateTerminality) -> &'static str {
    match value {
        PredicateTerminality::Intermediate => "intermediate",
        PredicateTerminality::Terminal => "terminal",
    }
}

#[allow(dead_code)]
fn _native_success_predicate(_value: &SuccessPredicate) {}

#[allow(dead_code)]
fn _native_soft_direction(value: SoftDirection) -> &'static str {
    match value {
        SoftDirection::Maximize => "maximize",
        SoftDirection::Minimize => "minimize",
    }
}

#[allow(dead_code)]
fn _source_constraint_comparator(value: ObjectiveConstraintComparatorV1) -> &'static str {
    constraint_comparator(value)
}
