use std::sync::Arc;
use std::sync::OnceLock;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use codex_config::McpServerConfig;
use codex_hooks::HookMcpCall;
use codex_hooks::HookMcpExecutor;
use pretty_assertions::assert_eq;
use serde_json::Map;
use serde_json::Value;
use serde_json::json;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::Request;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

use super::CoreHookMcpExecutor;
use crate::session::tests::make_session_and_context;
use crate::turn_metadata::McpTurnMetadataContext;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn hook_metadata_reaches_prepared_client_without_overriding_thread_identity() -> Result<()> {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/mcp"))
        .respond_with(|request: &Request| {
            let request = match serde_json::from_slice::<Value>(&request.body) {
                Ok(request) => request,
                Err(error) => return ResponseTemplate::new(400).set_body_string(error.to_string()),
            };
            let result = match request["method"].as_str() {
                Some("initialize") => json!({
                    "protocolVersion": request["params"]["protocolVersion"],
                    "capabilities": { "tools": {} },
                    "serverInfo": { "name": "hook-metadata", "version": "1.0.0" },
                }),
                Some("notifications/initialized") => return ResponseTemplate::new(202),
                Some("tools/list") => json!({ "tools": [{
                    "name": "record",
                    "inputSchema": { "type": "object" },
                }] }),
                Some("tools/call") => json!({
                    "content": [{ "type": "text", "text": "recorded" }],
                }),
                _ => return ResponseTemplate::new(400).set_body_string("unexpected MCP method"),
            };
            ResponseTemplate::new(200).set_body_json(json!({
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": result,
            }))
        })
        .mount(&server)
        .await;

    let (session, turn_context) = make_session_and_context().await;
    let session = Arc::new(session);
    let mut config = (*turn_context.config).clone();
    let server_config: McpServerConfig =
        serde_json::from_value(json!({ "url": format!("{}/mcp", server.uri()) }))?;
    config.mcp_servers.set(
        [("hook-metadata".to_string(), server_config)]
            .into_iter()
            .collect(),
    )?;
    session.refresh_mcp_config(config).await;
    session.wait_for_mcp_server("hook-metadata").await;

    let executor = CoreHookMcpExecutor {
        runtime: Arc::clone(&session.services.mcp_runtime),
        thread_id: session.thread_id,
        session: Arc::new(OnceLock::from(Arc::downgrade(&session))),
    };
    let turn_metadata = turn_context
        .turn_metadata_state
        .current_meta_value_for_mcp_request(McpTurnMetadataContext {
            model: turn_context.model_info.slug.as_str(),
            reasoning_effort: turn_context.reasoning_effort.clone(),
        })
        .context("the real turn should provide MCP request metadata")?;
    let metadata = serde_json::from_value::<Map<String, Value>>(json!({
        "threadId": "not-the-owning-thread",
        "x-codex-turn-metadata": turn_metadata,
        "extension": { "typed": [false, 7, null] },
    }))?;
    for metadata in [None, Some(metadata)] {
        assert_eq!(
            executor
                .execute(HookMcpCall {
                    server: "hook-metadata".to_string(),
                    tool: "record".to_string(),
                    environment_id: None,
                    metadata,
                    input: Map::new(),
                    timeout: Duration::from_secs(5),
                })
                .await?,
            "recorded"
        );
    }

    let requests = server
        .received_requests()
        .await
        .context("the server should record the real prepared-client requests")?;
    let requests = requests
        .iter()
        .filter(|request| request.method.as_str() == "POST")
        .map(|request| serde_json::from_slice::<Value>(&request.body))
        .collect::<serde_json::Result<Vec<_>>>()?;
    let metadata = requests
        .iter()
        .filter(|request| request["method"] == "tools/call")
        .map(|request| request["params"]["_meta"].clone())
        .collect::<Vec<_>>();
    assert_eq!(
        metadata,
        vec![
            json!({ "threadId": session.thread_id.to_string() }),
            json!({
                "threadId": session.thread_id.to_string(),
                "x-codex-turn-metadata": turn_metadata,
                "extension": { "typed": [false, 7, null] },
            }),
        ]
    );

    Ok(())
}
