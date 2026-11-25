//! JSON-RPC-backed `HttpClient` implementation.
//!
//! This code runs in the orchestrator process. It does not issue network
//! requests directly; instead it forwards buffered `http/request` and versioned
//! cancellable streaming requests to the remote runtime
//! and then reconstructs streamed bodies from `http/request/bodyDelta`
//! notifications on the shared connection.

use std::sync::Arc;

use futures::FutureExt;
use futures::future::BoxFuture;
use tokio::sync::mpsc;

use super::HttpResponseBodyStream;
use super::response_body_stream::HttpBodyStreamRegistration;
use super::stream_cancellation::HttpStreamCancellation;
use crate::HttpClient;
use crate::client::ExecServerClient;
use crate::client::ExecServerError;
use crate::protocol::HTTP_REQUEST_CANCELLABLE_METHOD;
use crate::protocol::HTTP_REQUEST_METHOD;
use crate::protocol::HTTP_REQUEST_RESTRICTED_METHOD;
use crate::protocol::HttpRequestParams;
use crate::protocol::HttpRequestResponse;
use crate::protocol::HttpRequestRestrictedParams;

/// Maximum queued body frames per streamed HTTP response.
const HTTP_BODY_DELTA_CHANNEL_CAPACITY: usize = 256;

enum HttpStreamAccess {
    Unrestricted,
    ConfiguredResource(String),
}

impl ExecServerClient {
    /// Performs an HTTP request and buffers the response body.
    pub async fn http_request(
        &self,
        mut params: HttpRequestParams,
    ) -> Result<HttpRequestResponse, ExecServerError> {
        params.stream_response = false;
        self.call(HTTP_REQUEST_METHOD, &params).await
    }

    /// Performs a cancellable HTTP request and returns a body stream.
    ///
    /// The method sets `stream_response` and replaces any caller-supplied
    /// `request_id` with a connection-local id, so late deltas from abandoned
    /// streams cannot be confused with later requests. Older executors must
    /// reject the versioned method; there is no unrestricted streaming fallback.
    pub async fn http_request_stream(
        &self,
        params: HttpRequestParams,
    ) -> Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError> {
        self.http_request_stream_with_access(params, HttpStreamAccess::Unrestricted)
            .await
    }

    /// Sends a mandatory restricted request over the same connection that owns
    /// its cancellation. A missing method is an error, never an ordinary retry.
    pub async fn http_request_stream_restricted(
        &self,
        params: HttpRequestRestrictedParams,
    ) -> Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError> {
        self.http_request_stream_with_access(
            params.request,
            HttpStreamAccess::ConfiguredResource(params.configured_resource_origin),
        )
        .await
    }

    async fn http_request_stream_with_access(
        &self,
        mut params: HttpRequestParams,
        access: HttpStreamAccess,
    ) -> Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError> {
        let rpc_client = self.rpc_client().await?;
        params.stream_response = true;
        let request_id = self.inner.next_http_body_stream_request_id()?;
        params.request_id = request_id.clone();
        let cancellation = Arc::new(HttpStreamCancellation::new(
            Arc::clone(&rpc_client),
            request_id.clone(),
        ));
        let (tx, rx) = mpsc::channel(HTTP_BODY_DELTA_CHANNEL_CAPACITY);
        self.inner
            .insert_http_body_stream(request_id.clone(), tx, Arc::clone(&cancellation))
            .await?;
        let mut registration = HttpBodyStreamRegistration::new(
            Arc::clone(&self.inner),
            request_id.clone(),
            Arc::clone(&cancellation),
        );
        let result = match access {
            HttpStreamAccess::Unrestricted => {
                self.call_rpc(&rpc_client, HTTP_REQUEST_CANCELLABLE_METHOD, &params)
                    .await
            }
            HttpStreamAccess::ConfiguredResource(configured_resource_origin) => {
                self.call_rpc(
                    &rpc_client,
                    HTTP_REQUEST_RESTRICTED_METHOD,
                    &HttpRequestRestrictedParams {
                        request: params,
                        configured_resource_origin,
                    },
                )
                .await
            }
        };
        let response = match result {
            Ok(response) => response,
            Err(error) => {
                cancellation.cancel();
                self.inner.remove_http_body_stream(&request_id).await;
                registration.disarm();
                return Err(error);
            }
        };
        registration.disarm();
        Ok((
            response,
            HttpResponseBodyStream::remote(Arc::clone(&self.inner), request_id, rx, cancellation),
        ))
    }
}

impl HttpClient for ExecServerClient {
    fn http_request_stream_restricted(
        &self,
        params: HttpRequestRestrictedParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        async move { ExecServerClient::http_request_stream_restricted(self, params).await }.boxed()
    }

    /// Orchestrator-side adapter that forwards buffered HTTP requests to the
    /// remote runtime over the shared JSON-RPC connection.
    fn http_request(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        async move { ExecServerClient::http_request(self, params).await }.boxed()
    }

    /// Orchestrator-side adapter that forwards streamed HTTP requests to the
    /// remote runtime and exposes body deltas as a byte stream.
    fn http_request_stream(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        async move { ExecServerClient::http_request_stream(self, params).await }.boxed()
    }
}
