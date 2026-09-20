use std::time::Duration;

use codex_api::ApiError;
use codex_api::RequestDispatchMetadata;
use codex_api::ResponseEvent;
use codex_api::TransportError;
use codex_extension_api::ModelProviderAttemptLease;
use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderPolicyFuture;
use codex_extension_api::ModelProviderTerminal;
use codex_model_provider::SharedModelProvider;
use codex_model_provider::create_model_provider;
use codex_model_provider_info::WireApi;
use codex_model_provider_info::create_oss_provider_with_base_url;
use codex_otel::SessionTelemetry;
use codex_protocol::ThreadId;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::SessionSource;
use codex_rollout_trace::InferenceTraceAttempt;
use futures::FutureExt;
use futures::StreamExt;
use http::StatusCode;
use tokio::sync::oneshot;
use tokio::sync::oneshot::error::TryRecvError;

use super::map_response_events;
use crate::model_provider_policy::ProviderAttemptOwner;
use crate::model_provider_policy::bytes_sha256;
use crate::model_provider_policy::canonical_sha256;

struct GatedLease {
    terminal: oneshot::Sender<ModelProviderTerminal>,
    acknowledge: oneshot::Receiver<Result<(), ModelProviderPolicyError>>,
}

impl ModelProviderAttemptLease for GatedLease {
    fn finish(
        self: Box<Self>,
        terminal: ModelProviderTerminal,
    ) -> ModelProviderPolicyFuture<'static, ()> {
        Box::pin(async move {
            let _ = self.terminal.send(terminal);
            self.acknowledge.await.map_err(|_| {
                ModelProviderPolicyError::new(
                    "test_acknowledgement_dropped",
                    "test terminal acknowledgement sender dropped",
                )
            })?
        })
    }
}

fn gated_owner() -> (
    ProviderAttemptOwner,
    oneshot::Receiver<ModelProviderTerminal>,
    oneshot::Sender<Result<(), ModelProviderPolicyError>>,
) {
    let (terminal_tx, terminal_rx) = oneshot::channel();
    let (acknowledge_tx, acknowledge_rx) = oneshot::channel();
    let owner = ProviderAttemptOwner::new(
        Box::new(GatedLease {
            terminal: terminal_tx,
            acknowledge: acknowledge_rx,
        }),
        RequestDispatchMetadata::new(),
    );
    (owner, terminal_rx, acknowledge_tx)
}

fn test_provider() -> SharedModelProvider {
    create_model_provider(
        create_oss_provider_with_base_url("https://example.com/v1", WireApi::Responses),
        /*auth_manager*/ None,
    )
}

fn test_telemetry() -> SessionTelemetry {
    SessionTelemetry::new(
        ThreadId::new(),
        "gpt-test",
        "gpt-test",
        /*account_id*/ None,
        /*account_email*/ None,
        /*auth_mode*/ None,
        "test-originator".to_string(),
        /*log_user_prompts*/ false,
        "test-terminal".to_string(),
        SessionSource::Cli,
    )
}

fn output_item() -> ResponseItem {
    ResponseItem::Message {
        id: None,
        role: "assistant".to_string(),
        content: vec![ContentItem::OutputText {
            text: "bounded output".to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

#[tokio::test]
async fn completed_is_hidden_until_exact_terminal_is_acknowledged() {
    let item = output_item();
    let events = futures::stream::iter([
        Ok(ResponseEvent::OutputItemDone(item.clone())),
        Ok(ResponseEvent::Completed {
            response_id: "response-1".to_string(),
            token_usage: None,
            end_turn: Some(true),
        }),
    ]);
    let (owner, terminal_rx, acknowledge_tx) = gated_owner();
    let (mut stream, mut last_response) = map_response_events(
        /*upstream_request_id*/ None,
        events,
        test_telemetry(),
        InferenceTraceAttempt::disabled(),
        test_provider(),
        Some(owner),
        /*redact_provider_errors*/ false,
    );

    assert!(matches!(
        stream.next().await,
        Some(Ok(ResponseEvent::OutputItemDone(_)))
    ));
    assert!(matches!(last_response.try_recv(), Err(TryRecvError::Empty)));
    assert_eq!(
        terminal_rx.await.expect("terminal should be proposed"),
        ModelProviderTerminal::Completed {
            response_id_sha256: bytes_sha256(b"response-1").expect("response digest"),
            response_items_sha256: canonical_sha256(&std::slice::from_ref(&item))
                .expect("items digest"),
            token_usage_sha256: canonical_sha256(&Option::<()>::None).expect("usage digest"),
            end_turn: Some(true),
        }
    );
    assert!(stream.next().now_or_never().is_none());

    acknowledge_tx
        .send(Ok(()))
        .expect("terminal acknowledgement should be accepted");
    assert!(matches!(
        stream.next().await,
        Some(Ok(ResponseEvent::Completed { .. }))
    ));
    assert_eq!(
        last_response
            .await
            .expect("last response follows terminal acknowledgement")
            .items_added,
        vec![item]
    );
}

#[tokio::test]
async fn terminal_failure_suppresses_completed_and_last_response() {
    let events = futures::stream::iter([Ok(ResponseEvent::Completed {
        response_id: "response-1".to_string(),
        token_usage: None,
        end_turn: None,
    })]);
    let (owner, terminal_rx, acknowledge_tx) = gated_owner();
    let (mut stream, last_response) = map_response_events(
        /*upstream_request_id*/ None,
        events,
        test_telemetry(),
        InferenceTraceAttempt::disabled(),
        test_provider(),
        Some(owner),
        /*redact_provider_errors*/ false,
    );

    assert!(matches!(
        terminal_rx.await.expect("terminal should be proposed"),
        ModelProviderTerminal::Completed { .. }
    ));
    acknowledge_tx
        .send(Err(ModelProviderPolicyError::new(
            "test_terminal_rejected",
            "terminal persistence failed",
        )))
        .expect("terminal failure should be accepted");

    let error = stream
        .next()
        .await
        .expect("policy failure should be emitted")
        .expect_err("completed must be suppressed");
    assert!(error.to_string().contains("test_terminal_rejected"));
    assert!(last_response.await.is_err());
}

#[tokio::test]
async fn consumer_drop_records_partial_indeterminate_terminal() {
    let item = output_item();
    let events = futures::stream::iter([Ok(ResponseEvent::OutputItemDone(item.clone()))])
        .chain(futures::stream::pending());
    let (owner, terminal_rx, acknowledge_tx) = gated_owner();
    let (mut stream, _last_response) = map_response_events(
        /*upstream_request_id*/ None,
        events,
        test_telemetry(),
        InferenceTraceAttempt::disabled(),
        test_provider(),
        Some(owner),
        /*redact_provider_errors*/ false,
    );

    assert!(stream.next().await.is_some());
    drop(stream);
    assert_eq!(
        terminal_rx.await.expect("drop should close the attempt"),
        ModelProviderTerminal::Indeterminate {
            reason_code: "provider_response_consumer_dropped".to_string(),
            partial_response_sha256: Some(
                canonical_sha256(&[item]).expect("partial response digest")
            ),
        }
    );
    acknowledge_tx
        .send(Ok(()))
        .expect("terminal acknowledgement should be accepted");
}

#[tokio::test]
async fn unauthorized_stream_error_records_rejected_before_downstream_error() {
    let events = futures::stream::iter([Err(ApiError::Transport(TransportError::Http {
        status: StatusCode::UNAUTHORIZED,
        url: None,
        headers: None,
        body: None,
    }))]);
    let (owner, terminal_rx, acknowledge_tx) = gated_owner();
    let (mut stream, _last_response) = map_response_events(
        /*upstream_request_id*/ None,
        events,
        test_telemetry(),
        InferenceTraceAttempt::disabled(),
        test_provider(),
        Some(owner),
        /*redact_provider_errors*/ false,
    );

    assert_eq!(
        terminal_rx.await.expect("401 should propose terminal"),
        ModelProviderTerminal::Rejected {
            reason_code: "provider_response_unauthorized".to_string(),
        }
    );
    assert!(stream.next().now_or_never().is_none());
    acknowledge_tx
        .send(Ok(()))
        .expect("terminal acknowledgement should be accepted");
    assert!(matches!(stream.next().await, Some(Err(_))));
}

#[tokio::test]
async fn eof_records_partial_indeterminate_terminal() {
    let item = output_item();
    let events = futures::stream::iter([Ok(ResponseEvent::OutputItemDone(item.clone()))]);
    let (owner, terminal_rx, acknowledge_tx) = gated_owner();
    let (mut stream, _last_response) = map_response_events(
        /*upstream_request_id*/ None,
        events,
        test_telemetry(),
        InferenceTraceAttempt::disabled(),
        test_provider(),
        Some(owner),
        /*redact_provider_errors*/ false,
    );

    assert!(stream.next().await.is_some());
    assert_eq!(
        terminal_rx.await.expect("EOF should close the attempt"),
        ModelProviderTerminal::Indeterminate {
            reason_code: "provider_response_stream_closed".to_string(),
            partial_response_sha256: Some(
                canonical_sha256(&[item]).expect("partial response digest")
            ),
        }
    );
    acknowledge_tx
        .send(Ok(()))
        .expect("terminal acknowledgement should be accepted");
    assert!(stream.next().await.is_none());
}

#[tokio::test]
async fn terminal_acknowledgement_wait_is_not_consumer_timeout_driven() {
    let events = futures::stream::iter([Ok(ResponseEvent::Completed {
        response_id: "response-1".to_string(),
        token_usage: None,
        end_turn: None,
    })]);
    let (owner, terminal_rx, acknowledge_tx) = gated_owner();
    let (mut stream, _last_response) = map_response_events(
        /*upstream_request_id*/ None,
        events,
        test_telemetry(),
        InferenceTraceAttempt::disabled(),
        test_provider(),
        Some(owner),
        /*redact_provider_errors*/ false,
    );

    let _ = terminal_rx.await.expect("terminal should be proposed");
    assert!(
        tokio::time::timeout(Duration::from_millis(10), stream.next())
            .await
            .is_err()
    );
    acknowledge_tx
        .send(Ok(()))
        .expect("terminal acknowledgement should be accepted");
    assert!(matches!(
        stream.next().await,
        Some(Ok(ResponseEvent::Completed { .. }))
    ));
}
