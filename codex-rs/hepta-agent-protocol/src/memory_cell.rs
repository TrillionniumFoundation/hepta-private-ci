//! Explicit opt-in memory decoder jobs on the existing Agentd control socket.

use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCellRole {
    Semantic,
    Procedural,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellReadIngress {
    pub invocation_id: String,
    pub role: MemoryCellRole,
    pub entity: String,
    pub relation: String,
    pub deadline_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCellReadState {
    Running,
    Succeeded,
    Rejected,
    Indeterminate,
}

/// The execution JSON retains exact prompt/token/weight measurements. Its hash
/// is committed by the durable source owner; it grants no effect authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellReadSnapshot {
    pub invocation_id: String,
    pub state: MemoryCellReadState,
    pub text: Option<String>,
    pub execution_json: Option<String>,
    pub execution_sha256: Option<String>,
    pub source_commit_event_id: Option<String>,
    pub refusal: Option<String>,
}

#[cfg(test)]
#[path = "memory_cell_tests.rs"]
mod tests;
