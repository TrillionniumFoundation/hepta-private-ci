//! Native canonical-JSON codecs for PromptFactorV1 and PromptRealizationV1.
//!
//! These codecs intentionally mirror docs/contracts/PROTOCOL_SCHEMAS.json:
//! exact field names, bounded values, deterministic struct-field ordering and
//! rejection of unknown fields.

use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::Lifecycle;
use crate::PromptRoleV2;

const MAX_PROTOCOL_BYTES: usize = 262_144;
const MAX_SEMANTIC_PURPOSE_BYTES: usize = 4_096;
const MAX_AUTHORITY_CLASS_BYTES: usize = 64;
const MAX_ELIGIBLE_DIMENSIONS_BYTES: usize = 8_192;
const MAX_MODEL_VERSION_BYTES: usize = 256;
const MAX_MESSAGE_ROLE_BYTES: usize = 32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFactorV1 {
    pub factor_id: StableId,
    pub semantic_purpose: String,
    pub authority_class: String,
    pub eligible_objective_dimensions: Vec<StableId>,
    pub lifecycle: Lifecycle,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PromptFactorWireV1 {
    factor_id: String,
    semantic_purpose: String,
    authority_class: String,
    eligible_objective_dimensions: Vec<String>,
    lifecycle: String,
    revision: u64,
}

impl PromptFactorV1 {
    pub fn encode_canonical_json(&self) -> Result<Vec<u8>, ProtocolCodecError> {
        self.validate()?;
        let wire = PromptFactorWireV1 {
            factor_id: self.factor_id.to_string(),
            semantic_purpose: self.semantic_purpose.clone(),
            authority_class: self.authority_class.clone(),
            eligible_objective_dimensions: self
                .eligible_objective_dimensions
                .iter()
                .map(ToString::to_string)
                .collect(),
            lifecycle: lifecycle_name(self.lifecycle).to_owned(),
            revision: self.revision,
        };
        let bytes = serde_json::to_vec(&wire).map_err(|_| ProtocolCodecError::InvalidJson)?;
        ensure_protocol_size(&bytes)?;
        Ok(bytes)
    }

    pub fn decode_canonical_json(bytes: &[u8]) -> Result<Self, ProtocolCodecError> {
        ensure_protocol_size(bytes)?;
        let wire: PromptFactorWireV1 =
            serde_json::from_slice(bytes).map_err(|_| ProtocolCodecError::InvalidJson)?;
        let value = Self {
            factor_id: parse_id(&wire.factor_id)?,
            semantic_purpose: wire.semantic_purpose,
            authority_class: wire.authority_class,
            eligible_objective_dimensions: wire
                .eligible_objective_dimensions
                .iter()
                .map(|value| parse_id(value))
                .collect::<Result<Vec<_>, _>>()?,
            lifecycle: parse_lifecycle(&wire.lifecycle)?,
            revision: wire.revision,
        };
        value.validate()?;
        if value.encode_canonical_json()? != bytes {
            return Err(ProtocolCodecError::NonCanonicalJson);
        }
        Ok(value)
    }

    fn validate(&self) -> Result<(), ProtocolCodecError> {
        if self.semantic_purpose.is_empty()
            || self.semantic_purpose.len() > MAX_SEMANTIC_PURPOSE_BYTES
            || self.authority_class.is_empty()
            || self.authority_class.len() > MAX_AUTHORITY_CLASS_BYTES
            || self.revision == 0
        {
            return Err(ProtocolCodecError::InvalidField);
        }
        let dimension_bytes = self
            .eligible_objective_dimensions
            .iter()
            .try_fold(0_usize, |total, value| {
                total.checked_add(value.as_str().len())
            })
            .ok_or(ProtocolCodecError::InvalidField)?;
        if dimension_bytes > MAX_ELIGIBLE_DIMENSIONS_BYTES
            || self
                .eligible_objective_dimensions
                .windows(2)
                .any(|window| window[0] >= window[1])
        {
            return Err(ProtocolCodecError::InvalidField);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRealizationV1 {
    pub factor_id: StableId,
    pub model_id: StableId,
    pub model_version: String,
    pub tokenizer_digest: Digest32,
    pub system_template_digest: Digest32,
    pub message_role: PromptRoleV2,
    pub payload_digest: Digest32,
    pub token_cost_upper_bound: u32,
    pub expires_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PromptRealizationWireV1 {
    factor_id: String,
    model_id: String,
    model_version: String,
    tokenizer_digest: String,
    system_template_digest: String,
    message_role: String,
    payload_digest: String,
    token_cost_upper_bound: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    expires_unix_ms: Option<u64>,
}

impl PromptRealizationV1 {
    pub fn encode_canonical_json(&self) -> Result<Vec<u8>, ProtocolCodecError> {
        self.validate()?;
        let wire = PromptRealizationWireV1 {
            factor_id: self.factor_id.to_string(),
            model_id: self.model_id.to_string(),
            model_version: self.model_version.clone(),
            tokenizer_digest: self.tokenizer_digest.to_string(),
            system_template_digest: self.system_template_digest.to_string(),
            message_role: prompt_role_name(self.message_role).to_owned(),
            payload_digest: self.payload_digest.to_string(),
            token_cost_upper_bound: self.token_cost_upper_bound,
            expires_unix_ms: self.expires_unix_ms,
        };
        let bytes = serde_json::to_vec(&wire).map_err(|_| ProtocolCodecError::InvalidJson)?;
        ensure_protocol_size(&bytes)?;
        Ok(bytes)
    }

    pub fn decode_canonical_json(bytes: &[u8]) -> Result<Self, ProtocolCodecError> {
        ensure_protocol_size(bytes)?;
        let wire: PromptRealizationWireV1 =
            serde_json::from_slice(bytes).map_err(|_| ProtocolCodecError::InvalidJson)?;
        let value = Self {
            factor_id: parse_id(&wire.factor_id)?,
            model_id: parse_id(&wire.model_id)?,
            model_version: wire.model_version,
            tokenizer_digest: parse_digest(&wire.tokenizer_digest)?,
            system_template_digest: parse_digest(&wire.system_template_digest)?,
            message_role: parse_prompt_role(&wire.message_role)?,
            payload_digest: parse_digest(&wire.payload_digest)?,
            token_cost_upper_bound: wire.token_cost_upper_bound,
            expires_unix_ms: wire.expires_unix_ms,
        };
        value.validate()?;
        if value.encode_canonical_json()? != bytes {
            return Err(ProtocolCodecError::NonCanonicalJson);
        }
        Ok(value)
    }

    fn validate(&self) -> Result<(), ProtocolCodecError> {
        if self.model_version.is_empty()
            || self.model_version.len() > MAX_MODEL_VERSION_BYTES
            || prompt_role_name(self.message_role).len() > MAX_MESSAGE_ROLE_BYTES
            || self.tokenizer_digest.is_zero()
            || self.system_template_digest.is_zero()
            || self.payload_digest.is_zero()
            || self.token_cost_upper_bound == 0
            || self.expires_unix_ms == Some(0)
        {
            return Err(ProtocolCodecError::InvalidField);
        }
        Ok(())
    }
}

fn ensure_protocol_size(bytes: &[u8]) -> Result<(), ProtocolCodecError> {
    if bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(ProtocolCodecError::PayloadTooLarge);
    }
    Ok(())
}

fn parse_id(value: &str) -> Result<StableId, ProtocolCodecError> {
    StableId::new(value.to_owned()).map_err(|_| ProtocolCodecError::InvalidField)
}

fn parse_digest(value: &str) -> Result<Digest32, ProtocolCodecError> {
    Digest32::from_str(value).map_err(|_| ProtocolCodecError::InvalidField)
}

const fn lifecycle_name(value: Lifecycle) -> &'static str {
    match value {
        Lifecycle::Draft => "draft",
        Lifecycle::Admitted => "admitted",
        Lifecycle::Retired => "retired",
        Lifecycle::Revoked => "revoked",
    }
}

const fn prompt_role_name(value: PromptRoleV2) -> &'static str {
    match value {
        PromptRoleV2::SystemInstruction => "system_instruction",
        PromptRoleV2::DeveloperInstruction => "developer_instruction",
        PromptRoleV2::UserTemplate => "user_template",
        PromptRoleV2::ToolSchemaFragment => "tool_schema_fragment",
    }
}

fn parse_prompt_role(value: &str) -> Result<PromptRoleV2, ProtocolCodecError> {
    match value {
        "system_instruction" => Ok(PromptRoleV2::SystemInstruction),
        "developer_instruction" => Ok(PromptRoleV2::DeveloperInstruction),
        "user_template" => Ok(PromptRoleV2::UserTemplate),
        "tool_schema_fragment" => Ok(PromptRoleV2::ToolSchemaFragment),
        _ => Err(ProtocolCodecError::InvalidField),
    }
}

fn parse_lifecycle(value: &str) -> Result<Lifecycle, ProtocolCodecError> {
    match value {
        "draft" => Ok(Lifecycle::Draft),
        "admitted" => Ok(Lifecycle::Admitted),
        "retired" => Ok(Lifecycle::Retired),
        "revoked" => Ok(Lifecycle::Revoked),
        _ => Err(ProtocolCodecError::InvalidField),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProtocolCodecError {
    InvalidJson,
    NonCanonicalJson,
    InvalidField,
    PayloadTooLarge,
}

impl fmt::Display for ProtocolCodecError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ProtocolCodecError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn prompt_factor_v1_round_trips_canonical_json_and_rejects_unknown_fields() {
        let value = PromptFactorV1 {
            factor_id: id("factor:1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "developer_policy".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            lifecycle: Lifecycle::Admitted,
            revision: 7,
        };
        let bytes = value
            .encode_canonical_json()
            .unwrap_or_else(|error| panic!("encode: {error}"));
        assert_eq!(
            PromptFactorV1::decode_canonical_json(&bytes)
                .unwrap_or_else(|error| panic!("decode: {error}")),
            value
        );
        let mut wire: serde_json::Value = serde_json::from_slice(&bytes).expect("valid json");
        wire.as_object_mut()
            .expect("object")
            .insert("unknown".to_owned(), serde_json::json!(true));
        let drifted = serde_json::to_vec(&wire).expect("json");
        assert_eq!(
            PromptFactorV1::decode_canonical_json(&drifted),
            Err(ProtocolCodecError::InvalidJson)
        );
    }

    #[test]
    fn prompt_factor_v1_rejects_noncanonical_dimension_order() {
        let value = PromptFactorV1 {
            factor_id: id("factor:2"),
            semantic_purpose: "bounded verification".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:z"), id("dimension:a")],
            lifecycle: Lifecycle::Admitted,
            revision: 2,
        };
        assert_eq!(
            value.encode_canonical_json(),
            Err(ProtocolCodecError::InvalidField)
        );
    }

    #[test]
    fn prompt_realization_v1_round_trips_digest_fields() {
        let value = PromptRealizationV1 {
            factor_id: id("factor:1"),
            model_id: id("model:1"),
            model_version: "2026-09-18".to_owned(),
            tokenizer_digest: digest("tokenizer"),
            system_template_digest: digest("template"),
            message_role: PromptRoleV2::DeveloperInstruction,
            payload_digest: digest("payload"),
            token_cost_upper_bound: 32,
            expires_unix_ms: Some(100),
        };
        let bytes = value
            .encode_canonical_json()
            .unwrap_or_else(|error| panic!("encode: {error}"));
        assert_eq!(
            PromptRealizationV1::decode_canonical_json(&bytes)
                .unwrap_or_else(|error| panic!("decode: {error}")),
            value
        );
    }
}
