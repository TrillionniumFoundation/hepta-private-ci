//! Explicit qualification: canonical correction, original TensorCell training,
//! native publication/reselection and retained reads. Ordinary CI skips this
//! environment-dependent experiment instead of claiming a training success.

use crate::AgentdInventoryCellRuntimeV1;
use crate::InventoryCellAddressResolverV1;
use crate::InventoryCellBundleCandidateV1;
use crate::InventoryCellResolvedAddressV1;
use crate::inventory_cell_test_support::InventoryReleaseFixture;
use crate::inventory_cell_test_support::OriginalData;
use crate::inventory_cell_test_support::key;
use crate::inventory_cell_test_support::request;
use crate::inventory_cell_test_support::snapshot;
use crate::memory_cell_release::test_support::fixture_manifest_template;
use crate::memory_cell_release::test_support::prepare_bound_request;
use crate::memory_cell_test_support::ControlFixture;
use codex_hepta_cognitive_types::InventoryCellKindV1;
use codex_hepta_cognitive_types::InventoryCellRequestV1;
use codex_hepta_cognitive_types::InventoryCellRouteV1;
use codex_hepta_cognitive_types::MemoryOperationV1;
use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::InventoryCellOwnerSnapshotV1;
use codex_hepta_memory::MemoryCellWriteModeV1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;
use std::future::Future;
use std::io::Write;
use std::path::Path;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;

struct PolicyResolver(Mutex<(InventoryCellKindV1, ContractIdV1)>);
impl InventoryCellAddressResolverV1 for PolicyResolver {
    fn model_digest(&self) -> ContractDigestV1 {
        ContractDigestV1::from_digest(Digest32::of_bytes(
            b"owner-learning-qualification-no-language-claim",
        ))
        .unwrap()
    }
    fn resolve<'a>(
        &'a self,
        request: &'a InventoryCellRequestV1,
        owner: &'a InventoryCellOwnerSnapshotV1,
    ) -> Pin<
        Box<
            dyn Future<Output = Result<Option<InventoryCellResolvedAddressV1>, String>> + Send + 'a,
        >,
    > {
        Box::pin(async move {
            let (kind, key) = self.0.lock().unwrap().clone();
            let route = if kind == InventoryCellKindV1::Semantic {
                InventoryCellRouteV1 {
                    operation: MemoryOperationV1::Semantic,
                    entity: Some(key),
                    workflow: None,
                }
            } else {
                InventoryCellRouteV1 {
                    operation: MemoryOperationV1::Procedure,
                    entity: None,
                    workflow: Some(key),
                }
            };
            Ok(Some(InventoryCellResolvedAddressV1 {
                request: request.clone(),
                route,
                owner_cut_digest: owner.owner_cut_digest(),
                model_digest: self.model_digest(),
            }))
        })
    }
}
fn evidence(root: &Path, name: &str, value: &Value) {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(name))
        .unwrap();
    file.write_all(&serde_json::to_vec(value).unwrap()).unwrap();
    file.sync_all().unwrap();
}

#[tokio::test]
#[ignore = "requires explicit HEPTA_NATIVE_INVENTORY_PYTHON and a new evidence directory"]
async fn inventory_native_retraining_owner_cycle() {
    let python =
        std::env::var_os("HEPTA_NATIVE_INVENTORY_PYTHON").expect("pinned Torch interpreter");
    let root = std::path::PathBuf::from(
        std::env::var_os("HEPTA_NATIVE_INVENTORY_EVIDENCE_DIR").expect("new evidence directory"),
    );
    std::fs::create_dir(&root)
        .expect("create a fresh evidence directory, never overwrite prior results");
    for kind in [InventoryCellKindV1::Semantic, InventoryCellKindV1::Skill] {
        let name = if kind == InventoryCellKindV1::Semantic {
            "semantic"
        } else {
            "skill"
        };
        let directory = root.join(name);
        std::fs::create_dir(&directory).unwrap();
        owner_cycle(kind, &python, &directory).await;
    }
}

async fn owner_cycle(kind: InventoryCellKindV1, python: &std::ffi::OsStr, root: &Path) {
    let (cell_name, address_kind, other_kind, other_address) =
        if kind == InventoryCellKindV1::Semantic {
            ("semantic", "entity", InventoryCellKindV1::Skill, "workflow")
        } else {
            ("skill", "workflow", InventoryCellKindV1::Semantic, "entity")
        };
    let fixture = ControlFixture::new().await;
    let data = OriginalData::read();
    data.import(&fixture).await;
    let before = snapshot(&fixture).await;
    evidence(
        root,
        "owner-before.json",
        &serde_json::to_value(&before).unwrap(),
    );
    let release = InventoryReleaseFixture::new(&before, &data);
    let resolver = Arc::new(PolicyResolver(Mutex::new((kind, key(address_kind, 0)))));
    let configured: Arc<dyn InventoryCellAddressResolverV1> = resolver.clone();
    let runtime = Arc::new(
        AgentdInventoryCellRuntimeV1::new(
            fixture.state.identity().agent_id.clone(),
            1,
            CognitiveScope::AgentPrivate,
            Arc::clone(&release.host),
            configured,
        )
        .unwrap(),
    );
    fixture.state.attach_inventory_cells(runtime).unwrap();
    fixture.ready();
    let initial = fixture
        .client
        .inventory_cell_read(request(&before))
        .await
        .unwrap();
    assert_eq!(
        initial.result.value,
        before
            .current(&key(address_kind, 0), kind)
            .unwrap()
            .record
            .value
    );
    let retained_digest = release
        .host
        .load_current()
        .unwrap()
        .model(other_kind)
        .unwrap()
        .artifact_digest();
    let mut changed = before
        .current(&key(address_kind, 0), kind)
        .unwrap()
        .record
        .clone();
    changed.value = if kind == InventoryCellKindV1::Semantic {
        json!({"reserve": 2, "pack": 5, "limit": 9})
    } else {
        json!({"program":[4,5,3,6]})
    };
    fixture
        .store
        .write_inventory_cell(
            &fixture.access(),
            &CognitiveScope::AgentPrivate,
            &changed,
            MemoryCellWriteModeV1::Correct {
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
    let after = snapshot(&fixture).await;
    evidence(
        root,
        "owner-after.json",
        &serde_json::to_value(&after).unwrap(),
    );
    let stale = fixture
        .client
        .inventory_cell_read(request(&after))
        .await
        .unwrap();
    assert_eq!(stale.result.status, MemoryReadStatusV1::Stale);
    assert!(stale.result.value.is_null());
    *resolver.0.lock().unwrap() = (other_kind, key(other_address, 0));
    let unrelated = fixture
        .client
        .inventory_cell_read(request(&after))
        .await
        .unwrap();
    assert_eq!(unrelated.result.status, MemoryReadStatusV1::Ok);
    assert_eq!(
        unrelated.result.value,
        after
            .current(&key(other_address, 0), other_kind)
            .unwrap()
            .record
            .value
    );
    *resolver.0.lock().unwrap() = (kind, key(address_kind, 0));
    let original: Value = serde_json::from_str(if kind == InventoryCellKindV1::Semantic {
        &data.semantic_json
    } else {
        &data.skill_json
    })
    .unwrap();
    let features: Vec<_> = data
        .bindings
        .iter()
        .map(|row| json!({"kind": row.kind, "key": row.key, "features": row.features}))
        .collect();
    evidence(
        root,
        "training-input.json",
        &json!({"schema": "hepta.memory.inventory-training-input.v1", "owner_snapshot": after,
        "encoder_sha256": original["encoder_sha256"], "feature_rows": features}),
    );
    let training = root.join("training");
    let script = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../qualification/memory-cell-adapters/train_native_inventory.py");
    let training_code_digest = Digest32::of_bytes(&std::fs::read(&script).unwrap());
    let process = tokio::process::Command::new(python)
        .arg(&script)
        .arg("--input")
        .arg(root.join("training-input.json"))
        .arg("--output")
        .arg(&training)
        .arg("--kind")
        .arg(cell_name)
        .output()
        .await
        .unwrap();
    evidence(
        root,
        "trainer-process.json",
        &json!({"exit_code": process.status.code(), "stdout": String::from_utf8_lossy(&process.stdout), "stderr": String::from_utf8_lossy(&process.stderr)}),
    );
    assert!(
        process.status.success(),
        "canonical trainer failed; inspect preserved process evidence"
    );
    let report: Value =
        serde_json::from_slice(&std::fs::read(training.join("training-result.json")).unwrap())
            .unwrap();
    assert_eq!(report["correct"], json!(8));
    assert_eq!(
        report["cell_training_cut_digest"],
        json!(after.cell_training_cut_digest(kind).unwrap())
    );
    let trained = std::fs::read(training.join(format!("{cell_name}.native.json"))).unwrap();
    let mut bindings = data.bindings(&after);
    for binding in &mut bindings {
        if binding.kind == kind {
            binding.training_source = binding.owner_source;
        }
    }
    let (semantic, skill) = if kind == InventoryCellKindV1::Semantic {
        (trained.as_slice(), data.skill_json.as_bytes())
    } else {
        (data.semantic_json.as_bytes(), trained.as_slice())
    };
    let candidate = InventoryCellBundleCandidateV1::from_owner_snapshot(
        &after,
        ContractGenerationV1::new(2).unwrap(),
        semantic,
        skill,
        bindings,
    )
    .unwrap();
    let mut template = fixture_manifest_template(&release.config, 2, training_code_digest);
    template.device_profile_digest = Digest32::of_bytes(b"test-cpu-f32-factored");
    let manifest = candidate.bind_manifest(template).unwrap();
    let successor = prepare_bound_request(
        &release.service,
        &release.config,
        manifest,
        candidate.bytes().to_vec(),
        2,
    );
    release.host.publish(successor.clone(), &after).unwrap();
    assert!(
        fixture
            .client
            .inventory_cell_read(request(&after))
            .await
            .is_err(),
        "publication cannot select itself"
    );
    release.install(&release.host, &successor).unwrap();
    assert_eq!(
        release
            .host
            .load_current()
            .unwrap()
            .model(other_kind)
            .unwrap()
            .artifact_digest(),
        retained_digest
    );
    *resolver.0.lock().unwrap() = (other_kind, key(other_address, 0));
    let retained = fixture
        .client
        .inventory_cell_read(request(&after))
        .await
        .unwrap();
    assert_eq!(retained.result.status, MemoryReadStatusV1::Ok);
    assert_eq!(retained.result.value, unrelated.result.value);
    let mut reads = Vec::new();
    for index in 0..8 {
        *resolver.0.lock().unwrap() = (kind, key(address_kind, index));
        let read = fixture
            .client
            .inventory_cell_read(request(&after))
            .await
            .unwrap();
        assert_eq!(read.result.status, MemoryReadStatusV1::Ok);
        assert_eq!(read.result.generation.get(), 2);
        assert_eq!(
            read.result.value,
            after
                .current(&key(address_kind, index), kind)
                .unwrap()
                .record
                .value
        );
        reads.push(read);
    }
    fixture
        .store
        .forget_inventory_cell(
            &fixture.access(),
            &CognitiveScope::AgentPrivate,
            &changed.address(),
            2,
            "explicit qualification withdrawal",
            crate::memory_cell_runtime::now_unix_seconds().unwrap(),
        )
        .await
        .unwrap();
    let withdrawn = fixture
        .client
        .inventory_cell_read(request(&after))
        .await
        .unwrap();
    assert_eq!(withdrawn.result.status, MemoryReadStatusV1::Stale);
    assert!(withdrawn.result.value.is_null());
    evidence(
        root,
        "RESULT.json",
        &json!({"schema": "hepta.memory.native-owner-learning-cycle.v2", "cell_kind":kind, "before_cut": before.owner_cut_digest(), "after_cut": after.owner_cut_digest(),
        "original_parameter_sha256": original["parameter_sha256"], "trained": report, "generation": 2, "bundle_digest": candidate.digest(), "retained_and_corrected_reads": reads,
        "corrected_rows": 1, "retained_rows": 7, "other_cell_artifact_unchanged":retained_digest.to_string(), "other_cell_during_correction":unrelated,
        "other_cell_after_republication":retained, "selection_required_after_publication": true, "withdrawal_readout": withdrawn}),
    );
    fixture.finish().await;
}
