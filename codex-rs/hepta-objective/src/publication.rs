use std::error::Error;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::ActionClass;
use crate::CompileDisposition;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionError;
use crate::ObjectiveAdmissionProfileV1;
use crate::ObjectiveAdmissionReceiptV1;
use crate::ObjectiveCompileReceipt;
use crate::ObjectiveConflictReceipt;
use crate::ObjectiveFunction;
use crate::ObjectiveSourceEnvelopeV1;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SoftPreference;
use crate::SuccessPredicate;
use crate::admit_and_compile_objective_v1;

pub const MAX_OBJECTIVE_RUN_START_PUBLICATION_BYTES: usize = 256 * 1024;
const PUBLICATION_SCHEMA: &str = "hepta.objective-run-start-publication.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRunStartBindingsV1 {
    pub run_id: StableId,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartSnapshotV1 {
    pub run_id: StableId,
    pub objective_digest: Digest32,
    pub hard_constraint_digest: Digest32,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRunStartPublicationV1 {
    admission: ObjectiveAdmissionReceiptV1,
    compile: ObjectiveCompileReceipt,
    run_start: RunStartSnapshotV1,
    publication_digest: Digest32,
}

impl ObjectiveRunStartPublicationV1 {
    #[must_use]
    pub const fn admission(&self) -> &ObjectiveAdmissionReceiptV1 {
        &self.admission
    }

    #[must_use]
    pub const fn compile_receipt(&self) -> &ObjectiveCompileReceipt {
        &self.compile
    }

    #[must_use]
    pub const fn run_start(&self) -> &RunStartSnapshotV1 {
        &self.run_start
    }

    #[must_use]
    pub const fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ObjectivePublicationError {
    Admission(ObjectiveAdmissionError),
    Conflict(ObjectiveConflictReceipt),
    InvalidBinding(&'static str),
    Encoding,
    Decode,
    NonCanonicalEncoding,
    TooLarge { actual: usize, maximum: usize },
    PublicationDigestMismatch,
}

impl fmt::Display for ObjectivePublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Admission(error) => error.fmt(formatter),
            Self::Conflict(receipt) => write!(
                formatter,
                "objective constraints conflict: {}",
                receipt.conflict_digest
            ),
            Self::InvalidBinding(field) => write!(formatter, "invalid run-start binding: {field}"),
            Self::Encoding => {
                formatter.write_str("objective run-start publication encoding failed")
            }
            Self::Decode => formatter.write_str("objective run-start publication decoding failed"),
            Self::NonCanonicalEncoding => {
                formatter.write_str("objective run-start publication is not canonical")
            }
            Self::TooLarge { actual, maximum } => write!(
                formatter,
                "objective run-start publication has {actual} bytes; maximum is {maximum}"
            ),
            Self::PublicationDigestMismatch => {
                formatter.write_str("objective run-start publication digest mismatch")
            }
        }
    }
}

impl Error for ObjectivePublicationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            _ => None,
        }
    }
}

impl From<ObjectiveAdmissionError> for ObjectivePublicationError {
    fn from(value: ObjectiveAdmissionError) -> Self {
        Self::Admission(value)
    }
}

/// Authenticates and compiles one source envelope, then freezes the exact
/// objective and run-start bindings into one immutable publication.
///
/// This function has no I/O or effect authority. Durable publication is owned by
/// the caller's registered store; identical inputs produce identical bytes.
pub fn prepare_objective_run_start_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ObjectiveAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    bindings: ObjectiveRunStartBindingsV1,
) -> Result<ObjectiveRunStartPublicationV1, ObjectivePublicationError> {
    validate_bindings(&bindings)?;
    let outcome = admit_and_compile_objective_v1(envelope, profile, context)?;
    let compile = outcome
        .compile_result
        .map_err(ObjectivePublicationError::Conflict)?;
    let admission = outcome.receipt;
    if admission.authority.grants_any() {
        return Err(ObjectivePublicationError::InvalidBinding(
            "admission authority",
        ));
    }
    let run_start = RunStartSnapshotV1 {
        run_id: bindings.run_id,
        objective_digest: compile.objective.semantic_digest,
        hard_constraint_digest: compile.objective.hard_constraint_digest,
        preference_state_digest: bindings.preference_state_digest,
        model_tuple_digest: bindings.model_tuple_digest,
        prompt_registry_digest: bindings.prompt_registry_digest,
        artifact_set_digest: bindings.artifact_set_digest,
        authority_epoch: bindings.authority_epoch,
        generation: bindings.generation,
        fence_digest: bindings.fence_digest,
    };
    let mut publication = ObjectiveRunStartPublicationV1 {
        admission,
        compile,
        run_start,
        publication_digest: Digest32::ZERO,
    };
    validate_publication(&publication)?;
    let bytes = canonical_bytes_unchecked(&publication)?;
    publication.publication_digest = Digest32::of_bytes(&bytes);
    Ok(publication)
}

pub fn encode_objective_run_start_publication_v1(
    publication: &ObjectiveRunStartPublicationV1,
) -> Result<Vec<u8>, ObjectivePublicationError> {
    validate_publication(publication)?;
    let bytes = canonical_bytes_unchecked(publication)?;
    let digest = Digest32::of_bytes(&bytes);
    if publication.publication_digest != digest {
        return Err(ObjectivePublicationError::PublicationDigestMismatch);
    }
    Ok(bytes)
}

pub fn decode_objective_run_start_publication_v1(
    input: &[u8],
) -> Result<ObjectiveRunStartPublicationV1, ObjectivePublicationError> {
    if input.len() > MAX_OBJECTIVE_RUN_START_PUBLICATION_BYTES {
        return Err(ObjectivePublicationError::TooLarge {
            actual: input.len(),
            maximum: MAX_OBJECTIVE_RUN_START_PUBLICATION_BYTES,
        });
    }
    let dto: PublicationDto =
        serde_json::from_slice(input).map_err(|_| ObjectivePublicationError::Decode)?;
    if dto.schema != PUBLICATION_SCHEMA {
        return Err(ObjectivePublicationError::Decode);
    }
    let canonical = serde_json::to_vec(&dto).map_err(|_| ObjectivePublicationError::Encoding)?;
    if canonical != input {
        return Err(ObjectivePublicationError::NonCanonicalEncoding);
    }
    let mut publication = publication_from_dto(dto)?;
    publication.publication_digest = Digest32::of_bytes(input);
    validate_publication(&publication)?;
    Ok(publication)
}

fn validate_bindings(
    bindings: &ObjectiveRunStartBindingsV1,
) -> Result<(), ObjectivePublicationError> {
    if bindings.authority_epoch == 0 {
        return Err(ObjectivePublicationError::InvalidBinding("authorityEpoch"));
    }
    if bindings.generation == 0 {
        return Err(ObjectivePublicationError::InvalidBinding("generation"));
    }
    for (name, digest) in [
        ("preferenceStateDigest", bindings.preference_state_digest),
        ("modelTupleDigest", bindings.model_tuple_digest),
        ("promptRegistryDigest", bindings.prompt_registry_digest),
        ("artifactSetDigest", bindings.artifact_set_digest),
        ("fenceDigest", bindings.fence_digest),
    ] {
        if digest.is_zero() {
            return Err(ObjectivePublicationError::InvalidBinding(name));
        }
    }
    Ok(())
}

fn validate_publication(
    publication: &ObjectiveRunStartPublicationV1,
) -> Result<(), ObjectivePublicationError> {
    if publication.admission.authority.grants_any() {
        return Err(ObjectivePublicationError::InvalidBinding(
            "admission authority",
        ));
    }
    for (name, digest) in [
        ("profileDigest", publication.admission.profile_digest),
        (
            "suppliedSourceDigest",
            publication.admission.supplied_source_digest,
        ),
        ("intentDigest", publication.admission.intent_digest),
        (
            "admittedSourceDigest",
            publication.admission.admitted_source_digest,
        ),
        (
            "objectiveDigest",
            publication.compile.objective.semantic_digest,
        ),
        (
            "hardConstraintDigest",
            publication.compile.objective.hard_constraint_digest,
        ),
        (
            "preferenceStateDigest",
            publication.run_start.preference_state_digest,
        ),
        ("modelTupleDigest", publication.run_start.model_tuple_digest),
        (
            "promptRegistryDigest",
            publication.run_start.prompt_registry_digest,
        ),
        (
            "artifactSetDigest",
            publication.run_start.artifact_set_digest,
        ),
        ("fenceDigest", publication.run_start.fence_digest),
    ] {
        if digest.is_zero() {
            return Err(ObjectivePublicationError::InvalidBinding(name));
        }
    }
    if publication.run_start.objective_digest != publication.compile.objective.semantic_digest {
        return Err(ObjectivePublicationError::InvalidBinding("objectiveDigest"));
    }
    if publication.run_start.hard_constraint_digest
        != publication.compile.objective.hard_constraint_digest
    {
        return Err(ObjectivePublicationError::InvalidBinding(
            "hardConstraintDigest",
        ));
    }
    Ok(())
}

fn canonical_bytes_unchecked(
    publication: &ObjectiveRunStartPublicationV1,
) -> Result<Vec<u8>, ObjectivePublicationError> {
    let dto = dto_from_publication(publication);
    let bytes = serde_json::to_vec(&dto).map_err(|_| ObjectivePublicationError::Encoding)?;
    if bytes.len() > MAX_OBJECTIVE_RUN_START_PUBLICATION_BYTES {
        return Err(ObjectivePublicationError::TooLarge {
            actual: bytes.len(),
            maximum: MAX_OBJECTIVE_RUN_START_PUBLICATION_BYTES,
        });
    }
    Ok(bytes)
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PublicationDto {
    schema: String,
    admission: AdmissionDto,
    objective: ObjectiveDto,
    disposition: String,
    removed_action_ids: Vec<String>,
    run_start: RunStartDto,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AdmissionDto {
    profile_id: String,
    profile_revision: u64,
    profile_digest: String,
    supplied_source_digest: String,
    intent_digest: String,
    admitted_source_digest: String,
    observed_at_unix_micros: u64,
    deadline_unix_micros: Option<u64>,
    authority: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ObjectiveDto {
    request_id: String,
    principal_scope: String,
    revision: u64,
    source_digest: String,
    schema_digest: String,
    hard_constraint_digest: String,
    semantic_digest: String,
    constraints: Vec<ConstraintDto>,
    success_predicates: Vec<PredicateDto>,
    legal_actions: Vec<ActionDto>,
    soft_preferences: Vec<PreferenceDto>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ConstraintDto {
    id: String,
    class: String,
    axis: String,
    relation: String,
    bound_q32: i64,
    evidence_source: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PredicateDto {
    id: String,
    axis: String,
    relation: String,
    bound_q32: i64,
    evidence_source: String,
    terminality: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ActionDto {
    id: String,
    confirmation: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PreferenceDto {
    dimension: String,
    direction: String,
    weight_q32: i64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RunStartDto {
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

fn dto_from_publication(publication: &ObjectiveRunStartPublicationV1) -> PublicationDto {
    PublicationDto {
        schema: PUBLICATION_SCHEMA.to_string(),
        admission: AdmissionDto {
            profile_id: publication.admission.profile_id.to_string(),
            profile_revision: publication.admission.profile_revision.get(),
            profile_digest: publication.admission.profile_digest.to_string(),
            supplied_source_digest: publication.admission.supplied_source_digest.to_string(),
            intent_digest: publication.admission.intent_digest.to_string(),
            admitted_source_digest: publication.admission.admitted_source_digest.to_string(),
            observed_at_unix_micros: publication.admission.observed_at_unix_micros,
            deadline_unix_micros: publication.admission.deadline_unix_micros,
            authority: "deny_all".to_string(),
        },
        objective: ObjectiveDto {
            request_id: publication.compile.objective.request_id.to_string(),
            principal_scope: publication.compile.objective.principal_scope.to_string(),
            revision: publication.compile.objective.revision.get(),
            source_digest: publication.compile.objective.source_digest.to_string(),
            schema_digest: publication.compile.objective.schema_digest.to_string(),
            hard_constraint_digest: publication
                .compile
                .objective
                .hard_constraint_digest
                .to_string(),
            semantic_digest: publication.compile.objective.semantic_digest.to_string(),
            constraints: publication
                .compile
                .objective
                .constraints
                .iter()
                .map(constraint_to_dto)
                .collect(),
            success_predicates: publication
                .compile
                .objective
                .success_predicates
                .iter()
                .map(predicate_to_dto)
                .collect(),
            legal_actions: publication
                .compile
                .objective
                .legal_actions
                .iter()
                .map(action_to_dto)
                .collect(),
            soft_preferences: publication
                .compile
                .objective
                .soft_preferences
                .iter()
                .map(preference_to_dto)
                .collect(),
        },
        disposition: match publication.compile.disposition {
            CompileDisposition::Compiled => "compiled",
            CompileDisposition::ExplicitAbstain => "explicit_abstain",
        }
        .to_string(),
        removed_action_ids: publication
            .compile
            .removed_action_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        run_start: RunStartDto {
            run_id: publication.run_start.run_id.to_string(),
            objective_digest: publication.run_start.objective_digest.to_string(),
            hard_constraint_digest: publication.run_start.hard_constraint_digest.to_string(),
            preference_state_digest: publication.run_start.preference_state_digest.to_string(),
            model_tuple_digest: publication.run_start.model_tuple_digest.to_string(),
            prompt_registry_digest: publication.run_start.prompt_registry_digest.to_string(),
            artifact_set_digest: publication.run_start.artifact_set_digest.to_string(),
            authority_epoch: publication.run_start.authority_epoch,
            generation: publication.run_start.generation,
            fence_digest: publication.run_start.fence_digest.to_string(),
        },
    }
}

fn publication_from_dto(
    dto: PublicationDto,
) -> Result<ObjectiveRunStartPublicationV1, ObjectivePublicationError> {
    if dto.admission.authority != "deny_all" {
        return Err(ObjectivePublicationError::Decode);
    }
    let objective = ObjectiveFunction {
        request_id: parse_id(dto.objective.request_id)?,
        principal_scope: parse_id(dto.objective.principal_scope)?,
        revision: parse_revision(dto.objective.revision)?,
        source_digest: parse_digest(&dto.objective.source_digest)?,
        schema_digest: parse_digest(&dto.objective.schema_digest)?,
        hard_constraint_digest: parse_digest(&dto.objective.hard_constraint_digest)?,
        semantic_digest: parse_digest(&dto.objective.semantic_digest)?,
        constraints: dto
            .objective
            .constraints
            .into_iter()
            .map(constraint_from_dto)
            .collect::<Result<Vec<_>, _>>()?,
        success_predicates: dto
            .objective
            .success_predicates
            .into_iter()
            .map(predicate_from_dto)
            .collect::<Result<Vec<_>, _>>()?,
        legal_actions: dto
            .objective
            .legal_actions
            .into_iter()
            .map(action_from_dto)
            .collect::<Result<Vec<_>, _>>()?,
        soft_preferences: dto
            .objective
            .soft_preferences
            .into_iter()
            .map(preference_from_dto)
            .collect::<Result<Vec<_>, _>>()?,
    };
    let disposition = match dto.disposition.as_str() {
        "compiled" => CompileDisposition::Compiled,
        "explicit_abstain" => CompileDisposition::ExplicitAbstain,
        _ => return Err(ObjectivePublicationError::Decode),
    };
    Ok(ObjectiveRunStartPublicationV1 {
        admission: ObjectiveAdmissionReceiptV1 {
            profile_id: parse_id(dto.admission.profile_id)?,
            profile_revision: parse_revision(dto.admission.profile_revision)?,
            profile_digest: parse_digest(&dto.admission.profile_digest)?,
            supplied_source_digest: parse_digest(&dto.admission.supplied_source_digest)?,
            intent_digest: parse_digest(&dto.admission.intent_digest)?,
            admitted_source_digest: parse_digest(&dto.admission.admitted_source_digest)?,
            observed_at_unix_micros: dto.admission.observed_at_unix_micros,
            deadline_unix_micros: dto.admission.deadline_unix_micros,
            authority: AuthorityPosture::DENY_ALL,
        },
        compile: ObjectiveCompileReceipt {
            objective,
            disposition,
            removed_action_ids: dto
                .removed_action_ids
                .into_iter()
                .map(parse_id)
                .collect::<Result<Vec<_>, _>>()?,
        },
        run_start: RunStartSnapshotV1 {
            run_id: parse_id(dto.run_start.run_id)?,
            objective_digest: parse_digest(&dto.run_start.objective_digest)?,
            hard_constraint_digest: parse_digest(&dto.run_start.hard_constraint_digest)?,
            preference_state_digest: parse_digest(&dto.run_start.preference_state_digest)?,
            model_tuple_digest: parse_digest(&dto.run_start.model_tuple_digest)?,
            prompt_registry_digest: parse_digest(&dto.run_start.prompt_registry_digest)?,
            artifact_set_digest: parse_digest(&dto.run_start.artifact_set_digest)?,
            authority_epoch: dto.run_start.authority_epoch,
            generation: dto.run_start.generation,
            fence_digest: parse_digest(&dto.run_start.fence_digest)?,
        },
        publication_digest: Digest32::ZERO,
    })
}

fn constraint_to_dto(value: &Constraint) -> ConstraintDto {
    ConstraintDto {
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

fn constraint_from_dto(value: ConstraintDto) -> Result<Constraint, ObjectivePublicationError> {
    Ok(Constraint {
        id: parse_id(value.id)?,
        class: match value.class.as_str() {
            "constitutional" => ConstraintClass::Constitutional,
            "principal" => ConstraintClass::Principal,
            "environment" => ConstraintClass::Environment,
            "task" => ConstraintClass::Task,
            _ => return Err(ObjectivePublicationError::Decode),
        },
        axis: parse_id(value.axis)?,
        relation: parse_relation(&value.relation)?,
        bound: FixedQ32::from_raw(value.bound_q32),
        evidence_source: parse_id(value.evidence_source)?,
    })
}

fn predicate_to_dto(value: &SuccessPredicate) -> PredicateDto {
    PredicateDto {
        id: value.id.to_string(),
        axis: value.axis.to_string(),
        relation: relation_name(value.relation).to_string(),
        bound_q32: value.bound.raw(),
        evidence_source: value.evidence_source.to_string(),
        terminality: match value.terminality {
            PredicateTerminality::Intermediate => "intermediate",
            PredicateTerminality::Terminal => "terminal",
        }
        .to_string(),
    }
}

fn predicate_from_dto(value: PredicateDto) -> Result<SuccessPredicate, ObjectivePublicationError> {
    Ok(SuccessPredicate {
        id: parse_id(value.id)?,
        axis: parse_id(value.axis)?,
        relation: parse_relation(&value.relation)?,
        bound: FixedQ32::from_raw(value.bound_q32),
        evidence_source: parse_id(value.evidence_source)?,
        terminality: match value.terminality.as_str() {
            "intermediate" => PredicateTerminality::Intermediate,
            "terminal" => PredicateTerminality::Terminal,
            _ => return Err(ObjectivePublicationError::Decode),
        },
    })
}

fn action_to_dto(value: &ActionClass) -> ActionDto {
    ActionDto {
        id: value.id.to_string(),
        confirmation: match value.confirmation {
            ConfirmationPolicy::NotRequired => "not_required",
            ConfirmationPolicy::Required => "required",
        }
        .to_string(),
    }
}

fn action_from_dto(value: ActionDto) -> Result<ActionClass, ObjectivePublicationError> {
    Ok(ActionClass {
        id: parse_id(value.id)?,
        confirmation: match value.confirmation.as_str() {
            "not_required" => ConfirmationPolicy::NotRequired,
            "required" => ConfirmationPolicy::Required,
            _ => return Err(ObjectivePublicationError::Decode),
        },
    })
}

fn preference_to_dto(value: &SoftPreference) -> PreferenceDto {
    PreferenceDto {
        dimension: value.dimension.to_string(),
        direction: match value.direction {
            SoftDirection::Maximize => "maximize",
            SoftDirection::Minimize => "minimize",
        }
        .to_string(),
        weight_q32: value.weight.raw(),
    }
}

fn preference_from_dto(value: PreferenceDto) -> Result<SoftPreference, ObjectivePublicationError> {
    Ok(SoftPreference {
        dimension: parse_id(value.dimension)?,
        direction: match value.direction.as_str() {
            "maximize" => SoftDirection::Maximize,
            "minimize" => SoftDirection::Minimize,
            _ => return Err(ObjectivePublicationError::Decode),
        },
        weight: FixedQ32::from_raw(value.weight_q32),
    })
}

const fn relation_name(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "at_least",
        ConstraintRelation::AtMost => "at_most",
        ConstraintRelation::Equal => "equal",
    }
}

fn parse_relation(value: &str) -> Result<ConstraintRelation, ObjectivePublicationError> {
    match value {
        "at_least" => Ok(ConstraintRelation::AtLeast),
        "at_most" => Ok(ConstraintRelation::AtMost),
        "equal" => Ok(ConstraintRelation::Equal),
        _ => Err(ObjectivePublicationError::Decode),
    }
}

fn parse_id(value: String) -> Result<StableId, ObjectivePublicationError> {
    StableId::new(value).map_err(|_| ObjectivePublicationError::Decode)
}

fn parse_revision(value: u64) -> Result<Revision, ObjectivePublicationError> {
    Revision::new(value).map_err(|_| ObjectivePublicationError::Decode)
}

fn parse_digest(value: &str) -> Result<Digest32, ObjectivePublicationError> {
    Digest32::from_str(value).map_err(|_| ObjectivePublicationError::Decode)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ObjectiveSourceEnvelope;
    use crate::SourceTrust;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn publication() -> ObjectiveRunStartPublicationV1 {
        let compile =
            crate::compiler::compile_prevalidated_legacy_objective(ObjectiveSourceEnvelope {
                request_id: id("request-publication"),
                principal_scope: id("principal.alpha"),
                revision: Revision::new(1).expect("revision"),
                source_trust: SourceTrust::PrincipalStructured,
                source_digest: digest("source"),
                schema_digest: digest("schema"),
                constraints: vec![Constraint {
                    id: id("constraint.one"),
                    class: ConstraintClass::Task,
                    axis: id("latency"),
                    relation: ConstraintRelation::AtMost,
                    bound: FixedQ32::ONE,
                    evidence_source: id("observer"),
                }],
                success_predicates: vec![SuccessPredicate {
                    id: id("success.one"),
                    axis: id("quality"),
                    relation: ConstraintRelation::AtLeast,
                    bound: FixedQ32::ONE,
                    evidence_source: id("observer"),
                    terminality: PredicateTerminality::Terminal,
                }],
                allowed_actions: vec![ActionClass {
                    id: id("action.read"),
                    confirmation: ConfirmationPolicy::NotRequired,
                }],
                forbidden_actions: Vec::new(),
                soft_preferences: Vec::new(),
            })
            .expect("compile error")
            .expect("conflict");
        let mut value = ObjectiveRunStartPublicationV1 {
            admission: ObjectiveAdmissionReceiptV1 {
                profile_id: id("profile.one"),
                profile_revision: Revision::new(1).expect("revision"),
                profile_digest: digest("profile"),
                supplied_source_digest: digest("supplied"),
                intent_digest: digest("intent"),
                admitted_source_digest: digest("admitted"),
                observed_at_unix_micros: 1,
                deadline_unix_micros: Some(2),
                authority: AuthorityPosture::DENY_ALL,
            },
            run_start: RunStartSnapshotV1 {
                run_id: id("run.one"),
                objective_digest: compile.objective.semantic_digest,
                hard_constraint_digest: compile.objective.hard_constraint_digest,
                preference_state_digest: digest("preference"),
                model_tuple_digest: digest("model"),
                prompt_registry_digest: digest("prompt"),
                artifact_set_digest: digest("artifact"),
                authority_epoch: 7,
                generation: 9,
                fence_digest: digest("fence"),
            },
            compile,
            publication_digest: Digest32::ZERO,
        };
        let bytes = canonical_bytes_unchecked(&value).expect("encode");
        value.publication_digest = Digest32::of_bytes(&bytes);
        value
    }

    #[test]
    fn publication_round_trip_is_canonical_and_digest_bound() {
        let value = publication();
        let bytes = encode_objective_run_start_publication_v1(&value).expect("encode");
        let decoded = decode_objective_run_start_publication_v1(&bytes).expect("decode");
        assert_eq!(decoded, value);
        assert_eq!(decoded.publication_digest(), Digest32::of_bytes(&bytes));
    }

    #[test]
    fn noncanonical_or_tampered_publication_is_rejected() {
        let value = publication();
        let bytes = encode_objective_run_start_publication_v1(&value).expect("encode");
        let mut spaced = b" ".to_vec();
        spaced.extend_from_slice(&bytes);
        assert_eq!(
            decode_objective_run_start_publication_v1(&spaced),
            Err(ObjectivePublicationError::NonCanonicalEncoding)
        );

        let mut changed = value.clone();
        changed.run_start.fence_digest = digest("different-fence");
        assert_eq!(
            encode_objective_run_start_publication_v1(&changed),
            Err(ObjectivePublicationError::PublicationDigestMismatch)
        );
    }
}
