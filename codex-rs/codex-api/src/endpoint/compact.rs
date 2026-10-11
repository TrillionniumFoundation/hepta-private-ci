use crate::auth::SharedAuthProvider;
use crate::common::CompactionInput;
use crate::dispatch_metadata::RequestDispatchMetadata;
use crate::endpoint::session::EndpointSession;
use crate::error::ApiError;
use crate::provider::Provider;
use codex_client::HttpTransport;
use codex_client::RequestTelemetry;
use codex_protocol::models::ResponseItem;
use http::HeaderMap;
use http::Method;
use serde::Deserialize;
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::Duration;

const X_CODEX_TURN_STATE_HEADER: &str = "x-codex-turn-state";

pub struct CompactClient<T: HttpTransport> {
    session: EndpointSession<T>,
}

impl<T: HttpTransport> CompactClient<T> {
    pub fn new(transport: T, provider: Provider, auth: SharedAuthProvider) -> Self {
        Self {
            session: EndpointSession::new(transport, provider, auth),
        }
    }

    pub fn with_telemetry(self, request: Option<Arc<dyn RequestTelemetry>>) -> Self {
        Self {
            session: self.session.with_request_telemetry(request),
        }
    }

    fn path() -> &'static str {
        "responses/compact"
    }

    pub async fn compact(
        &self,
        body: serde_json::Value,
        extra_headers: HeaderMap,
        request_timeout: Duration,
        turn_state: Option<&OnceLock<String>>,
    ) -> Result<Vec<ResponseItem>, ApiError> {
        self.compact_with_retry_mode(
            body,
            extra_headers,
            request_timeout,
            turn_state,
            CompactRetryMode::ProviderDefault,
        )
        .await
    }

    async fn compact_with_retry_mode(
        &self,
        body: serde_json::Value,
        extra_headers: HeaderMap,
        request_timeout: Duration,
        turn_state: Option<&OnceLock<String>>,
        retry_mode: CompactRetryMode,
    ) -> Result<Vec<ResponseItem>, ApiError> {
        let configure = |req: &mut codex_client::Request| {
            req.timeout = Some(request_timeout);
        };
        let resp = match retry_mode {
            CompactRetryMode::ProviderDefault => {
                self.session
                    .execute_with(
                        Method::POST,
                        Self::path(),
                        extra_headers,
                        Some(body),
                        configure,
                    )
                    .await?
            }
            CompactRetryMode::SingleTransportAttempt(dispatch_metadata) => {
                self.session
                    .execute_once_with(
                        Method::POST,
                        Self::path(),
                        extra_headers,
                        Some(body),
                        dispatch_metadata,
                        configure,
                    )
                    .await?
            }
        };
        if let Some(turn_state) = turn_state
            && let Some(header_value) = resp
                .headers
                .get(X_CODEX_TURN_STATE_HEADER)
                .and_then(|value| value.to_str().ok())
        {
            let _ = turn_state.set(header_value.to_string());
        }
        let parsed: CompactHistoryResponse =
            serde_json::from_slice(&resp.body).map_err(|e| ApiError::Stream(e.to_string()))?;
        Ok(parsed.output)
    }

    pub async fn compact_input(
        &self,
        input: &CompactionInput<'_>,
        extra_headers: HeaderMap,
        request_timeout: Duration,
        turn_state: Option<&OnceLock<String>>,
    ) -> Result<Vec<ResponseItem>, ApiError> {
        let body = serde_json::to_value(input)
            .map_err(|e| ApiError::Stream(format!("failed to encode compaction input: {e}")))?;
        self.compact(body, extra_headers, request_timeout, turn_state)
            .await
    }

    /// Compacts one input without transparent transport retries while exposing
    /// whether the request reached the transport invocation.
    pub async fn compact_input_single_attempt(
        &self,
        input: &CompactionInput<'_>,
        extra_headers: HeaderMap,
        request_timeout: Duration,
        turn_state: Option<&OnceLock<String>>,
        dispatch_metadata: RequestDispatchMetadata,
    ) -> Result<Vec<ResponseItem>, ApiError> {
        let body = serde_json::to_value(input)
            .map_err(|e| ApiError::Stream(format!("failed to encode compaction input: {e}")))?;
        self.compact_with_retry_mode(
            body,
            extra_headers,
            request_timeout,
            turn_state,
            CompactRetryMode::SingleTransportAttempt(dispatch_metadata),
        )
        .await
    }
}

enum CompactRetryMode {
    ProviderDefault,
    SingleTransportAttempt(RequestDispatchMetadata),
}

#[derive(Debug, Deserialize)]
struct CompactHistoryResponse {
    output: Vec<ResponseItem>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::AuthProvider;
    use crate::provider::RetryConfig;
    use codex_client::Request;
    use codex_client::Response;
    use codex_client::StreamResponse;
    use codex_client::TransportError;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    #[derive(Clone, Default)]
    struct DummyTransport;

    impl HttpTransport for DummyTransport {
        async fn execute(&self, _req: Request) -> Result<Response, TransportError> {
            Err(TransportError::Build("execute should not run".to_string()))
        }

        async fn stream(&self, _req: Request) -> Result<StreamResponse, TransportError> {
            Err(TransportError::Build("stream should not run".to_string()))
        }
    }

    #[test]
    fn path_is_responses_compact() {
        assert_eq!(CompactClient::<DummyTransport>::path(), "responses/compact");
    }

    #[derive(Clone, Default)]
    struct FailingTransport {
        attempts: Arc<AtomicUsize>,
    }

    impl HttpTransport for FailingTransport {
        async fn execute(&self, _req: Request) -> Result<Response, TransportError> {
            self.attempts.fetch_add(1, Ordering::SeqCst);
            Err(TransportError::Network("compact send failed".to_string()))
        }

        async fn stream(&self, _req: Request) -> Result<StreamResponse, TransportError> {
            Err(TransportError::Build("stream should not run".to_string()))
        }
    }

    #[derive(Clone, Default)]
    struct NoAuth;

    impl AuthProvider for NoAuth {
        fn add_auth_headers(&self, _headers: &mut HeaderMap) {}
    }

    #[derive(Clone, Default)]
    struct OverridingAuth;

    impl AuthProvider for OverridingAuth {
        fn add_auth_headers(&self, headers: &mut HeaderMap) {
            headers.insert(
                http::HeaderName::from_static("x-codex-routing-hint"),
                http::HeaderValue::from_static("auth-hint"),
            );
        }
    }

    #[tokio::test]
    async fn compact_single_attempt_marks_transport_and_disables_retry() {
        let transport = FailingTransport::default();
        let attempts = Arc::clone(&transport.attempts);
        let provider = Provider {
            name: "test".to_string(),
            base_url: "https://example.test/v1".to_string(),
            query_params: None,
            headers: HeaderMap::new(),
            retry: RetryConfig {
                max_attempts: 3,
                base_delay: Duration::from_millis(1),
                retry_429: false,
                retry_5xx: false,
                retry_transport: true,
            },
            stream_idle_timeout: Duration::from_secs(1),
        };
        let client = CompactClient::new(transport, provider, Arc::new(NoAuth));
        let dispatch_metadata = RequestDispatchMetadata::new();

        let result = client
            .compact_with_retry_mode(
                serde_json::json!({"model": "gpt-test", "input": []}),
                HeaderMap::new(),
                Duration::from_secs(1),
                /*turn_state*/ None,
                CompactRetryMode::SingleTransportAttempt(dispatch_metadata.clone()),
            )
            .await;

        assert!(result.is_err());
        assert_eq!(attempts.load(Ordering::SeqCst), 1);
        assert!(dispatch_metadata.transport_invoked());
    }

    #[tokio::test]
    async fn compact_single_attempt_rejects_auth_header_drift_before_dispatch() {
        let transport = FailingTransport::default();
        let attempts = Arc::clone(&transport.attempts);
        let provider = Provider {
            name: "test".to_string(),
            base_url: "https://example.test/v1".to_string(),
            query_params: None,
            headers: HeaderMap::new(),
            retry: RetryConfig {
                max_attempts: 3,
                base_delay: Duration::from_millis(1),
                retry_429: false,
                retry_5xx: false,
                retry_transport: true,
            },
            stream_idle_timeout: Duration::from_secs(1),
        };
        let client = CompactClient::new(transport, provider, Arc::new(OverridingAuth));
        let routing_hint = http::HeaderName::from_static("x-codex-routing-hint");
        let host_hint = http::HeaderValue::from_static("host-hint");
        let mut extra_headers = HeaderMap::new();
        extra_headers.insert(routing_hint.clone(), host_hint.clone());
        let dispatch_metadata = RequestDispatchMetadata::new_with_expected_headers(vec![(
            routing_hint,
            Some(host_hint),
        )]);

        let result = client
            .compact_with_retry_mode(
                serde_json::json!({"model": "gpt-test", "input": []}),
                extra_headers,
                Duration::from_secs(1),
                /*turn_state*/ None,
                CompactRetryMode::SingleTransportAttempt(dispatch_metadata.clone()),
            )
            .await;

        assert!(matches!(
            result,
            Err(ApiError::Transport(TransportError::Build(message)))
                if message ==
                    "request header state changed after provider policy admission: x-codex-routing-hint"
        ));
        assert_eq!(attempts.load(Ordering::SeqCst), 0);
        assert!(!dispatch_metadata.transport_invoked());
    }
}
