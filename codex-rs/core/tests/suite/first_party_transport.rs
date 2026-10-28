use anyhow::Result;
use codex_core::CodexThread;
use codex_core::TurnInputRequest;
use codex_core::config::Config;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_features::Feature;
use codex_model_provider_info::OPENAI_API_BASE_URL;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::user_input::UserInput;
use core_test_support::first_party::FirstPartyMockServer;
use core_test_support::responses::ev_completed;
use core_test_support::responses::mount_sse_sequence;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

struct CountThreadStarts(Arc<AtomicUsize>);

impl ThreadLifecycleContributor<Config> for CountThreadStarts {
    fn on_thread_start<'a>(
        &'a self,
        _input: ThreadStartInput<'a, Config>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            self.0.fetch_add(1, Ordering::SeqCst);
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn owned_http_fixture_preserves_metadata_and_contributors_on_resume_and_fork() -> Result<()> {
    skip_if_no_network!(Ok(()));
    let server = FirstPartyMockServer::start().await?;
    let requests = mount_sse_sequence(
        &server,
        vec![
            sse(vec![ev_completed("first")]),
            sse(vec![ev_completed("resumed")]),
            sse(vec![ev_completed("forked")]),
        ],
    )
    .await;
    let starts = Arc::new(AtomicUsize::new(0));
    let mut registry = ExtensionRegistryBuilder::new();
    registry.thread_lifecycle_contributor(Arc::new(CountThreadStarts(Arc::clone(&starts))));
    let mut builder = server
        .test_codex()
        .with_extensions(Arc::new(registry.build()));
    let initial = builder.build(&server).await?;
    assert_eq!(
        initial.config.model_provider.base_url.as_deref(),
        Some(OPENAI_API_BASE_URL)
    );
    let rollout = initial
        .session_configured
        .rollout_path
        .clone()
        .expect("rollout path");
    submit_and_shutdown(&initial.codex, "first fixture turn").await?;

    // Reuse the same builder: its ordinary one-shot config mutators have
    // already run, but the scoped fixture must remain attached on resume.
    let resumed = builder
        .resume(&server, initial.home.clone(), rollout.clone())
        .await?;
    assert_eq!(
        resumed.config.model_provider.base_url.as_deref(),
        Some(OPENAI_API_BASE_URL)
    );
    submit_and_shutdown(&resumed.codex, "resumed fixture turn").await?;
    let forked = resumed
        .thread_manager
        .fork_thread(
            /*snapshot*/ 0usize,
            resumed.config.clone(),
            rollout,
            /*thread_source*/ None,
            /*parent_trace*/ None,
        )
        .await?;
    submit_and_shutdown(&forked.thread, "forked fixture turn").await?;

    assert_eq!(starts.load(Ordering::SeqCst), 3);
    let requests = requests.requests();
    assert_eq!(requests.len(), 3);
    for (request, expected_text) in requests.iter().zip([
        "first fixture turn",
        "resumed fixture turn",
        "forked fixture turn",
    ]) {
        assert!(request.has_content_kinds(&["user.text"]));
        assert!(
            request
                .message_input_texts("user")
                .iter()
                .any(|text| text == expected_text)
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_loopback_provider_still_strips_internal_metadata() -> Result<()> {
    skip_if_no_network!(Ok(()));
    let server = start_mock_server().await;
    let requests = mount_sse_sequence(&server, vec![sse(vec![ev_completed("ordinary")])]).await;
    let test = test_codex()
        .with_config(|config| {
            config
                .features
                .enable(Feature::ContentItemKinds)
                .expect("test feature");
        })
        .build(&server)
        .await?;
    submit_and_shutdown(&test.codex, "ordinary loopback turn").await?;
    let request = requests.single_request();
    assert!(
        request
            .message_input_texts("user")
            .iter()
            .any(|text| text == "ordinary loopback turn")
    );
    assert!(!request.has_content_kinds(&["user.text"]));
    for item in request.input() {
        assert!(
            item.get("internal_chat_message_metadata_passthrough")
                .is_none()
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn owned_http_fixture_rejects_provider_and_websocket_overrides_before_model_requests()
-> Result<()> {
    skip_if_no_network!(Ok(()));
    let server = FirstPartyMockServer::start().await?;
    let result = server
        .test_codex()
        .with_config(|config| {
            config.model_provider.base_url = Some("https://not-first-party.example/v1".to_string());
        })
        .build(&server)
        .await;
    let Err(error) = result else {
        panic!("provider override must be rejected");
    };
    assert!(format!("{error:#}").contains("first-party HTTP fixture requires"));
    let result = server
        .test_codex()
        .with_config(|config| {
            config.model_provider.supports_websockets = true;
        })
        .build(&server)
        .await;
    let Err(error) = result else {
        panic!("WebSocket override must be rejected");
    };
    assert!(format!("{error:#}").contains("first-party HTTP fixture requires"));
    assert!(
        server
            .received_requests()
            .await
            .expect("recorded requests")
            .is_empty()
    );
    Ok(())
}

async fn submit_and_shutdown(thread: &Arc<CodexThread>, text: &str) -> Result<()> {
    thread
        .start_or_steer_turn(TurnInputRequest::user_input(vec![UserInput::Text {
            text: text.to_string(),
            text_elements: Vec::new(),
        }]))
        .await?;
    wait_for_event(thread, |event| matches!(event, EventMsg::TurnComplete(_))).await;
    thread.submit(Op::Shutdown).await?;
    wait_for_event(thread, |event| matches!(event, EventMsg::ShutdownComplete)).await;
    Ok(())
}
