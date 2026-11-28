//! Record-only observation profile. The original capture bytes are not present
//! in the two-file native material owner; this type cannot certify that source.

use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use super::digest_field;
use super::parse_integer_json;
use super::text;
use crate::AgentdError;
use crate::notes_literal_adapter::invalid;

pub(super) const SCHEMA: &str = "hepta.cell-experiments.opaque-teacher-observation.v1";

/// Evidence actually available to this native observation. Neither the capture
/// nor teacher weights, generation or execution have been authenticated.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PairedOpaqueEvidenceV1 {
    RecordOnly { unverified_capture_sha256: Digest32 },
}

/// One prompt and one observed answer, with no history, native labels or permit.
/// Only the fresh original material identity path constructs this value.
pub struct PairedOpaqueFinalAnswerObservationV1 {
    evidence: PairedOpaqueEvidenceV1,
    prompt: String,
    answer: String,
    declared_student_policy: Digest32,
}

impl PairedOpaqueFinalAnswerObservationV1 {
    pub fn evidence(&self) -> PairedOpaqueEvidenceV1 {
        self.evidence
    }

    pub fn prompt(&self) -> &str {
        &self.prompt
    }

    pub fn observed_final_answer(&self) -> &str {
        &self.answer
    }

    pub fn declared_student_policy(&self) -> Digest32 {
        self.declared_student_policy
    }
}

fn exact_fields(value: &Value, fields: &str) -> Result<(), AgentdError> {
    let object = value
        .as_object()
        .ok_or_else(|| invalid("opaque observation object required"))?;
    if object.len() != fields.split_whitespace().count()
        || fields
            .split_whitespace()
            .any(|field| !object.contains_key(field))
    {
        return Err(invalid(
            "opaque observation fields differ from the native profile",
        ));
    }
    Ok(())
}

fn check_depth(value: &Value, depth: usize) -> Result<(), AgentdError> {
    if depth > 32 {
        return Err(invalid("opaque observation nesting exceeds its profile"));
    }
    match value {
        Value::Array(values) => {
            for value in values {
                check_depth(value, depth + 1)?;
            }
        }
        Value::Object(values) => {
            for value in values.values() {
                check_depth(value, depth + 1)?;
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
    Ok(())
}

pub(super) fn project(value: &Value) -> Result<PairedOpaqueFinalAnswerObservationV1, AgentdError> {
    exact_fields(
        value,
        "schema record_id task_id lineage_id family_id project_id source_id teacher_id model_digest teacher_output_receipt_sha256 observed_at available_at split origin_kind exposure authorization source task final_answer trajectory teacher_observation production_eligible human_training_consent_proven verified_outcome",
    )?;
    check_depth(value, /*depth*/ 0)?;
    if serde_json::to_vec(value)?.len() > 32_768 {
        return Err(invalid("opaque observation exceeds its byte profile"));
    }
    text(value, "/teacher_id", /*maximum*/ 512)?;
    if !matches!(
        value["exposure"].as_str(),
        Some("development" | "previously_exposed" | "unexposed")
    ) || !value["model_digest"].is_null()
        || !value["teacher_output_receipt_sha256"].is_null()
        || value["production_eligible"] != false
        || value["human_training_consent_proven"] != false
    {
        return Err(invalid(
            "opaque observation cannot claim known weights or authority",
        ));
    }
    exact_fields(
        &value["authorization"],
        "training_allowed evaluation_allowed rights_basis scope",
    )?;
    exact_fields(&value["source"], "repository path sha256")?;
    exact_fields(&value["task"], "input verifier")?;
    exact_fields(&value["task"]["verifier"], "name version parameters")?;
    exact_fields(&value["task"]["verifier"]["parameters"], "expected")?;
    exact_fields(
        &value["verified_outcome"],
        "success receipt_sha256 verifier_name verifier_version",
    )?;
    if value["task"]["verifier"]["name"] != "json_artifact"
        || value["task"]["verifier"]["version"] != "1"
    {
        return Err(invalid(
            "opaque observation requires the JSON-artifact profile",
        ));
    }
    let prompt = text(value, "/task/input", /*maximum*/ 8192)?;
    let answer = text(value, "/final_answer", /*maximum*/ 8192)?;
    // The named verifier and outcome receipt remain declarations. Their source
    // and receipt bytes are not part of this owner's fixed two-file material.
    let source = digest_field(value, "/source/sha256")?;
    let profile = &value["teacher_observation"];
    exact_fields(
        profile,
        "schema identity_kind weights_sha256 generation_receipt_sha256 provider_reported model_reported source_sha256 thread_id session_id turn_id prompt_item_id prompt_item_sha256 answer_item_id answer_item_sha256 reported_phase student_policy_sha256 source_authentication selection_kind generation_authenticated execution_authenticated",
    )?;
    if profile["schema"] != "hepta.teacher-observation-identity.v1"
        || profile["identity_kind"] != "opaque"
        || profile["source_authentication"] != "local_unsigned_typed_projection"
        || profile["selection_kind"] != "explicit_correction_candidate"
        || !profile["weights_sha256"].is_null()
        || !profile["generation_receipt_sha256"].is_null()
        || !profile["model_reported"].is_null()
        || profile["generation_authenticated"] != false
        || profile["execution_authenticated"] != false
        || digest_field(profile, "/source_sha256")? != source
    {
        return Err(invalid(
            "opaque teacher identity must remain explicitly unattested",
        ));
    }
    for pointer in [
        "/thread_id",
        "/session_id",
        "/turn_id",
        "/prompt_item_id",
        "/answer_item_id",
    ] {
        text(profile, pointer, /*maximum*/ 256)?;
    }
    if profile["prompt_item_id"] == profile["answer_item_id"] {
        return Err(invalid("opaque prompt and answer identities overlap"));
    }
    digest_field(profile, "/prompt_item_sha256")?;
    digest_field(profile, "/answer_item_sha256")?;
    if !profile["provider_reported"].is_null() {
        text(profile, "/provider_reported", /*maximum*/ 512)?;
    }
    if !profile["reported_phase"].is_null()
        && !matches!(
            profile["reported_phase"].as_str(),
            Some("commentary" | "final_answer")
        )
    {
        return Err(invalid("unsupported opaque reported phase"));
    }
    let trajectory = json!([{
        "index": 0, "actor": "teacher", "kind": "observation", "content": answer,
        "executed": false, "trainable": false, "receipt_sha256": null,
        "source_item_id": profile["answer_item_id"],
        "source_item_sha256": profile["answer_item_sha256"]
    }]);
    if value["trajectory"] != trajectory {
        return Err(invalid(
            "opaque answer must remain one unexecuted masked observation",
        ));
    }
    Ok(PairedOpaqueFinalAnswerObservationV1 {
        evidence: PairedOpaqueEvidenceV1::RecordOnly {
            unverified_capture_sha256: source,
        },
        prompt: prompt.into(),
        answer: answer.into(),
        declared_student_policy: digest_field(profile, "/student_policy_sha256")?,
    })
}

pub(super) fn require_failure_binding(
    failure: &[u8],
    observation: &PairedOpaqueFinalAnswerObservationV1,
) -> Result<(), AgentdError> {
    let failure = parse_integer_json(failure)?;
    let trajectory = failure["trajectory"]
        .as_array()
        .filter(|items| items.len() <= 128)
        .ok_or_else(|| invalid("bounded original failure trajectory required"))?;
    let last = trajectory
        .iter()
        .rev()
        .find(|item| item["executed"] == true)
        .ok_or_else(|| invalid("original failure action declaration missing"))?;
    if last["actor"] != "student"
        || last["kind"] != "action"
        || last["receipt_actor"] != "student"
        || last["content"] != failure["final_answer"]
        || digest_field(last, "/policy_sha256")? != observation.declared_student_policy
    {
        return Err(invalid(
            "opaque observation differs from the declared student failure",
        ));
    }
    digest_field(last, "/receipt_sha256")?;
    Ok(())
}
