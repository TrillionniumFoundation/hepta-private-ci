use super::*;

use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::Request;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

#[tokio::test]
async fn configured_mcp_bootstrap_uses_original_config_auth_and_named_binding() -> Result<()> {
    let server = MockServer::start().await;
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&calls);
    Mock::given(method("POST")).and(path("/native")).respond_with(move |request: &Request| {
        assert_eq!(request.headers["x-hepta-runtime-token"], "fixture-original-runtime");
        let body: Value = request.body_json().expect("original MCP JSON");
        let result = match body["method"].as_str() {
            Some("initialize") => json!({
                "protocolVersion":"2025-06-18", "capabilities":{"tools":{}},
                "serverInfo":{"name":"original-native-fixture","version":"1"}
            }),
            Some("notifications/initialized" | "notifications/cancelled") => return ResponseTemplate::new(202),
            Some("tools/list") => json!({"tools":[{
                "name":"process_read", "inputSchema":{"type":"object"},
                "description":"fixture original read"
            }]}),
            Some("tools/call") => {
                assert_eq!(body["params"]["name"], "process_read");
                observed.fetch_add(1, Ordering::SeqCst);
                json!({"content":[{"type":"text","text":"original bounded reply"}]})
            }
            _ => return ResponseTemplate::new(400),
        };
        ResponseTemplate::new(200).insert_header("mcp-session-id", "original-fixture-session")
            .set_body_json(json!({"jsonrpc":"2.0","id":body["id"],"result":result}))
    }).mount(&server).await;
    let home = tempfile::tempdir()?;
    let workspace = tempfile::tempdir()?;
    std::fs::write(home.path().join("config.toml"), format!(
        "mcp_oauth_credentials_store = \"file\"\n\
         [mcp_servers.original_runtime]\nurl = \"{}/native\"\n\
         default_tools_approval_mode = \"approve\"\n\
         http_headers = {{ X-Hepta-Runtime-Token = \"fixture-original-runtime\" }}\n",
        server.uri(),
    ))?;
    let original = initialize_configured_mcp_server(
        AbsolutePathBuf::from_absolute_path(home.path())?,
        AbsolutePathBuf::from_absolute_path(workspace.path())?,
        Arg0DispatchPaths::default(),
        "original_runtime", "local", Duration::from_secs(10),
    ).await?;
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let retained = original.binding().retain_calls("original_runtime", "local", &["process_read"]).await?;
    assert!(original.binding().retain_calls("original_runtime", "local", &["process_start"]).await.is_err());
    let reply = retained.call_tool_once("process_read", Default::default(), Duration::from_secs(1)).await?;
    assert_eq!(reply.content[0].as_text().map(|value| value.text.as_str()), Some("original bounded reply"));
    original.shutdown().await;
    assert!(retained.call_tool_once("process_read", Default::default(), Duration::from_secs(1)).await.is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    Ok(())
}
