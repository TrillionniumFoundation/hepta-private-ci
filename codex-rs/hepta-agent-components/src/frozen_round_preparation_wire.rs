//! Schema 8 carries one original reservation and protected output references.
use super::*;
use std::path::Component;
use std::path::PathBuf;

pub const MAX_ROUND_PREPARATION_RESPONSE_BYTES_V1: usize = 16 * 1024;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RoundPreparationRequestV1 {
    pub schema_version: u32,
    pub round_payload_hex: String,
}
impl RoundPreparationRequestV1 {
    pub fn from_round_bytes(bytes: &[u8]) -> WireResult<Self> {
        if bytes.is_empty() || bytes.len() > 4096 {
            return Err("original reservation byte bound".into());
        }
        let payload = FrozenGeneratorRequestV1::from_payload(bytes)?;
        Ok(Self {
            schema_version: 8,
            round_payload_hex: payload.frozen_payload_hex,
        })
    }
    pub fn round_bytes(&self) -> WireResult<Vec<u8>> {
        if self.schema_version != 8 || self.round_payload_hex.len() > 8192 {
            return Err("original reservation preparation purpose".into());
        }
        FrozenGeneratorRequestV1 {
            schema_version: 1,
            frozen_payload_hex: self.round_payload_hex.clone(),
        }
        .payload()
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RoundPreparationSourceV1 {
    pub path: PathBuf,
    pub digest: String,
}
impl RoundPreparationSourceV1 {
    fn validate(&self) -> WireResult<()> {
        let digest: crate::types::Digest32 = self.digest.parse()?;
        if !self.path.is_absolute()
            || self.path.components().any(|part| {
                matches!(part, Component::CurDir | Component::ParentDir)
            })
            || self.path.components().collect::<PathBuf>().as_os_str() != self.path.as_os_str()
            || self.path.as_os_str().len() > 4096
            || digest.is_zero()
            || digest.to_string() != self.digest
        {
            return Err("bounded protected preparation Source".into());
        }
        Ok(())
    }
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case", deny_unknown_fields)]
pub enum RoundPreparationResultV1 {
    Prepared { bundle: RoundPreparationSourceV1 },
    Terminal { source: RoundPreparationSourceV1 },
    Refused { error: FrozenGeneratorErrorCodeV1 },
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RoundPreparationResponseV1 {
    pub schema_version: u32,
    pub round_payload_digest: String,
    pub result: RoundPreparationResultV1,
}
impl RoundPreparationResponseV1 {
    fn validate(&self) -> WireResult<()> {
        let digest: crate::types::Digest32 = self.round_payload_digest.parse()?;
        if self.schema_version != 8 || digest.is_zero()
            || digest.to_string() != self.round_payload_digest
        {
            return Err("whole original reservation response".into());
        }
        match &self.result {
            RoundPreparationResultV1::Prepared { bundle } => bundle.validate(),
            RoundPreparationResultV1::Terminal { source } => source.validate(),
            RoundPreparationResultV1::Refused { .. } => Ok(()),
        }
    }
}
pub fn encode_round_preparation_request_v1(request: &RoundPreparationRequestV1) -> WireResult<Vec<u8>> {
    request.round_bytes()?;
    bounded_json(request, MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1)
}
pub fn decode_round_preparation_request_v1(bytes: &[u8]) -> WireResult<RoundPreparationRequestV1> {
    validate_frame(bytes, MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1)?;
    let request: RoundPreparationRequestV1 = serde_json::from_slice(bytes)?;
    request.round_bytes()?;
    Ok(request)
}
pub fn encode_round_preparation_response_v1(response: &RoundPreparationResponseV1) -> WireResult<Vec<u8>> {
    response.validate()?;
    bounded_json(response, MAX_ROUND_PREPARATION_RESPONSE_BYTES_V1)
}
pub fn decode_round_preparation_response_v1(bytes: &[u8]) -> WireResult<RoundPreparationResponseV1> {
    validate_frame(bytes, MAX_ROUND_PREPARATION_RESPONSE_BYTES_V1)?;
    let response: RoundPreparationResponseV1 = serde_json::from_slice(bytes)?;
    response.validate()?;
    Ok(response)
}
