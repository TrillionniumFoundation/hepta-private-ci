use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio::runtime::Handle;
use tracing::debug;
use tracing::warn;

use crate::protocol::HTTP_REQUEST_CANCEL_METHOD;
use crate::protocol::HttpRequestCancelParams;
use crate::protocol::HttpRequestCancelResponse;
use crate::rpc::RpcClient;

const HTTP_CANCELLATION_ACK_TIMEOUT: Duration = Duration::from_secs(5);

/// Retained before spawning so even an unpolled or aborted cleanup task closes
/// only its original transport when no response has been received.
struct CancellationAttempt {
    rpc_client: Arc<RpcClient>,
    response_received: bool,
}

impl Drop for CancellationAttempt {
    fn drop(&mut self) {
        if !self.response_received {
            self.rpc_client.request_transport_close();
        }
    }
}

/// A stream can cancel only on the original physical connection. No recovery,
/// new connection lookup, or reuse of a later request id is allowed here.
pub(super) struct HttpStreamCancellation {
    rpc_client: Arc<RpcClient>,
    request_id: String,
    ended: AtomicBool,
}

impl HttpStreamCancellation {
    pub(super) fn new(rpc_client: Arc<RpcClient>, request_id: String) -> Self {
        Self {
            rpc_client,
            request_id,
            ended: AtomicBool::new(false),
        }
    }

    pub(super) fn complete(&self) {
        self.ended.store(true, Ordering::Release);
    }

    pub(super) fn cancel(&self) {
        if self.ended.swap(true, Ordering::AcqRel) {
            return;
        }
        let Ok(handle) = Handle::try_current() else {
            // A synchronous drop must not leave a live original transport behind
            // merely because its caller no longer runs inside a Tokio runtime.
            self.rpc_client.request_transport_close();
            return;
        };
        let rpc_client = Arc::clone(&self.rpc_client);
        let params = HttpRequestCancelParams {
            request_id: self.request_id.clone(),
        };
        let deadline = tokio::time::Instant::now() + HTTP_CANCELLATION_ACK_TIMEOUT;
        let attempt = CancellationAttempt {
            rpc_client: Arc::clone(&rpc_client),
            response_received: false,
        };
        handle.spawn(async move {
            // Retain the whole guard in the task. Capturing only its Copy bool
            // would drop the original guard as soon as cancel returns.
            let mut attempt = attempt;
            match tokio::time::timeout_at(
                deadline,
                rpc_client.call_for_cleanup::<_, HttpRequestCancelResponse>(
                    HTTP_REQUEST_CANCEL_METHOD,
                    &params,
                ),
            )
            .await
            {
                Ok(Ok(response)) => {
                    attempt.response_received = true;
                    match response {
                        HttpRequestCancelResponse::Cancelled => {
                            debug!("HTTP request owner acknowledged cancellation")
                        }
                        HttpRequestCancelResponse::NotActive => {
                            debug!("HTTP cancellation found no active request owner")
                        }
                    }
                }
                Ok(Err(_)) | Err(_) => {
                    // Unsupported or failed cleanup is not success. Close only the
                    // captured connection so its server shutdown owns remaining work.
                    warn!("HTTP cancellation outcome unknown; closing its original RPC connection");
                    rpc_client.close_transport().await;
                }
            }
        });
    }
}

#[cfg(test)]
#[path = "http_stream_cancellation_tests.rs"]
mod tests;
