#![cfg(unix)]

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_hepta_agentd::NotesThreadSeedReceipt;
use codex_hepta_agentd::ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG;
use codex_hepta_agentd::ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG;
use codex_hepta_agentd::text_session::AgentdTextSessionConfig;
use serde_json::Value;
use std::process::Command;
use wiremock::MockServer;

mod support;

use support::fleet::FleetHarness;
use support::fleet::connect_app_server_with_experimental;

const AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75df0";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn launcher_seeds_one_unused_original_thread_without_model_contact() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "notes-seed-workspace")?;
    let provider = MockServer::start().await;
    std::fs::write(
        agent.layout.home_root().join("config.toml"),
        format!(
            r#"model = "mock-model"
model_provider = "mock_provider"
{ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG}
[model_providers.mock_provider]
name = "Mock provider for original Notes seed"
base_url = "{}/v1"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
"#,
            provider.uri()
        ),
    )?;
    std::fs::write(
        agent.layout.home_root().join("environments.toml"),
        ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG,
    )?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let output = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-notes-thread-seed")?)
        .arg("--control-socket")
        .arg(agent.layout.agentd_control_socket())
        .arg("--agent-id")
        .arg(agent.agent_id.to_string())
        .arg("--spawn-generation")
        .arg("1")
        .arg("--codex-home")
        .arg(agent.layout.home_root())
        .arg("--cwd")
        .arg(&agent.workspace)
        .output()
        .context("run original Notes thread seed launcher")?;
    ensure!(
        output.status.success(),
        "seed launcher failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout)?;
    ensure!(value.get("schema_version").and_then(Value::as_u64) == Some(1));
    let interaction = value
        .get("interaction")
        .context("launcher omitted interaction")?;
    ensure!(interaction.get("kind").and_then(Value::as_str) == Some("original_thread_tool_v1"));
    let route: AgentdTextSessionConfig = serde_json::from_value(
        interaction
            .get("route")
            .context("launcher omitted Agentd route")?
            .clone(),
    )?;
    let receipt: NotesThreadSeedReceipt = serde_json::from_value(
        interaction
            .get("seed")
            .context("launcher omitted original thread receipt")?
            .clone(),
    )?;
    ensure!(route.control_socket == agent.layout.agentd_control_socket());
    ensure!(route.agent_id == agent.agent_id);
    ensure!(route.spawn_generation == 1);
    ensure!(route.codex_home == agent.layout.home_root());
    ensure!(route.thread_id == receipt.thread_id);
    ensure!(route.app_server_session_id == receipt.app_server_session_id);
    ensure!(receipt.execution_cwd == agent.workspace);
    receipt.verify_persisted()?;

    let ingress = control.session_ingress().await?;
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "hepta-original-notes-seed-observer",
        /*channel_capacity*/ 16,
        /*experimental_api*/ true,
    )
    .await?;
    let actual: ThreadReadResponse = client
        .request_typed(ClientRequest::ThreadRead {
            request_id: RequestId::Integer(1),
            params: ThreadReadParams {
                thread_id: receipt.thread_id.clone(),
                include_turns: true,
            },
        })
        .await?;
    ensure!(actual.thread.id == receipt.thread_id);
    ensure!(actual.thread.session_id == receipt.app_server_session_id);
    ensure!(actual.thread.turns.is_empty());
    ensure!(actual.thread.path.as_ref() == Some(&receipt.rollout_path));
    client.shutdown().await?;
    ensure!(
        provider
            .received_requests()
            .await
            .context("read mock provider requests")?
            .is_empty(),
        "seeding an unused original thread contacted the model provider"
    );
    Ok(())
}
