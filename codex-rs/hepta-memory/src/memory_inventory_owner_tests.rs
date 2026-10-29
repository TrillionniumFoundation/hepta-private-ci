use std::collections::BTreeSet;

use codex_hepta_cognitive_types::MemoryInventoryKindV1;
use codex_hepta_cognitive_types::MemoryInventoryPolicyV1;
use codex_hepta_cognitive_types::MemoryInventoryProgramV1;
use codex_hepta_cognitive_types::MemoryInventoryReadoutV1;
use codex_hepta_cognitive_types::MemoryInventoryRequestV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::execute_memory_inventory_program_v1;
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
use crate::MemoryCellWriteModeV1;
use crate::MemoryInventoryOwnerSnapshotV1;
use crate::MemoryInventoryRecordV1;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::layout;
use crate::cognitive_test_support::workspace;

const ENTITY: &str = "stock:owner-inventory";
const WORKFLOW: &str = "workflow:owner-inventory";
const OTHER: &str = "stock:other-inventory";
const OBSERVED: i64 = 100;

fn key(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("key")
}

fn digest(value: &[u8]) -> ContractDigestV1 {
    ContractDigestV1::from_digest(Digest32::of_bytes(value)).expect("digest")
}

fn record(key_text: &str, kind: MemoryInventoryKindV1, effective_at: u64, value: Value) -> MemoryInventoryRecordV1 {
    MemoryInventoryRecordV1 {
        schema: "hepta.memory.inventory-record.v1".to_string(),
        key: key(key_text), kind, effective_at, value,
    }
}

struct Fixture {
    temp: TempDir,
    store: CognitiveStore,
    access: CognitiveAccess,
    scope: CognitiveScope,
}

impl Fixture {
    async fn new() -> Self {
        use MemoryInventoryKindV1::{Event, Hold, Procedure, Semantic};
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(87);
        let store = CognitiveStore::open(&layout(&temp, &owner)).await.expect("store");
        let workspace = workspace("inventory-owner-workspace");
        let access = CognitiveAccess::workspace_private(owner, workspace.clone());
        let scope = CognitiveScope::WorkspacePrivate { workspace_sha256: workspace };
        let fixture = Self { temp, store, access, scope };
        // Both keys deliberately have other types. A single-key shortcut must fail.
        for (key, kind, at, value) in [
            (ENTITY, Event, 10, json!(4)),
            (ENTITY, Event, 20, json!(9)),
            (ENTITY, Semantic, 10, json!({"reserve":3,"pack":1,"limit":7})),
            (ENTITY, Semantic, 20, json!({"reserve":6,"pack":2,"limit":15})),
            (WORKFLOW, Procedure, 20, json!({"opcodes":[4,2,3,6]})),
            (ENTITY, Hold, 20, json!(false)),
            (ENTITY, Procedure, 20, json!({"opcodes":[0,0,0,6]})),
            (WORKFLOW, Semantic, 20, json!({"reserve":0,"pack":0,"limit":0})),
            (WORKFLOW, Hold, 20, json!(true)),
            (OTHER, Semantic, 20, json!({"reserve":2,"pack":3,"limit":13})),
        ] {
            fixture.write(&record(key, kind, at, value), MemoryCellWriteModeV1::Create)
                .await.expect("typed owner write");
        }
        fixture
    }

    async fn write(&self, record: &MemoryInventoryRecordV1, mode: MemoryCellWriteModeV1) -> Result<(), CognitiveStoreError> {
        self.store.write_memory_inventory(&self.access, &self.scope, record, mode).await.map(|_| ())
    }

    async fn snapshot(&self, now: i64) -> MemoryInventoryOwnerSnapshotV1 {
        self.store.memory_inventory_snapshot(&self.access, &self.scope, now).await.expect("owner snapshot")
    }

    async fn admit(&self, snapshot: &MemoryInventoryOwnerSnapshotV1, request: &MemoryInventoryRequestV1,
        readout: &MemoryInventoryReadoutV1, now: i64) -> Result<(), CognitiveStoreError> {
        self.store.revalidate_memory_inventory_readout(
            &self.access, &self.scope, snapshot, request, readout,
            ContractGenerationV1::new(1).expect("generation"), digest(b"inventory-bundle"), now,
        ).await
    }
}

fn request(snapshot: &MemoryInventoryOwnerSnapshotV1) -> MemoryInventoryRequestV1 {
    MemoryInventoryRequestV1 {
        schema: "hepta.memory.inventory-request.v1".to_string(),
        query_id: key("query:inventory-owner"), scope: snapshot.scope().clone(),
        entity_key: key(ENTITY), workflow_key: key(WORKFLOW),
        text: "Apply the current workflow to the latest stock".to_string(),
        at: 15, since: 10, max_hops: 3, max_cells: 4, max_steps: 4,
    }
}

fn source(snapshot: &MemoryInventoryOwnerSnapshotV1, key_text: &str, kind: MemoryInventoryKindV1) -> ContractDigestV1 {
    snapshot.current(&key(key_text), kind).expect("current source").source_id
}

// These are caller-constructed claims to exercise owner admission, not model-accuracy evidence.
fn apply_claim(snapshot: &MemoryInventoryOwnerSnapshotV1, request: &MemoryInventoryRequestV1) -> MemoryInventoryReadoutV1 {
    use MemoryInventoryKindV1::{Event, Hold, Procedure, Semantic};
    let execution = execute_memory_inventory_program_v1(
        &MemoryInventoryProgramV1 { opcodes: [4, 2, 3, 6] }, /*event*/ 9,
        &MemoryInventoryPolicyV1 { reserve: 6, pack: 2, limit: 15 }, /*max_steps*/ 4,
    ).expect("bounded fixture program");
    MemoryInventoryReadoutV1 {
        schema: "hepta.memory.inventory-readout.v1".to_string(),
        query_id: request.query_id.clone(), operation: Some(MemoryOperationV1::Apply),
        status: MemoryReadStatusV1::Ok, value: serde_json::to_value(execution).expect("execution"),
        source_ids: vec![source(snapshot, ENTITY, Event), source(snapshot, ENTITY, Semantic),
            source(snapshot, WORKFLOW, Procedure), source(snapshot, ENTITY, Hold)],
        generation: ContractGenerationV1::new(1).expect("generation"),
        snapshot_digest: digest(b"inventory-bundle"), prediction_kind: MemoryPredictionKindV1::Mixed,
        cell_digests: vec![digest(b"inventory-policy-model"), digest(b"inventory-program-model")],
        hops: 3, elapsed_seconds: 0.0, reason: None,
    }
}

#[tokio::test]
async fn two_keys_bind_exact_dependencies_and_survive_owner_reopen() {
    use MemoryInventoryKindV1::{Hold, Procedure, Semantic};
    let fixture = Fixture::new().await;
    let snapshot = fixture.snapshot(OBSERVED).await;
    let request = request(&snapshot);
    let claim = apply_claim(&snapshot, &request);
    assert_eq!(snapshot.required_sources(&request, MemoryOperationV1::Apply).expect("dependencies"),
        claim.source_ids.iter().copied().collect::<BTreeSet<_>>());
    assert_eq!(snapshot.required_sources(&request, MemoryOperationV1::Procedure).expect("procedure"),
        BTreeSet::from([source(&snapshot, WORKFLOW, Procedure)]));
    fixture.admit(&snapshot, &request, &claim, OBSERVED).await.expect("live owner admission");
    for (selected, wrong) in [
        (source(&snapshot, WORKFLOW, Procedure), source(&snapshot, ENTITY, Procedure)),
        (source(&snapshot, ENTITY, Semantic), source(&snapshot, WORKFLOW, Semantic)),
        (source(&snapshot, ENTITY, Hold), source(&snapshot, WORKFLOW, Hold)),
    ] {
        let mut substituted = claim.clone();
        *substituted.source_ids.iter_mut().find(|source| **source == selected).expect("selected") = wrong;
        assert!(fixture.admit(&snapshot, &request, &substituted, OBSERVED).await.is_err());
    }
    let mut missing_hold = claim.clone();
    missing_hold.source_ids.retain(|id| *id != source(&snapshot, ENTITY, Hold));
    let mut extra_source = claim.clone();
    extra_source.source_ids.push(source(&snapshot, OTHER, Semantic));
    for rejected in [missing_hold, extra_source] {
        assert!(fixture.admit(&snapshot, &request, &rejected, OBSERVED).await.is_err());
    }
    let Fixture { temp, store, access, scope } = fixture;
    drop(store);
    let reopened = CognitiveStore::open(&layout(&temp, access.agent_id())).await.expect("reopen");
    let fixture = Fixture { temp, store: reopened, access, scope };
    let persisted = fixture.snapshot(OBSERVED + 1).await;
    assert_eq!(persisted.records(), snapshot.records());
    assert_eq!(persisted.owner_cut_digest(), snapshot.owner_cut_digest());
    fixture.admit(&snapshot, &request, &claim, OBSERVED + 1).await.expect("reopened admission");
}

#[tokio::test]
async fn explicit_hold_false_is_required_and_true_or_missing_hold_stops_apply() {
    let fixture = Fixture::new().await;
    let before = fixture.snapshot(OBSERVED).await;
    let request = request(&before);
    fixture.admit(&before, &request, &apply_claim(&before, &request), OBSERVED)
        .await.expect("explicit false permits admission");
    let held_record = record(ENTITY, MemoryInventoryKindV1::Hold, /*effective_at*/ 20, json!(true));
    fixture.write(&held_record, MemoryCellWriteModeV1::Correct { expected_revision: 1 })
        .await.expect("set hold");
    let held = fixture.snapshot(OBSERVED + 1).await;
    let held_claim = apply_claim(&held, &request);
    assert_eq!(held.required_sources(&request, MemoryOperationV1::Apply).expect("hold is a dependency"),
        held_claim.source_ids.iter().copied().collect::<BTreeSet<_>>());
    assert!(matches!(fixture.admit(&held, &request, &held_claim, OBSERVED + 1).await,
        Err(CognitiveStoreError::Conflict(_))));
    fixture.store.forget_memory_inventory(&fixture.access, &fixture.scope, &held_record.address(),
        /*expected_revision*/ 2, "remove hold directive", OBSERVED + 2).await.expect("withdraw hold");
    let missing = fixture.snapshot(OBSERVED + 2).await;
    assert!(missing.current(&key(ENTITY), MemoryInventoryKindV1::Hold).is_none());
    assert!(missing.required_sources(&request, MemoryOperationV1::Apply).is_err());
    assert!(fixture.admit(&missing, &request, &held_claim, OBSERVED + 2).await.is_err());
}

#[tokio::test]
async fn correction_changes_source_identity_and_stale_cas_cannot_change_the_cut() {
    let fixture = Fixture::new().await;
    let before = fixture.snapshot(OBSERVED).await;
    let request = request(&before);
    let old_claim = apply_claim(&before, &request);
    let corrected = record(ENTITY, MemoryInventoryKindV1::Semantic, /*effective_at*/ 20,
        json!({"reserve":7,"pack":2,"limit":15}));
    fixture.write(&corrected, MemoryCellWriteModeV1::Correct { expected_revision: 1 })
        .await.expect("correction");
    let after = fixture.snapshot(OBSERVED + 1).await;
    assert_ne!(after.owner_cut_digest(), before.owner_cut_digest());
    let previous = before.current(&key(ENTITY), MemoryInventoryKindV1::Semantic).expect("previous");
    let updated = after.current(&key(ENTITY), MemoryInventoryKindV1::Semantic).expect("updated");
    assert_eq!(updated.owner_memory_id, previous.owner_memory_id);
    assert_eq!((&updated.record, updated.revision), (&corrected, 2));
    assert_ne!(updated.source_id, previous.source_id);
    assert!(matches!(fixture.admit(&before, &request, &old_claim, OBSERVED + 1).await,
        Err(CognitiveStoreError::Conflict(_))));
    fixture.admit(&after, &request, &apply_claim(&after, &request), OBSERVED + 1)
        .await.expect("new source dependencies");
    assert!(matches!(fixture.write(&corrected, MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await,
        Err(CognitiveStoreError::Conflict(_))));
    let unchanged = fixture.snapshot(OBSERVED + 1).await;
    assert_eq!(unchanged.owner_cut_digest(), after.owner_cut_digest());
    assert_eq!(unchanged.records(), after.records());
}

#[tokio::test]
async fn unqueried_training_source_change_invalidates_the_complete_owner_cut() {
    let fixture = Fixture::new().await;
    let before = fixture.snapshot(OBSERVED).await;
    let request = request(&before);
    let claim = apply_claim(&before, &request);
    let unrelated = source(&before, OTHER, MemoryInventoryKindV1::Semantic);
    assert!(before.training_records(MemoryInventoryKindV1::Semantic).iter().any(|record| record.source_id == unrelated));
    assert!(!claim.source_ids.contains(&unrelated));
    fixture.write(&record(OTHER, MemoryInventoryKindV1::Semantic, /*effective_at*/ 20,
        json!({"reserve":3,"pack":3,"limit":13})), MemoryCellWriteModeV1::Correct { expected_revision: 1 })
        .await.expect("unqueried source correction");
    let after = fixture.snapshot(OBSERVED + 1).await;
    assert_eq!(after.required_sources(&request, MemoryOperationV1::Apply).expect("same queried dependencies"),
        before.required_sources(&request, MemoryOperationV1::Apply).expect("previous dependencies"));
    assert_ne!(after.owner_cut_digest(), before.owner_cut_digest());
    assert!(matches!(fixture.admit(&before, &request, &claim, OBSERVED + 1).await,
        Err(CognitiveStoreError::Conflict(_))));
}

#[tokio::test]
async fn withdrawing_current_source_never_falls_back_to_the_old_address() {
    let fixture = Fixture::new().await;
    let before = fixture.snapshot(OBSERVED).await;
    let request = request(&before);
    let claim = apply_claim(&before, &request);
    let latest = before.current(&key(ENTITY), MemoryInventoryKindV1::Semantic).expect("latest");
    fixture.store.forget_memory_inventory(&fixture.access, &fixture.scope, &latest.record.address(),
        /*expected_revision*/ 1, "withdraw current policy", OBSERVED + 1).await.expect("withdraw");
    let after = fixture.snapshot(OBSERVED + 1).await;
    assert!(after.current(&key(ENTITY), MemoryInventoryKindV1::Semantic).is_none());
    assert!(after.training_records(MemoryInventoryKindV1::Semantic).iter().all(|record| record.record.key != key(ENTITY)));
    assert_eq!(after.at(&key(ENTITY), MemoryInventoryKindV1::Semantic, /*at*/ 15).expect("history remains").record.value,
        json!({"reserve":3,"pack":1,"limit":7}));
    assert!(after.required_sources(&request, MemoryOperationV1::Apply).is_err());
    assert!(fixture.admit(&before, &request, &claim, OBSERVED + 1).await.is_err());
    assert!(fixture.admit(&after, &request, &claim, OBSERVED + 1).await.is_err());
    assert!(matches!(fixture.write(&latest.record, MemoryCellWriteModeV1::Correct { expected_revision: 2 }).await,
        Err(CognitiveStoreError::Conflict(_))));
    assert_eq!(fixture.snapshot(OBSERVED + 1).await.owner_cut_digest(), after.owner_cut_digest());
}

#[tokio::test]
async fn owner_scope_request_generation_and_bundle_must_match_at_final_use() {
    let fixture = Fixture::new().await;
    let snapshot = fixture.snapshot(OBSERVED).await;
    let request = request(&snapshot);
    let claim = apply_claim(&snapshot, &request);
    let other_owner = CognitiveAccess::workspace_private(agent_id(88), workspace("inventory-owner-workspace"));
    let other_workspace = CognitiveAccess::workspace_private(fixture.access.agent_id().clone(), workspace("different"));
    for denied in [&other_owner, &other_workspace] {
        assert!(matches!(fixture.store.memory_inventory_snapshot(denied, &fixture.scope, OBSERVED).await,
            Err(CognitiveStoreError::AccessDenied(_))));
        assert!(matches!(fixture.store.revalidate_memory_inventory_readout(denied, &fixture.scope,
            &snapshot, &request, &claim, claim.generation, claim.snapshot_digest, OBSERVED).await,
            Err(CognitiveStoreError::AccessDenied(_))));
    }
    let mut wrong_scope = request.clone();
    wrong_scope.scope = key("scope:forged");
    let mut wrong_entity = request.clone();
    wrong_entity.entity_key = key(WORKFLOW);
    let mut wrong_workflow = request.clone();
    wrong_workflow.workflow_key = key(ENTITY);
    for rejected in [wrong_scope, wrong_entity, wrong_workflow] {
        assert!(fixture.admit(&snapshot, &rejected, &claim, OBSERVED).await.is_err());
    }
    let mut wrong_generation = claim.clone();
    wrong_generation.generation = ContractGenerationV1::new(2).expect("generation");
    let mut wrong_bundle = claim.clone();
    wrong_bundle.snapshot_digest = digest(b"different-bundle");
    let mut wrong_query = claim.clone();
    wrong_query.query_id = key("query:different");
    for rejected in [wrong_generation, wrong_bundle, wrong_query] {
        assert!(matches!(fixture.admit(&snapshot, &request, &rejected, OBSERVED).await,
            Err(CognitiveStoreError::Conflict(_))));
    }
}

#[tokio::test]
async fn execution_budget_and_forged_terminal_values_cannot_pass_owner_admission() {
    let fixture = Fixture::new().await;
    let snapshot = fixture.snapshot(OBSERVED).await;
    let request = request(&snapshot);
    let claim = apply_claim(&snapshot, &request);
    let mut too_few_cells = request.clone();
    too_few_cells.max_cells = 3;
    let mut too_few_hops = request.clone();
    too_few_hops.max_hops = 2;
    let mut too_few_steps = request.clone();
    too_few_steps.max_steps = 3;
    for rejected in [too_few_cells, too_few_hops, too_few_steps] {
        assert!(fixture.admit(&snapshot, &rejected, &claim, OBSERVED).await.is_err());
    }
    for value in [
        json!({"status":"completed","value":9,"trace":[]}),
        json!({"status":"completed","value":999,"trace":[{"op":"stop","before":9,"after":999}]}),
        json!({"status":"completed","value":999,"trace":[{"op":"keep","before":9,"after":999},
            {"op":"stop","before":999,"after":999}]}),
        json!({"status":"completed","value":999,"trace":[{"op":"halve","before":9,"after":999},
            {"op":"stop","before":999,"after":999}]}),
    ] {
        let mut forged = claim.clone();
        forged.value = value;
        assert!(fixture.admit(&snapshot, &request, &forged, OBSERVED).await.is_err());
    }
}
