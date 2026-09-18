use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Serialize;

use crate::CompileDisposition;
use crate::ConfirmationPolicy;
use crate::Constraint;
use crate::ConstraintClass;
use crate::ConstraintRelation;
use crate::ObjectiveAdmissionReceiptV1;
use crate::ObjectiveCompileReceipt;
use crate::PredicateTerminality;
use crate::SoftDirection;
use crate::SourceTrust;
use crate::SuccessPredicate;

const RUN_START_DOMAIN: &[u8] = b"hepta.objective.run-start.v1";
const PUBLICATION_DOMAIN: &[u8] = b"hepta.objective.run-publication.v1";

#[must_use]
pub fn objective_run_publication_digest_v1(canonical_json: &[u8]) -> Digest32 {
    let mut bytes = PUBLICATION_DOMAIN.to_vec();
    bytes.extend_from_slice(canonical_json);
    Digest32::of_bytes(&bytes)
}

/// Caller-owned bindings that are frozen with one compiled objective before a
/// runtime run can be admitted. These values are observations, not effect grants.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunStartBindingsV1 {
    pub run_id: StableId,
    pub preference_state_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub prompt_registry_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
}

/// Native representation of the registered `RunStartSnapshotV1` contract.
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

impl RunStartSnapshotV1 {
    pub fn canonical_json(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(&RunStartSnapshotWire::from(self))
    }

    pub fn semantic_digest(&self) -> Result<Digest32, serde_json::Error> {
        let bytes = self.canonical_json()?;
        let mut domain = RUN_START_DOMAIN.to_vec();
        domain.extend_from_slice(&bytes);
        Ok(Digest32::of_bytes(&domain))
    }
}

/// One immutable objective publication. The owning product caller persists the
/// canonical bytes atomically before exposing the run snapshot to runtime code.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveRunPublicationV1 {
    pub admission: ObjectiveAdmissionReceiptV1,
    pub compile: ObjectiveCompileReceipt,
    pub run_start: RunStartSnapshotV1,
}

impl ObjectiveRunPublicationV1 {
    pub fn new(
        admission: ObjectiveAdmissionReceiptV1,
        compile: ObjectiveCompileReceipt,
        bindings: RunStartBindingsV1,
    ) -> Result<Self, ObjectiveRunPublicationError> {
        if admission.authority.grants_any() {
            return Err(ObjectiveRunPublicationError::AuthorityEscalation);
        }
        validate_digest("objective", compile.objective.semantic_digest)?;
        validate_digest("hard constraint", compile.objective.hard_constraint_digest)?;
        validate_digest("preference state", bindings.preference_state_digest)?;
        validate_digest("model tuple", bindings.model_tuple_digest)?;
        validate_digest("prompt registry", bindings.prompt_registry_digest)?;
        validate_digest("artifact set", bindings.artifact_set_digest)?;
        validate_digest("fence", bindings.fence_digest)?;
        if bindings.authority_epoch == 0 {
            return Err(ObjectiveRunPublicationError::ZeroCounter("authority epoch"));
        }
        if bindings.generation == 0 {
            return Err(ObjectiveRunPublicationError::ZeroCounter("generation"));
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
        Ok(Self {
            admission,
            compile,
            run_start,
        })
    }

    pub fn canonical_json(&self) -> Result<Vec<u8>, serde_json::Error> {
        serde_json::to_vec(&ObjectiveRunPublicationWire::from(self))
    }

    pub fn publication_digest(&self) -> Result<Digest32, serde_json::Error> {
        let bytes = self.canonical_json()?;
        Ok(objective_run_publication_digest_v1(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectiveRunPublicationError {
    EmptyDigest(&'static str),
    ZeroCounter(&'static str),
    AuthorityEscalation,
}

impl fmt::Display for ObjectiveRunPublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyDigest(field) => write!(formatter, "empty run publication digest: {field}"),
            Self::ZeroCounter(field) => write!(formatter, "run publication counter must be non-zero: {field}"),
            Self::AuthorityEscalation => formatter.write_str("objective admission unexpectedly grants authority"),
        }
    }
}

impl Error for ObjectiveRunPublicationError {}

fn validate_digest(field: &'static str, digest: Digest32) -> Result<(), ObjectiveRunPublicationError> {
    if digest.is_zero() {
        Err(ObjectiveRunPublicationError::EmptyDigest(field))
    } else {
        Ok(())
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RunStartSnapshotWire<'a> {
    run_id: &'a str,
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

impl<'a> From<&'a RunStartSnapshotV1> for RunStartSnapshotWire<'a> {
    fn from(value: &'a RunStartSnapshotV1) -> Self {
        Self {
            run_id: value.run_id.as_str(),
            objective_digest: value.objective_digest.to_string(),
            hard_constraint_digest: value.hard_constraint_digest.to_string(),
            preference_state_digest: value.preference_state_digest.to_string(),
            model_tuple_digest: value.model_tuple_digest.to_string(),
            prompt_registry_digest: value.prompt_registry_digest.to_string(),
            artifact_set_digest: value.artifact_set_digest.to_string(),
            authority_epoch: value.authority_epoch,
            generation: value.generation,
            fence_digest: value.fence_digest.to_string(),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ObjectiveRunPublicationWire<'a> {
    schema_version: u32,
    admission: AdmissionWire<'a>,
    compile: CompileWire<'a>,
    run_start: RunStartSnapshotWire<'a>,
}

impl<'a> From<&'a ObjectiveRunPublicationV1> for ObjectiveRunPublicationWire<'a> {
    fn from(value: &'a ObjectiveRunPublicationV1) -> Self {
        Self {
            schema_version: 1,
            admission: AdmissionWire::from(&value.admission),
            compile: CompileWire::from(&value.compile),
            run_start: RunStartSnapshotWire::from(&value.run_start),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AdmissionWire<'a> {
    profile_id: &'a str,
    profile_revision: u64,
    profile_digest: String,
    supplied_source_digest: String,
    intent_digest: String,
    admitted_source_digest: String,
    observed_at_unix_micros: u64,
    deadline_unix_micros: Option<u64>,
    authority_deny_all: bool,
}

impl<'a> From<&'a ObjectiveAdmissionReceiptV1> for AdmissionWire<'a> {
    fn from(value: &'a ObjectiveAdmissionReceiptV1) -> Self {
        Self {
            profile_id: value.profile_id.as_str(),
            profile_revision: value.profile_revision.get(),
            profile_digest: value.profile_digest.to_string(),
            supplied_source_digest: value.supplied_source_digest.to_string(),
            intent_digest: value.intent_digest.to_string(),
            admitted_source_digest: value.admitted_source_digest.to_string(),
            observed_at_unix_micros: value.observed_at_unix_micros,
            deadline_unix_micros: value.deadline_unix_micros,
            authority_deny_all: value.authority == AuthorityPosture::DENY_ALL,
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CompileWire<'a> {
    disposition: &'static str,
    removed_action_ids: Vec<&'a str>,
    objective: ObjectiveWire<'a>,
}

impl<'a> From<&'a ObjectiveCompileReceipt> for CompileWire<'a> {
    fn from(value: &'a ObjectiveCompileReceipt) -> Self {
        Self {
            disposition: match value.disposition {
                CompileDisposition::Compiled => "compiled",
                CompileDisposition::ExplicitAbstain => "explicit_abstain",
            },
            removed_action_ids: value.removed_action_ids.iter().map(StableId::as_str).collect(),
            objective: ObjectiveWire::from(value),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ObjectiveWire<'a> {
    request_id: &'a str,
    principal_scope: &'a str,
    revision: u64,
    source_digest: String,
    schema_digest: String,
    hard_constraint_digest: String,
    semantic_digest: String,
    constraints: Vec<ConstraintWire<'a>>,
    success_predicates: Vec<PredicateWire<'a>>,
    legal_actions: Vec<ActionWire<'a>>,
    soft_preferences: Vec<PreferenceWire<'a>>,
}

impl<'a> From<&'a ObjectiveCompileReceipt> for ObjectiveWire<'a> {
    fn from(value: &'a ObjectiveCompileReceipt) -> Self {
        let objective = &value.objective;
        Self {
            request_id: objective.request_id.as_str(),
            principal_scope: objective.principal_scope.as_str(),
            revision: objective.revision.get(),
            source_digest: objective.source_digest.to_string(),
            schema_digest: objective.schema_digest.to_string(),
            hard_constraint_digest: objective.hard_constraint_digest.to_string(),
            semantic_digest: objective.semantic_digest.to_string(),
            constraints: objective.constraints.iter().map(ConstraintWire::from).collect(),
            success_predicates: objective.success_predicates.iter().map(PredicateWire::from).collect(),
            legal_actions: objective.legal_actions.iter().map(ActionWire::from).collect(),
            soft_preferences: objective.soft_preferences.iter().map(PreferenceWire::from).collect(),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ConstraintWire<'a> {
    id: &'a str,
    class: &'static str,
    axis: &'a str,
    relation: &'static str,
    bound_q32: i64,
    evidence_source: &'a str,
}

impl<'a> From<&'a Constraint> for ConstraintWire<'a> {
    fn from(value: &'a Constraint) -> Self {
        Self {
            id: value.id.as_str(),
            class: match value.class {
                ConstraintClass::Constitutional => "constitutional",
                ConstraintClass::Principal => "principal",
                ConstraintClass::Environment => "environment",
                ConstraintClass::Task => "task",
            },
            axis: value.axis.as_str(),
            relation: relation_name(value.relation),
            bound_q32: value.bound.raw(),
            evidence_source: value.evidence_source.as_str(),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PredicateWire<'a> {
    id: &'a str,
    axis: &'a str,
    relation: &'static str,
    bound_q32: i64,
    evidence_source: &'a str,
    terminality: &'static str,
}

impl<'a> From<&'a SuccessPredicate> for PredicateWire<'a> {
    fn from(value: &'a SuccessPredicate) -> Self {
        Self {
            id: value.id.as_str(),
            axis: value.axis.as_str(),
            relation: relation_name(value.relation),
            bound_q32: value.bound.raw(),
            evidence_source: value.evidence_source.as_str(),
            terminality: match value.terminality {
                PredicateTerminality::Intermediate => "intermediate",
                PredicateTerminality::Terminal => "terminal",
            },
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ActionWire<'a> {
    id: &'a str,
    confirmation: &'static str,
}

impl<'a> From<&'a crate::ActionClass> for ActionWire<'a> {
    fn from(value: &'a crate::ActionClass) -> Self {
        Self {
            id: value.id.as_str(),
            confirmation: match value.confirmation {
                ConfirmationPolicy::NotRequired => "not_required",
                ConfirmationPolicy::Required => "required",
            },
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PreferenceWire<'a> {
    dimension: &'a str,
    direction: &'static str,
    weight_q32: i64,
}

impl<'a> From<&'a crate::SoftPreference> for PreferenceWire<'a> {
    fn from(value: &'a crate::SoftPreference) -> Self {
        Self {
            dimension: value.dimension.as_str(),
            direction: match value.direction {
                SoftDirection::Maximize => "maximize",
                SoftDirection::Minimize => "minimize",
            },
            weight_q32: value.weight.raw(),
        }
    }
}

fn relation_name(value: ConstraintRelation) -> &'static str {
    match value {
        ConstraintRelation::AtLeast => "at_least",
        ConstraintRelation::AtMost => "at_most",
        ConstraintRelation::Equal => "equal",
    }
}

#[allow(dead_code)]
fn source_trust_name(value: SourceTrust) -> &'static str {
    match value {
        SourceTrust::PrincipalStructured => "principal_structured",
        SourceTrust::RegisteredAdapter => "registered_adapter",
        SourceTrust::UntrustedEvidence => "untrusted_evidence",
    }
}

#[cfg(test)]
#[path = "publication_tests.rs"]
mod tests;
