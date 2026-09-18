//! Canonical cross-module projection for the registered ObjectiveFunctionV1.
//!
//! Native ObjectiveFunction remains owner-local IR. This projection is the only
//! JSON-facing V1 shape and carries every semantic group named by the canonical
//! control-plane contract instead of silently dropping source fields.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use serde::Serialize;

use crate::ActionClass;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::SoftDirection;
use crate::SuccessPredicate;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectivePrincipalScopeV1 {
    pub id: String,
    pub digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectivePredicateProjectionV1 {
    pub predicate_id: String,
    pub axis: String,
    pub comparator: String,
    pub bound_q32: i64,
    pub evidence_source_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveConstraintProjectionV1 {
    pub constraint_id: String,
    pub precedence: String,
    pub axis: String,
    pub comparator: String,
    pub bound_q32: i64,
    pub evidence_source_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveEvidenceProjectionV1 {
    pub requirement_id: String,
    pub evidence_source_id: String,
    pub minimum_confidence_ppm: u32,
    pub terminal: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveActionProjectionV1 {
    pub action_id: String,
    pub confirmation_required: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveSoftUtilityProjectionV1 {
    pub dimension_id: String,
    pub direction: String,
    pub weight_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveResourceEndowmentV1 {
    pub time_micros: u64,
    pub token_count: u64,
    pub compute_micros: u64,
    pub memory_bytes: u64,
    pub network_bytes: u64,
    pub external_effect_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveRiskProjectionV1 {
    pub risk_class: String,
    pub abstention_rule: String,
    pub rollback_class: String,
    pub compensation_required: bool,
}

/// Exact registered cross-module V1 projection.
///
/// The source/profile are required because the native IR deliberately lowers
/// evidence, resource and risk semantics. Publication is permitted only after a
/// successful admission+compile outcome; a conflict has no ObjectiveFunctionV1.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ObjectiveFunctionV1 {
    pub objective_id: String,
    pub request_digest: String,
    pub principal_scope: ObjectivePrincipalScopeV1,
    pub success_predicates: Vec<ObjectivePredicateProjectionV1>,
    pub terminal_conditions: Vec<ObjectivePredicateProjectionV1>,
    pub hard_constraints: Vec<ObjectiveConstraintProjectionV1>,
    pub evidence_requirements: Vec<ObjectiveEvidenceProjectionV1>,
    pub allowed_action_classes: Vec<ObjectiveActionProjectionV1>,
    pub forbidden_action_classes: Vec<String>,
    pub confirmation_action_classes: Vec<String>,
    pub soft_utility_dimensions: Vec<ObjectiveSoftUtilityProjectionV1>,
    pub resource_endowment: ObjectiveResourceEndowmentV1,
    pub risk: ObjectiveRiskProjectionV1,
    pub deadline_unix_ms: Option<u64>,
    pub revision: u64,
    pub objective_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveProjectionError {
    CompileConflict,
    MissingPredicate(String),
    MissingAction(String),
    SubMillisecondDeadline,
}

impl fmt::Display for ObjectiveProjectionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ObjectiveProjectionError {}

pub fn project_objective_function_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    outcome: &ObjectiveAdmissionOutcomeV1,
) -> Result<ObjectiveFunctionV1, ObjectiveProjectionError> {
    let compiled = outcome
        .compile_result
        .as_ref()
        .map_err(|_| ObjectiveProjectionError::CompileConflict)?;
    let objective = &compiled.objective;
    let predicates = objective
        .success_predicates
        .iter()
        .map(|predicate| (predicate.id.as_str(), predicate))
        .collect::<BTreeMap<_, _>>();

    let success_predicates = envelope
        .structured_intent
        .success_predicates
        .iter()
        .map(|source| {
            predicates
                .get(source.predicate_id.as_str())
                .copied()
                .ok_or_else(|| ObjectiveProjectionError::MissingPredicate(source.predicate_id.clone()))
                .map(project_predicate)
        })
        .collect::<Result<Vec<_>, _>>()?;
    let terminal_conditions = envelope
        .structured_intent
        .terminal_conditions
        .iter()
        .map(|source| {
            predicates
                .get(source.predicate_id.as_str())
                .copied()
                .ok_or_else(|| ObjectiveProjectionError::MissingPredicate(source.predicate_id.clone()))
                .map(project_predicate)
        })
        .collect::<Result<Vec<_>, _>>()?;

    let allowed_action_classes = objective
        .legal_actions
        .iter()
        .filter(|action| action.id.as_str() != "abstain")
        .map(project_action)
        .collect();
    let forbidden_action_classes =
        map_actions(&envelope.structured_intent.forbidden_action_classes, profile)?;
    let confirmation_action_classes =
        map_actions(&envelope.structured_intent.confirmation_action_classes, profile)?;

    let deadline_unix_ms = match outcome.receipt.deadline_unix_micros {
        Some(value) if value % 1_000 == 0 => Some(value / 1_000),
        Some(_) => return Err(ObjectiveProjectionError::SubMillisecondDeadline),
        None => None,
    };

    let objective_digest = digest_hex(objective.semantic_digest);
    Ok(ObjectiveFunctionV1 {
        objective_id: format!("objective.{}", &objective_digest[..32]),
        request_digest: digest_hex(outcome.receipt.intent_digest),
        principal_scope: ObjectivePrincipalScopeV1 {
            id: objective.principal_scope.as_str().to_owned(),
            digest: digest_hex(envelope.principal_scope_digest),
        },
        success_predicates,
        terminal_conditions,
        hard_constraints: objective.constraints.iter().map(project_constraint).collect(),
        evidence_requirements: envelope
            .structured_intent
            .evidence_requirements
            .iter()
            .map(|source| ObjectiveEvidenceProjectionV1 {
                requirement_id: source.requirement_id.clone(),
                evidence_source_id: source.evidence_source_id.clone(),
                minimum_confidence_ppm: source.minimum_confidence_ppm,
                terminal: source.terminal,
            })
            .collect(),
        allowed_action_classes,
        forbidden_action_classes,
        confirmation_action_classes,
        soft_utility_dimensions: objective
            .soft_preferences
            .iter()
            .map(|soft| ObjectiveSoftUtilityProjectionV1 {
                dimension_id: soft.dimension.as_str().to_owned(),
                direction: match soft.direction {
                    SoftDirection::Maximize => "maximize",
                    SoftDirection::Minimize => "minimize",
                }
                .to_owned(),
                weight_q32: soft.weight.raw(),
            })
            .collect(),
        resource_endowment: ObjectiveResourceEndowmentV1 {
            time_micros: envelope.structured_intent.resources.time_micros,
            token_count: envelope.structured_intent.resources.token_count,
            compute_micros: envelope.structured_intent.resources.compute_micros,
            memory_bytes: envelope.structured_intent.resources.memory_bytes,
            network_bytes: envelope.structured_intent.resources.network_bytes,
            external_effect_count: envelope.structured_intent.resources.external_effect_count,
        },
        risk: ObjectiveRiskProjectionV1 {
            risk_class: match envelope.structured_intent.risk.risk_class {
                ObjectiveRiskClassV1::Low => "low",
                ObjectiveRiskClassV1::Medium => "medium",
                ObjectiveRiskClassV1::High => "high",
                ObjectiveRiskClassV1::Critical => "critical",
            }
            .to_owned(),
            abstention_rule: envelope.structured_intent.risk.abstention_rule.clone(),
            rollback_class: match envelope.structured_intent.risk.rollback_class {
                ObjectiveRollbackClassV1::None => "none",
                ObjectiveRollbackClassV1::Reversible => "reversible",
                ObjectiveRollbackClassV1::Compensatable => "compensatable",
                ObjectiveRollbackClassV1::Irreversible => "irreversible",
            }
            .to_owned(),
            compensation_required: envelope.structured_intent.risk.compensation_required,
        },
        deadline_unix_ms,
        revision: objective.revision.get(),
        objective_digest,
    })
}

fn map_actions(
    source: &[String],
    profile: &ObjectiveAdmissionProfileV1,
) -> Result<Vec<String>, ObjectiveProjectionError> {
    source
        .iter()
        .map(|name| {
            profile
                .actions
                .iter()
                .find(|mapping| mapping.source_action_class == *name)
                .map(|mapping| mapping.action_id.as_str().to_owned())
                .ok_or_else(|| ObjectiveProjectionError::MissingAction(name.clone()))
        })
        .collect()
}

fn project_predicate(predicate: &SuccessPredicate) -> ObjectivePredicateProjectionV1 {
    ObjectivePredicateProjectionV1 {
        predicate_id: predicate.id.as_str().to_owned(),
        axis: predicate.axis.as_str().to_owned(),
        comparator: relation_name(predicate.relation).to_owned(),
        bound_q32: predicate.bound.raw(),
        evidence_source_id: predicate.evidence_source.as_str().to_owned(),
    }
}

fn project_constraint(constraint: &Constraint) -> ObjectiveConstraintProjectionV1 {
    ObjectiveConstraintProjectionV1 {
        constraint_id: constraint.id.as_str().to_owned(),
        precedence: match constraint.class {
            ConstraintClass::Constitutional => "constitutional",
            ConstraintClass::Principal => "principal",
            ConstraintClass::Environment => "environment",
            ConstraintClass::Task => "task",
        }
        .to_owned(),
        axis: constraint.axis.as_str().to_owned(),
        comparator: relation_name(constraint.relation).to_owned(),
        bound_q32: constraint.bound.raw(),
        evidence_source_id: constraint.evidence_source.as_str().to_owned(),
    }
}

fn project_action(action: &ActionClass) -> ObjectiveActionProjectionV1 {
    ObjectiveActionProjectionV1 {
        action_id: action.id.as_str().to_owned(),
        confirmation_required: action.confirmation == ConfirmationPolicy::Required,
    }
}

fn relation_name(relation: ConstraintRelation) -> &'static str {
    match relation {
        ConstraintRelation::AtLeast => "gte",
        ConstraintRelation::AtMost => "lte",
        ConstraintRelation::Equal => "eq",
    }
}

fn digest_hex(digest: Digest32) -> String {
    let mut result = String::with_capacity(64);
    for byte in digest.as_array() {
        use std::fmt::Write as _;
        write!(&mut result, "{byte:02x}").expect("String formatting cannot fail");
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registered_field_names_are_stable() {
        let value = serde_json::to_value(ObjectiveResourceEndowmentV1 {
            time_micros: 1,
            token_count: 2,
            compute_micros: 3,
            memory_bytes: 4,
            network_bytes: 5,
            external_effect_count: 6,
        })
        .unwrap();
        assert_eq!(value["timeMicros"], 1);
        assert_eq!(value["externalEffectCount"], 6);
        assert_eq!(value.as_object().unwrap().len(), 6);
    }
}
