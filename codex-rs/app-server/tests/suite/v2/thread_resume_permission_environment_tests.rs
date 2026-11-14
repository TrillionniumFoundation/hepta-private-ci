use super::DEFAULT_READ_TIMEOUT;
use super::materialize_dev_permission_thread;
use super::write_dev_permission_config;
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ActivePermissionProfile;
use codex_app_server_protocol::SandboxPolicy;
use codex_app_server_protocol::ThreadHistoryMode;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::UserInput;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::path::Path;
use tempfile::TempDir;
use tokio::time::timeout;

async fn persist_runtime_roots(
    codex_home: &Path,
    history_mode: ThreadHistoryMode,
    root: &AbsolutePathBuf,
) -> Result<String> {
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home)
        .without_managed_config()
        .build_initialized()
        .await?;
    let thread_id = materialize_dev_permission_thread(&mut mcp, history_mode).await?;
    timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: thread_id.clone(),
            runtime_workspace_roots: Some(vec![root.clone()]),
            input: vec![UserInput::Text {
                text: "persist the selected runtime root".to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        }),
    )
    .await??;
    Ok(thread_id)
}

async fn resume(codex_home: &Path, params: ThreadResumeParams) -> Result<ThreadResumeResponse> {
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home)
        .without_managed_config()
        .build_initialized()
        .await?;
    let request_id = mcp.send_thread_resume_request(params).await?;
    timeout(DEFAULT_READ_TIMEOUT, mcp.read_response(request_id)).await?
}

#[tokio::test]
async fn cold_resume_keeps_runtime_roots_when_named_permissions_are_unchanged() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let codex_home = TempDir::new()?;
        let previous_root_dir = TempDir::new()?;
        let previous_root = AbsolutePathBuf::from_absolute_path(previous_root_dir.path())?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":workspace")?;
        let thread_id =
            persist_runtime_roots(codex_home.path(), history_mode, &previous_root).await?;
        let restored = resume(
            codex_home.path(),
            ThreadResumeParams {
                thread_id,
                ..Default::default()
            },
        )
        .await?;
        assert_eq!(restored.runtime_workspace_roots, vec![previous_root]);
        assert_eq!(
            restored.active_permission_profile,
            Some(ActivePermissionProfile {
                id: "dev".to_string(),
                extends: Some(":workspace".to_string()),
            })
        );
    }
    Ok(())
}

#[tokio::test]
async fn cold_resume_explicit_roots_win_after_named_permission_profile_changes() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let codex_home = TempDir::new()?;
        let previous_root_dir = TempDir::new()?;
        let explicit_root_dir = TempDir::new()?;
        let previous_root = AbsolutePathBuf::from_absolute_path(previous_root_dir.path())?;
        let explicit_root = AbsolutePathBuf::from_absolute_path(explicit_root_dir.path())?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":workspace")?;
        let thread_id =
            persist_runtime_roots(codex_home.path(), history_mode, &previous_root).await?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":read-only")?;
        let restored = resume(
            codex_home.path(),
            ThreadResumeParams {
                thread_id,
                runtime_workspace_roots: Some(vec![explicit_root.clone()]),
                ..Default::default()
            },
        )
        .await?;
        assert_eq!(restored.runtime_workspace_roots, vec![explicit_root]);
        assert!(matches!(restored.sandbox, SandboxPolicy::ReadOnly { .. }));
    }
    Ok(())
}

#[tokio::test]
async fn cold_resume_explicit_cwd_wins_without_reusing_previous_profile_roots() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let codex_home = TempDir::new()?;
        let previous_root_dir = TempDir::new()?;
        let explicit_cwd_dir = TempDir::new()?;
        let previous_root = AbsolutePathBuf::from_absolute_path(previous_root_dir.path())?;
        let explicit_cwd = AbsolutePathBuf::from_absolute_path(explicit_cwd_dir.path())?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":workspace")?;
        let thread_id =
            persist_runtime_roots(codex_home.path(), history_mode, &previous_root).await?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":read-only")?;
        let restored = resume(
            codex_home.path(),
            ThreadResumeParams {
                thread_id,
                cwd: Some(explicit_cwd.as_path().display().to_string()),
                ..Default::default()
            },
        )
        .await?;
        assert_eq!(restored.cwd, explicit_cwd);
        assert!(!restored.runtime_workspace_roots.contains(&previous_root));
        assert!(matches!(restored.sandbox, SandboxPolicy::ReadOnly { .. }));
    }
    Ok(())
}

#[tokio::test]
async fn cold_resume_rebuilds_roots_when_named_policy_changes_with_the_same_base() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let codex_home = TempDir::new()?;
        let previous_root_dir = TempDir::new()?;
        let previous_root = AbsolutePathBuf::from_absolute_path(previous_root_dir.path())?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":workspace")?;
        let thread_id =
            persist_runtime_roots(codex_home.path(), history_mode, &previous_root).await?;
        let denied_path = serde_json::to_string(previous_root.as_path())?;
        MockResponsesConfig::new(&server.uri())
            .with_root_config("default_permissions = \":danger-full-access\"")
            .with_extra_config(&format!(
                "[permissions.dev]\nextends = \":workspace\"\n\n[permissions.dev.filesystem]\n{denied_path} = \"deny\""
            ))
            .write(codex_home.path())?;
        let restored = resume(
            codex_home.path(),
            ThreadResumeParams {
                thread_id,
                ..Default::default()
            },
        )
        .await?;
        assert_eq!(
            restored.active_permission_profile,
            Some(ActivePermissionProfile {
                id: "dev".to_string(),
                extends: Some(":workspace".to_string()),
            })
        );
        assert!(!restored.runtime_workspace_roots.contains(&previous_root));
    }
    Ok(())
}
