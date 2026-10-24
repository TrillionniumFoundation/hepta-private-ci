use super::*;
use std::collections::VecDeque;
use std::sync::atomic::AtomicUsize;

use pretty_assertions::assert_eq;
use rmcp::ErrorData;
use rmcp::ServerHandler;
use rmcp::ServiceExt;
use rmcp::model::CallToolResult;
use rmcp::model::ServerCapabilities;
use rmcp::model::ServerInfo;
use rmcp::service::RequestContext;
use rmcp::service::RoleServer;
use rmcp::service::RunningService;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[derive(Clone)]
enum Reply {
    Json(Value),
    Fail,
    Delayed(Value),
    Revoke(Value),
}

#[derive(Clone)]
struct Server {
    replies: Arc<Mutex<VecDeque<Reply>>>,
    calls: Arc<Mutex<Vec<(String, Value)>>>,
    live: Arc<AtomicBool>,
    entered: Arc<tokio::sync::Notify>,
    next_job: Arc<AtomicUsize>,
}

impl ServerHandler for Server {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build())
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let arguments = json!(request.arguments);
        self.calls
            .lock()
            .expect("calls")
            .push((request.name.to_string(), arguments.clone()));
        self.entered.notify_one();
        let reply = self
            .replies
            .lock()
            .expect("replies")
            .pop_front()
            .expect("fixture reply");
        let mut value = match reply {
            Reply::Json(value) => value,
            Reply::Fail => {
                return Err(ErrorData::internal_error(
                    "lost start response",
                    /*data*/ None,
                ));
            }
            Reply::Delayed(value) => {
                tokio::time::sleep(Duration::from_millis(200)).await;
                value
            }
            Reply::Revoke(value) => {
                self.live.store(false, Ordering::Release);
                value
            }
        };
        if request.name == "process_start" {
            value["job"]["idempotency_key"] = arguments["idempotency_key"].clone();
            value["job"]["id"] = json!(format!(
                "original-job-{}",
                self.next_job.fetch_add(1, Ordering::Relaxed)
            ));
        } else {
            value["job_id"] = arguments["job_id"].clone();
        }
        let mut result = CallToolResult::success(Vec::new());
        result.structured_content = Some(value);
        Ok(result.into())
    }
}

struct Session {
    peer: Peer<RoleClient>,
    runtime: Handle,
    live: Arc<AtomicBool>,
}

// Deliberately synthetic verifier. No test session is exported to production.
impl OriginalAndroidRuntimeSession for Session {
    fn peer(&self) -> &Peer<RoleClient> {
        &self.peer
    }
    fn runtime(&self) -> &Handle {
        &self.runtime
    }
    fn verify_original(&self, _: &AndroidNativeTextObservation, _: Instant) -> Result<(), String> {
        if self.live.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err("fixture source revoked".into())
        }
    }
}

struct Fixture {
    device: Arc<OriginalRuntimeAndroidTextDevice>,
    server: Server,
    _client: RunningService<RoleClient, ()>,
    _server: RunningService<RoleServer, Server>,
}

fn payload() -> (AndroidSetTextV1, String) {
    let value: Value =
        serde_json::from_str(include_str!("../tests/fixtures/android-bound-text-v1.json"))
            .expect("fixture");
    let raw = value["request_utf8"].as_str().expect("request").to_string();
    (
        AndroidSetTextV1::from_json(&raw).expect("canonical fixture"),
        raw,
    )
}

fn request(mode: Mode) -> Vec<u8> {
    let (_, raw) = payload();
    serde_json::to_vec(&json!({
        "op": mode.operation(), "payload_base64": base64::engine::general_purpose::STANDARD.encode(raw.as_bytes()),
        "payload_sha256": Sha256Digest::for_bytes(raw.as_bytes()),
    })).expect("request")
}

fn start() -> Value {
    json!({"audit_recorded":true,"reused":false,"local_record_pending":false,"launch":{"ok":true},
        "job":{"id":"original-job-1","host":HOST,"executable":EXECUTABLE,"args":ARGS,
        "launch_error":null,"launch_state":"launched","cwd":null,"env_keys":[]}})
}

fn status(bytes: &[u8]) -> Value {
    json!({"audit_recorded":true,"job_id":"original-job-1","cancelled":false,"timed_out":false,
        "state":"succeeded","exit_code":0,"output_complete":true,
        "log_bytes":{"stdout":{"seen":bytes.len(),"stored":bytes.len()},"stderr":{"seen":0,"stored":0}},
        "log_errors":{"stdout":null,"stderr":null},"log_truncated":{"stdout":false,"stderr":false}})
}

fn read(bytes: &[u8]) -> Value {
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    json!({"audit_recorded":true,"job_id":"original-job-1",
        "stdout":{"offset":0,"next_offset":bytes.len(),"size":bytes.len(),"eof":true,
        "text":std::str::from_utf8(bytes).expect("UTF-8 fixture"),"bytes_hex":hex},
        "stderr":{"offset":0,"next_offset":0,"size":0,"eof":true,"text":"","bytes_hex":""}})
}

fn successful(bytes: &[u8]) -> Vec<Reply> {
    vec![
        Reply::Json(start()),
        Reply::Json(status(bytes)),
        Reply::Json(read(bytes)),
    ]
}

async fn fixture(
    replies: Vec<Reply>,
    timeout: Duration,
) -> Result<Fixture, Box<dyn std::error::Error>> {
    let server = Server {
        replies: Arc::new(Mutex::new(replies.into())),
        calls: Arc::new(Mutex::new(Vec::new())),
        live: Arc::new(AtomicBool::new(true)),
        entered: Arc::new(tokio::sync::Notify::new()),
        next_job: Arc::new(AtomicUsize::new(1)),
    };
    let (client_io, server_io) = tokio::io::duplex(65536);
    let service = server.clone();
    let serving = tokio::spawn(async move { service.serve(server_io).await });
    let client = ().serve(client_io).await?;
    let serving = serving.await??;
    let session = Arc::new(Session {
        peer: client.peer().clone(),
        runtime: Handle::current(),
        live: Arc::clone(&server.live),
    });
    let device = Arc::new(OriginalRuntimeAndroidTextDevice::from_retained_session(
        session,
        &payload().0.observation,
        timeout,
    )?);
    Ok(Fixture {
        device,
        server,
        _client: client,
        _server: serving,
    })
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_peer_preserves_utf8_uses_fixed_helper_and_separate_readback() -> TestResult {
    let bytes = "{\"text\":\"中文🙂\"}".as_bytes();
    let f = fixture(
        [successful(bytes), successful(bytes)].concat(),
        Duration::from_secs(2),
    )
    .await?;
    assert_eq!(f.device.apply(&request(Mode::Apply))?, bytes);
    assert_eq!(f.device.readback(&request(Mode::Readback))?, bytes);
    assert!(f.device.apply(&request(Mode::Apply)).is_err());
    let calls = f.server.calls.lock().expect("calls");
    assert_eq!(
        calls
            .iter()
            .map(|(name, _)| name.as_str())
            .collect::<Vec<_>>(),
        vec![
            "process_start",
            "process_status",
            "process_read",
            "process_start",
            "process_status",
            "process_read"
        ]
    );
    for index in [0, 3] {
        assert_eq!(calls[index].1["host"], HOST);
        assert_eq!(calls[index].1["executable"], EXECUTABLE);
        assert_eq!(calls[index].1["args"], json!(ARGS));
        assert!(calls[index].1.get("cwd").is_none());
        assert!(calls[index].1.get("env").is_none());
    }
    assert_eq!(
        calls[0].1["stdin"],
        std::str::from_utf8(&request(Mode::Apply))?
    );
    assert_eq!(
        calls[3].1["stdin"],
        std::str::from_utf8(&request(Mode::Readback))?
    );
    assert!(
        calls[0].1["idempotency_key"]
            .as_str()
            .is_some_and(|key| key.len() == 64)
    );
    assert!(calls[3].1.get("idempotency_key").is_none());
    let (payload, raw) = payload();
    assert_eq!(
        f.device.retained_attempts()?,
        vec![AndroidRuntimeAttempt {
            operation_id: payload.operation_id,
            payload_sha256: Sha256Digest::for_bytes(raw.as_bytes()),
            job_id: Some("original-job-1".into()),
        }]
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unknown_start_never_retries_but_retained_readonly_lane_remains_available() -> TestResult {
    let mut replies = vec![Reply::Fail];
    replies.extend(successful(b"{}"));
    let f = fixture(replies, Duration::from_secs(2)).await?;
    assert!(f.device.apply(&request(Mode::Apply)).is_err());
    assert!(f.device.apply(&request(Mode::Apply)).is_err());
    assert_eq!(f.server.calls.lock().expect("calls").len(), 1);
    assert_eq!(f.device.retained_attempts()?[0].job_id, None);
    assert_eq!(f.device.readback(&request(Mode::Readback))?, b"{}");
    assert!(f.device.apply(&request(Mode::Apply)).is_err());
    assert_eq!(f.server.calls.lock().expect("calls").len(), 4);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn independent_readback_cannot_reuse_an_earlier_job() -> TestResult {
    let f = fixture(
        [successful(b"{}"), successful(b"{}")].concat(),
        Duration::from_secs(2),
    )
    .await?;
    f.device.apply(&request(Mode::Apply))?;
    f.server.next_job.store(1, Ordering::Relaxed);
    assert!(f.device.readback(&request(Mode::Readback)).is_err());
    assert_eq!(f.server.calls.lock().expect("calls").len(), 4);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reused_job_and_revoked_source_retain_original_job_without_poll_or_replay() -> TestResult {
    let mut reused = start();
    reused["reused"] = json!(true);
    for reply in [Reply::Json(reused), Reply::Revoke(start())] {
        let f = fixture(vec![reply], Duration::from_secs(2)).await?;
        assert!(f.device.apply(&request(Mode::Apply)).is_err());
        assert_eq!(
            f.device.retained_attempts()?[0].job_id.as_deref(),
            Some("original-job-1")
        );
        assert!(f.device.apply(&request(Mode::Apply)).is_err());
        assert_eq!(f.server.calls.lock().expect("calls").len(), 1);
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn timeout_and_cancellation_close_effect_lane_without_a_second_start() -> TestResult {
    let f = fixture(vec![Reply::Delayed(start())], Duration::from_millis(50)).await?;
    assert!(f.device.apply(&request(Mode::Apply)).is_err());
    assert!(f.device.apply(&request(Mode::Apply)).is_err());
    assert_eq!(f.server.calls.lock().expect("calls").len(), 1);
    let f = fixture(vec![Reply::Delayed(start())], Duration::from_secs(2)).await?;
    let device = Arc::clone(&f.device);
    let applying = tokio::task::spawn_blocking(move || device.apply(&request(Mode::Apply)));
    f.server.entered.notified().await;
    f.device.invalidate();
    assert!(applying.await?.is_err());
    assert_eq!(
        f.device.retained_attempts()?[0].job_id.as_deref(),
        Some("original-job-1")
    );
    assert!(f.device.apply(&request(Mode::Apply)).is_err());
    assert_eq!(f.server.calls.lock().expect("calls").len(), 1);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn wrong_operation_hash_and_destination_reject_before_any_runtime_call() -> TestResult {
    let f = fixture(Vec::new(), Duration::from_secs(2)).await?;
    assert!(f.device.apply(&request(Mode::Readback)).is_err());
    for field in ["payload_sha256", "payload_base64", "op"] {
        let mut value: Value = serde_json::from_slice(&request(Mode::Apply))?;
        value[field] = json!("wrong");
        assert!(f.device.apply(&serde_json::to_vec(&value)?).is_err());
    }
    let (mut payload, _) = payload();
    payload.observation.generation.init_start_ticks = "777".into();
    payload.destination_id = payload.observation.destination_id()?;
    let raw = payload.to_json()?;
    let changed = json!({"op":"organ-set-text","payload_sha256":Sha256Digest::for_bytes(raw.as_bytes()),
        "payload_base64":base64::engine::general_purpose::STANDARD.encode(raw.as_bytes())});
    assert!(f.device.apply(&serde_json::to_vec(&changed)?).is_err());
    assert!(f.server.calls.lock().expect("calls").is_empty());
    Ok(())
}

#[test]
fn terminal_status_and_lossless_output_require_complete_original_bytes() -> TestResult {
    let bytes = "中文🙂".as_bytes();
    assert_eq!(
        wire::completed(&status(bytes), "original-job-1")?,
        Some([bytes.len(), 0])
    );
    assert_eq!(
        wire::output(&read(bytes), "original-job-1", [bytes.len(), 0])?,
        bytes
    );
    for (pointer, value) in [
        ("/job_id", json!("different")),
        ("/exit_code", json!(1)),
        ("/output_complete", json!(false)),
        ("/log_truncated/stdout", json!(true)),
        ("/log_errors/stdout", json!("lost")),
        ("/log_bytes/stdout/seen", json!(8193)),
    ] {
        let mut broken = status(bytes);
        *broken.pointer_mut(pointer).ok_or("pointer")? = value;
        assert!(wire::completed(&broken, "original-job-1").is_err());
    }
    for (pointer, value) in [
        ("/job_id", json!("different")),
        ("/stdout/offset", json!(1)),
        ("/stdout/next_offset", json!(1)),
        ("/stdout/eof", json!(false)),
        ("/stdout/bytes_hex", json!("00")),
        ("/stdout/text", json!("different")),
    ] {
        let mut broken = read(bytes);
        *broken.pointer_mut(pointer).ok_or("pointer")? = value;
        assert!(wire::output(&broken, "original-job-1", [bytes.len(), 0]).is_err());
    }
    Ok(())
}
