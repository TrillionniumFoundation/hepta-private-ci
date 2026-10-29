//! Additive, bounded transport for typed owner training data and cell readouts.
//! Exported rows and cuts are evidence only; the server reacquires its owner at use.

use codex_hepta_cognitive_types::InventoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

pub const INVENTORY_CELL_CONTROL_CAPABILITY_V1: &str = "memory.inventory";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellSnapshotValueV1 {
    pub schema: String,
    pub key: ContractIdV1,
    pub kind: InventoryCellKindV1,
    pub effective_at: u64,
    pub value: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub training_origin: Option<ContractDigestV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellSnapshotSourceV1 {
    pub source_id: ContractDigestV1,
    pub owner_memory_id: String,
    pub revision: u64,
    pub record: InventoryCellSnapshotValueV1,
}

/// Each page contains current, live training heads, ordered by source digest.
/// A subsequent page must supply both `next_after` and the exact owner cut.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct InventoryCellSnapshotPageV1 {
    pub schema: String,
    pub owner_agent_id: AgentId,
    pub scope: ContractIdV1,
    pub owner_cut_digest: ContractDigestV1,
    pub observed_at_unix_seconds: i64,
    pub records: Vec<InventoryCellSnapshotSourceV1>,
    pub next_after: Option<ContractDigestV1>,
}

