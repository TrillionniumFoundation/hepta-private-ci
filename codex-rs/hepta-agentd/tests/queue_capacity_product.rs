#![cfg(unix)]

use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_client::TypedRequestError;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadQueueAddParams;
use codex_app_server_protocol::ThreadQueueAddResponse;
use codex_app_server_protocol::ThreadQueueListParams;
use codex_app_server_protocol::ThreadQueueListResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::UserInput;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ResourceBudget;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use core_test_support::responses;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;

mod support;

use support::fleet::FleetHarness;
use support::fleet::connect_app_server_with_experimental;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const INVALID_REQUEST_ERROR_CODE: i64 = -32600;
const QUEUE_CAPACITY: usize = 2;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn real_agentd_manifest_capacity_bounds_its_private_app_server_queue() -> Result<()> {
    let mut resources = ResourceBudget::local_default();
    resources.turn_queue_capacity = u32::try_from(QUEUE_CAPACITY)?;

    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register_with_resources(AGENT_ID, "workspace", resources)?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    mount_two_delayed_turns(&model).await;

    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;
    let ingress = control.session_ingress().await?;
    // The queue RPC is still an experimental, agent-local adapter surface.
    // Enabling it here must not be confused with Matrix or Supervisor authority.
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "hepta-agentd-queue-capacity-product",
        64,
        /*experimental_api*/ true,
    )
    .await?;
    ensure!(
        client.codex_home() == Some(agent.layout.home_root().to_string_lossy().as_ref()),
        "real App Server did not bind the Agent's private Codex home"
    );

    let mut next_request_id = 1;
    let first_thread = start_thread(&client, &mut next_request_id, &agent.workspace).await?;
    let second_thread = start_thread(&client, &mut next_request_id, &agent.workspace).await?;
    let overflow_thread = start_thread(&client, &mut next_request_id, &agent.workspace).await?;
    start_turn(&client, &mut next_request_id, &first_thread, "hold first").await?;
    start_turn(&client, &mut next_request_id, &second_thread, "hold second").await?;
    wait_for_two_physical_sends(&model).await?;

    add_queued(
        &client,
        &mut next_request_id,
        &first_thread,
        "first-client-id",
    )
    .await?;
    add_queued(
        &client,
        &mut next_request_id,
        &second_thread,
        "second-client-id",
    )
    .await?;

    let error = add_queued(
        &client,
        &mut next_request_id,
        &overflow_thread,
        "overflow-client-id",
    )
    .await
    .expect_err("the third pending row must exceed this Agent's manifest capacity");
    let TypedRequestError::Server { method, source } = error else {
        anyhow::bail!("capacity rejection was not a server JSON-RPC error: {error}");
    };
    ensure!(method == "thread/queue/add", "unexpected method: {method}");
    ensure!(
        source.code == INVALID_REQUEST_ERROR_CODE,
        "capacity rejection used the wrong JSON-RPC code: {source:?}"
    );
    ensure!(
        source.message == "runtime queue cannot contain more than 2 submissions",
        "unexpected capacity rejection: {source:?}"
    );

    let first = list_queued(&client, &mut next_request_id, &first_thread).await?;
    let second = list_queued(&client, &mut next_request_id, &second_thread).await?;
    let overflow = list_queued(&client, &mut next_request_id, &overflow_thread).await?;
    ensure!(
        first
            .data
            .iter()
            .map(|item| item.client_user_message_id.as_str())
            .collect::<Vec<_>>()
            == vec!["first-client-id"]
    );
    ensure!(
        second
            .data
            .iter()
            .map(|item| item.client_user_message_id.as_str())
            .collect::<Vec<_>>()
            == vec!["second-client-id"]
    );
    ensure!(overflow.data.is_empty());
    let sqlite = SqliteConfig::new_for_testing(AbsolutePathBuf::from_absolute_path(
        agent.layout.home_root(),
    )?);
    let queue_path = sqlite.queue_db_path();
    ensure!(
        queue_path.parent() == Some(agent.layout.home_root()) && queue_path.is_file(),
        "durable queue was not rooted in the Agent's private Codex home"
    );
    client.shutdown().await?;
    drop(fleet);
    ensure!(
        physical_send_count(&model).await == 2,
        "queue-capacity validation unexpectedly sent another model request"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_agentd_rejects_redirected_sqlite_and_in_memory_thread_stores() -> Result<()> {
    let shared_sqlite = tempfile::tempdir()?;
    let shared_sqlite_path = shared_sqlite.path().canonicalize()?;
    let quoted_shared_sqlite = serde_json::to_string(&shared_sqlite_path.to_string_lossy())?;
    assert_agentd_startup_rejected(
        &format!("sqlite_home = {quoted_shared_sqlite}\n"),
        "embedding runtime requires SQLite home",
    )
    .await?;
    ensure!(
        !SqliteConfig::new_for_testing(AbsolutePathBuf::from_absolute_path(&shared_sqlite_path,)?)
            .queue_db_path()
            .exists(),
        "App Server touched the redirected shared SQLite root before rejecting it"
    );
    ensure!(
        std::fs::read_dir(&shared_sqlite_path)?.next().is_none(),
        "App Server initialized durable state in the redirected shared SQLite root before rejecting it"
    );

    assert_agentd_startup_rejected(
        "experimental_thread_store = { type = \"in_memory\", id = \"redirected\" }\n",
        "embedding runtime requires thread store Local",
    )
    .await?;
    Ok(())
}

async fn assert_agentd_startup_rejected(config_toml: &str, expected_error: &str) -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "rejected-workspace")?;
    std::fs::write(agent.layout.home_root().join("config.toml"), config_toml)?;
    fleet.start(&agent)?;

    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        let report = fleet.supervisor.tick(Instant::now());
        ensure!(
            report.faults.is_empty(),
            "supervisor faulted while observing rejected agentd startup: {:?}",
            report.faults
        );
        let lifecycle = fleet
            .registry
            .load()?
            .agent(&agent.agent_id)
            .context("rejected Agent disappeared from registry")?
            .lifecycle
            .lifecycle;
        let snapshot = fleet
            .supervisor
            .snapshot(&agent.agent_id)
            .context("rejected Agent disappeared from supervisor")?;
        if lifecycle == AgentLifecycle::Failed && !snapshot.active {
            let logs = snapshot
                .logs
                .iter()
                .map(|log| String::from_utf8_lossy(&log.bytes))
                .collect::<String>();
            ensure!(
                logs.contains(expected_error),
                "rejected startup omitted the expected fail-closed error {expected_error:?}; logs={logs:?}"
            );
            return Ok(());
        }
        ensure!(
            Instant::now() < deadline,
            "agentd did not fail closed for rejected App Server storage config; lifecycle={lifecycle:?}; snapshot={snapshot:?}"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

async fn mount_two_delayed_turns(server: &wiremock::MockServer) {
    let body = responses::sse(vec![
        responses::ev_assistant_message("held-message", "done"),
        responses::ev_completed("held-response"),
    ]);
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "text/event-stream")
                .set_body_string(body)
                .set_delay(Duration::from_secs(30)),
        )
        .mount(server)
        .await;
}

async fn wait_for_two_physical_sends(server: &wiremock::MockServer) -> Result<()> {
    timeout(Duration::from_secs(10), async {
        loop {
            if physical_send_count(server).await >= 2 {
                return;
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .context("two real turns did not reach the model transport")?;
    Ok(())
}

async fn physical_send_count(server: &wiremock::MockServer) -> usize {
    server
        .received_requests()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|request| request.url.path().ends_with("/responses"))
        .count()
}

async fn start_thread(
    client: &RemoteAppServerClient,
    next_request_id: &mut i64,
    workspace: &Path,
) -> Result<String> {
    let request_id = take_request_id(next_request_id);
    let response: ThreadStartResponse = client
        .request_typed(ClientRequest::ThreadStart {
            request_id,
            params: ThreadStartParams {
                cwd: Some(workspace.to_string_lossy().into_owned()),
                ephemeral: Some(false),
                ..ThreadStartParams::default()
            },
        })
        .await?;
    Ok(response.thread.id)
}

async fn start_turn(
    client: &RemoteAppServerClient,
    next_request_id: &mut i64,
    thread_id: &str,
    text: &str,
) -> Result<()> {
    let request_id = take_request_id(next_request_id);
    let _: TurnStartResponse = client
        .request_typed(ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread_id.to_string(),
                input: vec![text_input(text)],
                ..TurnStartParams::default()
            },
        })
        .await?;
    Ok(())
}

async fn add_queued(
    client: &RemoteAppServerClient,
    next_request_id: &mut i64,
    thread_id: &str,
    client_id: &str,
) -> Result<ThreadQueueAddResponse, TypedRequestError> {
    let request_id = take_request_id(next_request_id);
    client
        .request_typed(ClientRequest::ThreadQueueAdd {
            request_id,
            params: ThreadQueueAddParams {
                thread_id: thread_id.to_string(),
                input: vec![text_input(client_id)],
                client_user_message_id: client_id.to_string(),
            },
        })
        .await
}

async fn list_queued(
    client: &RemoteAppServerClient,
    next_request_id: &mut i64,
    thread_id: &str,
) -> Result<ThreadQueueListResponse> {
    let request_id = take_request_id(next_request_id);
    Ok(client
        .request_typed(ClientRequest::ThreadQueueList {
            request_id,
            params: ThreadQueueListParams {
                thread_id: thread_id.to_string(),
                cursor: None,
                limit: Some(10),
            },
        })
        .await?)
}

fn text_input(text: &str) -> UserInput {
    UserInput::Text {
        text: text.to_string(),
        text_elements: Vec::new(),
    }
}

fn take_request_id(next_request_id: &mut i64) -> RequestId {
    let request_id = RequestId::Integer(*next_request_id);
    *next_request_id += 1;
    request_id
}
