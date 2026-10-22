use anyhow::Context;
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_final_assistant_message_sse_response;
use app_test_support::create_mock_responses_server_sequence;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStartedNotification;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_protocol::models::BUILT_IN_PERMISSION_PROFILE_DANGER_FULL_ACCESS;
use pretty_assertions::assert_eq;
use std::time::Duration;
use tempfile::TempDir;
use tokio::time::timeout;

const READ_TIMEOUT: Duration = Duration::from_secs(/*secs*/ 25);

async fn complete_turn(mcp: &mut TestAppServer, thread_id: &str, text: &str) -> Result<String> {
    let TurnStartResponse { turn } = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread_id.to_owned(),
                input: vec![UserInput::Text {
                    text: text.to_owned(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    let started: TurnStartedNotification =
        timeout(READ_TIMEOUT, mcp.read_notification("turn/started")).await??;
    assert_eq!(
        (started.thread_id.as_str(), started.turn.id),
        (thread_id, turn.id.clone())
    );
    let completed: TurnCompletedNotification =
        timeout(READ_TIMEOUT, mcp.read_notification("turn/completed")).await??;
    assert_eq!(
        (
            completed.thread_id.as_str(),
            completed.turn.id,
            completed.turn.status
        ),
        (thread_id, turn.id.clone(), TurnStatus::Completed)
    );
    Ok(turn.id)
}

#[tokio::test]
async fn completed_turn_can_be_followed_by_one_start_without_weakening_permissions() -> Result<()> {
    let server = create_mock_responses_server_sequence(vec![
        create_final_assistant_message_sse_response("First complete")?,
        create_final_assistant_message_sse_response("Second complete")?,
        create_final_assistant_message_sse_response("Third complete")?,
    ])
    .await;
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri()).write(codex_home.path())?;
    std::fs::write(
        codex_home.path().join("managed_config.toml"),
        "sandbox_mode = \"read-only\"\n",
    )?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized()
        .await?;
    let thread = mcp.start_thread(ThreadStartParams::default()).await?.thread;
    let first = complete_turn(&mut mcp, &thread.id, "first").await?;
    let second = complete_turn(&mut mcp, &thread.id, "second immediately after completion").await?;
    assert_ne!(first, second);

    // This request also crosses the observation path, but receives no permission
    // from having observed a completed turn or from any elapsed wait budget.
    let rejected = mcp
        .send_turn_start_request(TurnStartParams {
            thread_id: thread.id.clone(),
            input: vec![UserInput::Text {
                text: "reject-forbidden-profile-fence-coverage".to_string(),
                text_elements: Vec::new(),
            }],
            permissions: Some(BUILT_IN_PERMISSION_PROFILE_DANGER_FULL_ACCESS.to_string()),
            ..Default::default()
        })
        .await?;
    let error = timeout(
        READ_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(rejected)),
    )
    .await??;
    assert_eq!(error.error.code, -32600);
    assert!(
        error
            .error
            .message
            .contains("requirements do not allow `sandbox_mode = \"danger-full-access\"`")
    );
    let third = complete_turn(&mut mcp, &thread.id, "third after rejected permission").await?;
    assert_ne!(third, first);
    assert_ne!(third, second);
    // This must be the final MCP read: its read_line-backed helper can lose a
    // partial frame on timeout, so the client is not reused after cancellation.
    assert!(
        timeout(
            Duration::from_millis(/*millis*/ 250),
            mcp.read_notification::<TurnStartedNotification>("turn/started"),
        )
        .await
        .is_err(),
        "only the three admitted turns may emit turn/started"
    );
    let requests = server
        .received_requests()
        .await
        .context("request capture")?;
    assert_eq!(
        requests
            .iter()
            .filter(|request| request.url.path().ends_with("/responses"))
            .count(),
        3
    );
    for request in requests
        .iter()
        .filter(|request| request.url.path().ends_with("/responses"))
    {
        let payload = std::str::from_utf8(&request.body)?;
        assert!(!payload.contains("reject-forbidden-profile-fence-coverage"));
    }
    Ok(())
}
