use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::Mutex;
use std::task::Context;
use std::task::Poll;

use codex_exec_server_protocol::JSONRPCErrorError;
use tokio_util::sync::CancellationToken;

use crate::protocol::HttpRequestCancelResponse;
use crate::rpc::invalid_params;

const MAX_ACTIVE_HTTP_STREAMS: usize = 256;
const MAX_HTTP_STREAM_ID_BYTES: usize = 128;

#[derive(Clone, Default)]
pub(super) struct HttpRequestScopes {
    active: Arc<Mutex<HashMap<String, Arc<ScopeState>>>>,
}

#[derive(Default)]
struct ScopeState {
    cancelled: CancellationToken,
    finished: CancellationToken,
}

/// One connection's guard follows the request future into its response producer.
/// Its owner must drop the network future/response before releasing this guard.
pub(super) struct HttpRequestScope {
    scopes: HttpRequestScopes,
    request_id: String,
    state: Arc<ScopeState>,
}

/// Rust drops fields in declaration order, including when this future has
/// never been polled. The network future must be gone before the scope can
/// acknowledge completion on another thread.
pub(super) struct ScopedHttpFuture<F> {
    network: Pin<Box<F>>,
    _scope: HttpRequestScope,
}

impl<F> ScopedHttpFuture<F> {
    pub(super) fn new(network: F, scope: HttpRequestScope) -> Self {
        Self {
            network: Box::pin(network),
            _scope: scope,
        }
    }
}

impl<F: Future> Future for ScopedHttpFuture<F> {
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        self.get_mut().network.as_mut().poll(context)
    }
}

impl HttpRequestScopes {
    // This runs during synchronous router setup, before request admission.
    pub(super) fn reserve(&self, request_id: &str) -> Result<HttpRequestScope, JSONRPCErrorError> {
        let mut active = self
            .active
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if request_id.is_empty() || request_id.len() > MAX_HTTP_STREAM_ID_BYTES {
            return Err(invalid_params("invalid HTTP stream request id".to_string()));
        }
        if active.contains_key(request_id) {
            return Err(invalid_params(format!(
                "http/request streamResponse requestId `{request_id}` is already active"
            )));
        }
        if active.len() >= MAX_ACTIVE_HTTP_STREAMS {
            return Err(invalid_params("too many active HTTP streams".to_string()));
        }
        let state = Arc::new(ScopeState::default());
        active.insert(request_id.to_string(), Arc::clone(&state));
        Ok(HttpRequestScope {
            scopes: self.clone(),
            request_id: request_id.to_string(),
            state,
        })
    }

    pub(super) fn cancellation(&self, request_id: &str) -> Option<CancellationToken> {
        self.active
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(request_id)
            .map(|state| state.cancelled.clone())
    }

    pub(super) async fn cancel(&self, request_id: &str) -> HttpRequestCancelResponse {
        let state = self
            .active
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(request_id)
            .cloned();
        let Some(state) = state else {
            return HttpRequestCancelResponse::NotActive;
        };
        state.cancelled.cancel();
        state.finished.cancelled().await;
        HttpRequestCancelResponse::Cancelled
    }
}

impl HttpRequestScope {
    pub(super) fn cancellation(&self) -> CancellationToken {
        self.state.cancelled.clone()
    }
}

impl Drop for HttpRequestScope {
    fn drop(&mut self) {
        let mut active = self
            .scopes
            .active
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if active
            .get(&self.request_id)
            .is_some_and(|state| Arc::ptr_eq(state, &self.state))
        {
            active.remove(&self.request_id);
        }
        self.state.finished.cancel();
    }
}

#[cfg(test)]
#[path = "http_request_scope_tests.rs"]
mod tests;
