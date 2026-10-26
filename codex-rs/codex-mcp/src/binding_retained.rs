//! One-shot transport calls constrained by an original published MCP binding.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use codex_config::AppToolApproval;
use codex_rmcp_client::RetainedMcpToolSession;
use rmcp::model::CallToolResult;
use serde_json::Map;
use serde_json::Value;

use super::McpBinding;
use super::PreparedMcpCall;

/// The exact ready client and a finite set of permitted tools from one frozen
/// binding. It never starts a server, reconnects, resolves new credentials or
/// follows a replacement catalog. Callers still own original approval and
/// effect authority; retaining a transport does not approve any operation.
pub struct RetainedMcpCalls {
    calls: HashMap<String, PreparedMcpCall>,
    session: RetainedMcpToolSession,
}

impl McpBinding {
    /// Retain only named, model-visible tools already present in this binding
    /// and running in the independently selected original environment. No bare
    /// client is exported, and disabled/unready tools cannot trigger startup.
    #[deny(unfulfilled_lint_expectations)]
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "the original catalog check and exact ready peer capture must share the same read fence"
    )]
    pub async fn retain_calls(
        &self,
        server: &str,
        environment_id: &str,
        tools: &[&str],
    ) -> Result<RetainedMcpCalls> {
        ensure!(
            !server.is_empty()
                && !environment_id.is_empty()
                && !tools.is_empty()
                && tools.len() <= 16,
            "retained MCP calls require an explicit server, environment and bounded tool set"
        );
        let mut calls = HashMap::new();
        for tool in tools {
            let call = self.prepare_call(server, tool).ok_or_else(|| {
                anyhow!("MCP tool `{server}/{tool}` is not permitted in the original binding")
            })?;
            ensure!(
                call.server_environment_id() == environment_id,
                "retained MCP tool environment differs from the original binding"
            );
            ensure!(
                !call.client.server_supports_sandbox_state_meta_capability,
                "retained MCP tools cannot omit required per-call sandbox metadata"
            );
            ensure!(
                calls.insert((*tool).to_string(), call).is_none(),
                "retained MCP tool set contains a duplicate"
            );
        }
        let first = calls
            .values()
            .next()
            .ok_or_else(|| anyhow!("retained MCP tool set is empty"))?;
        ensure!(
            calls.values().all(|call| {
                Arc::ptr_eq(&call.client.client, &first.client.client)
                    && Arc::ptr_eq(
                        &call.catalog_revision_source,
                        &first.catalog_revision_source,
                    )
                    && call.catalog_revision == first.catalog_revision
            }),
            "retained MCP calls do not share the same original peer and catalog"
        );
        let revision = first.catalog_revision_source.read().await;
        ensure!(
            *revision == first.catalog_revision,
            "retained MCP catalog changed before capture"
        );
        let session = first.client.client.retain_tool_session().await?;
        drop(revision);
        Ok(RetainedMcpCalls { calls, session })
    }
}

impl RetainedMcpCalls {
    /// Exposes the original policy for the trusted caller's existing approval
    /// gate. This value never turns an approval-required tool into an approved one.
    pub fn tool_approval_mode(&self, tool: &str) -> Option<AppToolApproval> {
        self.calls
            .get(tool)
            .map(PreparedMcpCall::tool_approval_mode)
    }

    /// Send once on the same peer, preserving the original catalog read fence
    /// and the smaller of the server timeout and caller's absolute budget.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "the original catalog fence must cover submission and response"
    )]
    pub async fn call_tool_once(
        &self,
        tool: &str,
        arguments: Map<String, Value>,
        budget: Duration,
    ) -> Result<CallToolResult> {
        let call = self
            .calls
            .get(tool)
            .ok_or_else(|| anyhow!("tool is outside the retained MCP binding"))?;
        let budget = call
            .client
            .tool_timeout
            .map_or(budget, |limit| budget.min(limit));
        ensure!(!budget.is_zero(), "retained MCP call deadline expired");
        let deadline = tokio::time::Instant::now()
            .checked_add(budget)
            .ok_or_else(|| anyhow!("retained MCP call deadline exceeds its bound"))?;
        tokio::time::timeout_at(deadline, async {
            let revision = call.catalog_revision_source.read().await;
            ensure!(
                *revision == call.catalog_revision,
                "retained MCP catalog changed before effect entry"
            );
            let result = self
                .session
                .call_tool_once(
                    &call.tool_info.tool.name,
                    arguments,
                    deadline.saturating_duration_since(tokio::time::Instant::now()),
                )
                .await;
            drop(revision);
            result
        })
        .await
        .map_err(|_| anyhow!("retained MCP call deadline expired"))?
    }
}
