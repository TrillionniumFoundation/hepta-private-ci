use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::MemoryCellOwnerSnapshotV1;
use crate::MemoryCellRecordV1;
use crate::MemoryCellWriteModeV1;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::workspace;

fn entity() -> ContractIdV1 {
    ContractIdV1::new("meter:owner-test").expect("entity")
}

fn record(kind: MemoryCellKindV1, effective_at: u64, value: Value) -> MemoryCellRecordV1 {
    MemoryCellRecordV1 {
        schema: "hepta.memory.cell-record.v1".to_string(),
        entity: entity(),
        kind,
        effective_at,
        value,
    }
}

async fn fixture() -> (TempDir, CognitiveStore, CognitiveAccess, CognitiveScope) {
    let temp = TempDir::new().expect("temp");
    let owner = agent_id(77);
    let store = CognitiveStore::open(&layout(&temp, &owner))
        .await
        .expect("store");
    let workspace = workspace("cell-owner-workspace");
    let access = CognitiveAccess::workspace_private(owner, workspace.clone());
    let scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: workspace,
    };
    let records = [
        record(MemoryCellKindV1::Event, 10, json!(4)),
        record(MemoryCellKindV1::Event, 20, json!(9)),
        record(
            MemoryCellKindV1::Semantic,
            10,
            json!({"factor": 2, "label": "earlier"}),
        ),
        record(
            MemoryCellKindV1::Semantic,
            20,
            json!({"factor": 3, "label": "current"}),
        ),
        record(
            MemoryCellKindV1::Procedure,
            20,
            json!({"opcode": "affine", "bias": 2, "limit": 1000}),
        ),
    ];
    for record in records {
        store
            .write_memory_cell(&access, &scope, &record, MemoryCellWriteModeV1::Create)
            .await
            .expect("typed write");
    }
    (temp, store, access, scope)
}

fn request(snapshot: &MemoryCellOwnerSnapshotV1) -> MemoryRequestV1 {
    MemoryRequestV1 {
        schema: "hepta.memory.request.v1".to_string(),
        query_id: ContractIdV1::new("query:owner-test").expect("query"),
        scope: snapshot.scope().clone(),
        entity: entity(),
        text: "Apply the stored procedure to the latest event".to_string(),
        at: 15,
        since: 10,
        max_hops: 4,
        max_cells: 3,
    }
}

fn digest(label: &[u8]) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(label)).expect("digest")
}

// Deliberately caller-constructed claims test owner admission, not model accuracy.
fn claim(
    snapshot: &MemoryCellOwnerSnapshotV1,
    request: &MemoryRequestV1,
    operation: MemoryOperationV1,
) -> MemoryReadoutV1 {
    let event = snapshot
        .current(&request.entity, MemoryCellKindV1::Event)
        .expect("event");
    let (value, sources, kind, models) = match operation {
        MemoryOperationV1::Current => (
            event.record.value.clone(),
            vec![event.source_id],
            MemoryPredictionKindV1::SourceEvidence,
            vec![],
        ),
        MemoryOperationV1::History => {
            let historical = snapshot
                .at(&request.entity, MemoryCellKindV1::Event, request.at)
                .expect("history");
            (
                historical.record.value.clone(),
                vec![historical.source_id],
                MemoryPredictionKindV1::SourceEvidence,
                vec![],
            )
        }
        MemoryOperationV1::Change => {
            let previous = snapshot
                .at(&request.entity, MemoryCellKindV1::Event, request.since)
                .expect("previous");
            (
                json!(5),
                vec![event.source_id, previous.source_id],
                MemoryPredictionKindV1::SourceEvidence,
                vec![],
            )
        }
        MemoryOperationV1::Semantic | MemoryOperationV1::Procedure => {
            let cell_kind = if operation == MemoryOperationV1::Semantic {
                MemoryCellKindV1::Semantic
            } else {
                MemoryCellKindV1::Procedure
            };
            let item = snapshot
                .current(&request.entity, cell_kind)
                .expect("parameter source");
            (
                item.record.value.clone(),
                vec![item.source_id],
                MemoryPredictionKindV1::ModelPrediction,
                vec![digest(b"model")],
            )
        }
        MemoryOperationV1::Apply => (
            json!(29),
            vec![
                event.source_id,
                snapshot
                    .current(&request.entity, MemoryCellKindV1::Semantic)
                    .expect("semantic")
                    .source_id,
                snapshot
                    .current(&request.entity, MemoryCellKindV1::Procedure)
                    .expect("procedure")
                    .source_id,
            ],
            MemoryPredictionKindV1::Mixed,
            vec![digest(b"semantic-model"), digest(b"procedure-model")],
        ),
    };
    MemoryReadoutV1 {
        schema: "hepta.memory.readout.v1".to_string(),
        query_id: request.query_id.clone(),
        operation: Some(operation),
        status: MemoryReadStatusV1::Ok,
        value,
        source_ids: sources,
        generation: ContractGenerationV1::new(1).expect("generation"),
        snapshot_digest: digest(b"bundle"),
        prediction_kind: kind,
        cell_digests: models,
        hops: 3,
        elapsed_seconds: 0.0,
        reason: None,
    }
}

async fn admit(
    store: &CognitiveStore,
    access: &CognitiveAccess,
    scope: &CognitiveScope,
    snapshot: &MemoryCellOwnerSnapshotV1,
    request: &MemoryRequestV1,
    readout: &MemoryReadoutV1,
    now: i64,
) -> Result<(), CognitiveStoreError> {
    store
        .revalidate_memory_cell_readout(
            access,
            scope,
            snapshot,
            request,
            readout,
            ContractGenerationV1::new(1).expect("generation"),
            digest(b"bundle"),
            now,
        )
        .await
}

#[tokio::test]
async fn typed_sources_use_real_owner_and_survive_reopen() {
    let (temp, store, access, scope) = fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, 100)
        .await
        .expect("snapshot");
    assert_eq!(snapshot.records().len(), 5);
    assert_eq!(snapshot.current_source_ids().len(), 3);
    assert_eq!(
        snapshot.training_records(MemoryCellKindV1::Semantic).len(),
        1
    );
    assert_eq!(
        snapshot
            .at(&entity(), MemoryCellKindV1::Event, 15)
            .expect("old")
            .record
            .value,
        json!(4)
    );
    let encoded = serde_json::to_value(&snapshot).expect("training export");
    assert_eq!(encoded["schema"], json!("hepta.memory.owner-snapshot.v1"));
    assert!(encoded.get("cut").is_none());
    assert!(
        encoded["records"]
            .as_array()
            .expect("rows")
            .iter()
            .all(|row| row["source_id"].as_str().expect("source").len() == 64)
    );
    let request = request(&snapshot);
    for operation in [
        MemoryOperationV1::Current,
        MemoryOperationV1::History,
        MemoryOperationV1::Change,
        MemoryOperationV1::Semantic,
        MemoryOperationV1::Procedure,
        MemoryOperationV1::Apply,
    ] {
        admit(
            &store,
            &access,
            &scope,
            &snapshot,
            &request,
            &claim(&snapshot, &request, operation),
            100,
        )
        .await
        .expect("actual owner admission");
    }
    drop(store);
    let reopened = CognitiveStore::open(&layout(&temp, access.agent_id()))
        .await
        .expect("reopen");
    let current = reopened
        .memory_cell_snapshot(&access, &scope, 101)
        .await
        .expect("new snapshot");
    assert_eq!(current.owner_cut_digest(), snapshot.owner_cut_digest());
    assert_eq!(current.records(), snapshot.records());
    admit(
        &reopened,
        &access,
        &scope,
        &snapshot,
        &request,
        &claim(&snapshot, &request, MemoryOperationV1::Apply),
        101,
    )
    .await
    .expect("reopened final use");
}

#[tokio::test]
async fn correction_and_tombstone_invalidate_old_training_cut_without_fallback() {
    let (_temp, store, access, scope) = fixture().await;
    let before = store
        .memory_cell_snapshot(&access, &scope, 100)
        .await
        .expect("before");
    let request = request(&before);
    let old = claim(&before, &request, MemoryOperationV1::Apply);
    let corrected = record(
        MemoryCellKindV1::Semantic,
        20,
        json!({"factor": 4, "label": "corrected"}),
    );
    store
        .write_memory_cell(
            &access,
            &scope,
            &corrected,
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .expect("correction");
    assert!(matches!(
        admit(&store, &access, &scope, &before, &request, &old, 101).await,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let after = store
        .memory_cell_snapshot(&access, &scope, 101)
        .await
        .expect("after");
    assert_ne!(before.owner_cut_digest(), after.owner_cut_digest());
    assert_ne!(
        before
            .current(&entity(), MemoryCellKindV1::Semantic)
            .expect("old semantic")
            .source_id,
        after
            .current(&entity(), MemoryCellKindV1::Semantic)
            .expect("new semantic")
            .source_id
    );
    let stale = store
        .write_memory_cell(
            &access,
            &scope,
            &corrected,
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await;
    assert!(matches!(stale, Err(CognitiveStoreError::Conflict(_))));
    assert_eq!(
        store
            .memory_cell_snapshot(&access, &scope, 101)
            .await
            .expect("after rejected CAS")
            .owner_cut_digest(),
        after.owner_cut_digest()
    );
    store
        .forget_memory_cell(&access, &scope, &corrected.address(), 2, "withdrawn", 102)
        .await
        .expect("withdraw");
    let withdrawn = store
        .memory_cell_snapshot(&access, &scope, 102)
        .await
        .expect("withdrawn snapshot");
    assert!(
        withdrawn
            .current(&entity(), MemoryCellKindV1::Semantic)
            .is_none()
    );
    assert!(
        withdrawn
            .training_records(MemoryCellKindV1::Semantic)
            .is_empty()
    );
    assert!(
        withdrawn
            .at(&entity(), MemoryCellKindV1::Semantic, 15)
            .is_some()
    );
    let same_address = store
        .write_memory_cell(
            &access,
            &scope,
            &corrected,
            MemoryCellWriteModeV1::Correct {
                expected_revision: 3,
            },
        )
        .await;
    assert!(matches!(
        same_address,
        Err(CognitiveStoreError::Conflict(_))
    ));
    let bad_address = record(MemoryCellKindV1::Semantic, 21, corrected.value);
    assert!(
        store
            .write_memory_cell(
                &access,
                &scope,
                &bad_address,
                MemoryCellWriteModeV1::Correct {
                    expected_revision: 2
                }
            )
            .await
            .is_err()
    );
    assert_eq!(
        store
            .memory_cell_snapshot(&access, &scope, 102)
            .await
            .expect("unchanged failed mutations")
            .owner_cut_digest(),
        withdrawn.owner_cut_digest()
    );
}

#[tokio::test]
async fn owner_principal_scope_entity_and_support_are_rechecked() {
    let (_temp, store, access, scope) = fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, 100)
        .await
        .expect("snapshot");
    let request = request(&snapshot);
    let readout = claim(&snapshot, &request, MemoryOperationV1::Current);
    let other_agent =
        CognitiveAccess::workspace_private(agent_id(78), workspace("cell-owner-workspace"));
    let other_workspace =
        CognitiveAccess::workspace_private(access.agent_id().clone(), workspace("different"));
    for denied in [&other_agent, &other_workspace] {
        assert!(matches!(
            store.memory_cell_snapshot(denied, &scope, 100).await,
            Err(CognitiveStoreError::AccessDenied(_))
        ));
        assert!(matches!(
            admit(&store, denied, &scope, &snapshot, &request, &readout, 100).await,
            Err(CognitiveStoreError::AccessDenied(_))
        ));
        assert!(matches!(
            store
                .write_memory_cell(
                    denied,
                    &scope,
                    &record(MemoryCellKindV1::Event, 30, json!(6)),
                    MemoryCellWriteModeV1::Create
                )
                .await,
            Err(CognitiveStoreError::AccessDenied(_))
        ));
    }
    let mut wrong_scope = request.clone();
    wrong_scope.scope = ContractIdV1::new("scope:forged").expect("scope");
    assert!(
        admit(
            &store,
            &access,
            &scope,
            &snapshot,
            &wrong_scope,
            &readout,
            100
        )
        .await
        .is_err()
    );
    let mut wrong_entity = request.clone();
    wrong_entity.entity = ContractIdV1::new("meter:different").expect("entity");
    assert!(
        admit(
            &store,
            &access,
            &scope,
            &snapshot,
            &wrong_entity,
            &readout,
            100
        )
        .await
        .is_err()
    );
    let mut old_source = readout.clone();
    old_source.source_ids = vec![
        snapshot
            .at(&entity(), MemoryCellKindV1::Event, 15)
            .expect("history")
            .source_id,
    ];
    assert!(
        admit(
            &store,
            &access,
            &scope,
            &snapshot,
            &request,
            &old_source,
            100
        )
        .await
        .is_err()
    );
    let mut wrong_value = readout.clone();
    wrong_value.value = json!(999);
    assert!(
        admit(
            &store,
            &access,
            &scope,
            &snapshot,
            &request,
            &wrong_value,
            100
        )
        .await
        .is_err()
    );
}

#[tokio::test]
async fn prediction_labels_clock_and_composition_budget_fail_closed() {
    let (_temp, store, access, scope) = fixture().await;
    let snapshot = store
        .memory_cell_snapshot(&access, &scope, 100)
        .await
        .expect("snapshot");
    let mut request = request(&snapshot);
    let apply = claim(&snapshot, &request, MemoryOperationV1::Apply);
    assert!(
        admit(&store, &access, &scope, &snapshot, &request, &apply, 99)
            .await
            .is_err()
    );
    request.max_cells = 2;
    assert!(
        admit(&store, &access, &scope, &snapshot, &request, &apply, 100)
            .await
            .is_err()
    );
    request.max_cells = 3;
    let mut semantic = claim(&snapshot, &request, MemoryOperationV1::Semantic);
    semantic.prediction_kind = MemoryPredictionKindV1::SourceEvidence;
    semantic.cell_digests.clear();
    assert!(
        admit(&store, &access, &scope, &snapshot, &request, &semantic, 100)
            .await
            .is_err()
    );
    store
        .write_memory_cell(
            &access,
            &scope,
            &record(MemoryCellKindV1::Event, 200, json!(30)),
            MemoryCellWriteModeV1::Create,
        )
        .await
        .expect("future event");
    let before_effective = store
        .memory_cell_snapshot(&access, &scope, 100)
        .await
        .expect("future not active");
    assert_eq!(
        before_effective
            .current(&entity(), MemoryCellKindV1::Event)
            .expect("current")
            .record
            .value,
        json!(9)
    );
    let current_readout = claim(&before_effective, &request, MemoryOperationV1::Current);
    assert!(
        admit(
            &store,
            &access,
            &scope,
            &before_effective,
            &request,
            &current_readout,
            201
        )
        .await
        .is_err()
    );
}
