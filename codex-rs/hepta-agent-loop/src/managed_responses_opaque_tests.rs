#![allow(
    clippy::expect_used,
    reason = "owned loopback opaque continuation qualification"
)]

use super::*;
use crate::ResponsesContinuation;
use codex_api::EncodedRequestTerminal;
use codex_api::OpaqueResponsesContinuation;
use codex_extension_api::ModelProviderTerminal;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::atomic::Ordering;

use super::error_tests::fixture;
use super::error_tests::fixture::*;
use super::error_tests::http_fixture::*;

struct Owner {
    state: Arc<State>,
    private: Vec<u8>,
    supported: Option<bool>,
}

impl ResponsesContinuationOwner for Owner {
    fn supports_opaque_retention(&self) -> bool {
        true
    }

    async fn retain(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
        _: ResponsesContinuation,
    ) -> Result<Digest32> {
        Err(Error::Contract(
            "opaque qualification cannot fall back to typed retention",
        ))
    }

    async fn retain_opaque(
        &mut self,
        binding: &TurnBinding,
        request: &ModelRequest,
        continuation: ResponsesContinuation,
        opaque: OpaqueResponsesContinuation,
    ) -> Result<Digest32> {
        let (expected_binding, expected_request, _) = fixture::request();
        assert_eq!(binding, &expected_binding);
        assert_eq!(request, &expected_request);
        assert_eq!(continuation.usage.output_tokens, 2);
        assert!(self.state.policy.lock().expect("policy lock").is_empty());
        assert!(self.state.encoded.lock().expect("encoded lock").is_empty());
        self.private = opaque
            .private_evidence_json()
            .expect("original private persistence fixture");
        self.supported = Some(opaque.projection_supported());
        self.state.continuations.fetch_add(1, Ordering::SeqCst);
        Ok(Digest32::of_bytes(&self.private))
    }
}

async fn qualify(unknown_field: bool) {
    let mut item = json!({"type":"message", "id":"m1", "role":"assistant", "status":"completed",
        "content":[{"type":"output_text","text":"fixture result","annotations":[]}]});
    if unknown_field {
        item["future"] = json!("PRIVATE_UNKNOWN_FIELD_FIXTURE");
    }
    let wire = [
        json!({"type":"response.output_item.done","item":item}),
        json!({"type":"response.completed","response":{"id":"response:opaque","status":"completed",
            "output":[item],"usage":{"input_tokens":0,"output_tokens":2,"total_tokens":2}}}),
    ]
    .iter()
    .map(|event| format!("data: {event}\n\n"))
    .collect();
    let (client, requests, stop, task) =
        Server::start(200, wire, "text/event-stream").await.parts();
    let (binding, request, api_request) = fixture::request();
    let state = State::new(&api_request);
    let dispatch = RequestDispatchMetadata::new();
    let mut owner = Owner {
        state: state.clone(),
        private: Vec::new(),
        supported: None,
    };
    let (events, mut received) = mpsc::channel(8);
    let result = client
        .stream_admitted_opaque(
            ManagedResponsesAttempt {
                binding: &binding,
                request: &request,
                expected_model: "diagnostic-fixture",
                api_request,
                options: ResponsesOptions {
                    encoded_body_observer: Some(Arc::new(Observer(state.clone()))),
                    ..Default::default()
                },
                dispatch: dispatch.clone(),
                lease: Box::new(Lease(state.clone())),
                maximum_elapsed: Duration::from_secs(5),
                terminal_timeout: Duration::from_secs(2),
                bridge_limits: ResponsesBridgeLimits {
                    maximum_items: 4,
                    maximum_retained_bytes: 8192,
                    maximum_visible_bytes: 256,
                },
            },
            None,
            &mut owner,
            events,
            &CancellationToken::new(),
        )
        .await;
    stop.cancel();
    task.await.expect("loopback server stopped");
    assert_eq!(
        requests.lock().expect("requests").len(),
        1,
        "one original physical attempt"
    );
    assert!(dispatch.transport_invoked());
    assert_eq!(state.bodies.load(Ordering::SeqCst), 1);
    assert_eq!(state.continuations.load(Ordering::SeqCst), 1);
    assert_eq!(owner.supported, Some(!unknown_field));
    let policy = state.policy.lock().expect("policy receipt");
    assert_eq!(policy.len(), 1);
    assert!(
        matches!(&policy[0], ModelProviderTerminal::Completed { .. }),
        "actual provider usage retained even when native projection rejects"
    );
    let encoded = state.encoded.lock().expect("encoded receipt");
    assert_eq!(encoded.len(), 1);
    assert!(matches!(
        &encoded[0],
        EncodedRequestTerminal::Completed { .. }
    ));
    let mut completed = false;
    while let Ok(event) = received.try_recv() {
        if matches!(event.expect("native event"), ModelEvent::Completed { .. }) {
            completed = true;
        }
    }
    assert_eq!(completed, !unknown_field);
    if unknown_field {
        assert!(matches!(
            result,
            Err(Error::Contract("opaque continuation semantics unsupported"))
        ));
        assert!(
            std::str::from_utf8(&owner.private)
                .expect("private JSON")
                .contains("PRIVATE_UNKNOWN_FIELD_FIXTURE")
        );
    } else {
        assert!(matches!(
            result,
            Ok(ManagedResponsesObservation {
                status: ResponsesBridgeStatus::Completed,
                ..
            })
        ));
    }
}

#[tokio::test]
async fn raw_completed_items_are_retained_by_original_owner_before_both_terminal_acks() {
    qualify(false).await;
}

#[tokio::test]
async fn unknown_fields_are_private_and_durable_but_never_native_completion() {
    qualify(true).await;
}

#[tokio::test]
async fn old_owner_cannot_silently_claim_opaque_retention() {
    let (binding, request, api_request) = fixture::request();
    let state = State::new(&api_request);
    let mut owner = Continuation(state.clone());
    let evidence = br#"{"schema":"responses-opaque-continuation:v1","events":[{"type":"response.completed","response":{"id":"response:empty","output":[]}}]}"#;
    let opaque =
        ResponseCapture::restore_private_evidence(evidence, 4, 8192, "response:empty", &[])
            .expect("private synthetic terminal");
    let result = owner
        .retain_opaque(
            &binding,
            &request,
            ResponsesContinuation {
                provider_response_id: "response:empty".into(),
                server_model: None,
                items: Vec::new(),
                usage: Default::default(),
                provider_rollout_budget_units: None,
                end_turn: Some(true),
            },
            opaque,
        )
        .await;
    assert!(matches!(
        result,
        Err(Error::Contract(
            "original continuation owner has no opaque retention"
        ))
    ));
    assert_eq!(state.continuations.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn missing_opaque_owner_is_rejected_before_a_physical_send() {
    let (client, requests, stop, task) = Server::start(200, String::new(), "text/event-stream")
        .await
        .parts();
    let (binding, request, api_request) = fixture::request();
    let state = State::new(&api_request);
    let dispatch = RequestDispatchMetadata::new();
    let mut owner = Continuation(state.clone());
    let (events, mut received) = mpsc::channel(8);
    let result = client
        .stream_admitted_opaque(
            ManagedResponsesAttempt {
                binding: &binding,
                request: &request,
                expected_model: "diagnostic-fixture",
                api_request,
                options: ResponsesOptions {
                    encoded_body_observer: Some(Arc::new(Observer(state.clone()))),
                    ..Default::default()
                },
                dispatch: dispatch.clone(),
                lease: Box::new(Lease(state.clone())),
                maximum_elapsed: Duration::from_secs(5),
                terminal_timeout: Duration::from_secs(2),
                bridge_limits: ResponsesBridgeLimits {
                    maximum_items: 4,
                    maximum_retained_bytes: 8192,
                    maximum_visible_bytes: 256,
                },
            },
            None,
            &mut owner,
            events,
            &CancellationToken::new(),
        )
        .await;
    stop.cancel();
    task.await.expect("loopback server stopped");
    assert!(matches!(
        result,
        Err(Error::Contract("prepared managed Responses attempt"))
    ));
    assert!(requests.lock().expect("requests").is_empty());
    assert!(!dispatch.transport_invoked());
    assert_eq!(state.bodies.load(Ordering::SeqCst), 0);
    assert_eq!(state.continuations.load(Ordering::SeqCst), 0);
    assert!(received.try_recv().is_err());
    let policy = state.policy.lock().expect("policy receipt");
    assert_eq!(policy.len(), 1);
    assert!(matches!(
        &policy[0],
        ModelProviderTerminal::NotDispatched { .. }
    ));
    let encoded = state.encoded.lock().expect("encoded receipt");
    assert_eq!(encoded.len(), 1);
    assert!(matches!(
        &encoded[0],
        EncodedRequestTerminal::Abandoned { .. }
    ));
}
