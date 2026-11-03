//! Real HTTP/SSE -> current native loop -> bounded qualification wire sink.

use super::*;
use codex_hepta_native_agent::Limits;
use codex_hepta_native_agent::NativeAgent;
use codex_hepta_native_agent::ResponsesModel;
use codex_hepta_native_agent::RunOutcome;
use codex_hepta_native_agent::ToolObservation;
use codex_hepta_native_agent::ToolPort;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use hepta_native_qualification::owner::FixtureConfig;
use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

struct Buffer(Arc<Mutex<Vec<u8>>>);
impl Write for Buffer {
    fn write(&mut self, value: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(value);
        Ok(value.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

struct NoTools;
impl ToolPort for NoTools {
    async fn execute_or_observe(
        &self,
        _: &RuntimeToolIntentV1,
        _: &[u8],
    ) -> Result<ToolObservation> {
        anyhow::bail!("unexpected tool dispatch")
    }
    async fn observe(&self, _: &RuntimeToolIntentV1) -> Result<ToolObservation> {
        anyhow::bail!("unexpected tool observation")
    }
    async fn cancel(&self, _: &RuntimeToolIntentV1) -> Result<()> {
        anyhow::bail!("unexpected tool cancellation")
    }
}

#[tokio::test]
async fn real_chinese_sse_deltas_and_settled_history_share_qualification_item_identity()
-> Result<()> {
    let text = "这是原始中文增量。".repeat(900);
    let midpoint = text
        .char_indices()
        .nth(text.chars().count() / 2)
        .context("midpoint")?
        .0;
    let item = json!({"type":"message", "id":"provider-original-item", "role":"assistant",
        "content":[{"type":"output_text", "text":text}]});
    let events = [
        json!({"type":"response.created", "response":{"id":"provider-original-response"}}),
        json!({"type":"response.output_item.added", "output_index":0,
            "item":{"type":"message", "id":"provider-original-item", "role":"assistant", "content":[]}}),
        json!({"type":"response.output_text.delta", "item_id":"provider-original-item", "output_index":0,
            "content_index":0, "delta":&text[..midpoint]}),
        json!({"type":"response.output_text.delta", "item_id":"provider-original-item", "output_index":0,
            "content_index":0, "delta":&text[midpoint..]}),
        json!({"type":"response.output_item.done", "output_index":0, "item":item}),
        json!({"type":"response.completed", "response":{"id":"provider-original-response", "status":"completed",
            "output":[item], "usage":{"input_tokens":1,"output_tokens":1}}}),
    ].into_iter().map(|event| format!("data: {event}\n\n")).collect::<String>();
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let endpoint = format!("http://{}/v1/responses", listener.local_addr()?);
    let server = std::thread::spawn(move || -> Result<Vec<u8>> {
        let (mut stream, _) = listener.accept()?;
        stream.set_read_timeout(Some(Duration::from_secs(5)))?;
        let mut request = Vec::new();
        let end = loop {
            let mut chunk = [0u8; 4096];
            let count = stream.read(&mut chunk)?;
            ensure!(
                count > 0 && request.len() + count <= 131072,
                "bounded original HTTP request required"
            );
            request.extend_from_slice(&chunk[..count]);
            if let Some(index) = request.windows(4).position(|window| window == b"\r\n\r\n") {
                break index + 4;
            }
        };
        let header = std::str::from_utf8(&request[..end])?;
        ensure!(
            header.starts_with("POST /v1/responses "),
            "original POST expected"
        );
        let length = header
            .lines()
            .find_map(|line| {
                line.split_once(':')
                    .filter(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                    .map(|(_, value)| value.trim().parse::<usize>())
            })
            .context("content length")??;
        ensure!(end + length <= 131072, "original request byte bound");
        while request.len() < end + length {
            let mut chunk = [0u8; 4096];
            let count = stream.read(&mut chunk)?;
            ensure!(count > 0, "request body truncated");
            request.extend_from_slice(&chunk[..count]);
        }
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            events.len(),
            events
        );
        stream.write_all(response.as_bytes())?;
        stream.flush()?;
        Ok(request)
    });
    let temporary = tempfile::tempdir()?;
    let config = FixtureConfig {
        representative: false,
        host: "unused".to_owned(),
        script: "unused".to_owned(),
        script_sha256: Digest32::of_bytes(b"").to_string(),
        data: "unused".to_owned(),
        data_sha256: Digest32::of_bytes(b"").to_string(),
        cwd: temporary.path().to_string_lossy().into_owned(),
        tool_timeout_seconds: 1,
    };
    let (owner, mut state) = SessionOwner::open(
        temporary.path().join("session"),
        "original-session",
        "原始输入",
        config,
        json!({"scope":OWNER_SCOPE,"ui":contract()}),
    )?;
    let owner = Arc::new(owner);
    let captured = Arc::new(Mutex::new(Vec::new()));
    let sink = QualificationUiSink {
        owner: owner.clone(),
        session: "original-session".to_owned(),
        writer: Mutex::new(Box::new(Buffer(captured.clone()))),
    };
    let agent = NativeAgent {
        model_name: "fixture-model".to_owned(),
        instructions: "Return the answer".to_owned(),
        tools: Vec::new(),
        store_responses: true,
        limits: Limits {
            context_bytes: 65536,
            output_tokens: 64,
            model_calls: 1,
            tool_calls: 1,
            tool_output_bytes: 4096,
            model_timeout: Duration::from_secs(5),
            tool_timeout: Duration::from_secs(1),
            observation_interval: Duration::from_millis(1),
        },
    };
    let factory = HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault);
    let model = ResponsesModel::new(
        &factory,
        endpoint,
        None,
        Duration::from_secs(5),
        1024 * 1024,
    )?;
    let result = agent
        .run_with_events(
            owner.as_ref(),
            &NoTools,
            &model,
            &mut state,
            &CancellationToken::new(),
            &sink,
        )
        .await?;
    assert_eq!(result, RunOutcome::Completed(text.clone()));
    sink.publish_completed(&state)?;
    let raw = captured.lock().unwrap().clone();
    let records = std::str::from_utf8(&raw)?
        .lines()
        .map(serde_json::from_str::<Value>)
        .collect::<std::result::Result<Vec<_>, _>>()?;
    assert_eq!(records.len(), 3);
    assert_eq!(records[0]["event"], "ui/text_delta");
    assert_eq!(records[1]["event"], "ui/text_delta");
    assert_eq!(records[2]["event"], "ui/item_completed");
    assert_eq!(records[0]["item_id"], records[1]["item_id"]);
    assert_eq!(records[0]["item_id"], records[2]["item_id"]);
    assert_eq!(records[2]["text"], text);
    assert_eq!(records[0]["session"], "original-session");
    assert_eq!(state.model_calls, 1);
    assert!(state.pending_model.is_none());
    assert!(!owner.store.root.join("model-00000001.json").exists());
    let request = server
        .join()
        .map_err(|_| anyhow::anyhow!("HTTP fixture panicked"))??;
    assert!(
        request
            .windows(b"idempotency-key:".len())
            .any(|window| window.eq_ignore_ascii_case(b"idempotency-key:"))
    );
    Ok(())
}
