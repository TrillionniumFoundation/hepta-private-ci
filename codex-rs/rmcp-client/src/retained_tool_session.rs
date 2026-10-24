//! A capability to the exact initialized peer, with no session recovery.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use anyhow::anyhow;
use rmcp::model::CallToolRequest;
use rmcp::model::CallToolRequestParams;
use rmcp::model::CallToolResult;
use rmcp::model::ClientRequest;
use rmcp::model::ServerResult;
use rmcp::service::PeerRequestOptions;
use rmcp::service::RoleClient;
use rmcp::service::RunningService;
use serde_json::Map;
use serde_json::Value;
use tokio_util::sync::CancellationToken;

use crate::elicitation_client_service::ElicitationClientService;

#[derive(Default)]
pub(crate) struct RetainedSessionLifetime(pub(crate) CancellationToken);

impl Drop for RetainedSessionLifetime {
    fn drop(&mut self) {
        self.0.cancel();
    }
}

/// Retains an already initialized, authenticated MCP peer. Its caller retains
/// responsibility for endpoint/source qualification and effect authorization.
/// There is no transport recipe, login, OAuth refresh, redirect, session repair,
/// or application-level retry. The original peer becoming unavailable is final
/// for this capability, even when its parent client later connects elsewhere.
/// A timeout or transport error says nothing about whether an effect occurred.
pub struct RetainedMcpToolSession {
    pub(crate) service: Arc<RunningService<RoleClient, ElicitationClientService>>,
    pub(crate) lifetime: CancellationToken,
}

#[cfg(test)]
#[path = "retained_tool_session_tests.rs"]
mod tests;

impl RetainedMcpToolSession {
    /// Submit one tools/call request on the retained peer with a wall-clock
    /// budget. Elicitation cannot pause or extend that budget. This does not
    /// confer authority to any tool; owners must still gate each actual effect.
    pub async fn call_tool_once(
        &self,
        name: &str,
        arguments: Map<String, Value>,
        timeout: Duration,
    ) -> Result<CallToolResult> {
        if timeout.is_zero()
            || self.lifetime.is_cancelled()
            || self.service.is_closed()
            || self.service.peer().is_transport_closed()
        {
            return Err(anyhow!("retained MCP peer is closed or its deadline expired"));
        }
        let mut params = CallToolRequestParams::new(name.to_string());
        params.arguments = Some(arguments);
        let call = async {
            self.service
                .peer()
                .send_request_with_option(
                    ClientRequest::CallToolRequest(CallToolRequest::new(params)),
                    PeerRequestOptions::no_options(),
                )
                .await?
                .await_response()
                .await
        };
        let response = tokio::select! {
            biased;
            _ = self.lifetime.cancelled() => return Err(anyhow!("original MCP peer lifetime ended")),
            result = tokio::time::timeout(timeout, call) => result??,
        };
        if self.lifetime.is_cancelled() {
            return Err(anyhow!("original MCP peer lifetime ended before its response"));
        }
        match response {
            ServerResult::CallToolResult(result) => Ok(result),
            _ => Err(anyhow!("retained MCP tools/call returned an unexpected response")),
        }
    }
}
