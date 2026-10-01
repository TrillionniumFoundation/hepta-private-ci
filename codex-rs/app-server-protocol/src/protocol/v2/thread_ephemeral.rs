use crate::JsonSchema;
use crate::TS;
use serde::Deserialize;
use serde::Serialize;

#[cfg(test)]
#[path = "thread_ephemeral_tests.rs"]
mod tests;

/// Opt-in V1 residency until explicit exact-session disposal. This grants no
/// execution, terminal observation or history-deletion authority.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadEphemeralRetainParams {
    pub protocol_version: u32,
    pub thread_id: String,
    pub expected_session_id: String,
    pub operation_id: String,
}

/// All bindings must match the request before a native caller may cross an
/// effect boundary. Unsupported servers cannot provide this positive V1 ACK.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ThreadEphemeralRetainResponse {
    pub protocol_version: u32,
    pub thread_id: String,
    pub session_id: String,
    pub operation_id: String,
}
