use super::DEFAULT_READ_TIMEOUT;
use super::materialize_dev_permission_thread;
use super::normalized_existing_path;
use super::write_dev_permission_config;
use anyhow::Result;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ActivePermissionProfile;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SandboxPolicy;
use codex_app_server_protocol::ThreadHistoryMode;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::UserInput;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::collections::HashMap;
use std::path::Path;
use tempfile::TempDir;
use tokio::time::timeout;

async fn persist_named_profile_roots(
    server_uri: &str,
    codex_home: &Path,
    history_mode: ThreadHistoryMode,
    root: &AbsolutePathBuf,
) -> Result<String> {
    write_dev_permission_config(server_uri, codex_home, ":workspace")?;
    let mut app = TestAppServer::builder()
        .with_codex_home(codex_home)
        .without_managed_config()
        .build_initialized()
        .await?;
    let thread_id = materialize_dev_permission_thread(&mut app, history_mode).await?;
    timeout(
        DEFAULT_READ_TIMEOUT,
        app.start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: thread_id.clone(),
            runtime_workspace_roots: Some(vec![root.clone()]),
            input: vec![UserInput::Text {
                text: "persist named-profile runtime roots".to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        }),
    )
    .await??;
    timeout(DEFAULT_READ_TIMEOUT, app.shutdown_gracefully()).await??;
    Ok(thread_id)
}

#[tokio::test]
async fn unchanged_named_policy_preserves_runtime_roots_on_cold_resume() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let home = TempDir::new()?;
        let workspace = TempDir::new()?;
        let root =
            AbsolutePathBuf::from_absolute_path(normalized_existing_path(workspace.path())?)?;
        let thread_id =
            persist_named_profile_roots(&server.uri(), home.path(), history_mode, &root).await?;
        let mut app = TestAppServer::builder()
            .with_codex_home(home.path())
            .without_managed_config()
            .build_initialized()
            .await?;
        let request = app
            .send_thread_resume_request(ThreadResumeParams {
                thread_id,
                ..Default::default()
            })
            .await?;
        let response: ThreadResumeResponse =
            timeout(DEFAULT_READ_TIMEOUT, app.read_response(request)).await??;
        assert_eq!(response.runtime_workspace_roots, vec![root]);
        assert_eq!(
            response.active_permission_profile,
            Some(ActivePermissionProfile {
                id: "dev".to_string(),
                extends: Some(":workspace".to_string()),
            })
        );
        assert!(matches!(
            response.sandbox,
            SandboxPolicy::WorkspaceWrite { .. }
        ));
    }
    Ok(())
}

#[tokio::test]
async fn changed_policy_body_invalidates_inferred_roots_even_with_the_same_profile_id() -> Result<()>
{
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    let workspace = TempDir::new()?;
    let root = AbsolutePathBuf::from_absolute_path(normalized_existing_path(workspace.path())?)?;
    let thread_id =
        persist_named_profile_roots(&server.uri(), home.path(), ThreadHistoryMode::Legacy, &root)
            .await?;
    let path = home.path().join("config.toml");
    let config = std::fs::read_to_string(&path)?;
    std::fs::write(
        path,
        format!("{config}\n[permissions.dev.network]\nenabled = true\n"),
    )?;
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let request = app
        .send_thread_resume_request(ThreadResumeParams {
            thread_id,
            ..Default::default()
        })
        .await?;
    let response: ThreadResumeResponse =
        timeout(DEFAULT_READ_TIMEOUT, app.read_response(request)).await??;
    assert_eq!(
        response.active_permission_profile,
        Some(ActivePermissionProfile {
            id: "dev".to_string(),
            extends: Some(":workspace".to_string()),
        })
    );
    assert!(!response.runtime_workspace_roots.contains(&root));
    assert!(matches!(
        response.sandbox,
        SandboxPolicy::WorkspaceWrite {
            network_access: true,
            ..
        }
    ));
    Ok(())
}

#[tokio::test]
async fn changed_named_policy_preserves_explicit_typed_and_raw_roots() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    let old_workspace = TempDir::new()?;
    let requested_workspace = TempDir::new()?;
    let old_root =
        AbsolutePathBuf::from_absolute_path(normalized_existing_path(old_workspace.path())?)?;
    let requested_root =
        AbsolutePathBuf::from_absolute_path(normalized_existing_path(requested_workspace.path())?)?;
    let thread_id = persist_named_profile_roots(
        &server.uri(),
        home.path(),
        ThreadHistoryMode::Paginated,
        &old_root,
    )
    .await?;
    write_dev_permission_config(&server.uri(), home.path(), ":read-only")?;
    for params in [
        ThreadResumeParams {
            thread_id: thread_id.clone(),
            runtime_workspace_roots: Some(vec![requested_root.clone()]),
            ..Default::default()
        },
        ThreadResumeParams {
            thread_id: thread_id.clone(),
            config: Some(HashMap::from([(
                "workspace_roots".to_string(),
                json!([requested_root]),
            )])),
            ..Default::default()
        },
    ] {
        let mut app = TestAppServer::builder()
            .with_codex_home(home.path())
            .without_managed_config()
            .build_initialized()
            .await?;
        let request = app.send_thread_resume_request(params).await?;
        let response: ThreadResumeResponse =
            timeout(DEFAULT_READ_TIMEOUT, app.read_response(request)).await??;
        assert_eq!(
            response.runtime_workspace_roots,
            vec![requested_root.clone()]
        );
        assert!(matches!(response.sandbox, SandboxPolicy::ReadOnly { .. }));
        timeout(DEFAULT_READ_TIMEOUT, app.shutdown_gracefully()).await??;
    }
    Ok(())
}

#[tokio::test]
async fn conflicting_typed_and_raw_roots_are_rejected() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    let old_workspace = TempDir::new()?;
    let requested_workspace = TempDir::new()?;
    let conflicting_workspace = TempDir::new()?;
    let old_root =
        AbsolutePathBuf::from_absolute_path(normalized_existing_path(old_workspace.path())?)?;
    let requested_root =
        AbsolutePathBuf::from_absolute_path(normalized_existing_path(requested_workspace.path())?)?;
    let conflicting_path = normalized_existing_path(conflicting_workspace.path())?;
    let conflicting_root = AbsolutePathBuf::from_absolute_path(conflicting_path)?;
    let thread_id = persist_named_profile_roots(
        &server.uri(),
        home.path(),
        ThreadHistoryMode::Paginated,
        &old_root,
    )
    .await?;
    write_dev_permission_config(&server.uri(), home.path(), ":read-only")?;
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let request = app
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread_id.clone(),
            runtime_workspace_roots: Some(vec![requested_root.clone()]),
            config: Some(HashMap::from([(
                "workspace_roots".to_string(),
                json!([conflicting_root]),
            )])),
            ..Default::default()
        })
        .await?;
    let error = timeout(
        DEFAULT_READ_TIMEOUT,
        app.read_stream_until_error_message(RequestId::Integer(request)),
    )
    .await??;
    assert_eq!(error.error.code, -32602);
    let error_message = &error.error.message;
    assert!(error_message.contains("conflicting `runtimeWorkspaceRoots` and `workspace_roots` overrides"));

    // Rejection must leave the thread available and admit agreeing overrides.
    let request = app
        .send_thread_resume_request(ThreadResumeParams {
            thread_id,
            runtime_workspace_roots: Some(vec![requested_root.clone()]),
            config: Some(HashMap::from([(
                "workspace_roots".to_string(),
                json!([requested_root]),
            )])),
            ..Default::default()
        })
        .await?;
    let response: ThreadResumeResponse =
        timeout(DEFAULT_READ_TIMEOUT, app.read_response(request)).await??;
    assert_eq!(response.runtime_workspace_roots, vec![requested_root]);
    assert!(matches!(response.sandbox, SandboxPolicy::ReadOnly { .. }));
    timeout(DEFAULT_READ_TIMEOUT, app.shutdown_gracefully()).await??;
    Ok(())
}

#[tokio::test]
async fn malformed_raw_roots_are_rejected_but_explicit_empty_roots_are_preserved() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    let home = TempDir::new()?;
    let old_workspace = TempDir::new()?;
    let old_root =
        AbsolutePathBuf::from_absolute_path(normalized_existing_path(old_workspace.path())?)?;
    let thread_id = persist_named_profile_roots(
        &server.uri(),
        home.path(),
        ThreadHistoryMode::Paginated,
        &old_root,
    )
    .await?;
    write_dev_permission_config(&server.uri(), home.path(), ":read-only")?;
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_managed_config()
        .build_initialized()
        .await?;
    let request = app
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: thread_id.clone(),
            config: Some(HashMap::from([(
                "workspace_roots".to_string(),
                json!({"unexpected": "map"}),
            )])),
            ..Default::default()
        })
        .await?;
    let error = timeout(
        DEFAULT_READ_TIMEOUT,
        app.read_stream_until_error_message(RequestId::Integer(request)),
    )
    .await??;
    assert_eq!(error.error.code, -32602);
    assert!(error.error.message.contains("workspace_roots"));
    let request = app
        .send_thread_resume_request(ThreadResumeParams {
            thread_id,
            config: Some(HashMap::from([(
                "workspace_roots".to_string(),
                json!([]),
            )])),
            ..Default::default()
        })
        .await?;
    let response: ThreadResumeResponse =
        timeout(DEFAULT_READ_TIMEOUT, app.read_response(request)).await??;
    assert!(response.runtime_workspace_roots.is_empty());
    assert!(matches!(response.sandbox, SandboxPolicy::ReadOnly { .. }));
    timeout(DEFAULT_READ_TIMEOUT, app.shutdown_gracefully()).await??;
    Ok(())
}
