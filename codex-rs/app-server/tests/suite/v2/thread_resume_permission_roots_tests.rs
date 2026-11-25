use super::DEFAULT_READ_TIMEOUT;
use super::materialize_dev_permission_thread;
use super::write_dev_permission_config;
use anyhow::Result;
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

async fn persist_runtime_environment(
    codex_home: &Path,
    workspace_root: &AbsolutePathBuf,
    history_mode: ThreadHistoryMode,
) -> Result<ThreadResumeResponse> {
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
            cwd: Some(workspace_root.to_path_buf()),
            runtime_workspace_roots: Some(vec![workspace_root.clone()]),
            input: vec![UserInput::Text {
                text: "persist runtime environment".to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        }),
    )
    .await??;
    let resume_id = mcp
        .send_thread_resume_request(ThreadResumeParams {
            thread_id,
            ..Default::default()
        })
        .await?;
    let response: ThreadResumeResponse =
        timeout(DEFAULT_READ_TIMEOUT, mcp.read_response(resume_id)).await??;
    assert_eq!(
        (&response.cwd, &response.runtime_workspace_roots),
        (workspace_root, &vec![workspace_root.clone()])
    );
    Ok(response)
}

#[tokio::test]
async fn cold_resume_preserves_roots_for_unchanged_named_profiles() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for profile_extends in [":workspace", ":read-only"] {
        for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
            let codex_home = TempDir::new()?;
            let workspace = TempDir::new()?;
            let workspace_root = AbsolutePathBuf::from_absolute_path(workspace.path())?;
            write_dev_permission_config(&server.uri(), codex_home.path(), profile_extends)?;
            let original =
                persist_runtime_environment(codex_home.path(), &workspace_root, history_mode)
                    .await?;

            let mut mcp = TestAppServer::builder()
                .with_codex_home(codex_home.path())
                .without_managed_config()
                .build_initialized()
                .await?;
            let resume_id = mcp
                .send_thread_resume_request(ThreadResumeParams {
                    thread_id: original.thread.id,
                    ..Default::default()
                })
                .await?;
            let resumed: ThreadResumeResponse =
                timeout(DEFAULT_READ_TIMEOUT, mcp.read_response(resume_id)).await??;

            assert_eq!(
                (
                    resumed.cwd,
                    resumed.runtime_workspace_roots,
                    resumed.active_permission_profile,
                ),
                (
                    original.cwd,
                    original.runtime_workspace_roots,
                    Some(ActivePermissionProfile {
                        id: "dev".to_string(),
                        extends: Some(profile_extends.to_string()),
                    }),
                )
            );
        }
    }
    Ok(())
}

#[tokio::test]
async fn cold_resume_profile_change_preserves_explicit_environment_overrides() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let codex_home = TempDir::new()?;
        let old_workspace = TempDir::new()?;
        let old_root = AbsolutePathBuf::from_absolute_path(old_workspace.path())?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":workspace")?;
        let original =
            persist_runtime_environment(codex_home.path(), &old_root, history_mode).await?;

        write_dev_permission_config(&server.uri(), codex_home.path(), ":read-only")?;
        let current_workspace = TempDir::new()?;
        let current_root = AbsolutePathBuf::from_absolute_path(current_workspace.path())?;
        let mut mcp = TestAppServer::builder()
            .with_codex_home(codex_home.path())
            .without_managed_config()
            .build_initialized()
            .await?;
        let resume_id = mcp
            .send_thread_resume_request(ThreadResumeParams {
                thread_id: original.thread.id,
                cwd: Some(current_root.as_path().to_string_lossy().into_owned()),
                runtime_workspace_roots: Some(vec![current_root.clone()]),
                ..Default::default()
            })
            .await?;
        let resumed: ThreadResumeResponse =
            timeout(DEFAULT_READ_TIMEOUT, mcp.read_response(resume_id)).await??;

        assert!(matches!(resumed.sandbox, SandboxPolicy::ReadOnly { .. }));
        assert_eq!(
            (
                resumed.cwd,
                resumed.runtime_workspace_roots,
                resumed.active_permission_profile,
            ),
            (
                current_root.clone(),
                vec![current_root],
                Some(ActivePermissionProfile {
                    id: "dev".to_string(),
                    extends: Some(":read-only".to_string()),
                }),
            )
        );
    }
    Ok(())
}
