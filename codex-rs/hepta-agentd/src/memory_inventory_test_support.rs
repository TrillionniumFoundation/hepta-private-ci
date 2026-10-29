use codex_hepta_cognitive_types::{MemoryInventoryKindV1, MemoryInventoryRequestV1};
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::{CognitiveScope, MemoryCellWriteModeV1, MemoryInventoryOwnerSnapshotV1, MemoryInventoryRecordV1};
use serde_json::{Value, json};

use crate::memory_cell_test_support::ControlFixture;

pub(crate) async fn fixture() -> (ControlFixture, MemoryInventoryOwnerSnapshotV1) {
    let fixture = ControlFixture::new().await;
    for record in [
        record(MemoryInventoryKindV1::Event, json!(4)),
        record(MemoryInventoryKindV1::Semantic, json!({"reserve":11,"pack":3,"limit":14})),
        record(MemoryInventoryKindV1::Procedure, json!({"opcodes":[1,2,3,6]})),
        record(MemoryInventoryKindV1::Hold, json!(false)),
    ] {
        fixture.store.write_memory_inventory(&fixture.access(), &CognitiveScope::AgentPrivate, &record, MemoryCellWriteModeV1::Create).await.expect("inventory owner write");
    }
    let snapshot = fixture.store.memory_inventory_snapshot(&fixture.access(), &CognitiveScope::AgentPrivate,
        crate::memory_cell_runtime::now_unix_seconds().expect("clock")).await.expect("inventory snapshot");
    (fixture, snapshot)
}

pub(crate) fn record(kind: MemoryInventoryKindV1, value: Value) -> MemoryInventoryRecordV1 {
    MemoryInventoryRecordV1 {
        schema:"hepta.memory.inventory-record.v1".into(), kind, effective_at:20, value,
        key:ContractIdV1::new(if kind == MemoryInventoryKindV1::Procedure {"workflow:amber"} else {"site:cedar"}).expect("key"),
    }
}

pub(crate) fn request(scope: ContractIdV1) -> MemoryInventoryRequestV1 {
    MemoryInventoryRequestV1 {
        schema:"hepta.memory.inventory-request.v1".into(), query_id:ContractIdV1::new("inventory-query").expect("query"), scope,
        entity_key:ContractIdV1::new("site:cedar").expect("entity"), workflow_key:ContractIdV1::new("workflow:amber").expect("workflow"),
        text:"Use workflow:amber with the current stock for site:cedar.".into(), at:20, since:20, max_hops:3, max_cells:4, max_steps:4,
    }
}
