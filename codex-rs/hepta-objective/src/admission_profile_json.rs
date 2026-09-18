use std::error::Error;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;

use crate::ConstraintClass;
use crate::ObjectiveAbstentionRuleProfileV1;
use crate::ObjectiveActionProfileV1;
use crate::ObjectiveAdmissionError;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveConstraintProfileV1;
use crate::ObjectiveEvidenceProfileV1;
use crate::ObjectivePredicateProfileV1;
use crate::ObjectiveResourceAxisProfileV1;
use crate::ObjectiveResourceProfileV1;
use crate::ObjectiveRiskProfileV1;
use crate::ObjectiveSoftDimensionProfileV1;
use crate::ObjectiveSoftDirectionV1;

pub const MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveAdmissionProfileJsonError {
    InputTooLarge { actual: usize, maximum: usize },
    InvalidJson { line: usize, column: usize },
    InvalidField(&'static str),
    Admission(ObjectiveAdmissionError),
}

impl fmt::Display for ObjectiveAdmissionProfileJsonError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InputTooLarge { actual, maximum } => {
                write!(formatter, "objective admission profile has {actual} bytes; maximum is {maximum}")
            }
            Self::InvalidJson { line, column } => {
                write!(formatter, "invalid objective admission profile JSON at line {line}, column {column}")
            }
            Self::InvalidField(field) => write!(formatter, "invalid objective admission profile field: {field}"),
            Self::Admission(error) => error.fmt(formatter),
        }
    }
}

impl Error for ObjectiveAdmissionProfileJsonError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            _ => None,
        }
    }
}

pub fn decode_admission_profile_json_v1(
    input: &[u8],
) -> Result<ObjectiveAdmissionProfileV1, ObjectiveAdmissionProfileJsonError> {
    if input.len() > MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES {
        return Err(ObjectiveAdmissionProfileJsonError::InputTooLarge {
            actual: input.len(),
            maximum: MAX_OBJECTIVE_ADMISSION_PROFILE_JSON_BYTES,
        });
    }
    let wire: ProfileWire = serde_json::from_slice(input).map_err(|error| {
        ObjectiveAdmissionProfileJsonError::InvalidJson {
            line: error.line(),
            column: error.column(),
        }
    })?;
    let profile = wire.try_into_profile()?;
    profile
        .digest()
        .map_err(ObjectiveAdmissionProfileJsonError::Admission)?;
    Ok(profile)
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ProfileWire {
    profile_id: String,
    profile_revision: u64,
    expected_input_schema_digest: String,
    expected_normalization_profile_digest: String,
    principal_scope_digest: String,
    principal_scope: String,
    allowed_locales: Vec<String>,
    maximum_source_age_micros: u64,
    maximum_future_skew_micros: u64,
    deadline_required: bool,
    allowed_trusted_source_identities: Vec<String>,
    constraints: Vec<ConstraintWire>,
    predicates: Vec<PredicateWire>,
    actions: Vec<ActionWire>,
    soft_dimensions: Vec<SoftDimensionWire>,
    evidence_requirements: Vec<EvidenceWire>,
    resources: ResourcesWire,
    risk: RiskWire,
}

impl ProfileWire {
    fn try_into_profile(self) -> Result<ObjectiveAdmissionProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectiveAdmissionProfileV1 {
            profile_id: stable_id(self.profile_id, "profileId")?,
            profile_revision: Revision::new(self.profile_revision)
                .map_err(|_| ObjectiveAdmissionProfileJsonError::InvalidField("profileRevision"))?,
            expected_input_schema_digest: digest(self.expected_input_schema_digest, "expectedInputSchemaDigest")?,
            expected_normalization_profile_digest: digest(
                self.expected_normalization_profile_digest,
                "expectedNormalizationProfileDigest",
            )?,
            principal_scope_digest: digest(self.principal_scope_digest, "principalScopeDigest")?,
            principal_scope: stable_id(self.principal_scope, "principalScope")?,
            allowed_locales: self.allowed_locales,
            maximum_source_age_micros: self.maximum_source_age_micros,
            maximum_future_skew_micros: self.maximum_future_skew_micros,
            deadline_required: self.deadline_required,
            allowed_trusted_source_identities: self
                .allowed_trusted_source_identities
                .into_iter()
                .map(|value| stable_id(value, "allowedTrustedSourceIdentities"))
                .collect::<Result<Vec<_>, _>>()?,
            constraints: self
                .constraints
                .into_iter()
                .map(ConstraintWire::try_into_mapping)
                .collect::<Result<Vec<_>, _>>()?,
            predicates: self
                .predicates
                .into_iter()
                .map(PredicateWire::try_into_mapping)
                .collect::<Result<Vec<_>, _>>()?,
            actions: self
                .actions
                .into_iter()
                .map(ActionWire::try_into_mapping)
                .collect::<Result<Vec<_>, _>>()?,
            soft_dimensions: self
                .soft_dimensions
                .into_iter()
                .map(SoftDimensionWire::try_into_mapping)
                .collect::<Result<Vec<_>, _>>()?,
            evidence_requirements: self
                .evidence_requirements
                .into_iter()
                .map(EvidenceWire::try_into_mapping)
                .collect::<Result<Vec<_>, _>>()?,
            resources: self.resources.try_into_profile()?,
            risk: self.risk.try_into_profile()?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ConstraintWire {
    source_constraint_id: String,
    expected_unit: String,
    class: String,
    axis: String,
}

impl ConstraintWire {
    fn try_into_mapping(self) -> Result<ObjectiveConstraintProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectiveConstraintProfileV1 {
            source_constraint_id: self.source_constraint_id,
            expected_unit: self.expected_unit,
            class: constraint_class(&self.class)?,
            axis: stable_id(self.axis, "constraint.axis")?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PredicateWire {
    source_predicate_id: String,
    expected_unit: String,
    axis: String,
}

impl PredicateWire {
    fn try_into_mapping(self) -> Result<ObjectivePredicateProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectivePredicateProfileV1 {
            source_predicate_id: self.source_predicate_id,
            expected_unit: self.expected_unit,
            axis: stable_id(self.axis, "predicate.axis")?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ActionWire {
    source_action_class: String,
    action_id: String,
}

impl ActionWire {
    fn try_into_mapping(self) -> Result<ObjectiveActionProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectiveActionProfileV1 {
            source_action_class: self.source_action_class,
            action_id: stable_id(self.action_id, "action.actionId")?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SoftDimensionWire {
    source_dimension_id: String,
    expected_unit: String,
    expected_direction: String,
    dimension: String,
    baseline_weight_q32: i64,
}

impl SoftDimensionWire {
    fn try_into_mapping(self) -> Result<ObjectiveSoftDimensionProfileV1, ObjectiveAdmissionProfileJsonError> {
        let expected_direction = match self.expected_direction.as_str() {
            "maximize" => ObjectiveSoftDirectionV1::Maximize,
            "minimize" => ObjectiveSoftDirectionV1::Minimize,
            _ => return Err(ObjectiveAdmissionProfileJsonError::InvalidField("softDimensions.expectedDirection")),
        };
        Ok(ObjectiveSoftDimensionProfileV1 {
            source_dimension_id: self.source_dimension_id,
            expected_unit: self.expected_unit,
            expected_direction,
            dimension: stable_id(self.dimension, "softDimensions.dimension")?,
            baseline_weight: FixedQ32::from_raw(self.baseline_weight_q32),
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceWire {
    source_requirement_id: String,
    axis: String,
}

impl EvidenceWire {
    fn try_into_mapping(self) -> Result<ObjectiveEvidenceProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectiveEvidenceProfileV1 {
            source_requirement_id: self.source_requirement_id,
            axis: stable_id(self.axis, "evidence.axis")?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourceAxisWire {
    constraint_id: String,
    axis: String,
    class: String,
    q32_per_source_unit: i64,
    evidence_source: String,
}

impl ResourceAxisWire {
    fn try_into_mapping(self, field: &'static str) -> Result<ObjectiveResourceAxisProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectiveResourceAxisProfileV1 {
            constraint_id: stable_id(self.constraint_id, field)?,
            axis: stable_id(self.axis, field)?,
            class: constraint_class(&self.class)?,
            q32_per_source_unit: FixedQ32::from_raw(self.q32_per_source_unit),
            evidence_source: stable_id(self.evidence_source, field)?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourcesWire {
    time_micros: ResourceAxisWire,
    token_count: ResourceAxisWire,
    compute_micros: ResourceAxisWire,
    memory_bytes: ResourceAxisWire,
    network_bytes: ResourceAxisWire,
    external_effect_count: ResourceAxisWire,
}

impl ResourcesWire {
    fn try_into_profile(self) -> Result<ObjectiveResourceProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectiveResourceProfileV1 {
            time_micros: self.time_micros.try_into_mapping("resources.timeMicros")?,
            token_count: self.token_count.try_into_mapping("resources.tokenCount")?,
            compute_micros: self.compute_micros.try_into_mapping("resources.computeMicros")?,
            memory_bytes: self.memory_bytes.try_into_mapping("resources.memoryBytes")?,
            network_bytes: self.network_bytes.try_into_mapping("resources.networkBytes")?,
            external_effect_count: self.external_effect_count.try_into_mapping("resources.externalEffectCount")?,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AbstentionRuleWire {
    source_rule: String,
    value_q32: i64,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RiskWire {
    evidence_source: String,
    class: String,
    risk_constraint_id: String,
    risk_axis: String,
    low_value_q32: i64,
    medium_value_q32: i64,
    high_value_q32: i64,
    critical_value_q32: i64,
    rollback_constraint_id: String,
    rollback_axis: String,
    rollback_none_value_q32: i64,
    rollback_reversible_value_q32: i64,
    rollback_compensatable_value_q32: i64,
    rollback_irreversible_value_q32: i64,
    compensation_constraint_id: String,
    compensation_axis: String,
    compensation_false_value_q32: i64,
    compensation_true_value_q32: i64,
    abstention_constraint_id: String,
    abstention_axis: String,
    abstention_rules: Vec<AbstentionRuleWire>,
}

impl RiskWire {
    fn try_into_profile(self) -> Result<ObjectiveRiskProfileV1, ObjectiveAdmissionProfileJsonError> {
        Ok(ObjectiveRiskProfileV1 {
            evidence_source: stable_id(self.evidence_source, "risk.evidenceSource")?,
            class: constraint_class(&self.class)?,
            risk_constraint_id: stable_id(self.risk_constraint_id, "risk.riskConstraintId")?,
            risk_axis: stable_id(self.risk_axis, "risk.riskAxis")?,
            low_value: FixedQ32::from_raw(self.low_value_q32),
            medium_value: FixedQ32::from_raw(self.medium_value_q32),
            high_value: FixedQ32::from_raw(self.high_value_q32),
            critical_value: FixedQ32::from_raw(self.critical_value_q32),
            rollback_constraint_id: stable_id(self.rollback_constraint_id, "risk.rollbackConstraintId")?,
            rollback_axis: stable_id(self.rollback_axis, "risk.rollbackAxis")?,
            rollback_none_value: FixedQ32::from_raw(self.rollback_none_value_q32),
            rollback_reversible_value: FixedQ32::from_raw(self.rollback_reversible_value_q32),
            rollback_compensatable_value: FixedQ32::from_raw(self.rollback_compensatable_value_q32),
            rollback_irreversible_value: FixedQ32::from_raw(self.rollback_irreversible_value_q32),
            compensation_constraint_id: stable_id(self.compensation_constraint_id, "risk.compensationConstraintId")?,
            compensation_axis: stable_id(self.compensation_axis, "risk.compensationAxis")?,
            compensation_false_value: FixedQ32::from_raw(self.compensation_false_value_q32),
            compensation_true_value: FixedQ32::from_raw(self.compensation_true_value_q32),
            abstention_constraint_id: stable_id(self.abstention_constraint_id, "risk.abstentionConstraintId")?,
            abstention_axis: stable_id(self.abstention_axis, "risk.abstentionAxis")?,
            abstention_rules: self
                .abstention_rules
                .into_iter()
                .map(|rule| ObjectiveAbstentionRuleProfileV1 {
                    source_rule: rule.source_rule,
                    value: FixedQ32::from_raw(rule.value_q32),
                })
                .collect(),
        })
    }
}

fn stable_id(value: String, field: &'static str) -> Result<StableId, ObjectiveAdmissionProfileJsonError> {
    StableId::new(value).map_err(|_| ObjectiveAdmissionProfileJsonError::InvalidField(field))
}

fn digest(value: String, field: &'static str) -> Result<Digest32, ObjectiveAdmissionProfileJsonError> {
    let digest = Digest32::from_str(&value)
        .map_err(|_| ObjectiveAdmissionProfileJsonError::InvalidField(field))?;
    if digest.is_zero() {
        return Err(ObjectiveAdmissionProfileJsonError::InvalidField(field));
    }
    Ok(digest)
}

fn constraint_class(value: &str) -> Result<ConstraintClass, ObjectiveAdmissionProfileJsonError> {
    match value {
        "constitutional" => Ok(ConstraintClass::Constitutional),
        "principal" => Ok(ConstraintClass::Principal),
        "environment" => Ok(ConstraintClass::Environment),
        "task" => Ok(ConstraintClass::Task),
        _ => Err(ObjectiveAdmissionProfileJsonError::InvalidField("constraint class")),
    }
}

#[cfg(test)]
#[path = "admission_profile_json_tests.rs"]
mod tests;
