use crate::auth::SharedAuthProvider;
use crate::common::ResponseStream;
use crate::common::ResponsesApiRequest;
use crate::dispatch_metadata::RequestDispatchMetadata;
use crate::endpoint::session::EndpointSession;
use crate::error::ApiError;
use crate::provider::Provider;
use crate::requests::Compression;
use crate::requests::headers::build_session_headers;
use crate::requests::headers::insert_header;
use crate::requests::headers::subagent_header;
use crate::sse::spawn_response_stream;
use crate::telemetry::SseTelemetry;
use codex_client::EncodedJsonBody;
use codex_client::HttpTransport;
use codex_client::RequestCompression;
use codex_client::RequestTelemetry;
use codex_protocol::protocol::SessionSource;
use http::HeaderMap;
use http::HeaderValue;
use http::Method;
use serde_json::Value;
use std::sync::Arc;
use std::sync::OnceLock;
use tracing::instrument;

pub struct ResponsesClient<T: HttpTransport> {
    session: EndpointSession<T>,
    sse_telemetry: Option<Arc<dyn SseTelemetry>>,
    redact_response_diagnostics: bool,
}

#[derive(Default)]
pub struct ResponsesOptions {
    pub session_id: Option<String>,
    pub thread_id: Option<String>,
    pub session_source: Option<SessionSource>,
    pub extra_headers: HeaderMap,
    pub compression: Compression,
    pub turn_state: Option<Arc<OnceLock<String>>>,
}

impl<T: HttpTransport> ResponsesClient<T> {
    pub fn new(transport: T, provider: Provider, auth: SharedAuthProvider) -> Self {
        Self {
            session: EndpointSession::new(transport, provider, auth),
            sse_telemetry: None,
            redact_response_diagnostics: false,
        }
    }

    pub fn with_telemetry(
        self,
        request: Option<Arc<dyn RequestTelemetry>>,
        sse: Option<Arc<dyn SseTelemetry>>,
    ) -> Self {
        Self {
            session: self.session.with_request_telemetry(request),
            sse_telemetry: sse,
            redact_response_diagnostics: self.redact_response_diagnostics,
        }
    }

    /// Keeps response metrics while excluding provider-controlled diagnostic payloads.
    pub fn with_redacted_response_diagnostics(mut self) -> Self {
        self.redact_response_diagnostics = true;
        self
    }

    #[instrument(
        name = "responses.stream_request",
        level = "info",
        skip_all,
        fields(
            transport = "responses_http",
            http.method = "POST",
            api.path = "responses"
        )
    )]
    pub async fn stream_request(
        &self,
        request: ResponsesApiRequest,
        options: ResponsesOptions,
    ) -> Result<ResponseStream, ApiError> {
        self.stream_request_with_retry_mode(request, options, StreamRetryMode::ProviderDefault)
            .await
    }

    /// Streams one request without transparent transport retries.
    ///
    /// A host that durably claims each physical provider send may perform a
    /// later retry, but it must call this method again with a fresh claim.
    pub async fn stream_request_single_attempt(
        &self,
        request: ResponsesApiRequest,
        options: ResponsesOptions,
        dispatch_metadata: RequestDispatchMetadata,
    ) -> Result<ResponseStream, ApiError> {
        self.stream_request_with_retry_mode(
            request,
            options,
            StreamRetryMode::SingleTransportAttempt(dispatch_metadata),
        )
        .await
    }

    async fn stream_request_with_retry_mode(
        &self,
        request: ResponsesApiRequest,
        options: ResponsesOptions,
        retry_mode: StreamRetryMode,
    ) -> Result<ResponseStream, ApiError> {
        let ResponsesOptions {
            session_id,
            thread_id,
            session_source,
            extra_headers,
            compression,
            turn_state,
        } = options;

        let body = EncodedJsonBody::encode(&request)
            .map_err(|e| ApiError::Stream(format!("failed to encode responses request: {e}")))?;

        let mut headers = extra_headers;
        if let Some(ref thread_id) = thread_id {
            insert_header(&mut headers, "x-client-request-id", thread_id);
        }
        headers.extend(build_session_headers(session_id, thread_id));
        if let Some(subagent) = subagent_header(&session_source) {
            insert_header(&mut headers, "x-openai-subagent", &subagent);
        }

        self.stream_encoded(body, headers, compression, turn_state, retry_mode)
            .await
    }

    fn path() -> &'static str {
        "responses"
    }

    #[instrument(
        name = "responses.stream",
        level = "info",
        skip_all,
        fields(
            transport = "responses_http",
            http.method = "POST",
            api.path = "responses",
            turn.has_state = turn_state.is_some()
        )
    )]
    pub async fn stream(
        &self,
        body: Value,
        extra_headers: HeaderMap,
        compression: Compression,
        turn_state: Option<Arc<OnceLock<String>>>,
    ) -> Result<ResponseStream, ApiError> {
        let body = EncodedJsonBody::encode(&body)
            .map_err(|e| ApiError::Stream(format!("failed to encode responses request: {e}")))?;
        self.stream_encoded(
            body,
            extra_headers,
            compression,
            turn_state,
            StreamRetryMode::ProviderDefault,
        )
        .await
    }

    async fn stream_encoded(
        &self,
        body: EncodedJsonBody,
        extra_headers: HeaderMap,
        compression: Compression,
        turn_state: Option<Arc<OnceLock<String>>>,
        retry_mode: StreamRetryMode,
    ) -> Result<ResponseStream, ApiError> {
        let request_compression = match compression {
            Compression::None => RequestCompression::None,
            Compression::Zstd => RequestCompression::Zstd,
        };

        let configure = |req: &mut codex_client::Request| {
            req.headers.insert(
                http::header::ACCEPT,
                HeaderValue::from_static("text/event-stream"),
            );
            req.compression = request_compression;
        };
        let stream_response = match retry_mode {
            StreamRetryMode::ProviderDefault => {
                self.session
                    .stream_encoded_json_with(
                        Method::POST,
                        Self::path(),
                        extra_headers,
                        Some(body),
                        configure,
                    )
                    .await?
            }
            StreamRetryMode::SingleTransportAttempt(dispatch_metadata) => {
                self.session
                    .stream_encoded_json_once_with(
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

        Ok(spawn_response_stream(
            stream_response,
            self.session.provider().stream_idle_timeout,
            self.sse_telemetry.clone(),
            turn_state,
            self.redact_response_diagnostics,
        ))
    }
}

enum StreamRetryMode {
    ProviderDefault,
    SingleTransportAttempt(RequestDispatchMetadata),
}
