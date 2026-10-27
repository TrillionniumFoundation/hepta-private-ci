//! These signed single-catalog fixtures verify product execution and final use.
//! The explicit trusted resolver seam is not natural-language quality evidence.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::MemoryCellOwnerSnapshotV1;
use codex_hepta_cognitive_store::MemoryCellRecordV1;
use codex_hepta_cognitive_store::MemoryCellWriteModeV1;
use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryPredictionKindV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use crate::AgentdMemoryCellRuntimeV1;
use crate::MemoryCellAddressResolverV1;
use crate::MemoryCellResolvedAddressV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_release::test_support::single_value_model;
use crate::memory_cell_test_support::ControlFixture;
use crate::memory_cell_test_support::record;
use crate::memory_cell_test_support::request;

#[derive(Clone)]
pub(crate) enum TestRoute {
    Read(MemoryOperationV1),
    Decline,
    SubstituteEntity,
    Correct { record: MemoryCellRecordV1, operation: MemoryOperationV1 },
    Hang,
}

pub(crate) struct TrustedTestResolver {
    store: Arc<DurableCognitiveStore>,
    route: Mutex<TestRoute>,
}

impl TrustedTestResolver {
    pub(crate) fn new(fixture: &ControlFixture) -> Arc<Self> {
        Arc::new(Self { store: Arc::clone(&fixture.store), route: Mutex::new(TestRoute::Read(MemoryOperationV1::Apply)) })
    }

    pub(crate) fn set(&self, route: TestRoute) { *self.route.lock().unwrap() = route; }
}

impl MemoryCellAddressResolverV1 for TrustedTestResolver {
    fn model_digest(&self) -> ContractDigestV1 {
        ContractDigestV1::from_digest(Digest32::of_bytes(b"explicit-test-resolver-no-language-claim")).unwrap()
    }

    fn resolve<'a>(&'a self, request: &'a MemoryRequestV1, snapshot: &'a MemoryCellOwnerSnapshotV1)
    -> Pin<Box<dyn Future<Output = Result<Option<MemoryCellResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move {
            let route = self.route.lock().unwrap().clone();
            let mut request = request.clone();
            let operation = match route {
                TestRoute::Read(operation) => operation,
                TestRoute::Decline => return Ok(None),
                TestRoute::SubstituteEntity => {
                    request.entity = ContractIdV1::new("entity:resolver-substitution").unwrap();
                    MemoryOperationV1::Semantic
                }
                TestRoute::Correct { record, operation } => {
                    self.set(TestRoute::Read(operation));
                    let access = CognitiveAccess::agent_private(self.store.owner_agent_id().clone());
                    self.store.write_memory_cell(&access, &CognitiveScope::AgentPrivate, &record,
                        MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.map_err(|error| error.to_string())?;
                    operation
                }
                TestRoute::Hang => return std::future::pending().await,
            };
            Ok(Some(MemoryCellResolvedAddressV1 { request, operation,
                owner_cut_digest: snapshot.owner_cut_digest(), model_digest: self.model_digest() }))
        })
    }
}

pub(crate) fn attach(fixture: &ControlFixture, release: &ReleaseFixture, resolver: &Arc<TrustedTestResolver>) -> Arc<AgentdMemoryCellRuntimeV1> {
    let resolver: Arc<dyn MemoryCellAddressResolverV1> = resolver.clone();
    let runtime = Arc::new(AgentdMemoryCellRuntimeV1::new(fixture.state.identity().agent_id.clone(),
        /*spawn_generation*/ 1, CognitiveScope::AgentPrivate, Arc::clone(&release.host), resolver).unwrap());
    fixture.state.attach_memory_cells(Arc::clone(&runtime)).unwrap();
    fixture.ready();
    runtime
}

fn assert_empty(readout: &MemoryReadoutV1, expected: MemoryReadStatusV1) {
    assert_eq!((readout.status, &readout.value, &readout.source_ids, &readout.cell_digests, readout.prediction_kind),
        (expected, &Value::Null, &Vec::new(), &Vec::new(), MemoryPredictionKindV1::None));
    assert!(readout.reason.is_some());
}

#[tokio::test]
async fn cell_control_executes_six_operations_through_real_publication_and_native_parameters() {
    let fixture = ControlFixture::new().await;
    let snapshot = fixture.snapshot().await;
    let release = ReleaseFixture::new(&snapshot);
    let resolver = TrustedTestResolver::new(&fixture);
    let _runtime = attach(&fixture, &release, &resolver);
    let request = request(snapshot.scope().clone());
    let cases = [
        (MemoryOperationV1::Current, json!(9), MemoryPredictionKindV1::SourceEvidence, 1, 0, 1),
        (MemoryOperationV1::History, json!(4), MemoryPredictionKindV1::SourceEvidence, 1, 0, 1),
        (MemoryOperationV1::Change, json!(5), MemoryPredictionKindV1::SourceEvidence, 2, 0, 2),
        (MemoryOperationV1::Semantic, json!({"factor": 3, "label": "owner semantic"}), MemoryPredictionKindV1::ModelPrediction, 1, 1, 1),
        (MemoryOperationV1::Procedure, json!({"opcode": "affine", "bias": 2, "limit": 1000}), MemoryPredictionKindV1::ModelPrediction, 1, 1, 1),
        (MemoryOperationV1::Apply, json!(29), MemoryPredictionKindV1::Mixed, 3, 2, 3),
    ];
    for (operation, value, kind, sources, cells, hops) in cases {
        resolver.set(TestRoute::Read(operation));
        let result = fixture.client.memory_cell_read(request.clone()).await.unwrap();
        assert_eq!((result.status, result.operation, result.value, result.prediction_kind, result.source_ids.len(), result.cell_digests.len(), result.hops),
            (MemoryReadStatusV1::Ok, Some(operation), value, kind, sources, cells, hops));
    }
    let mut budget = request.clone(); budget.max_cells = 2;
    assert_empty(&fixture.client.memory_cell_read(budget).await.unwrap(), MemoryReadStatusV1::BudgetExceeded);
    resolver.set(TestRoute::Decline);
    assert_empty(&fixture.client.memory_cell_read(request.clone()).await.unwrap(), MemoryReadStatusV1::Abstain);
    resolver.set(TestRoute::SubstituteEntity);
    assert_empty(&fixture.client.memory_cell_read(request.clone()).await.unwrap(), MemoryReadStatusV1::Unavailable);
    resolver.set(TestRoute::Read(MemoryOperationV1::Semantic));
    let mut wrong_scope = request.clone(); wrong_scope.scope = ContractIdV1::new("scope:wrong").unwrap();
    assert_empty(&fixture.client.memory_cell_read(wrong_scope).await.unwrap(), MemoryReadStatusV1::Abstain);
    let mut outside = request; outside.entity = ContractIdV1::new("entity:unwritten").unwrap();
    assert_empty(&fixture.client.memory_cell_read(outside).await.unwrap(), MemoryReadStatusV1::Abstain);
    fixture.finish().await;
}

#[tokio::test]
async fn parameter_output_is_used_as_prediction_and_never_replaced_with_owner_values() {
    let fixture = ControlFixture::new().await;
    let snapshot = fixture.snapshot().await;
    let mut semantic: Value = serde_json::from_slice(&single_value_model(&snapshot, MemoryCellKindV1::Semantic)).unwrap();
    semantic["catalog"][0] = json!({"factor": 7, "label": "deliberately different model output"});
    let release = ReleaseFixture::from_models(&snapshot, &serde_json::to_vec(&semantic).unwrap(),
        &single_value_model(&snapshot, MemoryCellKindV1::Procedure));
    let resolver = TrustedTestResolver::new(&fixture);
    let _runtime = attach(&fixture, &release, &resolver);
    let request = request(snapshot.scope().clone());
    let result = fixture.client.memory_cell_read(request.clone()).await.unwrap();
    assert_eq!((result.status, result.value, result.prediction_kind), (MemoryReadStatusV1::Ok, json!(65), MemoryPredictionKindV1::Mixed));
    resolver.set(TestRoute::Read(MemoryOperationV1::Semantic));
    let predicted = fixture.client.memory_cell_read(request).await.unwrap();
    assert_eq!((predicted.value, predicted.prediction_kind), (semantic["catalog"][0].clone(), MemoryPredictionKindV1::ModelPrediction));
    fixture.finish().await;
}

#[tokio::test]
async fn final_use_source_change_clears_prediction_and_real_successor_publication_restores_reading() {
    let fixture = ControlFixture::new().await;
    let snapshot = fixture.snapshot().await;
    let release = ReleaseFixture::new(&snapshot);
    let resolver = TrustedTestResolver::new(&fixture);
    let _runtime = attach(&fixture, &release, &resolver);
    let request = request(snapshot.scope().clone());
    resolver.set(TestRoute::Correct {
        record: record(MemoryCellKindV1::Semantic, /*effective_at*/ 20, json!({"factor": 5, "label": "corrected"})),
        operation: MemoryOperationV1::Apply,
    });
    assert_empty(&fixture.client.memory_cell_read(request.clone()).await.unwrap(), MemoryReadStatusV1::Stale);
    assert_empty(&fixture.client.memory_cell_read(request.clone()).await.unwrap(), MemoryReadStatusV1::Stale);
    let fresh = fixture.snapshot().await;
    let successor = release.prepare(&fresh, /*generation*/ 2);
    release.host.publish(successor.clone(), &fresh).unwrap();
    assert!(fixture.client.memory_cell_read(request.clone()).await.is_err());
    release.install(&successor).unwrap();
    let result = fixture.client.memory_cell_read(request).await.unwrap();
    assert_eq!((result.status, result.value, result.generation.get()), (MemoryReadStatusV1::Ok, json!(47), 2));
    fixture.finish().await;
}

#[tokio::test]
async fn unqueried_training_source_correction_invalidates_the_entire_model() {
    let fixture = ControlFixture::new().await;
    let mut other = record(MemoryCellKindV1::Semantic, /*effective_at*/ 20, json!({"factor": 3, "label": "owner semantic"}));
    other.entity = ContractIdV1::new("meter:another-training-entity").unwrap();
    fixture.store.write_memory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &other, MemoryCellWriteModeV1::Create).await.unwrap();
    let snapshot = fixture.snapshot().await;
    let release = ReleaseFixture::new(&snapshot);
    let resolver = TrustedTestResolver::new(&fixture);
    let _runtime = attach(&fixture, &release, &resolver);
    other.value = json!({"factor": 8, "label": "other correction"});
    resolver.set(TestRoute::Correct { record: other, operation: MemoryOperationV1::Semantic });
    assert_empty(&fixture.client.memory_cell_read(request(snapshot.scope().clone())).await.unwrap(), MemoryReadStatusV1::Stale);
    fixture.finish().await;
}

#[tokio::test]
async fn partial_composition_and_unbounded_resolver_never_escape_as_values() {
    let fixture = ControlFixture::new().await;
    let snapshot = fixture.snapshot().await;
    let mut semantic: Value = serde_json::from_slice(&single_value_model(&snapshot, MemoryCellKindV1::Semantic)).unwrap();
    semantic["acceptance_enabled"] = json!(false);
    let release = ReleaseFixture::from_models(&snapshot, &serde_json::to_vec(&semantic).unwrap(),
        &single_value_model(&snapshot, MemoryCellKindV1::Procedure));
    let resolver = TrustedTestResolver::new(&fixture);
    let runtime = attach(&fixture, &release, &resolver);
    let request = request(snapshot.scope().clone());
    assert_empty(&fixture.client.memory_cell_read(request.clone()).await.unwrap(), MemoryReadStatusV1::Abstain);
    resolver.set(TestRoute::Hang);
    // Test the runtime deadline directly: the control transport has a stricter
    // existing two-second I/O bound and cancels its request even earlier.
    let deadline = runtime.read(&fixture.store, &request).await.unwrap();
    assert_empty(&deadline, MemoryReadStatusV1::Unavailable);
    assert_eq!(deadline.reason.as_deref(), Some("memory cell read deadline exceeded"));
    fixture.finish().await;
}
