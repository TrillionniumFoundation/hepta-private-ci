#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadParams;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AuthBusTextBody;
use codex_hepta_agentd::AuthBusTextIngress;
use codex_hepta_agentd::AuthBusTextState;
use codex_hepta_agentd::AuthBusTextStatus;
use codex_hepta_agentd::authbus_text_claims;
use codex_hepta_contracts::AgentId;
use core_test_support::responses;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::time::timeout;

mod support;

use support::fleet::FleetHarness;
use support::fleet::connect_app_server_with_experimental;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";
const ISSUER_ID: &str = "issuer:native-authbus-test";
const TEXT: &str = "AuthBus native signed text: exactly this body reaches the model.";
const WAIT_TIMEOUT: Duration = Duration::from_secs(20);

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn signed_text_crosses_real_queue_once_and_current_trust_rejects_invalid_ingress()
-> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "signed-text-workspace")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    let observed = responses::mount_sse_once(
        &model,
        responses::sse(vec![
            responses::ev_assistant_message("authbus-assistant", "signed text received"),
            responses::ev_completed("authbus-response"),
        ]),
    )
    .await;
    // This independent test producer owns its signing key. The daemon receives
    // only an explicit owner-controlled public-key registration.
    let key = SigningKey::from_bytes(&[91; 32]);
    let trust_file = agent.layout.home_root().join("authbus-trust.json");
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    write_trust(
        &trust_file,
        &agent.agent_id,
        &key,
        &[],
        /*revoked*/ false,
    )?;
    fleet.start_with_authbus_trust_file(&agent, &trust_file)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let ingress = control.session_ingress().await?;
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "hepta-authbus-text-product",
        /*channel_capacity*/ 64,
        /*experimental_api*/ true,
    )
    .await?;
    ensure!(
        client.codex_home() == Some(agent.layout.home_root().to_string_lossy().as_ref()),
        "AuthBus target App Server escaped the Agent's private home"
    );
    let mut request_id = 1;
    let thread = start_thread(&client, &mut request_id, &agent.workspace).await?;
    let disallowed_thread = start_thread(&client, &mut request_id, &agent.workspace).await?;
    write_trust(
        &trust_file,
        &agent.agent_id,
        &key,
        std::slice::from_ref(&thread),
        /*revoked*/ false,
    )?;
    let request = signed_text(&agent.agent_id, &key, &thread, /*sequence*/ 1)?;
    let admitted = control.submit_authbus_text(request.clone()).await?;
    let accepted = wait_queue_accepted(&control, &admitted.delivery_id).await?;
    ensure!(
        accepted.delivery_attempts == 1,
        "first delivery unexpectedly required recovery: {accepted:?}"
    );
    ensure!(
        accepted.queue_receipt_digest.is_some(),
        "accepted delivery omitted its queue receipt"
    );
    wait_completed_text_turn(&client, &mut request_id, &thread).await?;
    ensure!(
        observed
            .single_request()
            .message_input_texts("user")
            .iter()
            .any(|text| text == TEXT),
        "the real model transport did not receive the exact signed text"
    );
    ensure!(physical_send_count(&model).await == 1);

    let duplicate = control.submit_authbus_text(request).await?;
    ensure!(
        duplicate == accepted,
        "retained duplicate changed the durable delivery result"
    );
    ensure!(
        control
            .authbus_text_status(accepted.delivery_id.clone())
            .await?
            == accepted,
        "status RPC disagrees with the durable accepted delivery"
    );
    let mut invalid_signature = signed_text(&agent.agent_id, &key, &thread, /*sequence*/ 2)?;
    invalid_signature.signature_hex = "00".repeat(64);
    assert_server_rejection(control.submit_authbus_text(invalid_signature).await)?;
    let wrong_thread = signed_text(
        &agent.agent_id,
        &key,
        &disallowed_thread,
        /*sequence*/ 3,
    )?;
    assert_server_rejection(control.submit_authbus_text(wrong_thread).await)?;
    write_trust(
        &trust_file,
        &agent.agent_id,
        &key,
        std::slice::from_ref(&thread),
        /*revoked*/ true,
    )?;
    let revoked = signed_text(&agent.agent_id, &key, &thread, /*sequence*/ 4)?;
    assert_server_rejection(control.submit_authbus_text(revoked).await)?;

    // Observe subsequent worker polls after the duplicate and failed requests.
    // QueueAccepted proves queue acceptance only; the completed persisted turn
    // and physical request count independently establish the product outcome.
    tokio::time::sleep(Duration::from_millis(750)).await;
    wait_completed_text_turn(&client, &mut request_id, &thread).await?;
    ensure!(
        physical_send_count(&model).await == 1,
        "duplicate or rejected ingress sent another model request"
    );
    client.shutdown().await?;
    drop(fleet);
    ensure!(physical_send_count(&model).await == 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn real_agentd_without_explicit_trust_rejects_signed_text() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(AGENT_ID, "no-authbus-trust-workspace")?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    fleet.start(&agent)?;
    let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
    let ingress = control.session_ingress().await?;
    let client = connect_app_server_with_experimental(
        &ingress.socket_path,
        "hepta-authbus-missing-trust-product",
        /*channel_capacity*/ 64,
        /*experimental_api*/ true,
    )
    .await?;
    let mut request_id = 1;
    let thread = start_thread(&client, &mut request_id, &agent.workspace).await?;
    let key = SigningKey::from_bytes(&[92; 32]);
    let request = signed_text(&agent.agent_id, &key, &thread, /*sequence*/ 1)?;
    assert_server_rejection(control.submit_authbus_text(request).await)?;
    client.shutdown().await?;
    drop(fleet);
    ensure!(
        physical_send_count(&model).await == 0,
        "missing-trust ingress reached the model"
    );
    Ok(())
}

fn write_trust(
    path: &Path,
    agent_id: &AgentId,
    key: &SigningKey,
    thread_ids: &[String],
    revoked: bool,
) -> Result<()> {
    let registration = serde_json::json!({
        "schema_version": 1,
        "agent_id": agent_id.to_string(),
        "issuer_id": ISSUER_ID,
        "key_epoch": 1,
        "public_key_hex": hex(key.verifying_key().as_bytes()),
        "revoked": revoked,
        "thread_ids": thread_ids,
    });
    let mut temporary =
        tempfile::NamedTempFile::new_in(path.parent().context("trust parent missing")?)?;
    temporary
        .as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    serde_json::to_writer(temporary.as_file_mut(), &registration)?;
    temporary.as_file().sync_all()?;
    temporary.persist(path)?;
    Ok(())
}

fn signed_text(
    agent_id: &AgentId,
    key: &SigningKey,
    thread_id: &str,
    sequence: u64,
) -> Result<AuthBusTextIngress> {
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let mut request = AuthBusTextIngress {
        issuer_id: ISSUER_ID.to_string(),
        key_epoch: 1,
        message_id: format!("message:native-authbus:{sequence}"),
        sequence,
        expires_at_ms: now + 300_000,
        signature_hex: String::new(),
        body: AuthBusTextBody {
            spawn_generation: 1,
            thread_id: thread_id.to_string(),
            text: TEXT.to_string(),
        },
    };
    request.signature_hex = hex(&key
        .sign(&authbus_text_claims(agent_id, &request)?.signing_bytes())
        .to_bytes());
    Ok(request)
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn assert_server_rejection(result: Result<AuthBusTextStatus, AgentdError>) -> Result<()> {
    let error = result
        .err()
        .context("invalid signed ingress was accepted")?;
    ensure!(
        matches!(&error, AgentdError::Protocol(message) if message.contains("agentd rejected request")),
        "ingress failed without a real server rejection: {error}"
    );
    Ok(())
}

async fn wait_queue_accepted(
    control: &AgentdClient,
    delivery_id: &str,
) -> Result<AuthBusTextStatus> {
    timeout(WAIT_TIMEOUT, async {
        loop {
            let status = control.authbus_text_status(delivery_id.to_string()).await?;
            match status.state {
                AuthBusTextState::QueueAccepted => return Ok(status),
                AuthBusTextState::Queued | AuthBusTextState::Leased => {}
                AuthBusTextState::Expired | AuthBusTextState::Quarantined => {
                    anyhow::bail!("real queue delivery failed: {status:?}");
                }
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .context("signed ingress did not reach real queue acceptance")?
}

async fn start_thread(
    client: &RemoteAppServerClient,
    request_id: &mut i64,
    workspace: &Path,
) -> Result<String> {
    let response: ThreadStartResponse = client
        .request_typed(ClientRequest::ThreadStart {
            request_id: take_request_id(request_id),
            params: ThreadStartParams {
                cwd: Some(workspace.to_string_lossy().into_owned()),
                ephemeral: Some(false),
                ..ThreadStartParams::default()
            },
        })
        .await?;
    Ok(response.thread.id)
}

async fn wait_completed_text_turn(
    client: &RemoteAppServerClient,
    request_id: &mut i64,
    thread_id: &str,
) -> Result<()> {
    timeout(WAIT_TIMEOUT, async {
        loop {
            let response: ThreadReadResponse = client
                .request_typed(ClientRequest::ThreadRead {
                    request_id: take_request_id(request_id),
                    params: ThreadReadParams {
                        thread_id: thread_id.to_string(),
                        include_turns: true,
                    },
                })
                .await?;
            ensure!(
                response.thread.turns.len() <= 1,
                "signed message created duplicate persisted turns"
            );
            if let Some(turn) = response.thread.turns.first()
                && turn.status == TurnStatus::Completed
            {
                let user_messages: Vec<_> = turn
                    .items
                    .iter()
                    .filter_map(|item| match item {
                        ThreadItem::UserMessage { content, .. } => Some(content.clone()),
                        _ => None,
                    })
                    .collect();
                ensure!(
                    user_messages
                        == vec![vec![UserInput::Text {
                            text: TEXT.to_string(),
                            text_elements: Vec::new(),
                        }]],
                    "persisted rollout did not contain exactly the signed user text"
                );
                return Ok::<(), anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .context("signed text did not complete in the persisted thread")?
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

fn take_request_id(request_id: &mut i64) -> RequestId {
    let id = RequestId::Integer(*request_id);
    *request_id += 1;
    id
}
