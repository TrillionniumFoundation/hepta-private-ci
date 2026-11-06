//! Metadata parser fixtures only. These do not start Core, run a model,
//! authenticate a human, or qualify a production seed/owner restart.
use super::*;
use codex_protocol::protocol::SessionMeta;
use codex_protocol::protocol::SessionMetaLine;

#[test]
fn persisted_seed_metadata_requires_exact_original_identity_and_catalog() {
    let directory = tempfile::tempdir().unwrap();
    let home = directory.path().canonicalize().unwrap();
    let path = home.join("original-rollout.jsonl");
    let catalog = original_notes_thread_tools();
    let config = format!(
        "model = \"fixture-model\"\nmodel_provider = \"fixture-provider\"\n{}",
        crate::ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG
    );
    std::fs::write(home.join("config.toml"), &config).unwrap();
    std::fs::write(
        home.join("environments.toml"),
        crate::ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG,
    )
    .unwrap();
    let execution = notes_thread_execution::inspect(&home).unwrap();
    let meta = SessionMeta {
        cwd: home.clone(),
        model_provider: Some("fixture-provider".into()),
        dynamic_tools: Some(catalog.clone()),
        ..Default::default()
    };
    let mut encoded = serde_json::to_vec(&RolloutLine {
        timestamp: "2026-10-26T00:00:00.000Z".into(),
        ordinal: None,
        item: RolloutItem::SessionMeta(SessionMetaLine {
            meta: meta.clone(),
            git: None,
        }),
    })
    .unwrap();
    encoded.push(b'\n');
    std::fs::write(&path, &encoded).unwrap();
    let mut receipt = NotesThreadSeedReceipt {
        schema_version: 2,
        codex_home: home.clone(),
        thread_id: meta.id.to_string(),
        app_server_session_id: meta.session_id.to_string(),
        model: "fixture-model".into(),
        model_provider: "fixture-provider".into(),
        rollout_path: path.clone(),
        catalog_sha256: Digest32::of_bytes(&serde_json::to_vec(&catalog).unwrap()).to_string(),
        session_meta_sha256: Digest32::of_bytes(&encoded).to_string(),
        execution_profile: notes_thread_execution::PROFILE.into(),
        execution_cwd: home.clone(),
        core_config_sha256: execution.config_sha256,
        environments_sha256: execution.environments_sha256,
    };
    assert_eq!(
        inspect_metadata(&receipt).unwrap(),
        receipt.session_meta_sha256
    );
    receipt.verify_persisted().unwrap();
    receipt.schema_version = 1;
    assert!(
        receipt.verify_persisted().is_err(),
        "legacy unrestricted seed was silently upgraded"
    );
    receipt.schema_version = 2;
    std::fs::write(home.join("config.toml"), format!("{config}\n")).unwrap();
    assert!(
        receipt.verify_persisted().is_err(),
        "changed execution bytes retained the old model tuple"
    );
    std::fs::write(home.join("config.toml"), &config).unwrap();
    let tuple = receipt.model_tuple_digest().unwrap();
    let route = crate::text_session::AgentdTextSessionConfig {
        control_socket: receipt.codex_home.join("control.sock"),
        agent_id: codex_hepta_contracts::AgentId::parse("12345678-1234-4234-8234-123456789abc")
            .unwrap(),
        spawn_generation: 1,
        thread_id: receipt.thread_id.clone(),
        app_server_session_id: receipt.app_server_session_id.clone(),
        codex_home: receipt.codex_home.clone(),
    };
    assert!(
        serde_json::from_value::<crate::notes_launch_mode::NotesLaunchMode>(serde_json::json!({
            "kind":"original_thread_tool_v1", "route": &route,
        }))
        .is_err(),
        "model mode has no default or missing seed compatibility"
    );
    let mut changed_seed = receipt.clone();
    changed_seed.model_provider = "another-provider".into();
    let mode = crate::notes_launch_mode::NotesLaunchMode::OriginalThreadToolV1 {
        route,
        seed: changed_seed,
    };
    assert!(
        mode.validate_model_tuple(tuple).is_err(),
        "a different provider cannot retain the frozen tuple digest"
    );
    receipt.app_server_session_id = "different-session".into();
    assert!(inspect_metadata(&receipt).is_err());
    receipt.app_server_session_id = meta.session_id.to_string();
    let mut changed = meta;
    changed.dynamic_tools.as_mut().unwrap().pop();
    let mut changed = serde_json::to_vec(&RolloutLine {
        timestamp: "2026-10-26T00:00:00.000Z".into(),
        ordinal: None,
        item: RolloutItem::SessionMeta(SessionMetaLine {
            meta: changed,
            git: None,
        }),
    })
    .unwrap();
    changed.push(b'\n');
    std::fs::write(&path, changed).unwrap();
    assert!(
        inspect_metadata(&receipt).is_err(),
        "a missing status/read/write tool cannot be silently added at resume"
    );
    std::fs::write(&path, &encoded[..encoded.len() - 1]).unwrap();
    assert!(
        inspect_metadata(&receipt).is_err(),
        "partial metadata is not a persisted original catalog"
    );
}
