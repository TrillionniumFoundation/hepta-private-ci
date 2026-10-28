//! Additive, bounded transport for typed owner training data and cell readouts.
//! Exported rows and cuts are evidence only; the server reacquires its owner at use.

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

pub const MEMORY_CELL_CONTROL_CAPABILITY_V1: &str = "memory.cells";
pub const MAX_MEMORY_CELL_PAGE_ROWS: u16 = 32;
pub const MAX_MEMORY_CELL_PAYLOAD_BYTES: usize = 48 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellSnapshotValueV1 {
    pub schema: String,
    pub entity: ContractIdV1,
    pub kind: MemoryCellKindV1,
    pub effective_at: u64,
    pub value: Value,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellSnapshotSourceV1 {
    pub source_id: ContractDigestV1,
    pub owner_memory_id: String,
    pub revision: u64,
    pub record: MemoryCellSnapshotValueV1,
}

/// Each page contains current, live training heads, ordered by source digest.
/// A subsequent page must supply both `next_after` and the exact owner cut.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryCellSnapshotPageV1 {
    pub schema: String,
    pub owner_agent_id: AgentId,
    pub scope: ContractIdV1,
    pub owner_cut_digest: ContractDigestV1,
    pub observed_at_unix_seconds: i64,
    pub records: Vec<MemoryCellSnapshotSourceV1>,
    pub next_after: Option<ContractDigestV1>,
}

#[cfg(test)]
#[path = "memory_cells_tests.rs"]
mod tests;
