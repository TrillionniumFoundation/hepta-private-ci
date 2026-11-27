use super::*;
use codex_app_server_protocol::WindowsSandboxReadiness;
use codex_app_server_protocol::WindowsSandboxReadinessResponse;

#[tokio::test]
async fn disabled_readiness_preserves_the_response_and_config() -> Result<()> {
    let home = TempDir::new()?;
    let config_path = home.path().join("config.toml");
    std::fs::write(
        &config_path,
        "[features]\nexperimental_windows_sandbox = false\nelevated_windows_sandbox = false\n",
    )?;
    let mut server = TestAppServer::builder()
        .with_codex_home(home.path())
        .without_auto_env()
        .build()
        .await?;
    timeout(DEFAULT_READ_TIMEOUT, server.initialize()).await??;
    let config_before = std::fs::read(&config_path)?;
    let id = server
        .send_raw_request("windowsSandbox/readiness", /*params*/ None)
        .await?;
    let response = timeout(
        DEFAULT_READ_TIMEOUT,
        server.read_stream_until_response_message(RequestId::Integer(id)),
    )
    .await??;
    let response: WindowsSandboxReadinessResponse = to_response(response)?;

    assert_eq!(
        response,
        WindowsSandboxReadinessResponse {
            status: WindowsSandboxReadiness::NotConfigured,
        }
    );
    assert_eq!(std::fs::read(config_path)?, config_before);
    timeout(DEFAULT_READ_TIMEOUT, server.shutdown_gracefully()).await??;
    Ok(())
}

#[tokio::test]
async fn configured_readiness_respects_platform_availability_without_mutating_config() -> Result<()>
{
    for mode in ["unelevated", "elevated"] {
        let home = TempDir::new()?;
        let config_path = home.path().join("config.toml");
        std::fs::write(&config_path, format!("[windows]\nsandbox = {mode:?}\n"))?;
        let mut server = TestAppServer::builder()
            .with_codex_home(home.path())
            .without_auto_env()
            .build()
            .await?;
        timeout(DEFAULT_READ_TIMEOUT, server.initialize()).await??;
        let config_before = std::fs::read(&config_path)?;
        let id = server
            .send_raw_request("windowsSandbox/readiness", /*params*/ None)
            .await?;
        #[cfg(target_os = "windows")]
        {
            let response = timeout(
                DEFAULT_READ_TIMEOUT,
                server.read_stream_until_error_message(RequestId::Integer(id)),
            )
            .await??;
            assert_eq!(
                response.error,
                codex_app_server_protocol::JSONRPCErrorError {
                    code: -32603,
                    message: codex_windows_sandbox::ensure_windows_managed_filesystem_isolation()
                        .expect_err("execution is unavailable")
                        .to_string(),
                    data: None,
                }
            );
        }
        #[cfg(not(target_os = "windows"))]
        {
            let response = timeout(
                DEFAULT_READ_TIMEOUT,
                server.read_stream_until_response_message(RequestId::Integer(id)),
            )
            .await??;
            let response: WindowsSandboxReadinessResponse = to_response(response)?;
            assert_eq!(
                response,
                WindowsSandboxReadinessResponse {
                    status: WindowsSandboxReadiness::NotConfigured,
                }
            );
        }
        assert_eq!(std::fs::read(config_path)?, config_before);
        timeout(DEFAULT_READ_TIMEOUT, server.shutdown_gracefully()).await??;
    }
    Ok(())
}

#[cfg(target_os = "windows")]
#[tokio::test]
async fn complete_setup_marker_cannot_enable_unavailable_execution() -> Result<()> {
    for mode in [
        WindowsSandboxSetupMode::Elevated,
        WindowsSandboxSetupMode::Unelevated,
    ] {
        let home = TempDir::new()?;
        let config_path = home.path().join("config.toml");
        let marker_dir = codex_windows_sandbox::sandbox_dir(home.path());
        let secrets_dir = codex_windows_sandbox::sandbox_secrets_dir(home.path());
        std::fs::create_dir_all(&marker_dir)?;
        std::fs::create_dir_all(&secrets_dir)?;
        let marker_path = marker_dir.join("setup_marker.json");
        let users_path = secrets_dir.join("sandbox_users.json");
        std::fs::write(&config_path, "# retain the original configuration\n")?;
        std::fs::write(
            &marker_path,
            serde_json::to_vec(&serde_json::json!({
                "version": codex_windows_sandbox::SETUP_VERSION,
                "offline_username": "fixture-offline",
                "online_username": "fixture-online",
            }))?,
        )?;
        std::fs::write(
            &users_path,
            serde_json::to_vec(&serde_json::json!({
                "version": codex_windows_sandbox::SETUP_VERSION,
                "offline": { "username": "fixture-offline", "password": "synthetic-unused" },
                "online": { "username": "fixture-online", "password": "synthetic-unused" },
            }))?,
        )?;
        assert!(codex_windows_sandbox::sandbox_setup_is_complete(
            home.path()
        ));
        let mut server = TestAppServer::builder()
            .with_codex_home(home.path())
            .without_auto_env()
            .build()
            .await?;
        timeout(DEFAULT_READ_TIMEOUT, server.initialize()).await??;
        let before = (
            std::fs::read(&config_path)?,
            std::fs::read(&marker_path)?,
            std::fs::read(&users_path)?,
        );
        let id = server
            .send_windows_sandbox_setup_start_request(WindowsSandboxSetupStartParams {
                mode,
                cwd: None,
            })
            .await?;
        let response = timeout(
            DEFAULT_READ_TIMEOUT,
            server.read_stream_until_response_message(RequestId::Integer(id)),
        )
        .await??;
        let response: WindowsSandboxSetupStartResponse = to_response(response)?;
        assert_eq!(response, WindowsSandboxSetupStartResponse { started: true });
        let notification = timeout(
            DEFAULT_READ_TIMEOUT,
            server.read_stream_until_notification_message("windowsSandbox/setupCompleted"),
        )
        .await??;
        let notification: WindowsSandboxSetupCompletedNotification = serde_json::from_value(
            notification
                .params
                .context("missing setup completion params")?,
        )?;
        assert_eq!(
            notification,
            WindowsSandboxSetupCompletedNotification {
                mode,
                success: false,
                error: Some(
                    codex_windows_sandbox::ensure_windows_managed_filesystem_isolation()
                        .expect_err("execution is unavailable")
                        .to_string(),
                ),
            }
        );
        assert_eq!(
            (
                std::fs::read(&config_path)?,
                std::fs::read(&marker_path)?,
                std::fs::read(&users_path)?,
            ),
            before
        );
        assert!(codex_windows_sandbox::sandbox_setup_is_complete(
            home.path()
        ));
        timeout(DEFAULT_READ_TIMEOUT, server.shutdown_gracefully()).await??;
    }
    Ok(())
}
