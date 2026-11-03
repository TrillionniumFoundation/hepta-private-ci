//! The actual runner binding must not reinterpret a legacy pending session.

use super::*;
use codex_hepta_native_agent::TurnOwner;

#[tokio::test]
async fn runner_policy_upgrade_preserves_legacy_pending_request_and_manifest() -> Result<()> {
    let temporary = tempfile::tempdir()?;
    let config: Config = serde_json::from_value(json!({
        "runtime_config":temporary.path().join("unused-runtime.json"),
        "sessions_dir":temporary.path().join("sessions"),
        "fixture":{"representative":false,"host":"unopened-fixture",
            "script":"unused.py","script_sha256":Digest32::of_bytes(b"").to_string(),
            "data":"unused.txt","data_sha256":Digest32::of_bytes(b"").to_string(),
            "cwd":temporary.path(),"tool_timeout_seconds":2},
        "model":"fixed-model","responses_url":"http://127.0.0.1:1/v1/responses",
        "context_bytes":65536,"output_tokens":256,"model_calls":6,"tool_calls":5,
        "tool_output_bytes":32768,"model_timeout_seconds":5,"tool_timeout_seconds":2
    }))?;
    let agent = native_agent(&config);
    let current = session_policy(&config, "run", &agent)?;
    assert_eq!(
        current["context_policy"]["version"],
        codex_hepta_native_agent::CONTEXT_POLICY_VERSION
    );
    let old_policy = json!({
        "version":"hepta-native-context-policy-v2",
        "request_projection_version":codex_hepta_native_agent::CONTEXT_PROJECTION_VERSION,
        "request_bytes":65536,"message_item_bytes":65536,"tool_item_bytes":8192,
        "retained_context_bytes":65536 * 12,
    });
    for (index, legacy) in [
        json!({"config":config,"mode":"run"}),
        json!({"config":config,"mode":"run","context_policy":old_policy}),
    ]
    .into_iter()
    .enumerate()
    {
        let root = temporary.path().join(format!("original-session-{index}"));
        let (owner, mut pending) = SessionOwner::open(
            root.clone(),
            "original-session",
            "original input",
            config.fixture.clone(),
            legacy.clone(),
        )?;
        let body = br#"{"model":"fixed-model","input":[{"role":"user","content":"original input"}],"stream":true}"#;
        let request = owner.admit_model(&pending.binding, 0, body).await?;
        let operation = request.operation_id.clone();
        pending.pending_model = Some(request);
        pending.model_calls = 1;
        pending.provider_response_id = Some("original-legacy-response".to_owned());
        owner.checkpoint(&pending).await?;
        let manifest = std::fs::read(root.join("manifest.json"))?;
        let snapshot_paths = std::fs::read_dir(&root)?
            .collect::<std::io::Result<Vec<_>>>()?
            .into_iter()
            .map(|entry| entry.path())
            .filter(|path| {
                path.file_name()
                    .is_some_and(|name| name.to_string_lossy().starts_with("snapshot-"))
            })
            .collect::<Vec<_>>();
        let snapshots = snapshot_paths
            .iter()
            .map(std::fs::read)
            .collect::<std::io::Result<Vec<_>>>()?;
        drop(owner);
        assert!(
            SessionOwner::open(
                root.clone(),
                "original-session",
                "original input",
                config.fixture.clone(),
                current.clone()
            )
            .is_err()
        );
        assert_eq!(std::fs::read(root.join("manifest.json"))?, manifest);
        assert_eq!(
            snapshot_paths
                .iter()
                .map(std::fs::read)
                .collect::<std::io::Result<Vec<_>>>()?,
            snapshots
        );
        let (_original_owner, restored) = SessionOwner::open(
            root.clone(),
            "original-session",
            "original input",
            config.fixture.clone(),
            legacy,
        )?;
        assert_eq!(
            restored
                .pending_model
                .as_ref()
                .context("original operation retained")?
                .operation_id,
            operation
        );
        assert_eq!(
            restored
                .pending_model
                .as_ref()
                .context("original body retained")?
                .body,
            body
        );
        assert_eq!(
            restored.provider_response_id.as_deref(),
            Some("original-legacy-response")
        );
        assert_eq!(restored.model_calls, 1);
        assert!(restored.final_answer.is_none());
        assert_eq!(
            std::fs::read_dir(root)?
                .filter_map(|entry| entry.ok())
                .filter(|entry| entry.file_name().to_string_lossy().starts_with("model-"))
                .count(),
            1
        );
    }
    Ok(())
}
