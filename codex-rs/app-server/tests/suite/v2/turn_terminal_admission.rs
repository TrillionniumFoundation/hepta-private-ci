use anyhow::Context;
use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::ThreadSettingsUpdateParams;
use codex_app_server_protocol::ThreadSettingsUpdateResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use pretty_assertions::assert_eq;
use std::time::Duration;
use tempfile::TempDir;
use test_case::test_case;
use tokio::time::timeout;

#[derive(Clone, Copy)]
enum AfterTerminal {
    NextTurn,
    SettingsAndNextTurn,
}

#[test_case(AfterTerminal::NextTurn; "next_turn")]
#[test_case(AfterTerminal::SettingsAndNextTurn; "settings_and_next_turn")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_turn_immediately_admits_next_client_request(
    action: AfterTerminal,
) -> Result<()> {
    let server = create_mock_responses_server_repeating_assistant("whole completed reply").await;
    let home = TempDir::new()?;
    let workspace = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .with_provider_config("supports_websockets = false")
        .write(home.path())?;
    let mut client = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let thread = client
        .start_thread(ThreadStartParams {
            model: Some("mock-model".into()),
            ..Default::default()
        })
        .await?
        .thread;
    let mut turns = Vec::new();
    for index in 0..16 {
        let request = client
            .send_turn_start_request(TurnStartParams {
                thread_id: thread.id.clone(),
                input: vec![UserInput::Text {
                    text: format!("original consecutive turn {index}"),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            })
            .await?;
        let response: TurnStartResponse =
            timeout(Duration::from_secs(10), client.read_response(request)).await??;
        let completed: TurnCompletedNotification = timeout(
            Duration::from_secs(10),
            client.read_notification("turn/completed"),
        )
        .await??;
        assert_eq!(completed.thread_id, thread.id);
        assert_eq!(completed.turn.id, response.turn.id);
        assert_eq!(completed.turn.status, TurnStatus::Completed);
        assert!(completed.turn.error.is_none());
        turns.push(response.turn.id);
        // No sleep, retry, idle polling or extra RPC between the public
        // terminal and the next client mutation. It must already be admitted.
        if matches!(action, AfterTerminal::SettingsAndNextTurn) {
            let request = client
                .send_thread_settings_update_request(ThreadSettingsUpdateParams {
                    thread_id: thread.id.clone(),
                    cwd: Some(workspace.path().to_owned()),
                    ..Default::default()
                })
                .await?;
            let _: ThreadSettingsUpdateResponse =
                timeout(Duration::from_secs(10), client.read_response(request)).await??;
        }
    }
    let request = client
        .send_thread_read_request(ThreadReadParams {
            thread_id: thread.id,
            include_turns: true,
        })
        .await?;
    let read: ThreadReadResponse =
        timeout(Duration::from_secs(10), client.read_response(request)).await??;
    assert_eq!(
        read.thread
            .turns
            .iter()
            .map(|turn| turn.id.clone())
            .collect::<Vec<_>>(),
        turns
    );
    assert!(
        read.thread
            .turns
            .iter()
            .all(|turn| turn.status == TurnStatus::Completed)
    );
    let requests = server
        .received_requests()
        .await
        .context("original model request log missing")?;
    assert_eq!(
        requests
            .iter()
            .filter(|request| request.url.path().ends_with("/responses"))
            .count(),
        16
    );
    Ok(())
}
