use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::MemoryCellWriteModeV1;
use crate::MemoryInventoryRecordV1;
use crate::MemoryTrainingSelectorV11;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;

fn record(
    key: &str,
    kind: MemoryInventoryKindV1,
    at: u64,
    value: Value,
) -> MemoryInventoryRecordV1 {
    MemoryInventoryRecordV1 {
        schema: "hepta.memory.inventory-record.v1".to_string(),
        key: ContractIdV1::new(key).expect("key"),
        kind,
        effective_at: at,
        value,
    }
}

fn selector(cell: &str, kind: MemoryInventoryKindV1, keys: &[&str]) -> MemoryTrainingSelectorV11 {
    MemoryTrainingSelectorV11 {
        cell_id: ContractIdV1::new(cell).expect("cell"),
        kind,
        keys: keys
            .iter()
            .map(|key| ContractIdV1::new(*key).expect("key"))
            .collect(),
    }
}

#[tokio::test]
async fn memory_v11_owner_projection_is_local_complete_and_recoverable() {
    use MemoryInventoryKindV1::Event;
    use MemoryInventoryKindV1::Hold;
    use MemoryInventoryKindV1::Procedure;
    use MemoryInventoryKindV1::Semantic;
    let temp = TempDir::new().expect("temp");
    let id = agent_id(91);
    let store = CognitiveStore::open(&layout(&temp, &id))
        .await
        .expect("owner");
    let access = CognitiveAccess::agent_private(id.clone());
    let scope = CognitiveScope::AgentPrivate;
    let write = |key, kind, value| record(key, kind, 20, value);
    for row in [
        write("item:a", Semantic, json!({"reserve":3,"pack":2,"limit":10})),
        write("item:b", Semantic, json!({"reserve":4,"pack":1,"limit":12})),
        write("flow:a", Procedure, json!({"opcodes":[1,2,3,6]})),
        write("item:a", Event, json!(5)),
        write("item:a", Hold, json!(false)),
    ] {
        store
            .write_memory_inventory(&access, &scope, &row, MemoryCellWriteModeV1::Create)
            .await
            .expect("write");
    }
    let first = store
        .memory_inventory_snapshot(&access, &scope, /*now_unix_seconds*/ 100)
        .await
        .expect("snapshot");
    let semantic = first
        .training_projection_v11(&selector("cell:semantic", Semantic, &["item:a", "item:b"]))
        .expect("semantic");
    let procedure = first
        .training_projection_v11(&selector("cell:procedure", Procedure, &["flow:a"]))
        .expect("procedure");
    // Event/Hold and another cell's keys change the complete cut, not these fits.
    for row in [
        write("item:a", Event, json!(8)),
        write("item:a", Hold, json!(true)),
    ] {
        store
            .write_memory_inventory(
                &access,
                &scope,
                &row,
                MemoryCellWriteModeV1::Correct {
                    expected_revision: 1,
                },
            )
            .await
            .expect("query-only correction");
    }
    let other = write(
        "item:other",
        Semantic,
        json!({"reserve":0,"pack":0,"limit":1}),
    );
    store
        .write_memory_inventory(&access, &scope, &other, MemoryCellWriteModeV1::Create)
        .await
        .expect("other cell");
    let current = store
        .revalidate_training_projection_v11(
            &access, &scope, &semantic, /*now_unix_seconds*/ 100,
        )
        .await
        .expect("unchanged semantic fit");
    assert_eq!(current.digest(), semantic.digest());
    assert_ne!(
        current.acquisition_cut_digest(),
        semantic.acquisition_cut_digest()
    );
    store
        .revalidate_training_projection_v11(
            &access, &scope, &procedure, /*now_unix_seconds*/ 100,
        )
        .await
        .expect("unchanged procedure fit");
    // Correct an unqueried member of this cell: all training dependencies count.
    store
        .write_memory_inventory(
            &access,
            &scope,
            &write("item:b", Semantic, json!({"reserve":9,"pack":2,"limit":15})),
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("relevant correction");
    assert!(
        store
            .revalidate_training_projection_v11(&access, &scope, &semantic, 100)
            .await
            .is_err()
    );
    store
        .revalidate_training_projection_v11(&access, &scope, &procedure, 100)
        .await
        .expect("independent procedure");
    let newest = store
        .memory_inventory_snapshot(&access, &scope, 100)
        .await
        .expect("new cut");
    let updated = newest
        .training_projection_v11(semantic.selector())
        .expect("new fit sources");
    assert_ne!(updated.digest(), semantic.digest());
    drop(store);
    let reopened = CognitiveStore::open(&layout(&temp, &id))
        .await
        .expect("reopen real SQLite");
    let restored = reopened
        .revalidate_training_projection_v11(&access, &scope, &updated, 100)
        .await
        .expect("recover projection");
    assert_eq!(restored.digest(), updated.digest());
    // A caller cannot replace owner authorization with a serialized digest.
    let denied = CognitiveAccess::agent_private(agent_id(92));
    assert!(
        reopened
            .revalidate_training_projection_v11(&denied, &scope, &updated, 100)
            .await
            .is_err()
    );
    reopened
        .forget_memory_inventory(
            &access,
            &scope,
            &write("item:b", Semantic, json!(null)).address(),
            /*expected_revision*/ 2,
            "withdraw trained source",
            /*now_unix_seconds*/ 101,
        )
        .await
        .expect("withdraw");
    assert!(
        reopened
            .revalidate_training_projection_v11(&access, &scope, &updated, 101)
            .await
            .is_err()
    );
    reopened
        .revalidate_training_projection_v11(&access, &scope, &procedure, 101)
        .await
        .expect("sibling survives withdrawal");
}

#[tokio::test]
async fn memory_v11_new_effective_version_and_tombstone_cannot_hide_behind_old_source_ids() {
    use MemoryInventoryKindV1::Semantic;
    let temp = TempDir::new().expect("temp");
    let id = agent_id(93);
    let store = CognitiveStore::open(&layout(&temp, &id))
        .await
        .expect("owner");
    let access = CognitiveAccess::agent_private(id);
    let scope = CognitiveScope::AgentPrivate;
    for at in [20, 200] {
        let row = record(
            "item:a",
            Semantic,
            at,
            json!({"reserve":3,"pack":2,"limit":10}),
        );
        store
            .write_memory_inventory(&access, &scope, &row, MemoryCellWriteModeV1::Create)
            .await
            .expect("version");
    }
    let before = store
        .memory_inventory_snapshot(&access, &scope, 100)
        .await
        .expect("before validity");
    let projection = before
        .training_projection_v11(&selector("cell:a", Semantic, &["item:a"]))
        .expect("projection");
    store
        .revalidate_training_projection_v11(&access, &scope, &projection, 199)
        .await
        .expect("not yet effective");
    assert!(
        store
            .revalidate_training_projection_v11(&access, &scope, &projection, 200)
            .await
            .is_err()
    );
    let latest = store
        .memory_inventory_snapshot(&access, &scope, 200)
        .await
        .expect("now effective");
    let updated = latest
        .training_projection_v11(projection.selector())
        .expect("new version");
    store
        .forget_memory_inventory(
            &access,
            &scope,
            &record("item:a", Semantic, /*at*/ 200, json!(null)).address(),
            /*expected_revision*/ 1,
            "withdraw latest",
            /*now_unix_seconds*/ 201,
        )
        .await
        .expect("withdraw latest");
    assert!(
        store
            .revalidate_training_projection_v11(&access, &scope, &updated, 201)
            .await
            .is_err()
    );
    assert!(
        store
            .revalidate_training_projection_v11(&access, &scope, &projection, 201)
            .await
            .is_err()
    );
}
