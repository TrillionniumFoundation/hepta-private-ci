use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::Weak;

use anyhow::Context;
use anyhow::bail;
use codex_features::Feature;
use codex_hooks::HookMcpCall;
use codex_hooks::HookMcpExecutor;
use codex_mcp::McpRuntime;
use codex_protocol::ThreadId;
use futures::FutureExt;
use futures::future::BoxFuture;
use serde_json::Value;

use crate::session::session::Session;
use crate::tools::lifecycle::has_active_tool_policy;

pub(crate) struct CoreHookMcpExecutor {
    pub(crate) runtime: Arc<McpRuntime>,
    // Session-scoped MCP tools require the owning thread ID in request metadata.
    pub(crate) thread_id: ThreadId,
    pub(crate) session: Arc<OnceLock<Weak<Session>>>,
}

impl HookMcpExecutor for CoreHookMcpExecutor {
    fn execute(&self, call: HookMcpCall) -> BoxFuture<'_, anyhow::Result<String>> {
        async move {
            let session = self
                .session
                .get()
                .and_then(Weak::upgrade)
                .context("hook MCP executor is not bound to its owning session")?;
            if session.enabled(Feature::HeptaGovernance)
                || has_active_tool_policy(session.as_ref())
            {
                bail!(
                    "MCP tool hooks are disabled in governed threads; configure the effect through a normal Codex tool path"
                );
            }

            let binding = self.runtime.current_binding().await.ok_or_else(|| {
                anyhow::anyhow!(
                    "MCP server `{}` or tool `{}` is not connected and available",
                    call.server,
                    call.tool
                )
            })?;
            let prepared_call = binding.prepare_call(&call.server, &call.tool).ok_or_else(|| {
                anyhow::anyhow!(
                    "MCP server `{}` or tool `{}` is not connected and available",
                    call.server,
                    call.tool
                )
            })?;

            let result = prepared_call
                .call(
                    Some(Value::Object(call.input)),
                    Some(serde_json::json!({ "threadId": self.thread_id.to_string() })),
                    Some(call.timeout),
                )
                .await?;
            let text = result
                .content
                .iter()
                .filter_map(|content| {
                    (content.get("type").and_then(Value::as_str) == Some("text"))
                        .then(|| content.get("text").and_then(Value::as_str))
                        .flatten()
                })
                .collect::<Vec<_>>()
                .join("\n");
            if result.is_error == Some(true) {
                bail!("MCP tool returned an error: {text}");
            }

            Ok(text)
        }
        .boxed()
    }
}
