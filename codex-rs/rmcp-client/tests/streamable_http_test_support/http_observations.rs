use std::sync::Arc;
use std::sync::atomic::AtomicU16;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_exec_server::ExecServerError;
use codex_exec_server::HttpClient;
use codex_exec_server::HttpRequestParams;
use codex_exec_server::HttpRequestResponse;
use codex_exec_server::HttpResponseBodyStream;
use futures::FutureExt as _;
use futures::future::BoxFuture;

/// Fixed-size, per-client observations of the existing HTTP calls only.
///
/// Debug reads each atomic independently, so this is not a coherent snapshot
/// or proof that another task cannot finish after it. No URL, headers, body,
/// stream contents, timing policy, or process-global state is captured.
#[derive(Debug, Default)]
pub(super) struct HttpObservations {
    buffered_started: AtomicUsize,
    buffered_completed: AtomicUsize,
    buffered_errors: AtomicUsize,
    buffered_last_status: AtomicU16,
    streamed_started: AtomicUsize,
    streamed_headers: AtomicUsize,
    streamed_errors: AtomicUsize,
    streamed_last_status: AtomicU16,
}

pub(super) struct ObservedHttpClient {
    pub(super) inner: Arc<dyn HttpClient>,
    pub(super) observations: Arc<HttpObservations>,
}

impl HttpClient for ObservedHttpClient {
    fn http_request(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<HttpRequestResponse, ExecServerError>> {
        async move {
            self.observations
                .buffered_started
                .fetch_add(/*val*/ 1, Ordering::Relaxed);
            let result = self.inner.http_request(params).await;
            match &result {
                Ok(response) => {
                    self.observations
                        .buffered_last_status
                        .store(response.status, Ordering::Relaxed);
                    self.observations
                        .buffered_completed
                        .fetch_add(/*val*/ 1, Ordering::Relaxed);
                }
                Err(_) => {
                    self.observations
                        .buffered_errors
                        .fetch_add(/*val*/ 1, Ordering::Relaxed);
                }
            }
            result
        }
        .boxed()
    }

    fn http_request_stream(
        &self,
        params: HttpRequestParams,
    ) -> BoxFuture<'_, Result<(HttpRequestResponse, HttpResponseBodyStream), ExecServerError>> {
        async move {
            self.observations
                .streamed_started
                .fetch_add(/*val*/ 1, Ordering::Relaxed);
            let result = self.inner.http_request_stream(params).await;
            match &result {
                Ok((response, _stream)) => {
                    self.observations
                        .streamed_last_status
                        .store(response.status, Ordering::Relaxed);
                    self.observations
                        .streamed_headers
                        .fetch_add(/*val*/ 1, Ordering::Relaxed);
                }
                Err(_) => {
                    self.observations
                        .streamed_errors
                        .fetch_add(/*val*/ 1, Ordering::Relaxed);
                }
            }
            result
        }
        .boxed()
    }
}
