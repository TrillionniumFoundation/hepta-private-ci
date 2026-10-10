use crate::auth::SharedAuthProvider;
use crate::dispatch_metadata::RequestDispatchMetadata;
use crate::error::ApiError;
use crate::provider::Provider;
use crate::telemetry::run_with_request_telemetry;
use codex_client::EncodedJsonBody;
use codex_client::HttpTransport;
use codex_client::Request;
use codex_client::RequestBody;
use codex_client::RequestTelemetry;
use codex_client::Response;
use codex_client::StreamResponse;
use codex_client::TransportError;
use http::HeaderMap;
use http::Method;
use serde_json::Value;
use std::sync::Arc;
use tracing::instrument;

pub(crate) struct EndpointSession<T: HttpTransport> {
    transport: T,
    provider: Provider,
    auth: SharedAuthProvider,
    request_telemetry: Option<Arc<dyn RequestTelemetry>>,
}

impl<T: HttpTransport> EndpointSession<T> {
    pub(crate) fn new(transport: T, provider: Provider, auth: SharedAuthProvider) -> Self {
        Self {
            transport,
            provider,
            auth,
            request_telemetry: None,
        }
    }

    pub(crate) fn with_request_telemetry(
        mut self,
        request: Option<Arc<dyn RequestTelemetry>>,
    ) -> Self {
        self.request_telemetry = request;
        self
    }

    pub(crate) fn provider(&self) -> &Provider {
        &self.provider
    }

    fn make_request(
        &self,
        method: &Method,
        path: &str,
        extra_headers: &HeaderMap,
        body: Option<&RequestBody>,
    ) -> Request {
        let mut req = self.provider.build_request(method.clone(), path);
        req.headers.extend(extra_headers.clone());
        if let Some(body) = body {
            req.body = Some(body.clone());
        }
        req
    }

    pub(crate) async fn execute(
        &self,
        method: Method,
        path: &str,
        extra_headers: HeaderMap,
        body: Option<Value>,
    ) -> Result<Response, ApiError> {
        self.execute_with(method, path, extra_headers, body, |_| {})
            .await
    }

    #[instrument(
        name = "endpoint_session.execute_with",
        level = "info",
        skip_all,
        fields(http.method = %method, api.path = path)
    )]
    pub(crate) async fn execute_with<C>(
        &self,
        method: Method,
        path: &str,
        extra_headers: HeaderMap,
        body: Option<Value>,
        configure: C,
    ) -> Result<Response, ApiError>
    where
        C: Fn(&mut Request),
    {
        self.execute_with_retry_mode(
            method,
            path,
            extra_headers,
            body,
            ExecuteRetryMode::ProviderDefault,
            configure,
        )
        .await
    }

    pub(crate) async fn execute_once_with<C>(
        &self,
        method: Method,
        path: &str,
        extra_headers: HeaderMap,
        body: Option<Value>,
        dispatch_metadata: RequestDispatchMetadata,
        configure: C,
    ) -> Result<Response, ApiError>
    where
        C: Fn(&mut Request),
    {
        self.execute_with_retry_mode(
            method,
            path,
            extra_headers,
            body,
            ExecuteRetryMode::SingleTransportAttempt(dispatch_metadata),
            configure,
        )
        .await
    }

    async fn execute_with_retry_mode<C>(
        &self,
        method: Method,
        path: &str,
        extra_headers: HeaderMap,
        body: Option<Value>,
        retry_mode: ExecuteRetryMode,
        configure: C,
    ) -> Result<Response, ApiError>
    where
        C: Fn(&mut Request),
    {
        let body = body.map(RequestBody::Json);
        let make_request = || {
            let mut req = self.make_request(&method, path, &extra_headers, body.as_ref());
            configure(&mut req);
            req
        };

        let mut retry_policy = self.provider.retry.to_policy();
        let dispatch_metadata = match retry_mode {
            ExecuteRetryMode::ProviderDefault => None,
            ExecuteRetryMode::SingleTransportAttempt(metadata) => {
                retry_policy.max_attempts = 0;
                Some(metadata)
            }
        };
        let response = run_with_request_telemetry(
            retry_policy,
            self.request_telemetry.clone(),
            make_request,
            |req| {
                let auth = self.auth.clone();
                let transport = &self.transport;
                let dispatch_metadata = dispatch_metadata.clone();
                async move {
                    let req = auth.apply_auth(req).await.map_err(TransportError::from)?;
                    if let Some(dispatch_metadata) = dispatch_metadata {
                        dispatch_metadata
                            .validate_headers(&req.headers)
                            .map_err(TransportError::Build)?;
                        dispatch_metadata.mark_transport_invoked();
                    }
                    transport.execute(req).await
                }
            },
        )
        .await?;

        Ok(response)
    }

    #[instrument(
        name = "endpoint_session.stream_encoded_json_with",
        level = "info",
        skip_all,
        fields(http.method = %method, api.path = path)
    )]
    pub(crate) async fn stream_encoded_json_with<C>(
        &self,
        method: Method,
        path: &str,
        extra_headers: HeaderMap,
        body: Option<EncodedJsonBody>,
        configure: C,
    ) -> Result<StreamResponse, ApiError>
    where
        C: Fn(&mut Request),
    {
        self.stream_encoded_json_with_retry_mode(
            method,
            path,
            extra_headers,
            body,
            StreamRetryMode::ProviderDefault,
            configure,
        )
        .await
    }

    /// Streams one encoded request without transparent transport retries.
    ///
    /// Hosts that durably claim physical provider sends use this entry point so
    /// every later retry must return through the host's claim boundary.
    pub(crate) async fn stream_encoded_json_once_with<C>(
        &self,
        method: Method,
        path: &str,
        extra_headers: HeaderMap,
        body: Option<EncodedJsonBody>,
        dispatch_metadata: RequestDispatchMetadata,
        configure: C,
    ) -> Result<StreamResponse, ApiError>
    where
        C: Fn(&mut Request),
    {
        self.stream_encoded_json_with_retry_mode(
            method,
            path,
            extra_headers,
            body,
            StreamRetryMode::SingleTransportAttempt(dispatch_metadata),
            configure,
        )
        .await
    }

    async fn stream_encoded_json_with_retry_mode<C>(
        &self,
        method: Method,
        path: &str,
        extra_headers: HeaderMap,
        body: Option<EncodedJsonBody>,
        retry_mode: StreamRetryMode,
        configure: C,
    ) -> Result<StreamResponse, ApiError>
    where
        C: Fn(&mut Request),
    {
        let body = body.map(RequestBody::EncodedJson);
        let mut request = self.make_request(&method, path, &extra_headers, body.as_ref());
        configure(&mut request);
        let request = request.into_prepared().map_err(TransportError::Build)?;
        let make_request = || request.clone();

        let mut retry_policy = self.provider.retry.to_policy();
        if matches!(retry_mode, StreamRetryMode::SingleTransportAttempt(_)) {
            // `max_attempts` is the maximum retry index; zero means the
            // initial invocation is made once and is never retried here.
            retry_policy.max_attempts = 0;
        }
        let dispatch_metadata = match retry_mode {
            StreamRetryMode::ProviderDefault => None,
            StreamRetryMode::SingleTransportAttempt(metadata) => Some(metadata),
        };
        let stream = run_with_request_telemetry(
            retry_policy,
            self.request_telemetry.clone(),
            make_request,
            |req| {
                let auth = self.auth.clone();
                let transport = &self.transport;
                let dispatch_metadata = dispatch_metadata.clone();
                async move {
                    let req = auth.apply_auth(req).await.map_err(TransportError::from)?;
                    if let Some(dispatch_metadata) = dispatch_metadata {
                        dispatch_metadata
                            .validate_headers(&req.headers)
                            .map_err(TransportError::Build)?;
                        dispatch_metadata.mark_transport_invoked();
                    }
                    transport.stream(req).await
                }
            },
        )
        .await?;

        Ok(stream)
    }
}

enum StreamRetryMode {
    ProviderDefault,
    SingleTransportAttempt(RequestDispatchMetadata),
}

enum ExecuteRetryMode {
    ProviderDefault,
    SingleTransportAttempt(RequestDispatchMetadata),
}
