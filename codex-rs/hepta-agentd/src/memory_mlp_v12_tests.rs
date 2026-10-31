use std::sync::Arc;

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_memory::MemoryTrainingSelectorV11;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::MemoryServingPlanV11;
use super::learned_test_support::publish_trained;
use super::learned_test_support::train;
use super::test_support::CellFixture;
use super::test_support::generation;
use super::test_support::key;
use super::test_support::now;
use super::test_support::owner_fixture;
use super::test_support::record;
use super::test_support::request;
use super::test_support::snapshot;
use crate::MemoryCellCandidateV11;
use crate::MemoryCellCandidateV12;

#[tokio::test]
async fn memory_v12_trained_payload_rejects_version_and_parameter_substitution() {
    let (_root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let projection = owner.training_projection_v11(&MemoryTrainingSelectorV11 {
        cell_id: key("cell:learned"), kind: MemoryInventoryKindV1::Semantic,
        keys: vec![key("item:a"), key("item:b")],
    }).expect("owner projection");
    let payload = train(&projection);
    MemoryCellCandidateV12::from_projection(&projection, generation(1), &payload).expect("V12");
    assert!(MemoryCellCandidateV11::from_projection(&projection, generation(1), &payload).is_err());
    let mut changed: serde_json::Value = serde_json::from_slice(&payload).expect("payload");
    changed["parameter_sha256"] = json!(Digest32::of_bytes(b"other-parameters").to_string());
    assert!(MemoryCellCandidateV12::from_projection(&projection, generation(1), &serde_json::to_vec(&changed).expect("JSON")).is_err());
    let mut changed: serde_json::Value = serde_json::from_slice(&payload).expect("payload");
    changed["owner_cut_sha256"] = json!(Digest32::of_bytes(b"other-owner-cut").to_string());
    assert!(MemoryCellCandidateV12::from_projection(&projection, generation(1), &serde_json::to_vec(&changed).expect("JSON")).is_err());
    let mut changed: serde_json::Value = serde_json::from_slice(&payload).expect("payload");
    let omitted = changed["supports"].as_object().expect("supports").keys().next().expect("support").clone();
    let source = changed["supports"][&omitted][0].clone();
    changed["supports"].as_object_mut().expect("supports").remove(&omitted);
    changed["features"].as_object_mut().expect("features").remove(&omitted);
    changed["lineage_sources"].as_array_mut().expect("lineage").retain(|item| *item != source);
    assert!(MemoryCellCandidateV12::from_projection(&projection, generation(1), &serde_json::to_vec(&changed).expect("JSON")).is_err());
}

#[tokio::test]
async fn memory_v12_trained_cells_publish_read_restart_correct_and_forget() {
    use MemoryInventoryKindV1::Event;
    use MemoryInventoryKindV1::Procedure;
    use MemoryInventoryKindV1::Semantic;
    let (root, store, access) = owner_fixture().await;
    let owner = snapshot(&store, &access).await;
    let mut semantic = CellFixture::new(root.path().join("semantic"), &owner, "cell:semantic", Semantic, "item:a");
    let mut procedure = CellFixture::new(root.path().join("procedure"), &owner, "cell:procedure", Procedure, "flow:a");
    semantic.selector.keys.push(key("item:b"));
    publish_trained(&mut semantic, &owner);
    publish_trained(&mut procedure, &owner);
    let plan = MemoryServingPlanV11::prepare(&owner, generation(2), vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)]).expect("learned plan");
    let scope = CognitiveScope::AgentPrivate;
    let query = request(&owner);
    let first = plan.read(&store, &access, &scope, &query, MemoryOperationV1::Apply).await.expect("learned composition");
    assert_eq!(first.value["value"], json!(14));
    let mut other = query.clone();
    other.entity_key = key("item:b");
    assert_eq!(plan.read(&store, &access, &scope, &other, MemoryOperationV1::Semantic).await.expect("second learned address").value,
        json!({"reserve":7,"pack":2,"limit":12}));
    semantic.host.sleep_selected().expect("evict decoded tensors");
    assert_eq!(plan.read(&store, &access, &scope, &query, MemoryOperationV1::Apply).await.expect("wake tensors").value, first.value);
    let saved = plan.checkpoint().expect("checkpoint");
    drop(plan);
    let mut semantic = semantic.reopen();
    let procedure = procedure.reopen();
    let restored = MemoryServingPlanV11::restore(&saved, &owner, vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)]).expect("authenticate recovered learned bytes");
    let sibling = procedure.host.load_current().expect("sibling");
    store.write_memory_inventory(&access, &scope, &record("item:a", Event, json!(9)), MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.expect("unrelated source");
    let fresh = restored.read(&store, &access, &scope, &query, MemoryOperationV1::Apply).await.expect("same learned weights fresh source");
    assert_eq!(fresh.value["value"], json!(6));
    assert_eq!(fresh.cells, first.cells);
    assert_ne!(fresh.query_cut_digest, first.query_cut_digest);
    store.write_memory_inventory(&access, &scope, &record("item:a", Semantic, json!({"reserve":14,"pack":2,"limit":15})), MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.expect("relevant correction");
    assert!(restored.read(&store, &access, &scope, &query, MemoryOperationV1::Apply).await.is_err());
    let corrected = snapshot(&store, &access).await;
    publish_trained(&mut semantic, &corrected);
    assert!(Arc::ptr_eq(&sibling, &procedure.host.load_current().expect("unchanged sibling")));
    let next = MemoryServingPlanV11::prepare(&corrected, generation(3), vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)]).expect("retrained semantic plan");
    assert_eq!(next.read(&store, &access, &scope, &query, MemoryOperationV1::Apply).await.expect("fresh learned source").value["value"], json!(10));
    assert!(MemoryServingPlanV11::restore(&saved, &corrected, vec![Arc::clone(&semantic.host), Arc::clone(&procedure.host)]).is_err());
    store.forget_memory_inventory(&access, &scope, &record("item:b", Semantic, json!(null)).address(), /*expected_revision*/ 1, "withdraw fitted dependency", now()).await.expect("tombstone");
    assert!(next.read(&store, &access, &scope, &query, MemoryOperationV1::Apply).await.is_err(), "even an unqueried trained dependency must invalidate its model");
}
