use anyhow::Result;
use codex_extension_api::ModelProviderRequestKind;
use codex_extension_api::ModelProviderTerminal;
use codex_extension_api::ModelProviderTransport;
use codex_features::Feature;
use codex_login::CodexAuth;
use codex_protocol::items::TurnItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ItemCompletedEvent;
use codex_protocol::protocol::Op;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_compact_response_sequence;
use core_test_support::responses::mount_response_sequence;
use core_test_support::responses::mount_sse_once;
use core_test_support::responses::sse;
use core_test_support::responses::sse_response;
use core_test_support::responses::start_mock_server;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::test_codex;
use core_test_support::wait_for_event;
use serde_json::json;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::time::Instant;
use tokio::time::timeout;
use wiremock::ResponseTemplate;

use super::compact::SUMMARY_TEXT;
use super::compact::non_openai_model_provider;
use super::compact::openai_model_provider;
use super::compact::set_test_compact_prompt;
use super::model_provider_policy::ProviderAttemptObservation;
use super::model_provider_policy::ProviderPolicyState;
use super::model_provider_policy::TestDecision;
use super::model_provider_policy::extensions_with_policy;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_policy_block_prevents_local_compaction_send_and_retry() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    let state = ProviderPolicyState::new(true, TestDecision::Block);
    let mut provider = non_openai_model_provider(&server);
    provider.stream_max_retries = Some(3);
    let mut builder = test_codex()
        .with_config(move |config| {
            config.model_provider = provider;
            set_test_compact_prompt(config);
        })
        .with_extensions(extensions_with_policy(Arc::clone(&state)));
    let test = builder.build(&server).await?;

    test.codex.submit(Op::Compact).await?;
    let error = wait_for_event(&test.codex, |event| matches!(event, EventMsg::Error(_))).await;
    let EventMsg::Error(error) = error else {
        unreachable!("event predicate requires an error")
    };
    assert!(
        error
            .message
            .contains("blocked by the test provider policy")
    );
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;

    assert_eq!(state.begin_count.load(Ordering::SeqCst), 1);
    assert_eq!(state.terminal_count.load(Ordering::SeqCst), 0);
    assert!(
        server
            .received_requests()
            .await
            .unwrap_or_default()
            .into_iter()
            .all(|request| request.url.path() != "/v1/responses")
    );
    assert_eq!(observations(&state), vec![http_compaction_observation()]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_policy_terminal_precedes_local_compaction_replacement() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    let response_mock = mount_sse_once(
        &server,
        sse(vec![
            ev_assistant_message("summary-message", SUMMARY_TEXT),
            ev_completed("summary-response"),
        ]),
    )
    .await;
    let state = ProviderPolicyState::new(true, TestDecision::Allow);
    let provider = non_openai_model_provider(&server);
    let mut builder = test_codex()
        .with_config(move |config| {
            config.model_provider = provider;
            set_test_compact_prompt(config);
        })
        .with_extensions(extensions_with_policy(Arc::clone(&state)));
    let test = builder.build(&server).await?;

    test.codex.submit(Op::Compact).await?;
    timeout(Duration::from_secs(5), state.wait_for_terminal_count(1)).await?;
    assert_eq!(response_mock.requests().len(), 1);
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 1);
    assert_eq!(state.completed_count.load(Ordering::SeqCst), 1);
    assert_compaction_replacement_pending(&test.codex).await;

    state.terminal_release.add_permits(1);
    wait_for_event(&test.codex, |event| {
        matches!(
            event,
            EventMsg::ItemCompleted(ItemCompletedEvent {
                item: TurnItem::ContextCompaction(_),
                ..
            })
        )
    })
    .await;
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;

    assert_eq!(state.terminal_count.load(Ordering::SeqCst), 1);
    assert_eq!(observations(&state), vec![http_compaction_observation()]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_policy_claims_each_remote_v2_compaction_retry() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    let response_mock = mount_response_sequence(
        &server,
        vec![
            ResponseTemplate::new(500)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({"error": {"message": "retry remote compaction"}})),
            sse_response(sse(vec![
                json!({
                    "type": "response.output_item.done",
                    "item": {
                        "type": "compaction",
                        "encrypted_content": "REMOTE_V2_SUMMARY",
                    }
                }),
                ev_completed("remote-v2-response"),
            ])),
        ],
    )
    .await;
    let state = ProviderPolicyState::new(true, TestDecision::Allow);
    let provider = openai_model_provider(&server);
    let mut builder = test_codex()
        .with_auth(CodexAuth::create_dummy_chatgpt_auth_for_testing())
        .with_config(move |config| {
            config.model_provider = provider;
            set_test_compact_prompt(config);
            config
                .features
                .enable(Feature::RemoteCompactionV2)
                .expect("test config should allow remote compaction v2");
        })
        .with_extensions(extensions_with_policy(Arc::clone(&state)));
    let test = builder.build(&server).await?;

    test.codex.submit(Op::Compact).await?;
    timeout(Duration::from_secs(5), state.wait_for_terminal_count(1)).await?;
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 1);
    assert_eq!(response_mock.requests().len(), 1);
    assert!(matches!(
        terminals(&state).as_slice(),
        [ModelProviderTerminal::Indeterminate {
            reason_code,
            partial_response_sha256: None,
        }] if reason_code == "provider_http_send_failed"
    ));

    state.terminal_release.add_permits(1);
    timeout(Duration::from_secs(5), state.wait_for_terminal_count(2)).await?;
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 2);
    assert_eq!(response_mock.requests().len(), 2);
    assert_eq!(state.completed_count.load(Ordering::SeqCst), 1);
    assert!(matches!(
        terminals(&state).as_slice(),
        [
            ModelProviderTerminal::Indeterminate { .. },
            ModelProviderTerminal::Completed { .. }
        ]
    ));
    assert_compaction_replacement_pending(&test.codex).await;

    state.terminal_release.add_permits(1);
    wait_for_event(&test.codex, |event| {
        matches!(
            event,
            EventMsg::ItemCompleted(ItemCompletedEvent {
                item: TurnItem::ContextCompaction(_),
                ..
            })
        )
    })
    .await;
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;

    assert_eq!(
        observations(&state),
        vec![http_compaction_observation(), http_compaction_observation()]
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_policy_block_prevents_remote_v1_compaction_send() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    mount_sse_once(
        &server,
        sse(vec![
            ev_response_created("seed-response"),
            ev_assistant_message("seed-message", "seed history"),
            ev_completed("seed-response"),
        ]),
    )
    .await;
    let compact_mock = mount_compact_response_sequence(
        &server,
        vec![
            ResponseTemplate::new(500)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({"error": {"message": "retry inactive compact"}})),
            ResponseTemplate::new(200)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({
                    "output": [{
                        "type": "compaction",
                        "encrypted_content": "INACTIVE_RETRY_SUMMARY",
                    }],
                })),
        ],
    )
    .await;
    let state = ProviderPolicyState::new(false, TestDecision::Block);
    let mut provider = openai_model_provider(&server);
    provider.request_max_retries = Some(1);
    let mut builder = test_codex()
        .with_auth(CodexAuth::create_dummy_chatgpt_auth_for_testing())
        .with_config(move |config| {
            config.model_provider = provider;
            set_test_compact_prompt(config);
            let _ = config.features.disable(Feature::RemoteCompactionV2);
        })
        .with_extensions(extensions_with_policy(Arc::clone(&state)));
    let test = builder.build(&server).await?;

    test.submit_turn("seed history before governed compaction")
        .await?;
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 0);
    test.codex.submit(Op::Compact).await?;
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;
    assert_eq!(compact_mock.requests().len(), 2);
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 0);

    state.set_active(true);
    test.codex.submit(Op::Compact).await?;

    let error = wait_for_event(&test.codex, |event| matches!(event, EventMsg::Error(_))).await;
    let EventMsg::Error(error) = error else {
        unreachable!("event predicate requires an error")
    };
    assert!(
        error
            .message
            .contains("blocked by the test provider policy")
    );
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;

    assert_eq!(state.begin_count.load(Ordering::SeqCst), 1);
    assert_eq!(state.terminal_count.load(Ordering::SeqCst), 0);
    assert_eq!(compact_mock.requests().len(), 2);
    assert_eq!(observations(&state), vec![http_compaction_observation()]);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_policy_claims_each_remote_v1_compaction_retry() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = start_mock_server().await;
    mount_sse_once(
        &server,
        sse(vec![
            ev_response_created("seed-response"),
            ev_assistant_message("seed-message", "seed history"),
            ev_completed("seed-response"),
        ]),
    )
    .await;
    let compact_mock = mount_compact_response_sequence(
        &server,
        vec![
            ResponseTemplate::new(500)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({"error": {"message": "retry compact"}})),
            ResponseTemplate::new(200)
                .insert_header("content-type", "application/json")
                .set_body_json(json!({
                    "output": [{
                        "type": "compaction",
                        "encrypted_content": "REMOTE_V1_SUMMARY",
                    }],
                })),
        ],
    )
    .await;
    let state = ProviderPolicyState::new(false, TestDecision::Allow);
    let mut provider = openai_model_provider(&server);
    provider.request_max_retries = Some(1);
    let mut builder = test_codex()
        .with_auth(CodexAuth::create_dummy_chatgpt_auth_for_testing())
        .with_config(move |config| {
            config.model_provider = provider;
            set_test_compact_prompt(config);
            let _ = config.features.disable(Feature::RemoteCompactionV2);
        })
        .with_extensions(extensions_with_policy(Arc::clone(&state)));
    let test = builder.build(&server).await?;

    test.submit_turn("seed history before governed compaction")
        .await?;
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 0);
    state.set_active(true);
    test.codex.submit(Op::Compact).await?;

    timeout(Duration::from_secs(5), state.wait_for_terminal_count(1)).await?;
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 1);
    assert_eq!(compact_mock.requests().len(), 1);
    assert!(matches!(
        terminals(&state).as_slice(),
        [ModelProviderTerminal::Indeterminate {
            reason_code,
            partial_response_sha256: None,
        }] if reason_code == "provider_http_send_failed"
    ));
    assert_compaction_replacement_pending(&test.codex).await;

    state.terminal_release.add_permits(1);
    timeout(Duration::from_secs(5), state.wait_for_terminal_count(2)).await?;
    assert_eq!(state.begin_count.load(Ordering::SeqCst), 2);
    assert_eq!(compact_mock.requests().len(), 2);
    assert_eq!(state.completed_count.load(Ordering::SeqCst), 1);
    assert!(matches!(
        terminals(&state).as_slice(),
        [
            ModelProviderTerminal::Indeterminate { .. },
            ModelProviderTerminal::CompletedUnary { .. }
        ]
    ));
    assert_compaction_replacement_pending(&test.codex).await;

    state.terminal_release.add_permits(1);
    wait_for_event(&test.codex, |event| {
        matches!(
            event,
            EventMsg::ItemCompleted(ItemCompletedEvent {
                item: TurnItem::ContextCompaction(_),
                ..
            })
        )
    })
    .await;
    wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnComplete(_))
    })
    .await;

    assert_eq!(
        observations(&state),
        vec![http_compaction_observation(), http_compaction_observation()]
    );
    Ok(())
}

async fn assert_compaction_replacement_pending(codex: &codex_core::CodexThread) {
    let deadline = Instant::now() + Duration::from_millis(50);
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return;
        }
        match timeout(remaining, codex.next_event()).await {
            Err(_) => return,
            Ok(Err(error)) => panic!("event stream ended before compact completion: {error}"),
            Ok(Ok(event)) => assert!(
                !matches!(
                    event.msg,
                    EventMsg::ItemCompleted(ItemCompletedEvent {
                        item: TurnItem::ContextCompaction(_),
                        ..
                    }) | EventMsg::TurnComplete(_)
                ),
                "compaction replaced history before provider terminal acknowledgement"
            ),
        }
    }
}

fn observations(state: &ProviderPolicyState) -> Vec<ProviderAttemptObservation> {
    state
        .attempts
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .clone()
}

fn terminals(state: &ProviderPolicyState) -> Vec<ModelProviderTerminal> {
    state
        .terminals
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .clone()
}

fn http_compaction_observation() -> ProviderAttemptObservation {
    ProviderAttemptObservation {
        request_kind: ModelProviderRequestKind::Compaction,
        transport: ModelProviderTransport::Http,
        has_previous_response: false,
        generate: true,
    }
}
