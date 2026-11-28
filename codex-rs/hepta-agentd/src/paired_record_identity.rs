//! Full-record identity for a bounded Python integer-JSON subprofile.
//! This projection keeps original bytes. It authenticates no declarations,
//! issues no dataset or permission, and supplies no model target or training.

use std::collections::BTreeMap;
use std::fmt;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Value;

use super::PairedTrainingMaterials;
use super::PairedTrainingReadResult;
use crate::AgentdError;
use crate::PairedLearningDataUse;
use crate::PairedPreparationRequest;
use crate::PairedTrainingMaterialManifestV1;
use crate::notes_literal_adapter::invalid;

#[path = "paired_opaque_record.rs"]
mod opaque;
pub use opaque::PairedOpaqueEvidenceV1;
pub use opaque::PairedOpaqueFinalAnswerObservationV1;

/// Independent full Python record_digest pins, not raw-file hashes or grants.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PairedRecordPinsV1 {
    pub failure_record_digest: Digest32,
    pub correction_record_digest: Digest32,
}

/// A declared identity projection, not the complete Python schema validator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedRecordMetadataV1 {
    pub record_digest: Digest32,
    pub record_id: String,
    pub task_id: String,
    pub lineage_id: String,
    pub project_id: String,
    pub declared_source_repository: String,
    pub declared_source_sha256: Digest32,
    pub declared_outcome_receipt_sha256: Digest32,
    pub task_digest: Digest32,
    pub observed_at: u64,
    pub available_at: u64,
}

/// Owned original bytes plus identity. No Deserialize, clone, or metadata constructor.
pub struct PairedRecordIdentityV1 {
    materials: PairedTrainingMaterials,
    request: PairedPreparationRequest,
    failure: PairedRecordMetadataV1,
    correction: PairedRecordMetadataV1,
    opaque_correction: Option<PairedOpaqueFinalAnswerObservationV1>,
}

impl PairedRecordIdentityV1 {
    pub fn materials(&self) -> &PairedTrainingMaterials {
        &self.materials
    }
    pub fn original_request(&self) -> &PairedPreparationRequest {
        &self.request
    }
    pub fn failure_record(&self) -> &PairedRecordMetadataV1 {
        &self.failure
    }
    pub fn correction_record(&self) -> &PairedRecordMetadataV1 {
        &self.correction
    }
    /// The record was received from the original owner. Its referenced capture
    /// was not received and is explicitly unverified; this is no training target.
    pub fn opaque_correction_observation(&self) -> Option<&PairedOpaqueFinalAnswerObservationV1> {
        self.opaque_correction.as_ref()
    }
}

/// Consume only a fresh native result and bind both complete raw and canonical bytes.
/// The original owner must retain request provenance. This creates no new authority.
/// Floating-point JSON and integers outside i64/u64 are explicitly unsupported.
pub fn identify_original_paired_records_v1(
    result: PairedTrainingReadResult,
    request: &PairedPreparationRequest,
    pins: PairedRecordPinsV1,
) -> Result<PairedRecordIdentityV1, AgentdError> {
    let materials = match result {
        PairedTrainingReadResult::FreshRead(value) => value,
        PairedTrainingReadResult::RetainedReadOnly { .. }
        | PairedTrainingReadResult::Unknown { .. } => {
            return Err(invalid(
                "paired record identity requires fresh owned material",
            ));
        }
    };
    request.original.validate()?;
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(materials.failure()),
        failure_bytes: materials.failure().len() as u64,
        correction_sha256: Digest32::of_bytes(materials.correction()),
        correction_bytes: materials.correction().len() as u64,
    };
    if request.operation.is_zero()
        || request.materials != manifest.commitment().map_err(|e| invalid(&e.to_string()))?
        || request.original.usage
            != (PairedLearningDataUse::TrainOnFailureAndCorrection {
                failure: manifest.failure_sha256,
                correction: manifest.correction_sha256,
            })
    {
        return Err(invalid(
            "paired raw material differs from original purpose or commitment",
        ));
    }
    let (failure, _) = project_record(
        materials.failure(),
        pins.failure_record_digest,
        AttemptRole::Failure,
    )?;
    let (correction, opaque_correction) = project_record(
        materials.correction(),
        pins.correction_record_digest,
        AttemptRole::Correction,
    )?;
    if failure.record_id == correction.record_id
        || failure.task_id != correction.task_id
        || failure.lineage_id != correction.lineage_id
        || failure.project_id != correction.project_id
        || failure.declared_source_repository != correction.declared_source_repository
        || failure.task_digest != correction.task_digest
        || failure.observed_at > correction.observed_at
    {
        return Err(invalid(
            "paired records do not describe ordered attempts of the same task",
        ));
    }
    if let Some(observation) = &opaque_correction {
        opaque::require_failure_binding(materials.failure(), observation)?;
    }
    Ok(PairedRecordIdentityV1 {
        materials,
        request: request.clone(),
        failure,
        correction,
        opaque_correction,
    })
}

fn text<'a>(value: &'a Value, pointer: &str, maximum: usize) -> Result<&'a str, AgentdError> {
    value
        .pointer(pointer)
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty() && s.len() <= maximum)
        .ok_or_else(|| invalid("paired record text field is missing, invalid or unbounded"))
}

fn digest_field(value: &Value, pointer: &str) -> Result<Digest32, AgentdError> {
    let field = text(value, pointer, 64)?;
    if field.len() != 64
        || !field
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(invalid("paired record digest is not lowercase SHA256"));
    }
    let digest: Digest32 = field
        .parse()
        .map_err(|_| invalid("paired record digest is invalid"))?;
    if digest.is_zero() {
        return Err(invalid("paired record digest is zero"));
    }
    Ok(digest)
}

#[derive(Clone, Copy)]
enum AttemptRole {
    Failure,
    Correction,
}

fn project_record(
    raw: &[u8],
    expected: Digest32,
    role: AttemptRole,
) -> Result<
    (
        PairedRecordMetadataV1,
        Option<PairedOpaqueFinalAnswerObservationV1>,
    ),
    AgentdError,
> {
    let value = parse_integer_json(raw)?;
    let canonical = serde_json::to_vec(&value)?;
    let record_digest = Digest32::of_bytes(&canonical);
    if expected.is_zero() || record_digest != expected {
        return Err(invalid(
            "full Python record digest differs from its frozen pin",
        ));
    }
    let opaque = match (role, text(&value, "/schema", 128)?) {
        (_, "hepta.cell-experiments.record.v1") => None,
        (AttemptRole::Correction, opaque::SCHEMA) => Some(opaque::project(&value)?),
        _ => {
            return Err(invalid(
                "paired record schema differs from its attempt role",
            ));
        }
    };
    if text(&value, "/split", 32)? != "train"
        || text(&value, "/origin_kind", 64)? != "authorized_agent_run"
        || value.pointer("/authorization/training_allowed") != Some(&Value::Bool(true))
        || value.pointer("/authorization/evaluation_allowed") != Some(&Value::Bool(true))
        || value.pointer("/verified_outcome/success")
            != Some(&Value::Bool(matches!(role, AttemptRole::Correction)))
    {
        return Err(invalid(
            "paired record schema, train declarations or outcome role differs",
        ));
    }
    for pointer in [
        "/authorization/rights_basis",
        "/authorization/scope",
        "/source/path",
    ] {
        text(&value, pointer, 4096)?;
    }
    for pointer in ["/family_id", "/source_id"] {
        text(&value, pointer, 512)?;
    }
    text(&value, "/task/input", 65536)?;
    text(&value, "/final_answer", 65536)?;
    if !value
        .pointer("/task/verifier/parameters")
        .is_some_and(Value::is_object)
        || text(&value, "/task/verifier/name", 256)?
            != text(&value, "/verified_outcome/verifier_name", 256)?
        || text(&value, "/task/verifier/version", 256)?
            != text(&value, "/verified_outcome/verifier_version", 256)?
    {
        return Err(invalid("paired record verifier declarations differ"));
    }
    let observed_at = value
        .get("observed_at")
        .and_then(Value::as_u64)
        .ok_or_else(|| invalid("invalid observed_at"))?;
    let available_at = value
        .get("available_at")
        .and_then(Value::as_u64)
        .ok_or_else(|| invalid("invalid available_at"))?;
    if observed_at > available_at {
        return Err(invalid("record availability precedes observation"));
    }
    Ok((
        PairedRecordMetadataV1 {
            record_digest,
            record_id: text(&value, "/record_id", 512)?.into(),
            task_id: text(&value, "/task_id", 512)?.into(),
            lineage_id: text(&value, "/lineage_id", 512)?.into(),
            project_id: text(&value, "/project_id", 512)?.into(),
            declared_source_repository: text(&value, "/source/repository", 4096)?.into(),
            declared_source_sha256: digest_field(&value, "/source/sha256")?,
            declared_outcome_receipt_sha256: digest_field(
                &value,
                "/verified_outcome/receipt_sha256",
            )?,
            task_digest: Digest32::of_bytes(&serde_json::to_vec(&value["task"])?),
            observed_at,
            available_at,
        },
        opaque,
    ))
}

// Inspect numeric lexemes before Serde: arbitrary_precision represents decimals
// and large integers as private maps instead of calling visit_f64. Quoted text
// remains ordinary text, including literal keys resembling Serde's private tags.
fn parse_integer_json(raw: &[u8]) -> Result<Value, AgentdError> {
    let (mut quoted, mut escaped, mut position) = (false, false, 0);
    while position < raw.len() {
        let byte = raw[position];
        if quoted {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                quoted = false;
            }
        } else if byte == b'"' {
            quoted = true;
        } else if byte == b'-' || byte.is_ascii_digit() {
            let start = position;
            while position < raw.len()
                && (raw[position].is_ascii_digit()
                    || matches!(raw[position], b'-' | b'+' | b'.' | b'e' | b'E'))
            {
                position += 1;
            }
            let number = std::str::from_utf8(&raw[start..position])
                .map_err(|_| invalid("invalid number bytes"))?;
            let in_range = if byte == b'-' {
                number.parse::<i64>().is_ok()
            } else {
                number.parse::<u64>().is_ok()
            };
            if !in_range || number == "-0" {
                return Err(invalid(
                    "number is outside the Python integer canonical profile",
                ));
            }
            continue;
        }
        position += 1;
    }
    Ok(serde_json::from_slice::<StrictJson>(raw)?.0)
}

// Sorting occurs recursively before serialization, including when serde_json's
// preserve_order feature is enabled elsewhere in the workspace.
struct StrictJson(Value);

impl<'de> Deserialize<'de> for StrictJson {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct StrictVisitor;
        impl<'de> Visitor<'de> for StrictVisitor {
            type Value = StrictJson;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("bounded integer-only Python JSON")
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<StrictJson, E> {
                Ok(StrictJson(Value::Null))
            }
            fn visit_bool<E: serde::de::Error>(self, value: bool) -> Result<StrictJson, E> {
                Ok(StrictJson(value.into()))
            }
            fn visit_i64<E: serde::de::Error>(self, value: i64) -> Result<StrictJson, E> {
                Ok(StrictJson(value.into()))
            }
            fn visit_u64<E: serde::de::Error>(self, value: u64) -> Result<StrictJson, E> {
                Ok(StrictJson(value.into()))
            }
            fn visit_f64<E: serde::de::Error>(self, _value: f64) -> Result<StrictJson, E> {
                Err(E::custom(
                    "floating-point JSON is outside Python integer canonical profile",
                ))
            }
            fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<StrictJson, E> {
                Ok(StrictJson(value.into()))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut access: A) -> Result<StrictJson, A::Error> {
                let mut values = Vec::new();
                while let Some(value) = access.next_element::<StrictJson>()? {
                    values.push(value.0);
                }
                Ok(StrictJson(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut access: A) -> Result<StrictJson, A::Error> {
                let mut values = BTreeMap::new();
                while let Some(key) = access.next_key::<String>()? {
                    if values.contains_key(&key) {
                        return Err(serde::de::Error::custom("duplicate JSON key"));
                    }
                    values.insert(key, access.next_value::<StrictJson>()?.0);
                }
                Ok(StrictJson(Value::Object(values.into_iter().collect())))
            }
        }
        deserializer.deserialize_any(StrictVisitor)
    }
}

#[cfg(test)]
#[path = "paired_record_identity_tests.rs"]
pub(crate) mod tests;
