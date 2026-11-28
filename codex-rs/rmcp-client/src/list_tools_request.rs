//! Request-local diagnostics for tools/list, whose response cache is disabled
//! when RmcpClient connects. Preserve the SDK's cancel-on-abandon behavior.

use futures::FutureExt;
use rmcp::model::CancelledNotificationParam;
use rmcp::model::ClientRequest;
use rmcp::model::ListToolsRequest;
use rmcp::model::ListToolsResult;
use rmcp::model::PaginatedRequestParams;
use rmcp::model::RequestId;
use rmcp::model::ServerResult;
use rmcp::service::Peer;
use rmcp::service::PeerRequestOptions;
use rmcp::service::RoleClient;
use rmcp::service::ServiceError;

use crate::local_response_diagnostic::LocalResponseOwner;
use crate::rmcp_client::ClientOperationError;

struct CancelAbandonedRequest {
    peer: Peer<RoleClient>,
    request_id: Option<RequestId>,
}

impl Drop for CancelAbandonedRequest {
    fn drop(&mut self) {
        if let Some(request_id) = self.request_id.take() {
            // SDK try_cancel_request is private. Poll public send once without
            // the task's coop budget (as try_send does), then discard the ACK.
            // Full/closed queues remain best effort; no background task is created.
            let _ = tokio::task::unconstrained(self.peer.notify_cancelled(
                CancelledNotificationParam {
                    request_id: Some(request_id),
                    reason: Some("request abandoned by the caller".to_string()),
                    meta: None,
                },
            ))
            .now_or_never();
        }
    }
}

#[cfg(test)]
#[path = "list_tools_request_tests.rs"]
mod tests;

pub(crate) async fn list_tools(
    peer: &Peer<RoleClient>,
    params: Option<PaginatedRequestParams>,
) -> Result<ListToolsResult, ClientOperationError> {
    let owner = LocalResponseOwner::new();
    let mut request = ListToolsRequest::default();
    request.params = params;
    request.extensions.insert(owner.observer());
    let handle = peer
        .send_request_with_option(
            ClientRequest::ListToolsRequest(request),
            PeerRequestOptions::no_options(),
        )
        .await?;
    let request_id = handle.id.clone();
    let mut cancellation = CancelAbandonedRequest {
        peer: peer.clone(),
        request_id: Some(request_id.clone()),
    };
    let result = handle.await_response().await;
    cancellation.request_id.take();
    let maximum_bytes = owner.finish(&request_id);
    match (result, maximum_bytes) {
        (Ok(ServerResult::ListToolsResult(result)), _) => Ok(result),
        (Ok(_), _) => Err(ServiceError::UnexpectedResponse.into()),
        (Err(source @ ServiceError::TransportClosed), Some(maximum_bytes)) => {
            Err(ClientOperationError::LocalResponseTooLarge {
                maximum_bytes,
                source,
            })
        }
        (Err(error), _) => Err(error.into()),
    }
}
