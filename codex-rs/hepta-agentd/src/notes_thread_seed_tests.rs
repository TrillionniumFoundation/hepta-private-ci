//! Metadata parser fixtures only. These do not start Core, run a model,
//! authenticate a human, or qualify a production seed/owner restart.
use super::*;
use codex_protocol::protocol::SessionMeta;
use codex_protocol::protocol::SessionMetaLine;
use pretty_assertions::assert_eq;

#[test]
fn persisted_seed_metadata_requires_exact_original_identity_and_catalog() {
    let directory = tempfile::tempdir().unwrap();
    let home = directory.path().canonicalize().unwrap();
    let path = home.join("original-rollout.jsonl");
    let catalog = original_notes_thread_tools();
    let meta = SessionMeta {
        cwd: home.clone(),
        model_provider: Some("fixture-provider".into()),
        dynamic_tools: Some(catalog.clone()),
        ..Default::default()
    };
    let mut encoded = serde_json::to_vec(&RolloutItem::SessionMeta(SessionMetaLine {
        meta: meta.clone(),
        git: None,
    }))
    .unwrap();
    encoded.push(b'\n');
    std::fs::write(&path, &encoded).unwrap();
    let mut receipt = NotesThreadSeedReceipt {
        schema_version: 1,
        codex_home: home,
        thread_id: meta.id.to_string(),
        app_server_session_id: meta.session_id.to_string(),
        model: "fixture-model".into(),
        model_provider: "fixture-provider".into(),
        rollout_path: path.clone(),
        catalog_sha256: Digest32::of_bytes(&serde_json::to_vec(&catalog).unwrap()).to_string(),
        session_meta_sha256: Digest32::of_bytes(&encoded).to_string(),
    };
    assert_eq!(
        inspect_metadata(&receipt).unwrap(),
        receipt.session_meta_sha256
    );
    receipt.app_server_session_id = "different-session".into();
    assert!(inspect_metadata(&receipt).is_err());
    receipt.app_server_session_id = meta.session_id.to_string();
    let mut changed = meta;
    changed.dynamic_tools.as_mut().unwrap().pop();
    let mut changed = serde_json::to_vec(&RolloutItem::SessionMeta(SessionMetaLine {
        meta: changed,
        git: None,
    }))
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
