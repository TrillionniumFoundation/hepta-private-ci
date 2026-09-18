use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use serde::Serialize;

use crate::CompileDisposition;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveAdmissionReceiptV1;
use crate::ObjectiveCompileReceipt;
use crate::ObjectiveConstraintComparatorV1;
use crate::ObjectivePredicateComparatorV1;
use crate::ObjectiveRiskClassV1;
use crate::ObjectiveRollbackClassV1;
use crate::ObjectiveRunStartPublicationV1;
use crate::ObjectiveSoftDirectionV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::RunStartSnapshotV1;

pub const MAX_CANONICAL_OBJECTIVE_PROTOCOL_BYTES: usize = 256 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveCanonicalArtifactsV1 {
    pub objective_function_bytes: Vec<u8>,
    pub constraint_set_bytes: Vec<u8>,
    pub compile_receipt_bytes: Vec<u8>,
    pub run_start_snapshot_bytes: Vec<u8>,
    pub objective_function_digest: Digest32,
    pub constraint_set_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectiveProtocolError {
    MissingActionMapping,
    DeadlinePrecisionLoss,
    EncodedBytesExceeded { actual: usize, maximum: usize },
    Arithmetic,
    Serialization,
}

impl fmt::Display for ObjectiveProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingActionMapping => {
                formatter.write_str("canonical objective action mapping is missing")
            }
            Self::DeadlinePrecisionLoss => {
                formatter.write_str("canonical objective deadline loses sub-millisecond precision")
            }
            Self::EncodedBytesExceeded { actual, maximum } => write!(
                formatter,
                "canonical objective protocol has {actual} bytes; maximum is {maximum}"
            ),
            Self::Arithmetic => formatter.write_str("canonical objective arithmetic failed"),
            Self::Serialization => {
                formatter.write_str("canonical objective protocol serialization failed")
            }
        }
    }
}

impl Error for ObjectiveProtocolError {}

pub fn build_canonical_objective_artifacts_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    admission: &ObjectiveAdmissionReceiptV1,
    compile: &ObjectiveCompileReceipt,
    run_start: &RunStartSnapshotV1,
) -> Result<ObjectiveCanonicalArtifactsV1, ObjectiveProtocolError> {
    let objective_id = objective_id(compile.objective.semantic_digest);
    let mut hard_constraints = compile
        .objective
        .constraints
        .iter()
        .map(canonical_constraint)
        .collect::<Vec<_>>();
    hard_constraints.sort_by(|left, right| {
        (&left.class, &left.axis, &left.constraint_id)
            .cmp(&(&right.class, &right.axis, &right.constraint_id))
    });

    let mut success_predicates = envelope
        .structured_intent
        .success_predicates
        .iter()
        .map(canonical_source_predicate)
        .collect::<Vec<_>>();
    success_predicates.sort_by(|left, right| left.predicate_id.cmp(&right.predicate_id));
    let mut terminal_conditions = envelope
        .structured_intent
        .terminal_conditions
        .iter()
        .map(canonical_source_predicate)
        .collect::<Vec<_>>();
    terminal_conditions.sort_by(|left, right| left.predicate_id.cmp(&right.predicate_id));

    let mut soft_utility_dimensions = compile
        .objective
        .soft_preferences
        .iter()
        .map(|value| CanonicalSoftDimension {
            dimension_id: value.dimension.to_string(),
            direction: match value.direction {
                crate::SoftDirection::Maximize => "maximize",
                crate::SoftDirection::Minimize => "minimize",
            },
            weight_q32: value.weight.raw(),
        })
        .collect::<Vec<_>>();
    soft_utility_dimensions.sort_by(|left, right| left.dimension_id.cmp(&right.dimension_id));

    let deadline_unix_ms = admission
        .deadline_unix_micros
        .map(|value| {
            if value % 1_000 != 0 {
                return Err(ObjectiveProtocolError::DeadlinePrecisionLoss);
            }
            Ok(value / 1_000)
        })
        .transpose()?;

    let objective_function = ObjectiveFunctionWire {
        objective_id: objective_id.clone(),
        request_digest: admission.intent_digest.to_string(),
        principal_scope: PrincipalScopeWire {
            scope_id: compile.objective.principal_scope.to_string(),
            scope_digest: envelope.principal_scope_digest.to_string(),
        },
        success_predicates,
        terminal_conditions,
        hard_constraints,
        soft_utility_dimensions,
        resource_endowment: ResourceWire::from(&envelope.structured_intent.resources),
        deadline_unix_ms,
        revision: compile.objective.revision.get(),
    };
    let objective_function_bytes = encode_bounded(&objective_function)?;
    let objective_function_digest = Digest32::of_bytes(&objective_function_bytes);

    let constraint_set = build_constraint_set(envelope, profile, compile, &objective_id)?;
    let constraint_set_bytes = encode_bounded(&constraint_set)?;
    let constraint_set_digest = Digest32::of_bytes(&constraint_set_bytes);

    let canonical_bytes = objective_function_bytes
        .len()
        .checked_add(constraint_set_bytes.len())
        .ok_or(ObjectiveProtocolError::Arithmetic)?;
    let canonical_bytes =
        u32::try_from(canonical_bytes).map_err(|_| ObjectiveProtocolError::Arithmetic)?;
    let compile_receipt = ObjectiveCompileReceiptWire {
        request_id: compile.objective.request_id.to_string(),
        objective_id,
        revision: compile.objective.revision.get(),
        source_envelope_digest: admission.admitted_source_digest.to_string(),
        constraint_set_digest: constraint_set_digest.to_string(),
        objective_function_digest: objective_function_digest.to_string(),
        normalization_profile_digest: envelope
            .structured_intent
            .provenance
            .normalization_profile_digest
            .to_string(),
        canonical_bytes,
        disposition: match compile.disposition {
            CompileDisposition::Compiled | CompileDisposition::ExplicitAbstain => "compiled",
        },
    };
    let compile_receipt_bytes = encode_bounded(&compile_receipt)?;
    let run_start_snapshot_bytes = encode_run_start_snapshot_v1(run_start)?;

    Ok(ObjectiveCanonicalArtifactsV1 {
        objective_function_bytes,
        constraint_set_bytes,
        compile_receipt_bytes,
        run_start_snapshot_bytes,
        objective_function_digest,
        constraint_set_digest,
    })
}

pub fn encode_run_start_snapshot_v1(
    snapshot: &RunStartSnapshotV1,
) -> Result<Vec<u8>, ObjectiveProtocolError> {
    encode_bounded(&RunStartSnapshotWire {
        run_id: snapshot.run_id.to_string(),
        objective_digest: snapshot.objective_digest.to_string(),
        hard_constraint_digest: snapshot.hard_constraint_digest.to_string(),
        preference_state_digest: snapshot.preference_state_digest.to_string(),
        model_tuple_digest: snapshot.model_tuple_digest.to_string(),
        prompt_registry_digest: snapshot.prompt_registry_digest.to_string(),
        artifact_set_digest: snapshot.artifact_set_digest.to_string(),
        authority_epoch: snapshot.authority_epoch,
        generation: snapshot.generation,
        fence_digest: snapshot.fence_digest.to_string(),
    })
}

pub(crate) fn validate_canonical_publication_artifacts_v1(
    publication: &ObjectiveRunStartPublicationV1,
) -> Result<(), ObjectiveProtocolError> {
    for bytes in [
        publication.objective_function_v1_bytes(),
        publication.objective_constraint_set_v1_bytes(),
        publication.objective_compile_receipt_v1_bytes(),
        publication.run_start_snapshot_v1_bytes(),
    ] {
        if bytes.is_empty() || bytes.len() > MAX_CANONICAL_OBJECTIVE_PROTOCOL_BYTES {
            return Err(ObjectiveProtocolError::EncodedBytesExceeded {
                actual: bytes.len(),
                maximum: MAX_CANONICAL_OBJECTIVE_PROTOCOL_BYTES,
            });
        }
        let _: serde_json::Value =
            serde_json::from_slice(bytes).map_err(|_| ObjectiveProtocolError::Serialization)?;
    }
    if Digest32::of_bytes(publication.objective_function_v1_bytes())
        != publication.objective_function_v1_digest()
        || Digest32::of_bytes(publication.objective_constraint_set_v1_bytes())
            != publication.objective_constraint_set_v1_digest()
    {
        return Err(ObjectiveProtocolError::Serialization);
    }
    Ok(())
}

fn build_constraint_set(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    compile: &ObjectiveCompileReceipt,
    objective_id: &str,
) -> Result<ObjectiveConstraintSetWire, ObjectiveProtocolError> {
    let mut constitutional_constraints = Vec::new();
    let mut principal_constraints = Vec::new();
    let mut environment_constraints = Vec::new();
    for constraint in &compile.objective.constraints {
        let wire = canonical_constraint(constraint);
        match constraint.class {
            ConstraintClass::Constitutional => constitutional_constraints.push(wire),
            ConstraintClass::Principal => principal_constraints.push(wire),
            ConstraintClass::Environment => environment_constraints.push(wire),
            ConstraintClass::Task => {}
        }
    }
    for values in [
        &mut constitutional_constraints,
        &mut principal_constraints,
        &mut environment_constraints,
    ] {
        values.sort_by(|left, right| {
            (&left.axis, &left.constraint_id).cmp(&(&right.axis, &right.constraint_id))
        });
    }

    let mut legal_action_classes = compile
        .objective
        .legal_actions
        .iter()
        .map(|action| action.id.to_string())
        .collect::<Vec<_>>();
    legal_action_classes.sort();

    let mut forbidden_action_classes = envelope
        .structured_intent
        .forbidden_action_classes
        .iter()
        .map(|source| {
            profile
                .actions
                .iter()
                .find(|mapping| mapping.source_action_class == *source)
                .map(|mapping| mapping.action_id.to_string())
                .ok_or(ObjectiveProtocolError::MissingActionMapping)
        })
        .collect::<Result<Vec<_>, _>>()?;
    forbidden_action_classes.sort();
    forbidden_action_classes.dedup();

    let mut evidence_requirements = envelope
        .structured_intent
        .evidence_requirements
        .iter()
        .map(|value| EvidenceRequirementWire {
            requirement_id: value.requirement_id.clone(),
            evidence_source_id: value.evidence_source_id.clone(),
            minimum_confidence_ppm: value.minimum_confidence_ppm,
            terminal: value.terminal,
        })
        .collect::<Vec<_>>();
    evidence_requirements.sort_by(|left, right| left.requirement_id.cmp(&right.requirement_id));

    Ok(ObjectiveConstraintSetWire {
        objective_id: objective_id.to_string(),
        revision: compile.objective.revision.get(),
        constitutional_constraints,
        principal_constraints,
        environment_constraints,
        legal_action_classes,
        forbidden_action_classes,
        evidence_requirements,
        resource_ceiling: ResourceWire::from(&envelope.structured_intent.resources),
        rollback_class: rollback_name(envelope.structured_intent.risk.rollback_class),
        semantic_digest: compile.objective.semantic_digest.to_string(),
    })
}

fn canonical_source_predicate(value: &crate::ObjectiveSourcePredicateV1) -> SourcePredicateWire {
    SourcePredicateWire {
        predicate_id: value.predicate_id.clone(),
        unit: value.unit.clone(),
        comparator: predicate_comparator_name(value.comparator),
        bound_q32: value.bound_q32,
        evidence_source_id: value.evidence_source_id.clone(),
        terminal: value.terminal,
    }
}

fn canonical_constraint(value: &Constraint) -> CanonicalConstraintWire {
    CanonicalConstraintWire {
        constraint_id: value.id.to_string(),
        class: class_name(value.class),
        axis: value.axis.to_string(),
        comparator: relation_name(value.relation),
        bound_q32: value.bound.raw(),
        evidence_source_id: value.evidence_source.to_string(),
        terminal: false,
    }
}

fn encode_bounded<T: Serialize>(value: &T) -> Result<Vec<u8>, ObjectiveProtocolError> {
    let bytes = serde_json::to_vec(value).map_err(|_| ObjectiveProtocolError::Serialization)?;
    if bytes.len() > MAX_CANONICAL_OBJECTIVE_PROTOCOL_BYTES {
        return Err(ObjectiveProtocolError::EncodedBytesExceeded {
            actual: bytes.len(),
            maximum: MAX_CANONICAL_OBJECTIVE_PROTOCOL_BYTES,
        });
    }
    Ok(bytes)
}

fn objective_id(digest: Digest32) -> String {
    format!("objective-{digest}")
}

const fn class_name(value: ConstraintClass) -> &'static str {
    match value {
        ConstraintClass::Constitutional => "constitutional",
        ConstraintClass::Principal => "principal",
        ConstraintClass::Environment => "environment",
        ConstraintClass::Task => "task",
    }
}

const fn relation_name(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "gte",
        ConstraintRelation::AtMost => "lte",
        ConstraintRelation::Equal => "eq",
    }
}

const fn predicate_comparator_name(value: ObjectivePredicateComparatorV1) -> &'static str {
    match value {
        ObjectivePredicateComparatorV1::Equal => "eq",
        ObjectivePredicateComparatorV1::NotEqual => "ne",
        ObjectivePredicateComparatorV1::LessThan => "lt",
        ObjectivePredicateComparatorV1::LessThanOrEqual => "lte",
        ObjectivePredicateComparatorV1::GreaterThan => "gt",
        ObjectivePredicateComparatorV1::GreaterThanOrEqual => "gte",
    }
}

const fn rollback_name(value: ObjectiveRollbackClassV1) -> &'static str {
    match value {
        ObjectiveRollbackClassV1::None => "none",
        ObjectiveRollbackClassV1::Reversible => "reversible",
        ObjectiveRollbackClassV1::Compensatable => "compensatable",
        ObjectiveRollbackClassV1::Irreversible => "irreversible",
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ObjectiveFunctionWire {
    objective_id: String,
    request_digest: String,
    principal_scope: PrincipalScopeWire,
    success_predicates: Vec<SourcePredicateWire>,
    terminal_conditions: Vec<SourcePredicateWire>,
    hard_constraints: Vec<CanonicalConstraintWire>,
    soft_utility_dimensions: Vec<CanonicalSoftDimension>,
    resource_endowment: ResourceWire,
    #[serde(skip_serializing_if = "Option::is_none")]
    deadline_unix_ms: Option<u64>,
    revision: u64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PrincipalScopeWire {
    scope_id: String,
    scope_digest: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SourcePredicateWire {
    predicate_id: String,
    unit: String,
    comparator: &'static str,
    bound_q32: i64,
    evidence_source_id: String,
    terminal: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CanonicalConstraintWire {
    constraint_id: String,
    class: &'static str,
    axis: String,
    comparator: &'static str,
    bound_q32: i64,
    evidence_source_id: String,
    terminal: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CanonicalSoftDimension {
    dimension_id: String,
    direction: &'static str,
    weight_q32: i64,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ResourceWire {
    time_micros: u64,
    token_count: u64,
    compute_micros: u64,
    memory_bytes: u64,
    network_bytes: u64,
    external_effect_count: u32,
}

impl From<&crate::ObjectiveResourcesV1> for ResourceWire {
    fn from(value: &crate::ObjectiveResourcesV1) -> Self {
        Self {
            time_micros: value.time_micros,
            token_count: value.token_count,
            compute_micros: value.compute_micros,
            memory_bytes: value.memory_bytes,
            network_bytes: value.network_bytes,
            external_effect_count: value.external_effect_count,
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ObjectiveConstraintSetWire {
    objective_id: String,
    revision: u64,
    constitutional_constraints: Vec<CanonicalConstraintWire>,
    principal_constraints: Vec<CanonicalConstraintWire>,
    environment_constraints: Vec<CanonicalConstraintWire>,
    legal_action_classes: Vec<String>,
    forbidden_action_classes: Vec<String>,
    evidence_requirements: Vec<EvidenceRequirementWire>,
    resource_ceiling: ResourceWire,
    rollback_class: &'static str,
    semantic_digest: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceRequirementWire {
    requirement_id: String,
    evidence_source_id: String,
    minimum_confidence_ppm: u32,
    terminal: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ObjectiveCompileReceiptWire {
    request_id: String,
    objective_id: String,
    revision: u64,
    source_envelope_digest: String,
    constraint_set_digest: String,
    objective_function_digest: String,
    normalization_profile_digest: String,
    canonical_bytes: u32,
    disposition: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunStartSnapshotWire {
    run_id: String,
    objective_digest: String,
    hard_constraint_digest: String,
    preference_state_digest: String,
    model_tuple_digest: String,
    prompt_registry_digest: String,
    artifact_set_digest: String,
    authority_epoch: u64,
    generation: u64,
    fence_digest: String,
}
