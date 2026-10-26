#![allow(
    clippy::expect_used,
    reason = "owned loopback capped provider qualification"
)]

use super::*;
use crate::ResponsesContinuation;
use codex_api::EncodedRequestTerminal;
use codex_api::OpaqueResponsesIncomplete;
use codex_api::encode_request_with_requested_output_limit;
use codex_extension_api::ModelProviderTerminal;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::atomic::Ordering;

use super::error_tests::fixture;
use super::error_tests::fixture::*;
use super::error_tests::http_fixture::*;

struct Owner {
    state: Arc<State>,
    expected_request: ModelRequest,
    private: Vec<u8>,
    retained_reservation: Option<(u64, u64)>,
    fail_retention: bool,
}

impl ResponsesContinuationOwner for Owner {
    fn supports_opaque_retention(&self) -> bool {
        true
    }
    fn supports_incomplete_retention(&self) -> bool {
        true
    }
    async fn retain(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
        _: ResponsesContinuation,
    ) -> Result<Digest32> {
        Err(Error::Contract("incomplete qualification cannot complete"))
    }
    async fn retain_incomplete(
        &mut self,
        _: &TurnBinding,
        request: &ModelRequest,
        incomplete: OpaqueResponsesIncomplete,
    ) -> Result<Digest32> {
        assert_eq!(request, &self.expected_request);
        assert!(self.state.policy.lock().expect("policy lock").is_empty());
        assert!(self.state.encoded.lock().expect("encoded lock").is_empty());
        if self.fail_retention {
            return Err(Error::Owner(
                "controlled incomplete retention failure".into(),
            ));
        }
        assert_eq!(incomplete.reason().as_str(), "max_output_tokens");
        assert_eq!(incomplete.usage().expect("actual usage").output_tokens, 32);
        self.private = incomplete
            .private_evidence_json()
            .expect("private original-owner retention");
        self.retained_reservation = Some((
            request.maximum_provider_input_tokens,
            request.maximum_output_tokens,
        ));
        Ok(Digest32::of_bytes(&self.private))
    }
}

async fn run_fixture(rejected: bool, fail_retention: bool) {
    let body = if rejected {
        json!({"error":{"type":"invalid_request_error","code":"unsupported_parameter","param":"max_output_tokens","message":"PRIVATE_CAP_REJECTION_FIXTURE"}}).to_string()
    } else {
        format!(
            "data: {}\n\n",
            json!({"type":"response.incomplete", "response":{
            "id":"response:bounded", "status":"incomplete", "max_output_tokens":32,
            "incomplete_details":{"reason":"max_output_tokens"},
            "usage":{"input_tokens":7,"output_tokens":32,"total_tokens":39},
            "output":[{"type":"reasoning","encrypted_content":"PRIVATE_PARTIAL_FIXTURE"}]}})
        )
    };
    let server = Server::start_with_cap(
        if rejected { 400 } else { 200 },
        body,
        if rejected {
            "application/json"
        } else {
            "text/event-stream"
        },
        Some(32),
    )
    .await;
    let (client, requests, stop, task) = server.parts();
    let (binding, mut request, api_request) = fixture::request();
    request.maximum_output_tokens = 32;
    let limit = RequestedOutputLimit::new(32).expect("requested wire limit");
    let body = encode_request_with_requested_output_limit(&api_request, None, limit)
        .expect("exact body for original admission");
    let state = State::for_encoded_body(body.as_bytes());
    let dispatch = RequestDispatchMetadata::new();
    let mut owner = Owner {
        state: state.clone(),
        expected_request: request.clone(),
        private: Vec::new(),
        retained_reservation: None,
        fail_retention,
    };
    let (events, mut received) = mpsc::channel(8);
    let result = client
        .stream_admitted_bounded_opaque(
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
            limit,
            &mut owner,
            events,
            &CancellationToken::new(),
        )
        .await;
    stop.cancel();
    task.await.expect("loopback server stopped");
    assert!(result.is_err());
    assert!(dispatch.transport_invoked());
    let requests = requests.lock().expect("actual requests");
    assert_eq!(
        requests.as_slice(),
        &[true],
        "one actual request retained the cap and original fixture auth; no cap-dropping retry"
    );
    assert_eq!(state.bodies.load(Ordering::SeqCst), 1);
    assert!(
        received.try_recv().is_err(),
        "incomplete must never become native completion"
    );
    let policy = state.policy.lock().expect("original policy terminal");
    assert_eq!(policy.len(), 1);
    match &policy[0] {
        ModelProviderTerminal::Indeterminate {
            partial_response_sha256,
            ..
        } => {
            assert_eq!(
                partial_response_sha256.is_some(),
                !rejected && !fail_retention
            );
            if let Some(digest) = partial_response_sha256 {
                assert_eq!(
                    digest.as_str(),
                    Digest32::of_bytes(&owner.private).to_string()
                );
            }
        }
        _ => {
            panic!("incomplete/rejected uncertain provider outcome cannot be settled as Completed")
        }
    }
    let encoded = state.encoded.lock().expect("original encoded terminal");
    assert_eq!(encoded.len(), 1);
    assert!(matches!(
        &encoded[0],
        EncodedRequestTerminal::Indeterminate { .. }
    ));
    assert_eq!(
        owner.retained_reservation,
        (!rejected && !fail_retention).then_some((8, 32))
    );
}

#[tokio::test]
async fn requested_cap_reaches_transport_and_incomplete_usage_stays_with_original_owner() {
    run_fixture(false, false).await;
}

#[tokio::test]
async fn rejected_cap_is_never_removed_or_retried() {
    run_fixture(true, false).await;
}

#[tokio::test]
async fn failed_incomplete_retention_still_records_both_conservative_terminal_owners() {
    run_fixture(false, true).await;
}

#[tokio::test]
async fn a_wire_limit_different_from_the_original_reservation_is_not_dispatched() {
    let (client, requests, stop, task) =
        Server::start_with_cap(200, String::new(), "text/event-stream", Some(32))
            .await
            .parts();
    let (binding, mut request, api_request) = fixture::request();
    request.maximum_output_tokens = 16;
    let limit = RequestedOutputLimit::new(32).expect("different wire limit");
    let body = encode_request_with_requested_output_limit(&api_request, None, limit).expect("wire");
    let state = State::for_encoded_body(body.as_bytes());
    let dispatch = RequestDispatchMetadata::new();
    let mut owner = Owner {
        state: state.clone(),
        expected_request: request.clone(),
        private: Vec::new(),
        retained_reservation: None,
        fail_retention: false,
    };
    let (events, _) = mpsc::channel(8);
    let result = client
        .stream_admitted_bounded_opaque(
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
            limit,
            &mut owner,
            events,
            &CancellationToken::new(),
        )
        .await;
    stop.cancel();
    task.await.expect("server stopped");
    assert!(matches!(
        result,
        Err(Error::Contract("prepared managed Responses attempt"))
    ));
    assert!(requests.lock().expect("requests").is_empty());
    assert!(!dispatch.transport_invoked());
    assert_eq!(state.bodies.load(Ordering::SeqCst), 0);
    assert!(matches!(
        state.policy.lock().expect("policy").as_slice(),
        [ModelProviderTerminal::NotDispatched { .. }]
    ));
    assert!(matches!(
        state.encoded.lock().expect("encoded").as_slice(),
        [EncodedRequestTerminal::Abandoned { .. }]
    ));
}
