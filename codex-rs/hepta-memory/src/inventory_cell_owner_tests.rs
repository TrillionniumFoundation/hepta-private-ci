use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellReadoutV1, InventoryCellRequestV1, InventoryCellRouteV1, MemoryOperationV1, MemoryPredictionKindV1, MemoryReadStatusV1, MemoryReadoutV1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractGenerationV1, ContractIdV1};
use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use tempfile::TempDir;
use crate::{CognitiveAccess, CognitiveScope, CognitiveStore, InventoryCellOwnerSnapshotV1, InventoryCellRecordV1, MemoryCellWriteModeV1};
use crate::cognitive_test_support::{agent_id, layout};

fn id(name: &str) -> ContractIdV1 { ContractIdV1::new(name).unwrap() }
fn digest(name: &[u8]) -> ContractDigestV1 { ContractDigestV1::from_digest(Digest32::of_bytes(name)).unwrap() }
fn record(key: &str, kind: InventoryCellKindV1, effective_at: u64, value: Value) -> InventoryCellRecordV1 {
    InventoryCellRecordV1 { schema: "hepta.memory.inventory-cell-record.v1".to_string(), key: id(key), kind, effective_at, value, training_origin: None }
}
async fn fixture() -> (TempDir, CognitiveStore, CognitiveAccess) {
    let temp = TempDir::new().unwrap();
    let owner = agent_id(78);
    let store = CognitiveStore::open(&layout(&temp, &owner)).await.unwrap();
    let access = CognitiveAccess::agent_private(owner);
    for row in [
        record("entity:a", InventoryCellKindV1::Event, 10, json!(4)),
        record("entity:a", InventoryCellKindV1::Event, 20, json!(9)),
        record("entity:a", InventoryCellKindV1::Semantic, 10, json!({"reserve": 3, "pack": 2, "limit": 7})),
        record("entity:a", InventoryCellKindV1::Semantic, 20, json!({"reserve": 5, "pack": 3, "limit": 14})),
        record("workflow:b", InventoryCellKindV1::Skill, 20, json!({"program": [1, 2, 3, 6]})),
    ] {
        store.write_inventory_cell(&access, &CognitiveScope::AgentPrivate, &row, MemoryCellWriteModeV1::Create).await.unwrap();
    }
    (temp, store, access)
}
fn request(snapshot: &InventoryCellOwnerSnapshotV1) -> InventoryCellRequestV1 {
    InventoryCellRequestV1 { schema: "hepta.memory.inventory-request.v1".to_string(), query_id: id("query:inventory"), scope: snapshot.scope().clone(), text: "Apply workflow:b to entity:a".to_string(), at: 15, since: 10, max_cells: 3, max_hops: 3, max_steps: 4 }
}
fn apply_route() -> InventoryCellRouteV1 {
    InventoryCellRouteV1 { operation: MemoryOperationV1::Apply, entity: Some(id("entity:a")), workflow: Some(id("workflow:b")) }
}
fn claim(snapshot: &InventoryCellOwnerSnapshotV1, request: &InventoryCellRequestV1) -> InventoryCellReadoutV1 {
    let route = apply_route();
    InventoryCellReadoutV1 {
        schema: "hepta.memory.inventory-readout.v1".to_string(),
        result: MemoryReadoutV1 {
            schema: "hepta.memory.readout.v1".to_string(), query_id: request.query_id.clone(), operation: Some(route.operation),
            status: MemoryReadStatusV1::Ok, value: json!(0), source_ids: snapshot.required_sources(request, &route).unwrap().into_iter().collect(),
            generation: ContractGenerationV1::new(1).unwrap(), snapshot_digest: digest(b"bundle"), prediction_kind: MemoryPredictionKindV1::Mixed,
            cell_digests: vec![digest(b"policy"), digest(b"program")], hops: 3, elapsed_seconds: 0.0, reason: None,
        }, route: Some(route),
    }
}

#[tokio::test]
async fn inventory_owner_preserves_dual_addresses_and_reopen_without_legacy_alias() {
    let (temp, store, access) = fixture().await;
    let scope = CognitiveScope::AgentPrivate;
    let snapshot = store.inventory_cell_snapshot(&access, &scope, 100).await.unwrap();
    assert_eq!(snapshot.records().len(), 5);
    assert_eq!(snapshot.current_source_ids().len(), 3);
    assert_eq!(snapshot.at(&id("entity:a"), InventoryCellKindV1::Event, 15).unwrap().record.value, json!(4));
    assert!(snapshot.current(&id("entity:a"), InventoryCellKindV1::Skill).is_none());
    assert!(snapshot.current(&id("workflow:b"), InventoryCellKindV1::Skill).is_some());
    assert!(store.memory_cell_snapshot(&access, &scope, 100).await.unwrap().records().is_empty());
    let request = request(&snapshot);
    let readout = claim(&snapshot, &request);
    store.revalidate_inventory_cell_readout(&access, &scope, &snapshot, &request, &readout, ContractGenerationV1::new(1).unwrap(), digest(b"bundle"), 100).await.unwrap();
    let reopened = CognitiveStore::open(&layout(&temp, store.owner_agent_id())).await.unwrap();
    let after = reopened.inventory_cell_snapshot(&access, &scope, 100).await.unwrap();
    assert_eq!(after.owner_cut_digest(), snapshot.owner_cut_digest());
    assert_eq!(after.current_source_ids(), snapshot.current_source_ids());
}

#[tokio::test]
async fn inventory_owner_rejects_corrected_cut_swapped_workflow_and_hold() {
    let (_temp, store, access) = fixture().await;
    let scope = CognitiveScope::AgentPrivate;
    let snapshot = store.inventory_cell_snapshot(&access, &scope, 100).await.unwrap();
    let request = request(&snapshot);
    let mut readout = claim(&snapshot, &request);
    readout.route.as_mut().unwrap().workflow = Some(id("entity:a"));
    assert!(store.revalidate_inventory_cell_readout(&access, &scope, &snapshot, &request, &readout, ContractGenerationV1::new(1).unwrap(), digest(b"bundle"), 100).await.is_err());
    let readout = claim(&snapshot, &request);
    let corrected = record("entity:a", InventoryCellKindV1::Event, 20, json!(11));
    store.write_inventory_cell(&access, &scope, &corrected, MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.unwrap();
    assert!(store.revalidate_inventory_cell_readout(&access, &scope, &snapshot, &request, &readout, ContractGenerationV1::new(1).unwrap(), digest(b"bundle"), 100).await.is_err());
    let hold = record("entity:a", InventoryCellKindV1::Hold, 21, json!({"reason": "manual owner hold"}));
    store.write_inventory_cell(&access, &scope, &hold, MemoryCellWriteModeV1::Create).await.unwrap();
    let held = store.inventory_cell_snapshot(&access, &scope, 100).await.unwrap();
    assert!(held.required_sources(&request, &apply_route()).is_err());
    store.forget_inventory_cell(&access, &scope, &hold.address(), 1, "owner explicitly cleared hold", 101).await.unwrap();
    assert!(store.inventory_cell_snapshot(&access, &scope, 102).await.unwrap().required_sources(&request, &apply_route()).is_ok());
}

#[tokio::test]
async fn inventory_tombstone_does_not_resurrect_older_policy_and_scope_is_authorized() {
    let (_temp, store, access) = fixture().await;
    let scope = CognitiveScope::AgentPrivate;
    let row = record("entity:a", InventoryCellKindV1::Semantic, 20, json!({"reserve": 5, "pack": 3, "limit": 14}));
    store.forget_inventory_cell(&access, &scope, &row.address(), 1, "withdraw policy", 101).await.unwrap();
    let after = store.inventory_cell_snapshot(&access, &scope, 102).await.unwrap();
    assert!(after.current(&id("entity:a"), InventoryCellKindV1::Semantic).is_none());
    assert!(after.at(&id("entity:a"), InventoryCellKindV1::Semantic, 15).is_some());
    let other = CognitiveAccess::agent_private(agent_id(79));
    assert!(store.inventory_cell_snapshot(&other, &scope, 102).await.is_err());
}
