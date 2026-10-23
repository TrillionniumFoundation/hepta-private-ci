use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_mock_responses_server_repeating_assistant;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use pretty_assertions::assert_eq;
use std::time::Duration;
use tempfile::TempDir;
use tokio::time::timeout;
const DEFAULT_READ_TIMEOUT: Duration = Duration::from_secs(10);

#[tokio::test]
async fn metadata_resume_subscribes_the_same_unmaterialized_persistent_thread_before_first_input()
-> Result<()> {
    let model = create_mock_responses_server_repeating_assistant("unused").await;
    let home = TempDir::new()?;
    MockResponsesConfig::new(&model.uri()).write(home.path())?;
    let mut client = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let start = client
        .send_thread_start_request_with_auto_env(ThreadStartParams {
            ephemeral: Some(false),
            ..Default::default()
        })
        .await?;
    let started: ThreadStartResponse =
        timeout(DEFAULT_READ_TIMEOUT, client.read_response(start)).await??;
    let resume = client
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: started.thread.id.clone(),
            exclude_turns: true,
            ..Default::default()
        })
        .await?;
    let resumed: ThreadResumeResponse =
        timeout(DEFAULT_READ_TIMEOUT, client.read_response(resume)).await??;
    assert_eq!(resumed.thread.id, started.thread.id);
    assert_eq!(resumed.thread.session_id, started.thread.session_id);
    assert!(resumed.thread.turns.is_empty());
    assert!(!resumed.thread.ephemeral);
    assert!(
        model
            .received_requests()
            .await
            .unwrap_or_default()
            .iter()
            .all(|request| !request.url.path().ends_with("/responses"))
    );
    Ok(())
}
