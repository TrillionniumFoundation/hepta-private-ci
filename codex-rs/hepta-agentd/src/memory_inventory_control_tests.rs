use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::{CognitiveScope, MemoryCellWriteModeV1};
use pretty_assertions::assert_eq;
use serde_json::json;

use crate::memory_inventory_test_support::{fixture, record, request};

#[tokio::test]
async fn inventory_control_pages_real_sources_and_closes_after_drift_or_owner_stop() {
    let (fixture, owner) = fixture().await;
    assert!(fixture.client.memory_inventory_snapshot(None, None, 2).await.is_err());
    fixture.ready();
    let first = fixture.client.memory_inventory_snapshot(None, None, 2).await.expect("first page");
    let last = fixture.client.memory_inventory_snapshot(first.next_after, Some(first.owner_cut_digest), 2).await.expect("last page");
    let sources = first.records.iter().chain(&last.records).map(|row| row.source_id).collect::<BTreeSet<_>>();
    assert_eq!(sources, owner.current_source_ids().iter().copied().collect());
    assert!(last.next_after.is_none());
    assert!(first.records.iter().chain(&last.records).all(|row| row.record.schema == "hepta.memory.inventory-record.v1"));
    assert!(fixture.client.memory_inventory_read(request(owner.scope().clone())).await.is_err());
    assert!(fixture.client.memory_inventory_snapshot(first.next_after, None, 2).await.is_err());
    fixture.store.write_memory_inventory(&fixture.access(), &CognitiveScope::AgentPrivate,
        &record(MemoryInventoryKindV1::Hold, json!(true)), MemoryCellWriteModeV1::Correct { expected_revision:1 }).await.expect("actual owner correction");
    assert!(fixture.client.memory_inventory_snapshot(first.next_after, Some(first.owner_cut_digest), 2).await.is_err());
    let changed = fixture.client.memory_inventory_snapshot(None, None, 32).await.expect("current cut");
    assert_ne!(changed.owner_cut_digest, first.owner_cut_digest);
    assert!(changed.records.iter().any(|row| row.record.kind == MemoryInventoryKindV1::Hold && row.revision == 2 && row.record.value == json!(true)));
    fixture.registry.compare_and_transition(&fixture.state.identity().agent_id, 2, AgentLifecycle::Draining).expect("real lifecycle stop");
    assert!(fixture.client.memory_inventory_snapshot(None, None, 32).await.is_err());
    fixture.finish().await;
}

#[tokio::test]
async fn inventory_export_never_restores_a_deleted_source() {
    let (fixture, owner) = fixture().await;
    fixture.ready();
    let removed = record(MemoryInventoryKindV1::Semantic, json!({"reserve":11,"pack":3,"limit":14}));
    let old_source = owner.current(&removed.key, removed.kind).expect("source before deletion").source_id;
    fixture.store.forget_memory_inventory(&fixture.access(), &CognitiveScope::AgentPrivate, &removed.address(), 1,
        "explicit inventory deletion", crate::memory_cell_runtime::now_unix_seconds().expect("clock")).await.expect("actual owner deletion");
    let page = fixture.client.memory_inventory_snapshot(None, None, 32).await.expect("current source export");
    assert_eq!(page.records.len(), 3);
    assert!(page.records.iter().all(|row| row.source_id != old_source && row.record.kind != MemoryInventoryKindV1::Semantic));
    assert!(fixture.client.memory_inventory_snapshot(None, Some(owner.owner_cut_digest()), 32).await.is_err());
    fixture.finish().await;
}
