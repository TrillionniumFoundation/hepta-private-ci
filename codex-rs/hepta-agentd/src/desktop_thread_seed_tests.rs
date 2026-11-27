//! Persisted metadata fixtures only; no original Core or human is simulated.
use super::*;
use codex_protocol::protocol::SessionMeta;
use codex_protocol::protocol::SessionMetaLine;

fn fixture() -> (tempfile::TempDir, DesktopThreadSeedReceipt, String) {
    let directory = tempfile::tempdir().unwrap();
    let home = directory.path().canonicalize().unwrap();
    let path = home.join("original-rollout.jsonl");
    let catalog = original_desktop_thread_tools();
    let config = format!(
        "model = \"fixture-model\"\nmodel_provider = \"fixture-provider\"\n{}",
        crate::ORIGINAL_DESKTOP_THREAD_EXECUTION_CONFIG
    );
    std::fs::write(home.join("config.toml"), &config).unwrap();
    std::fs::write(
        home.join("environments.toml"),
        crate::ORIGINAL_DESKTOP_THREAD_ENVIRONMENTS_CONFIG,
    )
    .unwrap();
    let execution = desktop_thread_execution::inspect(&home).unwrap();
    let meta = SessionMeta {
        cwd: home.clone(),
        model_provider: Some("fixture-provider".into()),
        dynamic_tools: Some(catalog.clone()),
        ..Default::default()
    };
    let mut encoded = serde_json::to_vec(&RolloutLine {
        timestamp: "2026-11-03T00:00:00.000Z".into(),
        ordinal: None,
        item: RolloutItem::SessionMeta(SessionMetaLine {
            meta: meta.clone(),
            git: None,
        }),
    })
    .unwrap();
    encoded.push(b'\n');
    std::fs::write(&path, &encoded).unwrap();
    let receipt = DesktopThreadSeedReceipt {
        schema_version: 1,
        codex_home: home.clone(),
        thread_id: meta.id.to_string(),
        app_server_session_id: meta.session_id.to_string(),
        model: "fixture-model".into(),
        model_provider: "fixture-provider".into(),
        rollout_path: path,
        catalog_sha256: Digest32::of_bytes(&serde_json::to_vec(&catalog).unwrap()).to_string(),
        session_meta_sha256: Digest32::of_bytes(&encoded).to_string(),
        execution_profile: desktop_thread_execution::PROFILE.into(),
        execution_cwd: home,
        core_config_sha256: execution.config_sha256,
        environments_sha256: execution.environments_sha256,
    };
    (directory, receipt, config)
}

#[test]
fn new_desktop_seed_binds_six_tools_and_cannot_enter_legacy_notes_recovery() {
    let (_directory, receipt, _) = fixture();
    receipt.verify_persisted().unwrap();
    let legacy: crate::NotesThreadSeedReceipt =
        serde_json::from_value(serde_json::to_value(&receipt).unwrap()).unwrap();
    assert!(legacy.verify_persisted().is_err());
    let mut altered = receipt.clone();
    altered.catalog_sha256 =
        Digest32::of_bytes(&serde_json::to_vec(&crate::original_notes_thread_tools()).unwrap())
            .to_string();
    assert!(altered.verify_persisted().is_err());
    altered = receipt;
    altered.execution_profile = crate::notes_thread_execution::PROFILE.into();
    assert!(altered.verify_persisted().is_err());
}

#[test]
fn desktop_seed_rechecks_actual_configuration_and_session_metadata() {
    let (_directory, receipt, config) = fixture();
    receipt.verify_persisted().unwrap();
    std::fs::write(
        receipt.codex_home.join("config.toml"),
        format!("{config}\n"),
    )
    .unwrap();
    assert!(receipt.verify_persisted().is_err());
    std::fs::write(receipt.codex_home.join("config.toml"), config).unwrap();
    let mut changed = receipt.clone();
    changed.model_provider = "different-provider".into();
    assert!(changed.verify_persisted().is_err());
    changed = receipt.clone();
    changed.app_server_session_id = "different-original-session".into();
    assert!(changed.verify_persisted().is_err());
    let bytes = std::fs::read(&receipt.rollout_path).unwrap();
    std::fs::write(&receipt.rollout_path, &bytes[..bytes.len() - 1]).unwrap();
    assert!(receipt.verify_persisted().is_err());
}
