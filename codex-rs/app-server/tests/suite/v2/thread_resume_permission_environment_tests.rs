use super::DEFAULT_READ_TIMEOUT;
use super::materialize_dev_permission_thread;
use super::write_dev_permission_config;
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ActivePermissionProfile;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::SandboxPolicy;
use codex_app_server_protocol::ThreadHistoryMode;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::UserInput;
use codex_exec_server::CreateDirectoryOptions;
use codex_protocol::protocol::TurnContextEnvironmentItem;
use codex_rollout::RolloutItem;
use codex_rollout::RolloutRecorder;
use codex_utils_absolute_path::AbsolutePathBuf;
use core_test_support::is_wine_exec_test_environment;
use core_test_support::test_codex::TestEnv;
use pretty_assertions::assert_eq;
use std::path::Path;
use tempfile::TempDir;
use tokio::time::timeout;

async fn persist_runtime_roots(
    codex_home: &Path,
    history_mode: ThreadHistoryMode,
    root: &AbsolutePathBuf,
) -> Result<(String, TestAppServer)> {
    // These legacy API roots and profile paths are host AbsolutePathBuf values.
    let mut mcp = TestAppServer::builder()
        .with_test_env(TestEnv::local_with_exec_server_url(/*exec_server_url*/ None).await?)
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
    assert!(
        timeout(DEFAULT_READ_TIMEOUT, mcp.shutdown_gracefully())
            .await??
            .success()
    );
    Ok((thread_id, mcp))
}

async fn resume(codex_home: &Path, params: ThreadResumeParams) -> Result<ThreadResumeResponse> {
    let mut mcp = TestAppServer::builder()
        .with_test_env(TestEnv::local_with_exec_server_url(/*exec_server_url*/ None).await?)
        .with_codex_home(codex_home)
        .without_managed_config()
        .build_initialized()
        .await?;
    let request_id = mcp.send_thread_resume_request(params).await?;
    timeout(DEFAULT_READ_TIMEOUT, mcp.read_response(request_id)).await?
}

async fn persist_native_turn(mcp: &mut TestAppServer, thread_id: &str) -> Result<()> {
    timeout(
        DEFAULT_READ_TIMEOUT,
        mcp.start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: thread_id.to_string(),
            input: vec![UserInput::Text {
                text: "persist native environment paths".to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        }),
    )
    .await??;
    Ok(())
}

async fn last_native_environments(path: &Path) -> Result<Vec<TurnContextEnvironmentItem>> {
    let (items, _, errors) = RolloutRecorder::load_rollout_items(path).await?;
    assert_eq!(errors, 0);
    Ok(items
        .into_iter()
        .rev()
        .find_map(|item| match item {
            RolloutItem::TurnContext(context) => Some(context.environments),
            _ => None,
        })
        .expect("persisted turn")
        .expect("complete native snapshot"))
}

#[tokio::test]
async fn cold_resume_preserves_native_paths_and_rebuilds_changed_policy_roots() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for (changed_access, roots_only) in [
        (None, false),
        (Some("deny"), false),
        (Some("read"), false),
        (None, true),
    ] {
        let codex_home = TempDir::new()?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":workspace")?;
        let mut origin = TestAppServer::builder()
            .with_codex_home(codex_home.path())
            .without_managed_config()
            .build_initialized()
            .await?;
        let selected = origin.auto_env()?.selection().clone();
        let extra = selected.cwd.join("additional-root")?;
        origin
            .auto_env()?
            .environment()
            .get_filesystem()
            .create_directory(
                &extra,
                CreateDirectoryOptions {
                    recursive: true,
                    follow_symlinks: true,
                },
                /*sandbox*/ None,
            )
            .await?;
        let mut environment = origin.auto_env_params()?;
        environment.runtime_workspace_roots =
            Some(vec![selected.cwd.clone().into(), extra.clone().into()]);
        let mut expected = vec![TurnContextEnvironmentItem {
            environment_id: selected.environment_id,
            cwd: selected.cwd.inferred_native_path_string(),
            workspace_roots: vec![
                selected.cwd.inferred_native_path_string(),
                extra.inferred_native_path_string(),
            ],
        }];
        let request = origin
            .send_thread_start_request(ThreadStartParams {
                model: Some("mock-model".to_string()),
                history_mode: Some(ThreadHistoryMode::Legacy),
                permissions: Some("dev".to_string()),
                environments: Some(vec![environment]),
                ..Default::default()
            })
            .await?;
        let ThreadStartResponse { thread, .. } =
            timeout(DEFAULT_READ_TIMEOUT, origin.read_response(request)).await??;
        let path = thread.path.expect("legacy rollout path");
        persist_native_turn(&mut origin, &thread.id).await?;
        if roots_only {
            timeout(
                DEFAULT_READ_TIMEOUT,
                origin.start_turn_and_wait_for_completion(TurnStartParams {
                    thread_id: thread.id.clone(),
                    runtime_workspace_roots: Some(Vec::new()),
                    input: vec![UserInput::Text {
                        text: "clear runtime roots without replacing native cwd".to_string(),
                        text_elements: Vec::new(),
                    }],
                    ..Default::default()
                }),
            )
            .await??;
            expected[0].workspace_roots.clear();
        }
        assert!(
            timeout(DEFAULT_READ_TIMEOUT, origin.shutdown_gracefully())
                .await??
                .success()
        );
        assert_eq!(last_native_environments(&path).await?, expected);
        let persisted_environments = expected.clone();

        if let Some(access) = changed_access {
            MockResponsesConfig::new(&server.uri())
                .with_root_config("default_permissions = \":danger-full-access\"")
                .with_extra_config(&format!(
                    "[permissions.dev]\nextends = \":workspace\"\n\n[permissions.dev.filesystem.\":workspace_roots\"]\n\".native-resume-denied\" = \"{access}\""
                ))
                .write(codex_home.path())?;
            expected[0].workspace_roots = vec![selected.cwd.inferred_native_path_string()];
        }
        // Keep the original TestEnv owner alive while its app-server process is stopped.
        let mut resumed = TestAppServer::builder()
            .with_codex_home(codex_home.path())
            .without_managed_config()
            .build_initialized()
            .await?;
        let request = resumed
            .send_thread_resume_request(ThreadResumeParams {
                thread_id: thread.id.clone(),
                ..Default::default()
            })
            .await?;
        if changed_access == Some("deny") && is_wine_exec_test_environment() {
            // Wine uses the unelevated Windows executor, which must reject deny-read
            // restrictions. The read-only carveout above still exercises a successful
            // same-base policy change and native root reconstruction on this executor.
            let error = timeout(
                DEFAULT_READ_TIMEOUT,
                resumed.read_stream_until_error_message(RequestId::Integer(request)),
            )
            .await??;
            assert_eq!(
                error.error,
                JSONRPCErrorError {
                    code: -32603,
                    message: format!(
                        "error resuming thread: Fatal error: Failed to initialize session: failed to load AGENTS.md instructions for environment `{}`: failed to prepare fs sandbox: failed to prepare windows sandbox wrapper: windows unelevated restricted-token sandbox cannot enforce deny-read restrictions directly; refusing to run unsandboxed",
                        expected[0].environment_id,
                    ),
                    data: None,
                },
            );
            assert_eq!(
                last_native_environments(&path).await?,
                persisted_environments
            );
            assert!(
                timeout(DEFAULT_READ_TIMEOUT, resumed.shutdown_gracefully())
                    .await??
                    .success()
            );
            continue;
        }
        let response: ThreadResumeResponse =
            timeout(DEFAULT_READ_TIMEOUT, resumed.read_response(request)).await??;
        assert_eq!(
            response.active_permission_profile,
            Some(ActivePermissionProfile {
                id: "dev".to_string(),
                extends: Some(":workspace".to_string()),
            })
        );
        persist_native_turn(&mut resumed, &thread.id).await?;
        assert!(
            timeout(DEFAULT_READ_TIMEOUT, resumed.shutdown_gracefully())
                .await??
                .success()
        );
        assert_eq!(last_native_environments(&path).await?, expected);
    }
    Ok(())
}

#[tokio::test]
async fn cold_resume_keeps_runtime_roots_when_named_permissions_are_unchanged() -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("Done").await;
    for history_mode in [ThreadHistoryMode::Legacy, ThreadHistoryMode::Paginated] {
        let codex_home = TempDir::new()?;
        let previous_root_dir = TempDir::new()?;
        let previous_root = AbsolutePathBuf::from_absolute_path(previous_root_dir.path())?;
        write_dev_permission_config(&server.uri(), codex_home.path(), ":workspace")?;
        let (thread_id, _origin) =
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
        let (thread_id, _origin) =
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
        let (thread_id, _origin) =
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
        let (thread_id, _origin) =
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
