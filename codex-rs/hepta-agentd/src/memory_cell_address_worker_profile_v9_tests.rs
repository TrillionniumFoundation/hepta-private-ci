//! Real file mutations exercise the closed profile and source-pin boundary.

use std::collections::BTreeMap;

use pretty_assertions::assert_eq;
use serde_json::json;

use super::super::super::test_support::WorkerFixture;
use super::super::super::wire::canonical;
use super::super::super::wire::hash;
use super::source_profile;

fn v9_fixture() -> WorkerFixture {
    let mut fixture = WorkerFixture::new();
    let old = fixture.config.worker_script.clone();
    let qualification = old.parent().unwrap().parent().unwrap().parent().unwrap();
    let addressing = qualification.join("memory-cell-v9/addressing");
    std::fs::create_dir_all(addressing.join("v9_addressing")).unwrap();
    let script = addressing.join("worker.py");
    std::fs::copy(&old, &script).unwrap();
    let profile =
        source_profile(&script, Some("hepta.memory.v9.compatibility-intent-model.v1")).unwrap();
    for path in &profile.required {
        if !path.exists() {
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(
                path,
                "# Explicit source-pin fixture, not learned addressing.\n",
            )
            .unwrap();
        }
        fixture
            .config
            .code_pins
            .insert(path.clone(), hash(&std::fs::read(path).unwrap()));
    }
    let policy: BTreeMap<_, _> = profile
        .policy_files
        .into_iter()
        .map(|(name, path)| (name, fixture.config.code_pins[&path].to_string()))
        .collect();
    let manifest = canonical(
        &json!({"schema":"hepta.memory.v9.compatibility-intent-model.v1",
        "policy_digest":hash(&canonical(&serde_json::to_value(policy).unwrap()).unwrap())}),
    )
    .unwrap();
    std::fs::write(
        fixture.config.model_directory.join("manifest.json"),
        &manifest,
    )
    .unwrap();
    fixture.config.worker_script_digest = fixture.config.code_pins[&script];
    fixture.config.worker_script = script;
    fixture.config.model_digest = hash(&manifest);
    fixture
}

#[tokio::test]
async fn v9_profile_binds_new_and_frozen_import_bytes() {
    let mut fixture = v9_fixture();
    let expected = fixture.config.verify().await.unwrap();
    assert_eq!(fixture.config.verify().await.unwrap(), expected);
    let model = fixture
        .config
        .worker_script
        .parent()
        .unwrap()
        .join("v9_addressing/model.py");
    let pin = fixture.config.code_pins.remove(&model).unwrap();
    assert!(
        fixture.config.verify().await.is_err(),
        "missing V9 head module must fail"
    );
    fixture.config.code_pins.insert(model, pin);
    let frozen = fixture
        .config
        .worker_script
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("memory-cell-v7/addressing/contracts.py");
    std::fs::write(frozen, "# Changed contracts after source selection.\n").unwrap();
    assert!(
        fixture.config.verify().await.is_err(),
        "mutated frozen owner contract must fail"
    );
}

#[tokio::test]
async fn v9_profile_rejects_an_unpinned_import_added_after_admission() {
    let fixture = v9_fixture();
    fixture.config.verify().await.unwrap();
    let unexpected = fixture
        .config
        .worker_script
        .parent()
        .unwrap()
        .join("v9_addressing/unregistered.py");
    std::fs::write(unexpected, "# Added after the closed import inventory.\n").unwrap();
    assert!(fixture.config.verify().await.is_err());
}

#[tokio::test]
async fn v9_profile_does_not_admit_an_unknown_schema_or_entry_point() {
    let mut fixture = v9_fixture();
    fixture.config.verify().await.unwrap();
    let manifest_path = fixture.config.model_directory.join("manifest.json");
    let original = std::fs::read(&manifest_path).unwrap();
    let mut manifest: serde_json::Value = serde_json::from_slice(&original).unwrap();
    manifest["schema"] = json!("hepta.memory.unregistered-model.v1");
    let unknown = canonical(&manifest).unwrap();
    std::fs::write(&manifest_path, &unknown).unwrap();
    fixture.config.model_digest = hash(&unknown);
    assert!(fixture.config.verify().await.is_err());
    std::fs::write(manifest_path, &original).unwrap();
    fixture.config.model_digest = hash(&original);
    let other = fixture
        .config
        .worker_script
        .parent()
        .unwrap()
        .join("unregistered_worker.py");
    std::fs::copy(&fixture.config.worker_script, &other).unwrap();
    fixture.config.worker_script = other.clone();
    fixture
        .config
        .code_pins
        .insert(other, fixture.config.worker_script_digest);
    assert!(fixture.config.verify().await.is_err());
}
