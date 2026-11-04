use anyhow::Context;
use anyhow::Result;
use codex_core::CodexThread;
use codex_core::StartThreadOptions;
use codex_core::TurnInputRequest;
use codex_protocol::mcp::ClientMcpExtensions;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use codex_protocol::user_input::UserInput;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once;
use core_test_support::responses::mount_sse_sequence;
use core_test_support::responses::sse;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use pretty_assertions::assert_eq;
use serde_json::Value;
use std::sync::Arc;
use wiremock::MockServer;

async fn submit(thread: &Arc<CodexThread>, text: &str) -> Result<()> {
    thread
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: text.to_string(),
            text_elements: Vec::new(),
        }]))
        .await?;
    wait_for_event(thread, |event| matches!(event, EventMsg::TurnComplete(_))).await;
    Ok(())
}

fn user_metadata<'a>(body: &'a Value, text: &str) -> Option<&'a Value> {
    body["input"]
        .as_array()
        .expect("request input")
        .iter()
        .find(|item| {
            item["role"] == "user"
                && item["content"].as_array().is_some_and(|parts| {
                    parts.iter().any(|part| part["text"].as_str() == Some(text))
                })
        })
        .expect("submitted user message")
        .get("internal_chat_message_metadata_passthrough")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn metadata_lease_survives_dropping_the_test_container() -> Result<()> {
    let server = MockServer::start().await;
    let response = mount_sse_once(
        &server,
        sse(vec![ev_response_created("extracted"), ev_completed("extracted")]),
    )
    .await;
    let codex = test_codex().build(&server).await?.codex;
    submit(&codex, "extracted client").await?;
    let body = response.single_request().body_json();
    assert!(user_metadata(&body, "extracted client")
        .is_some_and(|metadata| metadata["turn_id"].as_str().is_some()));
    codex.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn metadata_lease_follows_child_and_resumed_sessions_in_the_same_manager() -> Result<()> {
    let server = MockServer::start().await;
    let response = mount_sse_sequence(
        &server,
        ["parent", "child", "resumed"]
            .into_iter()
            .map(|id| sse(vec![ev_response_created(id), ev_completed(id)]))
            .collect(),
    )
    .await;
    let test = test_codex().build(&server).await?;
    test.submit_text_turn("parent request").await?;
    let parent_id = test.session_configured.thread_id;
    let mut options = StartThreadOptions::new(test.config.clone());
    options.session_source = Some(SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
        parent_thread_id: parent_id,
        depth: 1,
        agent_path: None,
        agent_nickname: None,
        agent_role: None,
    }));
    let child = test.thread_manager.start_thread(options).await?;
    submit(&child.thread, "child request").await?;
    child.thread.shutdown_and_wait().await?;
    test.codex.shutdown_and_wait().await?;
    assert!(test.thread_manager.remove_thread(&parent_id).await.is_some());
    let resumed = test
        .thread_manager
        .resume_thread_from_rollout(
            test.config.clone(),
            test.session_configured.rollout_path.clone().context("rollout path")?,
            test.thread_manager.auth_manager(),
            /*parent_trace*/ None,
            ClientMcpExtensions::default(),
        )
        .await?;
    assert_eq!(resumed.session_configured.thread_id, parent_id);
    assert!(!Arc::ptr_eq(&resumed.thread, &test.codex));
    submit(&resumed.thread, "resumed request").await?;
    let requests = response.requests();
    assert_eq!(requests.len(), 3);
    for (request, text) in requests
        .iter()
        .zip(["parent request", "child request", "resumed request"])
    {
        assert!(
            user_metadata(&request.body_json(), text)
                .is_some_and(|metadata| metadata["turn_id"].as_str().is_some()),
            "{text}",
        );
    }
    resumed.thread.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn replacing_provider_in_the_same_manager_does_not_inherit_metadata() -> Result<()> {
    let server = MockServer::start().await;
    let response = mount_sse_once(
        &server,
        sse(vec![ev_response_created("replacement"), ev_completed("replacement")]),
    )
    .await;
    let test = test_codex().build(&server).await?;
    let mut replaced = test.config.clone();
    replaced.model_provider_id = "third-party".to_string();
    replaced.model_provider.name = "Test Responses".to_string();
    let thread = test
        .thread_manager
        .start_thread(StartThreadOptions::new(replaced))
        .await?;
    submit(&thread.thread, "replacement request").await?;
    let body = response.single_request().body_json();
    assert!(user_metadata(&body, "replacement request").is_none());
    thread.thread.shutdown_and_wait().await?;
    test.codex.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn changing_fixture_url_in_the_same_manager_does_not_inherit_metadata() -> Result<()> {
    let original = MockServer::start().await;
    let redirected = MockServer::start().await;
    let response = mount_sse_once(
        &redirected,
        sse(vec![ev_response_created("other-url"), ev_completed("other-url")]),
    )
    .await;
    let test = test_codex().build(&original).await?;
    let mut replaced = test.config.clone();
    replaced.model_provider.base_url = Some(format!("{}/v1", redirected.uri()));
    let thread = test
        .thread_manager
        .start_thread(StartThreadOptions::new(replaced))
        .await?;
    submit(&thread.thread, "other endpoint request").await?;
    let body = response.single_request().body_json();
    assert!(user_metadata(&body, "other endpoint request").is_none());
    thread.thread.shutdown_and_wait().await?;
    test.codex.shutdown_and_wait().await?;
    Ok(())
}
