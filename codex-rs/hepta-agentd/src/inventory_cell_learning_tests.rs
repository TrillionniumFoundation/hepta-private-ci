//! Explicit qualification: canonical correction, original TensorCell training,
//! native publication/reselection and retained reads. Ordinary CI skips this
//! environment-dependent experiment instead of claiming a training success.

use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::path::Path;
use std::io::Write;
use codex_hepta_cognitive_types::{InventoryCellKindV1, InventoryCellRequestV1, InventoryCellRouteV1, MemoryOperationV1, MemoryReadStatusV1};
use codex_hepta_cognitive_types::hnmf::{ContractDigestV1, ContractGenerationV1, ContractIdV1};
use codex_hepta_memory::{CognitiveScope, InventoryCellOwnerSnapshotV1, MemoryCellWriteModeV1};
use codex_hepta_types::Digest32;
use serde_json::{Value, json};
use crate::{AgentdInventoryCellRuntimeV1, InventoryCellAddressResolverV1, InventoryCellBundleCandidateV1, InventoryCellResolvedAddressV1};
use crate::inventory_cell_test_support::{InventoryReleaseFixture, OriginalData, key, request, snapshot};
use crate::memory_cell_release::test_support::{fixture_manifest_template, prepare_bound_request};
use crate::memory_cell_test_support::ControlFixture;

struct PolicyResolver(Mutex<ContractIdV1>);
impl InventoryCellAddressResolverV1 for PolicyResolver {
    fn model_digest(&self) -> ContractDigestV1 { ContractDigestV1::from_digest(Digest32::of_bytes(b"owner-learning-qualification-no-language-claim")).unwrap() }
    fn resolve<'a>(&'a self, request: &'a InventoryCellRequestV1, owner: &'a InventoryCellOwnerSnapshotV1) -> Pin<Box<dyn Future<Output = Result<Option<InventoryCellResolvedAddressV1>, String>> + Send + 'a>> {
        Box::pin(async move { Ok(Some(InventoryCellResolvedAddressV1 { request: request.clone(),
            route: InventoryCellRouteV1 { operation: MemoryOperationV1::Semantic, entity: Some(self.0.lock().unwrap().clone()), workflow: None },
            owner_cut_digest: owner.owner_cut_digest(), model_digest: self.model_digest() })) })
    }
}
fn evidence(root: &Path, name: &str, value: &Value) {
    let mut file = std::fs::OpenOptions::new().write(true).create_new(true).open(root.join(name)).unwrap();
    file.write_all(&serde_json::to_vec(value).unwrap()).unwrap(); file.sync_all().unwrap();
}

#[tokio::test]
#[ignore = "requires explicit HEPTA_NATIVE_INVENTORY_PYTHON and a new evidence directory"]
async fn inventory_native_retraining_owner_cycle() {
    let python = std::env::var_os("HEPTA_NATIVE_INVENTORY_PYTHON").expect("pinned Torch interpreter");
    let root = std::path::PathBuf::from(std::env::var_os("HEPTA_NATIVE_INVENTORY_EVIDENCE_DIR").expect("new evidence directory"));
    std::fs::create_dir(&root).expect("create a fresh evidence directory, never overwrite prior results");
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read(); data.import(&fixture).await;
    let before = snapshot(&fixture).await;
    evidence(&root, "owner-before.json", &serde_json::to_value(&before).unwrap());
    let release = InventoryReleaseFixture::new(&before, &data);
    let resolver = Arc::new(PolicyResolver(Mutex::new(key("entity", 0))));
    let configured: Arc<dyn InventoryCellAddressResolverV1> = resolver.clone();
    let runtime = Arc::new(AgentdInventoryCellRuntimeV1::new(fixture.state.identity().agent_id.clone(), 1, CognitiveScope::AgentPrivate, Arc::clone(&release.host), configured).unwrap());
    fixture.state.attach_inventory_cells(runtime).unwrap(); fixture.ready();
    let initial = fixture.client.inventory_cell_read(request(&before)).await.unwrap();
    assert_eq!(initial.result.value, json!({"reserve": 11, "pack": 3, "limit": 14}));
    let mut changed = before.current(&key("entity", 0), InventoryCellKindV1::Semantic).unwrap().record.clone();
    changed.value = json!({"reserve": 2, "pack": 5, "limit": 9});
    fixture.store.write_inventory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &changed, MemoryCellWriteModeV1::Correct { expected_revision: 1 }).await.unwrap();
    let after = snapshot(&fixture).await;
    evidence(&root, "owner-after.json", &serde_json::to_value(&after).unwrap());
    let stale = fixture.client.inventory_cell_read(request(&after)).await.unwrap();
    assert_eq!(stale.result.status, MemoryReadStatusV1::Stale); assert!(stale.result.value.is_null());
    let original: Value = serde_json::from_str(&data.semantic_json).unwrap();
    let features: Vec<_> = data.bindings.iter().map(|row| json!({"kind": row.kind, "key": row.key, "features": row.features})).collect();
    evidence(&root, "training-input.json", &json!({"schema": "hepta.memory.inventory-training-input.v1", "owner_snapshot": after,
        "encoder_sha256": original["encoder_sha256"], "feature_rows": features}));
    let training = root.join("training");
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../qualification/memory-cell-adapters/train_native_inventory.py");
    let training_code_digest = Digest32::of_bytes(&std::fs::read(&script).unwrap());
    let process = tokio::process::Command::new(python).arg(&script).arg("--input").arg(root.join("training-input.json")).arg("--output").arg(&training).output().await.unwrap();
    evidence(&root, "trainer-process.json", &json!({"exit_code": process.status.code(), "stdout": String::from_utf8_lossy(&process.stdout), "stderr": String::from_utf8_lossy(&process.stderr)}));
    assert!(process.status.success(), "canonical trainer failed; inspect preserved process evidence");
    let report: Value = serde_json::from_slice(&std::fs::read(training.join("training-result.json")).unwrap()).unwrap();
    assert_eq!(report["correct"], json!(8));
    let semantic = std::fs::read(training.join("semantic.native.json")).unwrap();
    let mut bindings = data.bindings(&after);
    for binding in &mut bindings { if binding.kind == InventoryCellKindV1::Semantic { binding.training_source = binding.owner_source; } }
    let candidate = InventoryCellBundleCandidateV1::from_owner_snapshot(&after, ContractGenerationV1::new(2).unwrap(), &semantic, data.skill_json.as_bytes(), bindings).unwrap();
    let mut template = fixture_manifest_template(&release.config, 2, training_code_digest);
    template.device_profile_digest = Digest32::of_bytes(b"test-cpu-f32-factored");
    let manifest = candidate.bind_manifest(template).unwrap();
    let successor = prepare_bound_request(&release.service, &release.config, manifest, candidate.bytes().to_vec(), 2);
    release.host.publish(successor.clone(), &after).unwrap();
    assert!(fixture.client.inventory_cell_read(request(&after)).await.is_err(), "publication cannot select itself");
    release.install(&release.host, &successor).unwrap();
    let mut reads = Vec::new();
    for index in 0..8 {
        *resolver.0.lock().unwrap() = key("entity", index);
        let read = fixture.client.inventory_cell_read(request(&after)).await.unwrap();
        assert_eq!(read.result.status, MemoryReadStatusV1::Ok);
        assert_eq!(read.result.generation.get(), 2);
        assert_eq!(read.result.value, after.current(&key("entity", index), InventoryCellKindV1::Semantic).unwrap().record.value);
        reads.push(read);
    }
    fixture.store.forget_inventory_cell(&fixture.access(), &CognitiveScope::AgentPrivate, &changed.address(), 2, "explicit qualification withdrawal", crate::memory_cell_runtime::now_unix_seconds().unwrap()).await.unwrap();
    let withdrawn = fixture.client.inventory_cell_read(request(&after)).await.unwrap();
    assert_eq!(withdrawn.result.status, MemoryReadStatusV1::Stale); assert!(withdrawn.result.value.is_null());
    evidence(&root, "RESULT.json", &json!({"schema": "hepta.memory.native-owner-learning-cycle.v1", "before_cut": before.owner_cut_digest(), "after_cut": after.owner_cut_digest(),
        "original_parameter_sha256": original["parameter_sha256"], "trained": report, "generation": 2, "bundle_digest": candidate.digest(), "retained_and_corrected_reads": reads,
        "corrected_rows": 1, "retained_rows": 7, "selection_required_after_publication": true, "withdrawal_readout": withdrawn}));
    fixture.finish().await;
}
