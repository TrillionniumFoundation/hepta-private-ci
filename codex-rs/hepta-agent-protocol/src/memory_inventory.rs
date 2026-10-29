//! Additive, bounded transport for typed owner training data and cell readouts.
//! Exported rows and cuts are evidence only; the server reacquires its owner at use.

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

pub const MEMORY_INVENTORY_CONTROL_CAPABILITY_V1: &str = "memory.inventory";
pub const MAX_MEMORY_INVENTORY_PAGE_ROWS: u16 = 32;
pub const MAX_MEMORY_INVENTORY_PAYLOAD_BYTES: usize = 48 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventorySnapshotValueV1 {
    pub schema: String,
    pub key: ContractIdV1,
    pub kind: MemoryInventoryKindV1,
    pub effective_at: u64,
    pub value: Value,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventorySnapshotSourceV1 {
    pub source_id: ContractDigestV1,
    pub owner_memory_id: String,
    pub revision: u64,
    pub record: MemoryInventorySnapshotValueV1,
}

/// Each page contains current, live training heads, ordered by source digest.
/// A subsequent page must supply both `next_after` and the exact owner cut.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryInventorySnapshotPageV1 {
    pub schema: String,
    pub owner_agent_id: AgentId,
    pub scope: ContractIdV1,
    pub owner_cut_digest: ContractDigestV1,
    pub observed_at_unix_seconds: i64,
    pub records: Vec<MemoryInventorySnapshotSourceV1>,
    pub next_after: Option<ContractDigestV1>,
}

