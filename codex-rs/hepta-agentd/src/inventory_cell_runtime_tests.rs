use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellReadoutV1, InventoryCellRequestV1, InventoryCellRouteV1, InventoryPolicyV1, InventoryProgramV1, MemoryOperationV1, MemoryPredictionKindV1, MemoryReadStatusV1, execute_inventory_program_v1};
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_fleet::{AgentLifecycle, FleetRegistry};
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_memory::{CognitiveAccess, CognitiveScope, InventoryCellOwnerSnapshotV1, InventoryCellRecordV1, MemoryCellWriteModeV1};
use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use crate::{AgentdInventoryCellRuntimeV1, InventoryCellAddressResolverV1, InventoryCellReleaseHostV1, InventoryCellResolvedAddressV1};
use crate::inventory_cell_test_support::{InventoryReleaseFixture, OriginalData, key, request, snapshot};
use crate::memory_cell_release::test_support::selection_trust;
use crate::memory_cell_test_support::ControlFixture;

#[derive(Clone)]
enum RouteAction { Read, Decline, SubstituteRequest, Correct(InventoryCellRecordV1), Drain }
struct Resolver {
    store: Arc<DurableCognitiveStore>, registry: FleetRegistry,
    choice: Mutex<(RouteAction, InventoryCellRouteV1)>,
}
impl Resolver {
    fn set(&self, operation: MemoryOperationV1, entity: usize, workflow: usize) {
        let mut route = InventoryCellRouteV1 { operation, entity: Some(key("entity", entity)), workflow: None };
        if matches!(operation, MemoryOperationV1::Procedure | MemoryOperationV1::Apply) { route.workflow = Some(key("workflow", workflow)); }
        if operation == MemoryOperationV1::Procedure { route.entity = None; }
        *self.choice.lock().unwrap() = (RouteAction::Read, route);
    }
    fn action(&self, action: RouteAction) { self.choice.lock().unwrap().0 = action; }
}
impl InventoryCellAddressResolverV1 for Resolver {
    fn model_digest(&self) -> ContractDigestV1 { ContractDigestV1::from_digest(Digest32::of_bytes(b"test-resolver-no-language-claim")).unwrap() }
    fn resolve<'a>(&'a self, request: &'a InventoryCellRequestV1, snapshot: &'a InventoryCellOwnerSnapshotV1) -> Pin<Box<dyn Future<Output = Result<Option<InventoryCellResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            let (action, route) = self.choice.lock().unwrap().clone();
            let mut request = request.clone();
            match action {
                RouteAction::Decline => return Ok(None),
                RouteAction::SubstituteRequest => request.text.push_str(" changed"),
                RouteAction::Correct(record) => {
                    self.action(RouteAction::Read);
                    self.store.write_inventory_cell(&CognitiveAccess::agent_private(self.store.owner_agent_id().clone()), &CognitiveScope::AgentPrivate, &record, MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.map_err(|error| error.to_string())?;
                }
                RouteAction::Drain => { self.registry.compare_and_transition(self.store.owner_agent_id(), 2, AgentLifecycle::Draining).map_err(|error| error.to_string())?; }
                RouteAction::Read => {}
            }
            Ok(Some(InventoryCellResolvedAddressV1 { request, route, owner_cut_digest: snapshot.owner_cut_digest(), model_digest: self.model_digest() }))
        })
    }
}
fn attach(fixture: &ControlFixture, release: &InventoryReleaseFixture) -> Arc<Resolver> {
    let resolver = Arc::new(Resolver { store: Arc::clone(&fixture.store), registry: fixture.registry.clone(), choice: Mutex::new((RouteAction::Read, InventoryCellRouteV1 { operation: MemoryOperationV1::Apply, entity: Some(key("entity", 0)), workflow: Some(key("workflow", 3)) })) });
    let configured: Arc<dyn InventoryCellAddressResolverV1> = resolver.clone();
    let runtime = Arc::new(AgentdInventoryCellRuntimeV1::new(fixture.state.identity().agent_id.clone(), 1, CognitiveScope::AgentPrivate, Arc::clone(&release.host), configured).unwrap());
    fixture.state.attach_inventory_cells(runtime).unwrap(); fixture.ready(); resolver
}
fn empty(readout: &InventoryCellReadoutV1, status: MemoryReadStatusV1) {
    assert_eq!(readout.result.status, status);
    assert_eq!(readout.result.value, Value::Null);
    assert!(readout.result.source_ids.is_empty() && readout.result.cell_digests.is_empty() && readout.route.is_none());
    assert_eq!(readout.result.prediction_kind, MemoryPredictionKindV1::None);
}

#[tokio::test]
async fn inventory_original_trained_parameters_execute_through_signed_agentd_control() {
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read(); data.import(&fixture).await;
    let owner = snapshot(&fixture).await;
    let release = InventoryReleaseFixture::new(&owner, &data);
    let resolver = attach(&fixture, &release);
    let request = request(&owner);
    for index in 0..8 {
        for (operation, kind, name) in [(MemoryOperationV1::Semantic, InventoryCellKindV1::Semantic, "entity"), (MemoryOperationV1::Procedure, InventoryCellKindV1::Skill, "workflow")] {
            resolver.set(operation, index, index);
            let read = fixture.client.inventory_cell_read(request.clone()).await.unwrap();
            assert_eq!(read.result.status, MemoryReadStatusV1::Ok);
            assert_eq!(read.result.value, owner.current(&key(name, index), kind).unwrap().record.value);
            assert_eq!(read.result.prediction_kind, MemoryPredictionKindV1::ModelPrediction);
        }
    }
    for entity in 0..7 {
        for workflow in 0..8 {
            resolver.set(MemoryOperationV1::Apply, entity, workflow);
            let policy: InventoryPolicyV1 = serde_json::from_value(owner.current(&key("entity", entity), InventoryCellKindV1::Semantic).unwrap().record.value.clone()).unwrap();
            let program: InventoryProgramV1 = serde_json::from_value(owner.current(&key("workflow", workflow), InventoryCellKindV1::Skill).unwrap().record.value.clone()).unwrap();
            let event = owner.current(&key("entity", entity), InventoryCellKindV1::Event).unwrap().record.value.as_i64().unwrap();
            let expected = execute_inventory_program_v1(event, &policy, &program, 4).unwrap();
            let read = fixture.client.inventory_cell_read(request.clone()).await.unwrap();
            assert_eq!((read.result.status, read.result.value), (MemoryReadStatusV1::Ok, json!(expected)));
            assert_eq!(read.result.prediction_kind, MemoryPredictionKindV1::Mixed);
            assert_eq!((read.result.source_ids.len(), read.result.cell_digests.len()), (3, 2));
            assert_eq!(read.route.unwrap().workflow, Some(key("workflow", workflow)));
        }
    }
    for (operation, value) in [(MemoryOperationV1::Current, 5), (MemoryOperationV1::History, 0), (MemoryOperationV1::Change, 5)] {
        resolver.set(operation, 0, 0);
        let read = fixture.client.inventory_cell_read(request.clone()).await.unwrap();
        assert_eq!(read.result.value, json!(value));
        assert_eq!(read.result.prediction_kind, MemoryPredictionKindV1::SourceEvidence);
    }
    resolver.set(MemoryOperationV1::Apply, 7, 3);
    empty(&fixture.client.inventory_cell_read(request.clone()).await.unwrap(), MemoryReadStatusV1::Abstain);
    resolver.set(MemoryOperationV1::Apply, 0, 3);
    let mut short = request.clone(); short.max_steps = 3;
    empty(&fixture.client.inventory_cell_read(short).await.unwrap(), MemoryReadStatusV1::BudgetExceeded);
    let mut short = request.clone(); short.max_cells = 2;
    empty(&fixture.client.inventory_cell_read(short).await.unwrap(), MemoryReadStatusV1::BudgetExceeded);
    resolver.action(RouteAction::Decline);
    empty(&fixture.client.inventory_cell_read(request.clone()).await.unwrap(), MemoryReadStatusV1::Abstain);
    resolver.action(RouteAction::SubstituteRequest);
    empty(&fixture.client.inventory_cell_read(request).await.unwrap(), MemoryReadStatusV1::Unavailable);
    fixture.finish().await;
}

#[tokio::test]
async fn inventory_original_import_cannot_rebind_after_correction_or_leak_partial_read() {
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read(); data.import(&fixture).await;
    let owner = snapshot(&fixture).await;
    let release = InventoryReleaseFixture::new(&owner, &data);
    let resolver = attach(&fixture, &release);
    let mut corrected = owner.current(&key("entity", 5), InventoryCellKindV1::Semantic).unwrap().record.clone();
    corrected.value = json!({"reserve": 1, "pack": 1, "limit": 1});
    resolver.set(MemoryOperationV1::Apply, 0, 3);
    resolver.action(RouteAction::Correct(corrected));
    empty(&fixture.client.inventory_cell_read(request(&owner)).await.unwrap(), MemoryReadStatusV1::Stale);
    let after = snapshot(&fixture).await;
    assert!(data.candidate(&after, 2).is_err(), "old authored parameter lineage cannot be rebound to revision 2");
    empty(&fixture.client.inventory_cell_read(request(&after)).await.unwrap(), MemoryReadStatusV1::Stale);
    fixture.finish().await;
}

#[tokio::test]
async fn inventory_readout_uses_parameter_values_even_when_owner_fact_is_different() {
    let fixture = ControlFixture::new().await;
    let mut data = OriginalData::read(); data.import(&fixture).await;
    let owner = snapshot(&fixture).await;
    // Deliberately synthetic, signed integration perturbation: remove the head
    // weights and force all semantic bits to zero. This is not accuracy evidence.
    let mut model: Value = serde_json::from_str(&data.semantic_json).unwrap();
    let head_hex = model["tensors"]["head.weight"]["f32le_hex"].as_str().unwrap();
    model["tensors"]["head.weight"]["f32le_hex"] = json!("0".repeat(head_hex.len()));
    model["tensors"]["head.bias"]["f32le_hex"] = json!("0000c8c2".repeat(12));
    let mut bytes = Vec::new();
    for name in ["A", "B", "head.bias", "head.weight"] {
        bytes.extend(serde_json::to_vec(&json!([name, model["tensors"][name]["shape"], "float32"])).unwrap());
        for pair in model["tensors"][name]["f32le_hex"].as_str().unwrap().as_bytes().chunks_exact(2) {
            bytes.push(u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap());
        }
    }
    model["parameter_sha256"] = json!(Digest32::of_bytes(&bytes).to_string());
    for field in ["checkpoint_manifest_sha256", "training_history_sha256"] {
        model[field] = json!(Digest32::of_bytes(b"synthetic-integration-perturbation-not-original-training").to_string());
    }
    data.semantic_json = serde_json::to_string(&model).unwrap();
    let release = InventoryReleaseFixture::new(&owner, &data);
    let resolver = attach(&fixture, &release);
    resolver.set(MemoryOperationV1::Semantic, 0, 3);
    let read = fixture.client.inventory_cell_read(request(&owner)).await.unwrap();
    assert_eq!(read.result.value, json!({"reserve": 0, "pack": 0, "limit": 0}));
    assert_ne!(read.result.value, owner.current(&key("entity", 0), InventoryCellKindV1::Semantic).unwrap().record.value);
    assert_eq!(read.result.prediction_kind, MemoryPredictionKindV1::ModelPrediction);
    resolver.set(MemoryOperationV1::Apply, 0, 3);
    assert_eq!(fixture.client.inventory_cell_read(request(&owner)).await.unwrap().result.value, json!(0));
    fixture.finish().await;
}

#[tokio::test]
async fn inventory_release_restart_requires_selection_and_control_rechecks_lifecycle_after_read() {
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read(); data.import(&fixture).await;
    let owner = snapshot(&fixture).await;
    let release = InventoryReleaseFixture::new(&owner, &data);
    let fresh = InventoryCellReleaseHostV1::new(Arc::clone(&release.service), ArtifactSelectionVerifierV1::new(selection_trust(&release.config), &release.config.trust).unwrap());
    assert!(fresh.load_current().is_err());
    release.install(&fresh, &release.initial_request).unwrap();
    assert_eq!(fresh.load_current().unwrap().bundle_digest(), release.host.load_current().unwrap().bundle_digest());
    let resolver = attach(&fixture, &release);
    let first = fixture.client.inventory_cell_snapshot(None, None, 2).await.unwrap();
    assert_eq!(first.owner_cut_digest, owner.owner_cut_digest());
    assert!(first.next_after.is_some());
    assert!(fixture.client.inventory_cell_snapshot(first.next_after, None, 2).await.is_err());
    resolver.action(RouteAction::Drain);
    assert!(fixture.client.inventory_cell_read(request(&owner)).await.is_err(), "post-read lifecycle fence must discard even a numerically valid result");
    assert!(fixture.client.inventory_cell_snapshot(None, None, 2).await.is_err());
    fixture.finish().await;
}

#[tokio::test]
async fn inventory_exact_event_and_hold_changes_do_not_republish_unchanged_parameters() {
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read(); data.import(&fixture).await;
    let owner = snapshot(&fixture).await;
    let release = InventoryReleaseFixture::new(&owner, &data);
    let resolver = attach(&fixture, &release);
    let bundle = release.host.load_current().unwrap().bundle_digest();
    let mut changed = owner.current(&key("entity", 0), InventoryCellKindV1::Event).unwrap().record.clone();
    changed.value = json!(9);
    fixture.store.write_inventory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &changed, MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.unwrap();
    let event_cut = snapshot(&fixture).await;
    assert_ne!(event_cut.owner_cut_digest(), owner.owner_cut_digest());
    assert_eq!(event_cut.parameter_training_cut_digest().unwrap(), owner.parameter_training_cut_digest().unwrap());
    resolver.set(MemoryOperationV1::Apply, 0, 3);
    let read = fixture.client.inventory_cell_read(request(&event_cut)).await.unwrap();
    assert_eq!((read.result.status, read.result.value, read.result.generation.get()), (MemoryReadStatusV1::Ok, json!(14), 1));
    assert_eq!(read.result.snapshot_digest, bundle);
    let hold = InventoryCellRecordV1 { schema: "hepta.memory.inventory-cell-record.v1".to_string(), key: key("entity", 0), kind: InventoryCellKindV1::Hold, effective_at: 21, value: json!({"reason":"explicit owner hold"}), training_origin: None };
    fixture.store.write_inventory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &hold, MemoryCellWriteModeV1::Create).await.unwrap();
    let held = fixture.client.inventory_cell_read(request(&event_cut)).await.unwrap();
    empty(&held, MemoryReadStatusV1::Abstain);
    assert_eq!(held.result.reason.as_deref(), Some("exact owner hold stops inventory composition"));
    fixture.store.forget_inventory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &hold.address(), 1, "owner explicitly cleared hold", crate::memory_cell_runtime::now_unix_seconds().unwrap()).await.unwrap();
    let resumed = fixture.client.inventory_cell_read(request(&event_cut)).await.unwrap();
    assert_eq!((resumed.result.status, resumed.result.value, resumed.result.generation.get()), (MemoryReadStatusV1::Ok, json!(14), 1));
    assert_eq!(resumed.result.snapshot_digest, bundle);
    fixture.finish().await;
}
