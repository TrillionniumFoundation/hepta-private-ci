//! Schema 4 observes original settled model facts; it cannot reserve or dispatch.
use super::*;
use codex_hepta_infer_core::MAX_SELF_ITERATION_MODEL_FAILURE_FACTS_BYTES_V1;
use codex_hepta_infer_core::MAX_SELF_ITERATION_MODEL_REQUEST_BYTES_V1;
use codex_hepta_infer_core::SelfIterationModelFailureFactsV1;
use codex_hepta_infer_core::SelfIterationModelRequestV1;
use codex_hepta_infer_core::decode_self_iteration_model_failure_facts_v1;
use codex_hepta_infer_core::decode_self_iteration_model_request_v1;
use codex_hepta_infer_core::encode_self_iteration_model_failure_facts_v1;
use codex_hepta_infer_core::encode_self_iteration_model_request_v1;

pub const MAX_SELF_ITERATION_FAILURE_OBSERVATION_REQUEST_BYTES_V1: usize =
    2 * MAX_SELF_ITERATION_MODEL_REQUEST_BYTES_V1 + 2048;
pub const MAX_SELF_ITERATION_FAILURE_OBSERVATION_RESPONSE_BYTES_V1: usize =
    2 * MAX_SELF_ITERATION_MODEL_FAILURE_FACTS_BYTES_V1 + 2048;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SelfIterationModelFailureObservationRequestV1 {
    pub schema_version: u32,
    pub model_request_hex: String,
}
impl SelfIterationModelFailureObservationRequestV1 {
    pub fn from_request(request: &SelfIterationModelRequestV1) -> WireResult<Self> {
        Ok(Self {
            schema_version: 4,
            model_request_hex: hex(&encode_self_iteration_model_request_v1(request)?)?,
        })
    }
    pub fn request(&self) -> WireResult<SelfIterationModelRequestV1> {
        if self.schema_version != 4 {
            return Err("readonly model failure schema".into());
        }
        Ok(decode_self_iteration_model_request_v1(&unhex(
            &self.model_request_hex,
            MAX_SELF_ITERATION_MODEL_REQUEST_BYTES_V1,
        )?)?)
    }
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SelfIterationModelFailureObservationFactsV1 {
    pub schema_version: u32,
    pub failure_facts_hex: String,
}
impl SelfIterationModelFailureObservationFactsV1 {
    pub fn from_facts(facts: &SelfIterationModelFailureFactsV1) -> WireResult<Self> {
        Ok(Self {
            schema_version: 4,
            failure_facts_hex: hex(&encode_self_iteration_model_failure_facts_v1(facts)?)?,
        })
    }
    pub fn facts(&self) -> WireResult<SelfIterationModelFailureFactsV1> {
        if self.schema_version != 4 {
            return Err("readonly model failure facts schema".into());
        }
        Ok(decode_self_iteration_model_failure_facts_v1(&unhex(
            &self.failure_facts_hex,
            MAX_SELF_ITERATION_MODEL_FAILURE_FACTS_BYTES_V1,
        )?)?)
    }
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(untagged)]
pub enum SelfIterationModelFailureObservationResponseV1 {
    Facts(SelfIterationModelFailureObservationFactsV1),
    Refused(FrozenGeneratorFailureV1),
}
pub fn encode_self_iteration_model_failure_observation_request_v1(
    request: &SelfIterationModelFailureObservationRequestV1,
) -> WireResult<Vec<u8>> {
    request.request()?;
    bounded_json(
        request,
        MAX_SELF_ITERATION_FAILURE_OBSERVATION_REQUEST_BYTES_V1,
    )
}
pub fn decode_self_iteration_model_failure_observation_request_v1(
    bytes: &[u8],
) -> WireResult<SelfIterationModelFailureObservationRequestV1> {
    validate_frame(
        bytes,
        MAX_SELF_ITERATION_FAILURE_OBSERVATION_REQUEST_BYTES_V1,
    )?;
    let request: SelfIterationModelFailureObservationRequestV1 = serde_json::from_slice(bytes)?;
    request.request()?;
    Ok(request)
}
pub fn encode_self_iteration_model_failure_observation_response_v1(
    response: &SelfIterationModelFailureObservationResponseV1,
) -> WireResult<Vec<u8>> {
    if let SelfIterationModelFailureObservationResponseV1::Facts(facts) = response {
        facts.facts()?;
    }
    bounded_json(
        response,
        MAX_SELF_ITERATION_FAILURE_OBSERVATION_RESPONSE_BYTES_V1,
    )
}
pub fn decode_self_iteration_model_failure_observation_response_v1(
    bytes: &[u8],
) -> WireResult<SelfIterationModelFailureObservationResponseV1> {
    validate_frame(
        bytes,
        MAX_SELF_ITERATION_FAILURE_OBSERVATION_RESPONSE_BYTES_V1,
    )?;
    let response = serde_json::from_slice(bytes)?;
    if let SelfIterationModelFailureObservationResponseV1::Facts(facts) = &response {
        facts.facts()?;
    }
    Ok(response)
}
fn hex(bytes: &[u8]) -> WireResult<String> {
    use std::fmt::Write;
    let mut result = String::with_capacity(2 * bytes.len());
    for byte in bytes {
        write!(result, "{byte:02x}")?;
    }
    Ok(result)
}
fn unhex(value: &str, maximum: usize) -> WireResult<Vec<u8>> {
    if value.is_empty()
        || value.len() > 2 * maximum
        || !value.len().is_multiple_of(2)
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("readonly model failure lowercase whole byte bound".into());
    }
    Ok(value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let digit = |b: u8| {
                if b.is_ascii_digit() {
                    b - b'0'
                } else {
                    b - b'a' + 10
                }
            };
            digit(pair[0]) * 16 + digit(pair[1])
        })
        .collect())
}
