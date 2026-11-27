//! Only the Agentd wire variants used by the paired process fixture.
//!
//! Keep the full protocol codecs in compatibility tests, not the installed
//! fixture executable. Production clients and admission still use the real
//! protocol and catalog. This module is not a replacement Agentd protocol.

use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Deserialize)]
#[cfg_attr(test, derive(Debug, Eq, PartialEq, Serialize))]
#[serde(deny_unknown_fields)]
pub(super) struct AgentdRequest {
    // The original fixture parsed these fields but derived response identity
    // from its launch environment. Preserve that behavior for known fields.
    #[serde(rename = "schema_version")]
    pub(super) _schema_version: u32,
    pub(super) request_id: u64,
    #[serde(rename = "spawn_generation")]
    pub(super) _spawn_generation: u64,
    pub(super) method: AgentdMethod,
}

#[derive(Deserialize)]
#[cfg_attr(test, derive(Debug, Eq, PartialEq, Serialize))]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum AgentdMethod {
    Health {},
    Drain {},
}

#[derive(Serialize)]
#[cfg_attr(test, derive(Debug, Deserialize, Eq, PartialEq))]
#[serde(deny_unknown_fields)]
pub(super) struct AgentdResponse {
    pub(super) schema_version: u32,
    pub(super) request_id: u64,
    pub(super) agent_id: AgentId,
    pub(super) spawn_generation: u64,
    pub(super) current_generation: u64,
    pub(super) payload: AgentdPayload,
}

#[derive(Serialize)]
#[cfg_attr(test, derive(Debug, Deserialize, Eq, PartialEq))]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum AgentdPayload {
    Health(HealthSnapshot),
    Drain(DrainSnapshot),
}

#[cfg(test)]
#[path = "paired_process_fixture_wire_tests.rs"]
mod tests;
