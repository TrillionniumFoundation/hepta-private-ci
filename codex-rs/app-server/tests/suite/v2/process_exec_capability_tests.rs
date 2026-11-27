use codex_app_server_protocol::ClientInfo;
use codex_app_server_protocol::InitializeCapabilities;
use codex_app_server_protocol::InitializeResponse;
use codex_app_server_protocol::JSONRPCMessage;
use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn process_spawn_refuses_legacy_or_terminal_opt_out_before_creating_a_process() -> Result<()>
{
    for (supports_unknown, opted_out) in [
        (false, None),
        (true, Some("process/indeterminate")),
        (true, Some("process/exited")),
    ] {
        let codex_home = TempDir::new()?;
        let server = create_mock_responses_server_sequence_unchecked(Vec::new()).await;
        create_config_toml(codex_home.path(), &server.uri(), "never")?;
        let mut mcp = TestAppServer::builder()
            .with_codex_home(codex_home.path())
            .without_auto_env()
            .build()
            .await?;
        let initialized = timeout(
            DEFAULT_READ_TIMEOUT,
            mcp.initialize_with_capabilities(
                ClientInfo {
                    name: "process-negotiation".to_string(),
                    title: None,
                    version: "1".to_string(),
                },
                Some(InitializeCapabilities {
                    experimental_api: true,
                    process_indeterminate: supports_unknown,
                    opt_out_notification_methods: opted_out.map(|method| vec![method.to_string()]),
                    ..Default::default()
                }),
            ),
        )
        .await??;
        let JSONRPCMessage::Response(response) = initialized else {
            anyhow::bail!("initialize failed: {initialized:?}");
        };
        let response: InitializeResponse = serde_json::from_value(response.result)?;
        assert!(!response.process_indeterminate);

        let probe = codex_home.path().join("must-not-be-created");
        let command = if cfg!(windows) {
            vec![
                "powershell.exe".to_string(),
                "-NoProfile".to_string(),
                "-NonInteractive".to_string(),
                "-Command".to_string(),
                "[IO.File]::WriteAllText($env:PROCESS_NEGOTIATION_PROBE, 'effect')".to_string(),
            ]
        } else {
            vec![
                "sh".to_string(),
                "-c".to_string(),
                "printf effect > \"$PROCESS_NEGOTIATION_PROBE\"".to_string(),
            ]
        };
        let id = mcp
            .send_process_spawn_request(ProcessSpawnParams {
                env: Some(HashMap::from([(
                    "PROCESS_NEGOTIATION_PROBE".to_string(),
                    Some(probe.display().to_string()),
                )])),
                ..process_spawn_params("blocked".to_string(), codex_home.path(), command)?
            })
            .await?;
        let error = timeout(
            DEFAULT_READ_TIMEOUT,
            mcp.read_stream_until_error_message(RequestId::Integer(id)),
        )
        .await??;
        assert_eq!(
            error.error.message,
            "process/spawn requires negotiated processIndeterminate and both process/exited and process/indeterminate notifications"
        );
        assert!(!probe.exists());
    }
    Ok(())
}
