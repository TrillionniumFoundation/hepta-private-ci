use std::time::Duration;

use anyhow::Context;
use futures::FutureExt;
use pretty_assertions::assert_eq;
use rmcp::ServerHandler;
use rmcp::model::CancelledNotificationParam;
use rmcp::model::ClientCapabilities;
use rmcp::model::ClientRequest;
use rmcp::model::ErrorData;
use rmcp::model::Implementation;
use rmcp::model::InitializeRequestParams;
use rmcp::model::InitializeResult;
use rmcp::model::ListToolsRequest;
use rmcp::model::ListToolsResult;
use rmcp::model::PaginatedRequestParams;
use rmcp::model::ProtocolVersion;
use rmcp::model::RequestId;
use rmcp::model::ServerCapabilities;
use rmcp::model::ServerConfig;
use rmcp::service::NotificationContext;
use rmcp::service::PeerRequestOptions;
use rmcp::service::RequestContext;
use rmcp::service::RoleClient;
use rmcp::service::RoleServer;
use rmcp::service::serve_directly;
use tokio::sync::mpsc;

use super::CancelAbandonedRequest;

struct CancellationProbe {
    started: mpsc::UnboundedSender<RequestId>,
    cancelled: mpsc::UnboundedSender<CancelledNotificationParam>,
}

impl ServerHandler for CancellationProbe {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
    }

    async fn list_tools(
        &self,
        _params: Option<PaginatedRequestParams>,
        context: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        let _ = self.started.send(context.id.clone());
        context.ct.cancelled().await;
        Err(ErrorData::internal_error("cancelled probe request", None))
    }

    async fn on_cancelled(
        &self,
        notification: CancelledNotificationParam,
        _context: NotificationContext<RoleServer>,
    ) {
        let _ = self.cancelled.send(notification);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn abandoned_request_cancels_with_exhausted_coop_budget() -> anyhow::Result<()> {
    const WAIT: Duration = Duration::from_secs(5);
    let (started_tx, mut started) = mpsc::unbounded_channel();
    let (cancelled_tx, mut cancelled) = mpsc::unbounded_channel();
    let (server_transport, client_transport) = tokio::io::duplex(/*max_buf_size*/ 4096);
    let client_info = InitializeRequestParams::new(
        ClientCapabilities::default(),
        Implementation::new("cancellation-budget-probe", "0.0.0"),
    )
    .with_protocol_version(ProtocolVersion::LATEST_WITH_INITIALIZE);
    let mut server_info =
        InitializeResult::new(ServerCapabilities::builder().enable_tools().build());
    server_info.protocol_version = ProtocolVersion::LATEST_WITH_INITIALIZE;
    let server = serve_directly::<RoleServer, _, _, _, _>(
        CancellationProbe {
            started: started_tx,
            cancelled: cancelled_tx,
        },
        server_transport,
        Some(client_info),
    );
    let client =
        serve_directly::<RoleClient, _, _, _, _>((), client_transport, Some(server_info.into()));

    let handle = client
        .peer()
        .send_request_with_option(
            ClientRequest::ListToolsRequest(ListToolsRequest::default()),
            PeerRequestOptions::no_options(),
        )
        .await?;
    let actual_id = handle.id.clone();
    let cancellation = CancelAbandonedRequest {
        peer: client.peer().clone(),
        request_id: Some(actual_id.clone()),
    };
    // The real SDK handle already exists before waiting for the server. Seeing
    // this sole request on the server also means its outbound queue was drained.
    let observed_id = tokio::time::timeout(WAIT, started.recv())
        .await
        .context("server did not receive tools/list")?
        .context("server closed the started channel")?;
    assert_eq!(observed_id, actual_id);

    // A scheduled task has Tokio's cooperative budget. Do not await between
    // exhausting that budget and Drop: an await could silently replenish it.
    tokio::spawn(async move {
        let exhausted = (0..1024).any(|_| tokio::task::consume_budget().now_or_never().is_none());
        assert!(exhausted, "the control must really exhaust the coop budget");
        assert!(!tokio::task::coop::has_budget_remaining());
        drop(handle);
        drop(cancellation);
    })
    .await?;

    let notification = tokio::time::timeout(WAIT, cancelled.recv())
        .await
        .context("abandonment lost the cancellation despite a writable queue")?
        .context("server closed the cancellation channel")?;
    assert_eq!(notification.request_id, Some(actual_id));
    assert_eq!(
        notification.reason.as_deref(),
        Some("request abandoned by the caller")
    );
    assert!(notification.meta.is_none());
    client.cancel().await?;
    server.cancel().await?;
    Ok(())
}
