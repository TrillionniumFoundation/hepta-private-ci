//! Original neutral Agentd response envelope and one bounded readonly purpose.
//! These decoded facts are not authenticated peer custody or execution authority.
use crate::AgentId;
use serde::{Deserialize, Serialize};

pub const ORIGINAL_AGENTD_CONTROL_SCHEMA_VERSION: u32 = 2;
pub const MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1: usize = 65_536;

/// Same original six-field response codec, independent of runtime owners.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OriginalAgentdResponseV1<P> {
    pub schema_version: u32,
    pub request_id: u64,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub current_generation: u64,
    pub payload: P,
}
/// Full original Serving owner observation; it supplies no RunStart identity.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterServingScopeV1 {
    pub round_hex: String,
    pub neuron_generation: u64,
    pub configuration_digest: String,
    pub body_bundle_digest: String,
    pub scope_digest: String,
    pub objective_digest: String,
    pub goal_ordinal: Option<u64>,
}
/// Only this original readonly purpose is admitted by the low reader.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum ParameterServingScopePayloadV1 {
    ParameterServingScopeV1(ParameterServingScopeV1),
}
pub type ParameterServingScopeResponseV1 = OriginalAgentdResponseV1<ParameterServingScopePayloadV1>;

/// Preserve source bytes separately. A successful bounded parse does not prove
/// that a response came from an authenticated current Agentd peer.
pub fn decode_original_parameter_serving_scope_response_v1(
    bytes: &[u8],
) -> Result<ParameterServingScopeResponseV1, String> {
    if bytes.is_empty() || bytes.len() > MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1 {
        return Err("whole original Serving response bound".into());
    }
    let response: ParameterServingScopeResponseV1 =
        serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    if response.schema_version != ORIGINAL_AGENTD_CONTROL_SCHEMA_VERSION
        || response.request_id == 0
        || response.spawn_generation == 0
        || response.current_generation == 0
    {
        return Err("original Serving response identity".into());
    }
    let ParameterServingScopePayloadV1::ParameterServingScopeV1(p) = &response.payload;
    let lower_hex = |s: &str| {
        s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    };
    if p.round_hex.is_empty()
        || p.round_hex.len() > 8192
        || p.round_hex.len() % 2 != 0
        || !lower_hex(&p.round_hex)
        || p.neuron_generation == 0
        || p.goal_ordinal == Some(0)
        || [
            &p.configuration_digest,
            &p.body_bundle_digest,
            &p.scope_digest,
            &p.objective_digest,
        ]
        .into_iter()
        .any(|s| s.len() != 64 || !lower_hex(s) || s.bytes().all(|b| b == b'0'))
    {
        return Err("complete original Serving payload".into());
    }
    Ok(response)
}
#[cfg(test)]
#[path = "original_agentd_response_tests.rs"]
mod tests;
