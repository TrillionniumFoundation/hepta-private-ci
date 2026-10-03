//! One shared transport codec. It conveys original frozen bytes and original
//! signed evidence; decoding grants no role, model or filesystem authority.
use crate::learning_ledger::ReviewEvidenceWireV1;
use serde::Deserialize;
use serde::Serialize;

pub const MAX_FROZEN_GENERATOR_PAYLOAD_BYTES_V1: usize = 512 * 1024;
pub const MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1: usize =
    2 * MAX_FROZEN_GENERATOR_PAYLOAD_BYTES_V1 + 2048;
pub const MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1: usize = 16 * 1024;

type WireResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[path = "frozen_model_failure_wire.rs"]
mod model_failure;
pub use model_failure::*;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FrozenGeneratorRequestV1 {
    pub schema_version: u32,
    pub frozen_payload_hex: String,
}

impl FrozenGeneratorRequestV1 {
    pub fn from_payload(payload: &[u8]) -> WireResult<Self> {
        use std::fmt::Write;
        if payload.is_empty() || payload.len() > MAX_FROZEN_GENERATOR_PAYLOAD_BYTES_V1 {
            return Err("frozen Generator payload bounds".into());
        }
        let mut frozen_payload_hex = String::with_capacity(payload.len() * 2);
        for byte in payload {
            write!(frozen_payload_hex, "{byte:02x}")?;
        }
        Ok(Self {
            schema_version: 1,
            frozen_payload_hex,
        })
    }

    pub fn payload(&self) -> WireResult<Vec<u8>> {
        self.validate()?;
        self.frozen_payload_hex
            .as_bytes()
            .chunks_exact(2)
            .map(|pair| {
                let digit = |byte: u8| {
                    if byte.is_ascii_digit() {
                        byte - b'0'
                    } else {
                        byte - b'a' + 10
                    }
                };
                Ok(digit(pair[0]) * 16 + digit(pair[1]))
            })
            .collect()
    }

    fn validate(&self) -> WireResult<()> {
        let hex = &self.frozen_payload_hex;
        if self.schema_version != 1
            || hex.is_empty()
            || hex.len() > 2 * MAX_FROZEN_GENERATOR_PAYLOAD_BYTES_V1
            || !hex.len().is_multiple_of(2)
            || !hex
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err("frozen Generator request schema or lowercase payload bounds".into());
        }
        Ok(())
    }
}

/// Schema 2 only observes an original immutable publication. It cannot ask the
/// Root service to reserve an output or dispatch the Generator.
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FrozenGeneratorObservationRequestV2 {
    pub schema_version: u32,
    pub frozen_payload_hex: String,
}

impl FrozenGeneratorObservationRequestV2 {
    pub fn from_payload(payload: &[u8]) -> WireResult<Self> {
        let request = FrozenGeneratorRequestV1::from_payload(payload)?;
        Ok(Self {
            schema_version: 2,
            frozen_payload_hex: request.frozen_payload_hex,
        })
    }

    pub fn payload(&self) -> WireResult<Vec<u8>> {
        if self.schema_version != 2 {
            return Err("frozen Generator observation schema".into());
        }
        FrozenGeneratorRequestV1 {
            schema_version: 1,
            frozen_payload_hex: self.frozen_payload_hex.clone(),
        }
        .payload()
    }
}

/// A finite service operation; legacy schema 1 remains an issuance request.
pub enum FrozenGeneratorOperationV1 {
    Issue(FrozenGeneratorRequestV1),
    Observe(FrozenGeneratorObservationRequestV2),
    ObserveModelFailure(SelfIterationModelFailureObservationRequestV1),
}

pub fn encode_frozen_generator_observation_request_v2(
    request: &FrozenGeneratorObservationRequestV2,
) -> WireResult<Vec<u8>> {
    request.payload()?;
    bounded_json(request, MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1)
}

pub fn decode_frozen_generator_observation_request_v2(
    bytes: &[u8],
) -> WireResult<FrozenGeneratorObservationRequestV2> {
    validate_frame(bytes, MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1)?;
    let request: FrozenGeneratorObservationRequestV2 = serde_json::from_slice(bytes)?;
    request.payload()?;
    Ok(request)
}

pub fn decode_frozen_generator_operation_v1(
    bytes: &[u8],
) -> WireResult<FrozenGeneratorOperationV1> {
    #[derive(Deserialize)]
    struct Header {
        schema_version: u32,
    }
    validate_frame(bytes, MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1)?;
    let header: Header = serde_json::from_slice(bytes)?;
    match header.schema_version {
        1 => Ok(FrozenGeneratorOperationV1::Issue(
            decode_frozen_generator_request_v1(bytes)?,
        )),
        2 => Ok(FrozenGeneratorOperationV1::Observe(
            decode_frozen_generator_observation_request_v2(bytes)?,
        )),
        4 => Ok(FrozenGeneratorOperationV1::ObserveModelFailure(
            decode_self_iteration_model_failure_observation_request_v1(bytes)?,
        )),
        _ => Err("frozen Generator operation schema".into()),
    }
}

/// Finite refusal codes, with no caller-controlled explanation or new receipt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FrozenGeneratorErrorCodeV1 {
    InvalidRequest,
    NotAdmitted,
    Pending,
    Unavailable,
    Failed,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FrozenGeneratorFailureV1 {
    pub error: FrozenGeneratorErrorCodeV1,
}

#[derive(Deserialize, Serialize)]
#[serde(untagged)]
pub enum FrozenGeneratorResponseV1 {
    Granted(Box<ReviewEvidenceWireV1>),
    Refused(FrozenGeneratorFailureV1),
}

pub fn encode_frozen_generator_request_v1(
    request: &FrozenGeneratorRequestV1,
) -> WireResult<Vec<u8>> {
    request.validate()?;
    bounded_json(request, MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1)
}

pub fn decode_frozen_generator_request_v1(bytes: &[u8]) -> WireResult<FrozenGeneratorRequestV1> {
    validate_frame(bytes, MAX_FROZEN_GENERATOR_REQUEST_BYTES_V1)?;
    let request: FrozenGeneratorRequestV1 = serde_json::from_slice(bytes)?;
    request.validate()?;
    Ok(request)
}

pub fn encode_frozen_generator_response_v1(
    response: &FrozenGeneratorResponseV1,
) -> WireResult<Vec<u8>> {
    bounded_json(response, MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1)
}

pub fn decode_frozen_generator_response_v1(bytes: &[u8]) -> WireResult<FrozenGeneratorResponseV1> {
    validate_frame(bytes, MAX_FROZEN_GENERATOR_RESPONSE_BYTES_V1)?;
    Ok(serde_json::from_slice(bytes)?)
}

fn validate_frame(bytes: &[u8], maximum: usize) -> WireResult<()> {
    if bytes.is_empty() || bytes.len() > maximum {
        return Err("frozen Generator frame bounds".into());
    }
    Ok(())
}

fn bounded_json(value: &impl Serialize, maximum: usize) -> WireResult<Vec<u8>> {
    let bytes = serde_json::to_vec(value)?;
    // Reserve the original transport's single terminating newline.
    validate_frame(&bytes, maximum - 1)?;
    Ok(bytes)
}
