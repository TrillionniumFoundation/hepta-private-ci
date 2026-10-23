//! Real supervised Agentd/App Server processes and signed SQLite ingress.
//! Only the HTTP model is a fixture; this is not production-user/audio acceptance.
#![cfg(unix)]
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
use codex_hepta_agentd::AuthBusTextIngress;
use codex_hepta_agentd::authbus_text_claims;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use core_test_support::responses;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::io::ReadHalf;
use tokio::io::WriteHalf;
use wiremock::Mock;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;
#[path = "support/authbus_text.rs"]
mod authbus_fixture;
mod support;
use authbus_fixture::hex;
use authbus_fixture::signed_text;
use authbus_fixture::write_checkpoint;
use authbus_fixture::write_trust;
use support::fleet::AgentFixture;
use support::fleet::FleetHarness;
use support::fleet::connect_app_server_with_experimental;
const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";
const INPUT: &str = "请在原来的同一个线程回答中文";
const ANSWER: &str = "你好，同一个线程";
struct Fixture {
    fleet: FleetHarness,
    agent: AgentFixture,
    client: RemoteAppServerClient,
    thread: String,
    key: SigningKey,
    trust: PathBuf,
    _checkpoint: tempfile::TempDir,
}
impl Fixture {
    async fn new(model: &wiremock::MockServer) -> Result<Self> {
        let mut fleet = FleetHarness::new()?;
        let agent = fleet.register(AGENT_ID, "hmi-text-workspace")?;
        MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
        let key = SigningKey::from_bytes(&[91; 32]); // Reuses the existing AuthBus test producer; never persisted.
        let trust = agent.layout.home_root().join("authbus-trust.json");
        std::fs::set_permissions(
            agent.layout.home_root(),
            std::fs::Permissions::from_mode(0o700),
        )?;
        write_trust(&trust, &agent.agent_id, &key, &[], /*revoked*/ false)?;
        let checkpoint = tempfile::tempdir()?;
        std::fs::set_permissions(checkpoint.path(), std::fs::Permissions::from_mode(0o700))?;
        let checkpoint_file = checkpoint.path().join("authbus-replay-checkpoint.json");
        let store = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::from_absolute_path(agent.layout.home_root())?,
        ))
        .await?;
        let frontier = store.authbus_replay_frontier_digest().await?;
        drop(store);
        write_checkpoint(&checkpoint_file, &agent.agent_id, 1, frontier)?;
        fleet.start_with_hmi_text(&agent, &trust, &checkpoint_file)?;
        let (control, _) = fleet.wait_ready(&agent, /*generation*/ 1).await?;
        let ingress = control.session_ingress().await?;
        let client = connect_app_server_with_experimental(
            &ingress.socket_path,
            "hmi-original-owner-product",
            64,
            /*experimental_api*/ true,
        )
        .await?;
        let response: ThreadStartResponse = client
            .request_typed(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(1),
                params: ThreadStartParams {
                    cwd: Some(agent.workspace.to_string_lossy().into_owned()),
                    ephemeral: Some(false),
                    ..Default::default()
                },
            })
            .await?;
        let thread = response.thread.id;
        write_trust(
            &trust,
            &agent.agent_id,
            &key,
            std::slice::from_ref(&thread),
            /*revoked*/ false,
        )?;
        Ok(Self {
            fleet,
            agent,
            client,
            thread,
            key,
            trust,
            _checkpoint: checkpoint,
        })
    }
    fn request(&self, sequence: u64) -> Result<AuthBusTextIngress> {
        let mut request = signed_text(&self.agent.agent_id, &self.key, &self.thread, sequence)?;
        request.body.text = INPUT.into();
        request.signature_hex = hex(&self
            .key
            .sign(&authbus_text_claims(&self.agent.agent_id, &request)?.signing_bytes())
            .to_bytes());
        Ok(request)
    }
    async fn ui(&self) -> Result<Ui> {
        let path = self.agent.layout.run_root().join("hmi-text.sock");
        let stream = tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                match codex_uds::UnixStream::connect(&path).await {
                    Ok(stream) => return Ok::<_, std::io::Error>(stream),
                    Err(error)
                        if matches!(
                            error.kind(),
                            std::io::ErrorKind::NotFound | std::io::ErrorKind::ConnectionRefused
                        ) =>
                    {
                        tokio::time::sleep(Duration::from_millis(25)).await
                    }
                    Err(error) => return Err(error),
                }
            }
        })
        .await??;
        let (read, write) = tokio::io::split(stream);
        Ok(Ui {
            read: BufReader::new(read),
            write,
        })
    }
}
struct Ui {
    read: BufReader<ReadHalf<codex_uds::UnixStream>>,
    write: WriteHalf<codex_uds::UnixStream>,
}
impl Ui {
    async fn send(&mut self, value: Value) -> Result<()> {
        self.write
            .write_all(format!("{value}\n").as_bytes())
            .await?;
        Ok(())
    }
    async fn next(&mut self) -> Result<Value> {
        let mut line = String::new();
        let bytes =
            tokio::time::timeout(Duration::from_secs(20), self.read.read_line(&mut line)).await??;
        ensure!(bytes > 0, "real HMI socket ended before expected outcome");
        ensure!(bytes <= 65536);
        Ok(serde_json::from_str(&line)?)
    }
    async fn until(&mut self, kind: &str) -> Result<Value> {
        loop {
            let event = self.next().await?;
            ensure!(
                event["type"] != "sessionError",
                "real HMI session failed: {event}"
            );
            if event["type"] == kind {
                return Ok(event);
            }
        }
    }
}
async fn sends(server: &wiremock::MockServer) -> usize {
    server
        .received_requests()
        .await
        .unwrap_or_default()
        .iter()
        .filter(|r| r.url.path().ends_with("/responses"))
        .count()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn original_agentd_signed_hmi_streams_same_thread_deduplicates_and_reconnects_without_replay()
-> Result<()> {
    let model = responses::start_mock_server().await;
    let observed = responses::mount_sse_once(
        &model,
        responses::sse(vec![
            responses::ev_response_created("hmi-response"),
            responses::ev_message_item_added("hmi-answer", ""),
            responses::ev_output_text_delta("你好"),
            responses::ev_output_text_delta("，同一个线程"),
            responses::ev_assistant_message("hmi-answer", ANSWER),
            responses::ev_completed("hmi-response"),
        ]),
    )
    .await;
    let fixture = Fixture::new(&model).await?;
    let request = fixture.request(1)?;
    let mut invalid = request.clone();
    invalid.signature_hex = "00".repeat(64);
    let mut rejected = fixture.ui().await?;
    rejected
        .send(json!({"type":"submit","request":invalid}))
        .await?;
    let failure = rejected.next().await?;
    ensure!(
        failure["type"] == "sessionError"
            && failure["error"]
                .as_str()
                .context("signature rejection")?
                .contains("InvalidSignature"),
        "{failure}"
    );
    ensure!(sends(&model).await == 0);
    drop(rejected);
    let mut ui = fixture.ui().await?;
    ui.send(json!({"type":"submit","request":request})).await?;
    let mut receipt = None;
    let mut completed = false;
    let mut streamed = String::new();
    let mut connection = None;
    while receipt.is_none() || !completed {
        let event = ui.next().await?;
        ensure!(
            event["type"] != "sessionError" && event["type"] != "inputError",
            "{event}"
        );
        match event["type"].as_str() {
            Some("attached") => {
                ensure!(event["binding"]["threadId"] == fixture.thread);
                connection = event["connectionId"].as_u64();
            }
            Some("admission") => receipt = Some(event["receipt"].clone()),
            Some("output") => {
                let kind = &event["outcome"]["event"]["kind"];
                if kind["type"] == "textDelta" {
                    streamed.push_str(kind["delta"].as_str().context("stream delta")?);
                }
                if kind["type"] == "terminal" {
                    ensure!(kind["outcome"]["status"] == "completed", "{event}");
                    ensure!(kind["outcome"]["generatedText"] == ANSWER);
                    completed = true;
                }
            }
            _ => {}
        }
    }
    ensure!(
        streamed == ANSWER,
        "actual App Server deltas not preserved: {streamed}"
    );
    let receipt = receipt.context("durable signed receipt")?;
    let delivery = receipt["delivery_id"]
        .as_str()
        .context("delivery ID")?
        .to_owned();
    ensure!(
        observed
            .single_request()
            .message_input_texts("user")
            .iter()
            .any(|text| text == INPUT)
    );
    ui.send(json!({"type":"submit","request":request})).await?;
    let duplicate = ui.until("admission").await?;
    ensure!(duplicate["receipt"]["delivery_id"] == delivery);
    ui.send(json!({"type":"reconnect"})).await?;
    let new = ui.until("reconnected").await?;
    ensure!(new["binding"]["threadId"] == fixture.thread);
    ensure!(new["connectionId"].as_u64() != connection);
    ui.send(json!({"type":"reconcile","delivery_id":delivery,"text":INPUT}))
        .await?;
    let recovered = ui.until("reconciled").await?;
    ensure!(
        recovered["receipt"]["outcome"]["type"] == "persisted",
        "{recovered}"
    );
    ensure!(
        sends(&model).await == 1,
        "same input was physically dispatched again"
    );
    let thread: ThreadReadResponse = fixture
        .client
        .request_typed(ClientRequest::ThreadRead {
            request_id: RequestId::Integer(2),
            params: ThreadReadParams {
                thread_id: fixture.thread.clone(),
                include_turns: true,
            },
        })
        .await?;
    ensure!(thread.thread.turns.len() == 1);
    ensure!(
        thread.thread.turns[0]
            .items
            .iter()
            .filter(|item| matches!(item, ThreadItem::UserMessage { .. }))
            .count()
            == 1
    );
    ensure!(thread.thread.turns[0].items.iter().any(|item|matches!(item,ThreadItem::UserMessage {client_id:Some(client_id),..} if client_id==&format!("hepta.authbus:{delivery}"))),"HMI used another Core identity instead of the original AuthBus delivery");
    ui.send(json!({"type":"stop"})).await?;
    let terminal = ui.until("sessionTerminal").await?;
    ensure!(terminal["error"].is_null());
    fixture.client.shutdown().await?;
    drop(fixture.fleet);
    ensure!(sends(&model).await == 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn original_agentd_hmi_cancels_a_live_turn_and_current_trust_revokes_the_ui() -> Result<()> {
    let model = responses::start_mock_server().await;
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .respond_with(
            ResponseTemplate::new(200)
                .insert_header("content-type", "text/event-stream")
                .set_body_string(responses::sse(vec![
                    responses::ev_assistant_message("late", "must not display"),
                    responses::ev_completed("late-response"),
                ]))
                .set_delay(Duration::from_secs(5)),
        )
        .mount(&model)
        .await;
    let fixture = Fixture::new(&model).await?;
    let mut ui = fixture.ui().await?;
    ui.send(json!({"type":"submit","request":fixture.request(1)?}))
        .await?;
    ui.until("admission").await?;
    tokio::time::timeout(Duration::from_secs(10), async {
        while sends(&model).await != 1 {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await?;
    ui.send(json!({"type":"interrupt"})).await?;
    let retired = ui.until("outputRetired").await?;
    let interrupt = ui.until("interruptRequested").await?;
    ensure!(interrupt["outcome"]["scope"]["outputEpoch"] == retired["outputEpoch"]);
    ensure!(interrupt["outcome"]["localStopError"].is_null());
    ensure!(
        !interrupt["outcome"]["terminalObserved"]
            .as_bool()
            .unwrap_or(true)
    );
    loop {
        let event = ui.next().await?;
        if event["type"] == "output" {
            let kind = &event["outcome"]["event"]["kind"];
            ensure!(
                kind["type"] != "textDelta" && kind["type"] != "textFinal",
                "late generated output escaped retirement: {event}"
            );
            if kind["type"] == "terminal" {
                ensure!(kind["outcome"]["status"] == "interrupted", "{event}");
                break;
            }
        }
    }
    write_trust(
        &fixture.trust,
        &fixture.agent.agent_id,
        &fixture.key,
        std::slice::from_ref(&fixture.thread),
        /*revoked*/ true,
    )?;
    let terminal = ui.until("sessionTerminal").await?;
    ensure!(
        terminal["error"]
            .as_str()
            .context("revocation reason")?
            .contains("permission changed")
    );
    ensure!(sends(&model).await == 1);
    fixture.client.shutdown().await?;
    drop(fixture.fleet);
    Ok(())
}
