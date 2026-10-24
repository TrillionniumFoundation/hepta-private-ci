//! Protocol faults over the actual retained MCP client; no device or authority claims.

use super::*;
use std::future::Future;
use std::io;
use std::pin::Pin;
use std::sync::atomic::AtomicUsize;

use codex_rmcp_client::InProcessTransportFactory;
use codex_rmcp_client::RmcpClient;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::io::DuplexStream;

type TestResult = Result<(), Box<dyn std::error::Error>>;
const RECEIVER_BYTES: &str = "{\"fixture_only\":\"中文😀\"}\n";

#[derive(Clone, Copy)]
pub(crate) enum Fault {
    None,
    LostStart,
    LateStart,
    Nonzero,
    WrongJob,
    Partial,
    LossyOnly,
    InvalidUtf8,
    UnfinishedOutput,
    Truncated,
    LogError,
}

#[derive(Default)]
pub(crate) struct Calls {
    pub(crate) requests: Mutex<Vec<Value>>,
    opens: AtomicUsize,
}

struct Factory {
    calls: Arc<Calls>,
    fault: Fault,
}

impl InProcessTransportFactory for Factory {
    fn open(&self) -> Pin<Box<dyn Future<Output = io::Result<DuplexStream>> + Send + 'static>> {
        let calls = Arc::clone(&self.calls);
        let fault = self.fault;
        Box::pin(async move {
            calls.opens.fetch_add(1, Ordering::SeqCst);
            let (client, server) = tokio::io::duplex(65536);
            tokio::spawn(serve(server, calls, fault));
            Ok(client)
        })
    }
}

async fn serve(stream: DuplexStream, calls: Arc<Calls>, fault: Fault) -> io::Result<()> {
    let (read, mut write) = tokio::io::split(stream);
    let mut lines = BufReader::new(read).lines();
    let mut jobs = 0;
    while let Some(line) = lines.next_line().await? {
        let request: Value = serde_json::from_str(&line)?;
        let result = match request["method"].as_str() {
            Some("initialize") => json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}},
                "serverInfo":{"name":"synthetic-original-runtime","version":"1"}}),
            Some("tools/call") => {
                let params = &request["params"];
                let arguments = &params["arguments"];
                calls.requests.lock().expect("calls").push(params.clone());
                let output = match params["name"].as_str() {
                    Some("process_start") => {
                        jobs += 1;
                        if matches!(fault, Fault::LostStart) { return Ok(()); }
                        if matches!(fault, Fault::LateStart) { tokio::time::sleep(Duration::from_secs(2)).await; }
                        json!({"reused":false,"job":{
                            "id":format!("fixture-job-{jobs}"),"host":arguments["host"],
                            "executable":arguments["executable"],"args":arguments["args"],
                            "cwd":null,"env_keys":[],"launch_state":"launched","system_jobctl":true,
                            "idempotency_key":arguments["idempotency_key"]
                        }})
                    }
                    Some("process_wait") => json!({
                        "job_id":arguments["job_id"],
                        "state":if matches!(fault,Fault::Nonzero) { "failed" } else { "succeeded" },
                        "exit_code":if matches!(fault,Fault::Nonzero) { 1 } else { 0 },
                        "output_complete":!matches!(fault,Fault::UnfinishedOutput),
                        "cancelled":false,"timed_out":false,"audit_recorded":true,
                        "log_bytes":{"stdout":{"seen":if matches!(fault,Fault::InvalidUtf8){1}else{RECEIVER_BYTES.len()},
                            "stored":if matches!(fault,Fault::InvalidUtf8){1}else{RECEIVER_BYTES.len()}}},
                        "log_truncated":{"stdout":matches!(fault,Fault::Truncated),"stderr":false},
                        "log_errors":{"stdout":if matches!(fault,Fault::LogError){json!("fixture log failure")}else{Value::Null},"stderr":null},
                    }),
                    Some("process_read") => {
                        let bytes = if matches!(fault, Fault::InvalidUtf8) { &[0xff][..] } else { RECEIVER_BYTES.as_bytes() };
                        let mut stdout = json!({"offset":0,"next_offset":bytes.len(),"size":bytes.len(),
                            "eof":!matches!(fault,Fault::Partial),"text":String::from_utf8_lossy(bytes),
                            "bytes_hex":bytes.iter().map(|b|format!("{b:02x}")).collect::<String>()});
                        if matches!(fault, Fault::LossyOnly) { stdout.as_object_mut().expect("stdout").remove("bytes_hex"); }
                        json!({"audit_recorded":true,"job_id":if matches!(fault, Fault::WrongJob) { json!("other-job") } else { arguments["job_id"].clone() },"stdout":stdout})
                    }
                    _ => panic!("unexpected process tool"),
                };
                json!({"content":[{"type":"text","text":serde_json::to_string(&output)?}],"isError":false})
            }
            _ if request["id"].is_null() => continue,
            _ => panic!("unexpected MCP method"),
        };
        let mut response = serde_json::to_vec(&json!({"jsonrpc":"2.0","id":request["id"],"result":result}))?;
        response.push(b'\n');
        write.write_all(&response).await?;
    }
    Ok(())
}

pub(crate) async fn inputs(fault: Fault, budget: Duration) -> Result<(AgentdAndroidRuntimeInputs, RmcpClient, Arc<Calls>), Box<dyn std::error::Error>> {
    let calls = Arc::new(Calls::default());
    let client = RmcpClient::new_in_process_client(Arc::new(Factory { calls: Arc::clone(&calls), fault })).await?;
    client.initialize(serde_json::from_value(json!({
        "protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"android-protocol-test","version":"1"},
    }))?, Some(Duration::from_secs(2)),
        Box::new(|_,_|Box::pin(async { anyhow::bail!("fixture never authorizes elicitation") }))).await?;
    let fixture: Value = serde_json::from_str(include_str!("../tests/fixtures/android-bound-text-v1.json"))?;
    Ok((AgentdAndroidRuntimeInputs {
        session: client.retain_tool_session().await?,
        runtime: Handle::current(),
        payload_json: fixture["request_utf8"].as_str().expect("golden UTF-8").to_string(),
        deadline: Instant::now() + budget,
    }, client, calls))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn android_runtime_fixed_helper_uses_original_bytes_then_independent_read_job() -> TestResult {
    let (inputs, client, calls) = inputs(Fault::None, Duration::from_secs(2)).await?;
    let (device, _) = AgentdAndroidTextDevice::new(inputs)?;
    assert_eq!(device.apply(&device.apply_request)?, RECEIVER_BYTES.as_bytes());
    assert_eq!(device.readback(&device.read_request)?, RECEIVER_BYTES.as_bytes());
    assert!(device.apply(&device.apply_request).is_err());
    let requests = calls.requests.lock().expect("calls").clone();
    let starts = requests.iter().filter(|r|r["name"]=="process_start").collect::<Vec<_>>();
    assert_eq!(starts.len(), 2);
    assert_eq!(starts[0]["arguments"], json!({"host":"pocket4","executable":"/usr/bin/sudo",
        "args":["-n","/usr/local/libexec/android-digitalis-observe-helper"],
        "stdin":String::from_utf8(device.apply_request.clone())?,"timeout_seconds":1,
        "idempotency_key":device.idempotency_key}));
    assert_eq!(starts[1]["arguments"]["stdin"], String::from_utf8(device.read_request.clone())?);
    assert!(starts[1]["arguments"].get("idempotency_key").is_none());
    assert_eq!(device.attempt()?, AndroidRuntimeAttempt {
        operation_id:"fixture-original-android-op".to_string(),
        payload_sha256:Sha256Digest::parse("69754c6cd929910f0d43cde0af0f1f3356ad7521ee79086bb5c95c1c7e1089f2")?,
        start_attempted:true,job_id:Some("fixture-job-1".to_string()),
    });
    assert_eq!(calls.opens.load(Ordering::SeqCst),1);
    client.shutdown().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn android_runtime_unknown_start_and_lost_reply_never_repeat_effect_or_reconnect() -> TestResult {
    for fault in [Fault::LostStart, Fault::LateStart] {
        let (inputs, client, calls) = inputs(fault, Duration::from_millis(120)).await?;
        let (device, _) = AgentdAndroidTextDevice::new(inputs)?;
        assert!(device.apply(&device.apply_request).is_err());
        assert!(device.apply(&device.apply_request).is_err());
        let attempt = device.attempt()?;
        assert_eq!((attempt.start_attempted, attempt.job_id), (true, None));
        assert_eq!((calls.requests.lock().expect("calls").len(), calls.opens.load(Ordering::SeqCst)), (1,1));
        client.shutdown().await;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn android_runtime_requires_terminal_success_complete_lossless_same_job_output() -> TestResult {
    for fault in [Fault::Nonzero,Fault::WrongJob,Fault::Partial,Fault::LossyOnly,Fault::InvalidUtf8,Fault::UnfinishedOutput,Fault::Truncated,Fault::LogError] {
        let (inputs, client, calls) = inputs(fault, Duration::from_secs(2)).await?;
        let (device, _) = AgentdAndroidTextDevice::new(inputs)?;
        assert!(device.apply(&device.apply_request).is_err());
        assert!(device.apply(&device.apply_request).is_err());
        assert_eq!(device.attempt()?.job_id, Some("fixture-job-1".to_string()));
        assert_eq!(calls.requests.lock().expect("calls").iter().filter(|r|r["name"]=="process_start").count(),1);
        client.shutdown().await;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn android_runtime_invalidation_allows_only_original_readback_and_payload_drift_sends_nothing() -> TestResult {
    let (inputs, client, calls) = inputs(Fault::None, Duration::from_secs(2)).await?;
    let (device, _) = AgentdAndroidTextDevice::new(inputs)?;
    device.invalidate();
    assert!(device.apply(&device.apply_request).is_err());
    assert!(device.readback(b"{\"op\":\"organ-readback\"}").is_err());
    assert_eq!(device.readback(&device.read_request)?, RECEIVER_BYTES.as_bytes());
    assert_eq!(calls.requests.lock().expect("calls").iter().filter(|r|r["name"]=="process_start").count(),1);
    assert!(!device.attempt()?.start_attempted);
    client.shutdown().await;
    Ok(())
}
