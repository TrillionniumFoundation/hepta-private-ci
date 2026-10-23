//! Actual API send-boundary controls, not a model or I10 qualification.

use super::*;
use codex_api::EncodedRequestBodyObserver;
use futures::future::BoxFuture;
use pretty_assertions::assert_eq;

#[derive(Debug, Default)]
struct BodyObserver {
    bodies: Mutex<Vec<Vec<u8>>>,
    reject: bool,
}

impl EncodedRequestBodyObserver for BodyObserver {
    fn observe_encoded_body<'a>(&'a self, body: &'a [u8]) -> BoxFuture<'a, Result<(), String>> {
        Box::pin(async move {
            self.bodies
                .lock()
                .expect("observer body lock")
                .push(body.to_vec());
            if self.reject {
                Err("controlled observer refusal".to_string())
            } else {
                Ok(())
            }
        })
    }
}

#[derive(Clone, Copy, Debug)]
enum Mutation {
    HeadersOnly,
    Body,
    Url,
    Method,
    Compression,
    ContentType,
    ContentEncoding,
    ContentLength,
    TransferEncoding,
    Host,
    DuplicateFraming,
    Timeout,
}

impl AuthProvider for Mutation {
    fn add_auth_headers(&self, _headers: &mut HeaderMap) {}

    fn apply_auth(&self, mut request: Request) -> codex_api::AuthProviderFuture<'_> {
        let mutation = *self;
        Box::pin(async move {
            match mutation {
                Mutation::HeadersOnly => {
                    request
                        .headers
                        .insert("authorization", HeaderValue::from_static("Bearer fixture"));
                }
                Mutation::Body => {
                    request.body = Some(RequestBody::Raw(Bytes::from_static(b"changed bytes")))
                }
                Mutation::Url => request.url.push_str("/different-destination"),
                Mutation::Method => request.method = http::Method::DELETE,
                Mutation::Compression => {
                    request.compression = codex_client::RequestCompression::Zstd
                }
                Mutation::ContentType => {
                    request.headers.insert(
                        "content-type",
                        HeaderValue::from_static("application/octet-stream"),
                    );
                }
                Mutation::ContentEncoding => {
                    request
                        .headers
                        .insert("content-encoding", HeaderValue::from_static("gzip"));
                }
                Mutation::ContentLength => {
                    request
                        .headers
                        .insert("content-length", HeaderValue::from_static("999"));
                }
                Mutation::TransferEncoding => {
                    request
                        .headers
                        .insert("transfer-encoding", HeaderValue::from_static("chunked"));
                }
                Mutation::Host => {
                    request
                        .headers
                        .insert("host", HeaderValue::from_static("different-vhost"));
                }
                Mutation::DuplicateFraming => {
                    request
                        .headers
                        .append("content-type", HeaderValue::from_static("application/json"));
                }
                Mutation::Timeout => request.timeout = Some(Duration::from_secs(3600)),
            }
            Ok(request)
        })
    }
}

fn request() -> ResponsesApiRequest {
    ResponsesApiRequest {
        model: "fixed-local-profile".into(),
        instructions: "preserve the entire request".into(),
        input: Vec::new(),
        tools: Some(empty_tools().into()),
        tool_choice: "none".into(),
        parallel_tool_calls: false,
        reasoning: None,
        store: false,
        stream: true,
        stream_options: None,
        include: Vec::new(),
        service_tier: None,
        prompt_cache_key: None,
        text: None,
        client_metadata: None,
    }
}

#[tokio::test]
async fn observed_single_attempt_rejects_post_auth_changes_before_dispatch() {
    for compression in [Compression::None, Compression::Zstd] {
        for mutation in [
            Mutation::Body,
            Mutation::Url,
            Mutation::Method,
            Mutation::Compression,
            Mutation::ContentType,
            Mutation::ContentEncoding,
            Mutation::ContentLength,
            Mutation::TransferEncoding,
            Mutation::Host,
            Mutation::DuplicateFraming,
            Mutation::Timeout,
        ] {
            let state = RecordingState::default();
            let observer = Arc::new(BodyObserver::default());
            let client = ResponsesClient::new(
                RecordingTransport::new(state.clone()),
                provider("local"),
                Arc::new(mutation),
            );
            let dispatch = RequestDispatchMetadata::new();
            let result = client
                .stream_request_single_attempt(
                    request(),
                    ResponsesOptions {
                        compression,
                        encoded_body_observer: Some(observer.clone()),
                        ..Default::default()
                    },
                    dispatch.clone(),
                )
                .await;
            assert_eq!(
                (
                    matches!(result, Err(ApiError::Transport(TransportError::Build(_)))),
                    state.take_stream_requests().len(),
                    dispatch.transport_invoked()
                ),
                (true, 0, false),
                "{mutation:?}"
            );
            assert_eq!(observer.bodies.lock().unwrap().len(), 1);
        }
    }
}

#[tokio::test]
async fn observed_default_retry_path_is_rejected_before_observation_or_send() {
    let state = RecordingState::default();
    let observer = Arc::new(BodyObserver::default());
    let client = ResponsesClient::new(
        RecordingTransport::new(state.clone()),
        provider("local"),
        Arc::new(Mutation::HeadersOnly),
    );
    let result = client
        .stream_request(
            request(),
            ResponsesOptions {
                encoded_body_observer: Some(observer.clone()),
                ..Default::default()
            },
        )
        .await;
    assert!(matches!(result, Err(ApiError::Stream(_))));
    assert!(state.take_stream_requests().is_empty());
    assert!(observer.bodies.lock().unwrap().is_empty());
}

#[tokio::test]
async fn observed_single_attempt_allows_header_auth_and_unchanged_compressed_bytes() {
    for compression in [Compression::None, Compression::Zstd] {
        let state = RecordingState::default();
        let observer = Arc::new(BodyObserver::default());
        let client = ResponsesClient::new(
            RecordingTransport::new(state.clone()),
            provider("local"),
            Arc::new(Mutation::HeadersOnly),
        );
        let dispatch = RequestDispatchMetadata::new();
        let _stream = client
            .stream_request_single_attempt(
                request(),
                ResponsesOptions {
                    compression,
                    encoded_body_observer: Some(observer.clone()),
                    ..Default::default()
                },
                dispatch.clone(),
            )
            .await
            .unwrap();
        let sent = state.take_stream_requests();
        assert_eq!(sent.len(), 1);
        assert!(dispatch.transport_invoked());
        let mut expected = Request::new(http::Method::POST, sent[0].url.clone());
        expected.body = Some(RequestBody::EncodedJson(
            codex_client::EncodedJsonBody::encode(&request()).unwrap(),
        ));
        expected.compression = match compression {
            Compression::None => codex_client::RequestCompression::None,
            Compression::Zstd => codex_client::RequestCompression::Zstd,
        };
        let expected = expected.into_prepared().unwrap();
        assert_eq!(request_body_bytes(&sent[0]), request_body_bytes(&expected));
        assert_eq!(
            observer.bodies.lock().unwrap().as_slice(),
            &[serde_json::to_vec(&request()).unwrap()]
        );
        assert_eq!(
            sent[0].headers.get("authorization"),
            Some(&HeaderValue::from_static("Bearer fixture"))
        );
    }
}

#[tokio::test]
async fn observed_refusal_never_reaches_auth_or_transport() {
    let state = RecordingState::default();
    let client = ResponsesClient::new(
        RecordingTransport::new(state.clone()),
        provider("local"),
        Arc::new(Mutation::Body),
    );
    let dispatch = RequestDispatchMetadata::new();
    let result = client
        .stream_request_single_attempt(
            request(),
            ResponsesOptions {
                encoded_body_observer: Some(Arc::new(BodyObserver {
                    reject: true,
                    ..Default::default()
                })),
                ..Default::default()
            },
            dispatch.clone(),
        )
        .await;
    assert!(matches!(result, Err(ApiError::Stream(_))));
    assert!(state.take_stream_requests().is_empty());
    assert!(!dispatch.transport_invoked());
}

#[tokio::test]
async fn observed_connection_failure_is_not_retried() {
    let transport = FlakyTransport::new();
    let mut provider = provider("local");
    provider.retry.max_attempts = 3;
    let client = ResponsesClient::new(transport.clone(), provider, Arc::new(NoAuth));
    let dispatch = RequestDispatchMetadata::new();
    let result = client
        .stream_request_single_attempt(
            request(),
            ResponsesOptions {
                encoded_body_observer: Some(Arc::new(BodyObserver::default())),
                ..Default::default()
            },
            dispatch.clone(),
        )
        .await;
    assert!(result.is_err());
    assert_eq!(transport.attempts(), 1);
    assert!(dispatch.transport_invoked());
}

#[tokio::test]
async fn unobserved_default_path_retains_authoritative_auth_replacement() {
    let state = RecordingState::default();
    let client = ResponsesClient::new(
        RecordingTransport::new(state.clone()),
        provider("local"),
        Arc::new(Mutation::Body),
    );
    let _stream = client
        .stream_request(request(), ResponsesOptions::default())
        .await
        .unwrap();
    let sent = state.take_stream_requests();
    assert_eq!(sent.len(), 1);
    assert_eq!(
        sent[0].prepare_body_for_send().unwrap().body_bytes(),
        Bytes::from_static(b"changed bytes")
    );
}
