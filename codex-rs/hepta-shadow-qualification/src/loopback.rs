use std::collections::BTreeMap;
use std::net::Ipv4Addr;
use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use serde::Serialize;
use serde_json::Value;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::task::JoinHandle;

use crate::QualificationError;
use crate::Surface;
use crate::digest::sha256;
use crate::durable::create_or_verify_private_directory;
use crate::durable::write_private_new;
use crate::request::FIXED_MODEL;

const MAX_HEADER_BYTES: usize = 64 * 1024;
const MAX_BODY_BYTES: usize = 8 * 1024 * 1024;
const FUNCTION_ARGUMENTS: &str =
    r#"{"command":"/usr/bin/printf hepta-shadow-probe","login":false,"timeout_ms":5000}"#;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct HttpAuditRecord {
    call_id: String,
    post_ordinal: u8,
    request_body_sha256: String,
    request_wire_sha256: String,
    response_body_sha256: String,
    response_wire_sha256: String,
    sample_ordinal: u8,
    surface: Surface,
    validated_output_sha256: Option<String>,
}

impl HttpAuditRecord {
    pub fn call_id(&self) -> &str {
        &self.call_id
    }

    pub fn post_ordinal(&self) -> u8 {
        self.post_ordinal
    }

    pub(crate) fn request_body_sha256(&self) -> &str {
        &self.request_body_sha256
    }

    pub(crate) fn request_wire_sha256(&self) -> &str {
        &self.request_wire_sha256
    }

    pub(crate) fn response_body_sha256(&self) -> &str {
        &self.response_body_sha256
    }

    pub(crate) fn response_wire_sha256(&self) -> &str {
        &self.response_wire_sha256
    }

    pub fn sample_ordinal(&self) -> u8 {
        self.sample_ordinal
    }

    pub fn surface(&self) -> Surface {
        self.surface
    }

    pub fn validated_output_sha256(&self) -> Option<&str> {
        self.validated_output_sha256.as_deref()
    }
}

pub struct LoopbackHandle {
    address: SocketAddr,
    task: Option<JoinHandle<Result<Vec<HttpAuditRecord>, QualificationError>>>,
    timeout: Duration,
}

impl LoopbackHandle {
    pub async fn start(
        surface: Surface,
        run_root: impl AsRef<Path>,
        timeout: Duration,
    ) -> Result<Self, QualificationError> {
        let artifact_root = run_root.as_ref().join("http");
        create_or_verify_private_directory(&artifact_root)?;
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        if !address.ip().is_loopback() {
            return Err(state("loopback listener escaped IPv4 loopback"));
        }
        let task = tokio::spawn(serve(listener, surface, artifact_root, timeout));
        Ok(Self {
            address,
            task: Some(task),
            timeout,
        })
    }

    pub fn address(&self) -> SocketAddr {
        self.address
    }

    pub async fn finish(mut self) -> Result<Vec<HttpAuditRecord>, QualificationError> {
        let mut task = self
            .task
            .take()
            .ok_or_else(|| state("loopback task is unavailable"))?;
        match tokio::time::timeout(self.timeout, &mut task).await {
            Ok(result) => {
                result.map_err(|error| state(format!("loopback task failed: {error}")))?
            }
            Err(_) => {
                task.abort();
                let _ = tokio::time::timeout(self.timeout, &mut task).await;
                Err(state("timed out waiting for loopback completion"))
            }
        }
    }
}

impl Drop for LoopbackHandle {
    fn drop(&mut self) {
        if let Some(task) = &self.task {
            task.abort();
        }
    }
}

async fn serve(
    listener: TcpListener,
    surface: Surface,
    artifact_root: PathBuf,
    timeout: Duration,
) -> Result<Vec<HttpAuditRecord>, QualificationError> {
    let expected_host = listener.local_addr()?.to_string();
    let mut records = Vec::with_capacity(4);
    for request_ordinal in 1..=4_u8 {
        let (mut stream, peer) = tokio::time::timeout(timeout, listener.accept())
            .await
            .map_err(|_| {
                state(format!(
                    "timed out waiting for HTTP request {request_ordinal}"
                ))
            })??;
        if !peer.ip().is_loopback() {
            return Err(invalid("loopback server received a non-loopback peer"));
        }
        let request = tokio::time::timeout(timeout, read_request(&mut stream))
            .await
            .map_err(|_| state(format!("timed out reading HTTP request {request_ordinal}")))??;
        let sample_ordinal = (request_ordinal - 1) / 2 + 1;
        let post_ordinal = (request_ordinal - 1) % 2 + 1;
        let prefix = format!("{}-{sample_ordinal:02}-{post_ordinal:02}", surface.as_str());
        write_private_new(
            &artifact_root.join(format!("{prefix}-request.http")),
            &request.wire,
        )?;
        write_private_new(
            &artifact_root.join(format!("{prefix}-request-body.json")),
            &request.body,
        )?;
        let call_id = format!("{}-{sample_ordinal}-call-v1", surface.as_str());
        let validated_output = validate_request(
            &request,
            &expected_host,
            surface,
            sample_ordinal,
            &call_id,
            post_ordinal,
        )?;
        let response_body = if post_ordinal == 1 {
            function_call_sse(surface, sample_ordinal, &call_id)
        } else {
            final_message_sse(surface, sample_ordinal)
        };
        let response_wire = response_wire(response_body.as_bytes())?;
        write_private_new(
            &artifact_root.join(format!("{prefix}-response.sse")),
            response_body.as_bytes(),
        )?;
        write_private_new(
            &artifact_root.join(format!("{prefix}-response.http")),
            &response_wire,
        )?;
        stream.write_all(&response_wire).await?;
        stream.flush().await?;
        stream.shutdown().await?;
        records.push(HttpAuditRecord {
            call_id,
            post_ordinal,
            request_body_sha256: sha256(&request.body),
            request_wire_sha256: sha256(&request.wire),
            response_body_sha256: sha256(response_body.as_bytes()),
            response_wire_sha256: sha256(&response_wire),
            sample_ordinal,
            surface,
            validated_output_sha256: validated_output
                .as_deref()
                .map(|value| sha256(value.as_bytes())),
        });
    }
    Ok(records)
}

struct HttpRequest {
    body: Vec<u8>,
    headers: BTreeMap<String, String>,
    method: String,
    target: String,
    wire: Vec<u8>,
}

async fn read_request(stream: &mut TcpStream) -> Result<HttpRequest, QualificationError> {
    let mut buffer = Vec::with_capacity(8_192);
    let header_end = loop {
        if let Some(index) = find_subslice(&buffer, b"\r\n\r\n") {
            break index + 4;
        }
        if buffer.len() >= MAX_HEADER_BYTES {
            return Err(invalid("HTTP request headers exceed bound"));
        }
        let mut chunk = [0_u8; 4_096];
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            return Err(invalid("HTTP peer closed before headers completed"));
        }
        buffer.extend_from_slice(&chunk[..count]);
    };
    if header_end > MAX_HEADER_BYTES {
        return Err(invalid("HTTP request headers exceed bound"));
    }
    let header = std::str::from_utf8(&buffer[..header_end - 4])
        .map_err(|error| invalid(format!("HTTP headers are not UTF-8: {error}")))?;
    let mut lines = header.split("\r\n");
    let mut request_line = lines
        .next()
        .ok_or_else(|| invalid("HTTP request line is missing"))?
        .split(' ');
    let method = request_line.next().unwrap_or_default().to_string();
    let target = request_line.next().unwrap_or_default().to_string();
    if request_line.next() != Some("HTTP/1.1") || request_line.next().is_some() {
        return Err(invalid("HTTP request line is invalid"));
    }
    let mut headers = BTreeMap::new();
    for line in lines {
        let (name, value) = line
            .split_once(':')
            .ok_or_else(|| invalid("malformed HTTP header"))?;
        let name = name.trim().to_ascii_lowercase();
        if name.is_empty()
            || headers
                .insert(name.clone(), value.trim().to_string())
                .is_some()
        {
            return Err(invalid(format!("empty or duplicate HTTP header {name}")));
        }
    }
    let content_length = headers
        .get("content-length")
        .ok_or_else(|| invalid("Content-Length is missing"))?
        .parse::<usize>()
        .map_err(|error| invalid(format!("invalid Content-Length: {error}")))?;
    if content_length > MAX_BODY_BYTES || headers.contains_key("transfer-encoding") {
        return Err(invalid("HTTP body is oversized or transfer-encoded"));
    }
    let content_type = headers
        .get("content-type")
        .ok_or_else(|| invalid("Content-Type is missing"))?;
    if !content_type
        .split(';')
        .next()
        .is_some_and(|value| value.trim().eq_ignore_ascii_case("application/json"))
    {
        return Err(invalid("Content-Type must be application/json"));
    }
    for name in headers.keys() {
        if name.contains("api-key")
            || name.contains("authorization")
            || name.contains("cookie")
            || name.contains("token")
        {
            return Err(invalid(format!(
                "sensitive HTTP header {name} is forbidden"
            )));
        }
    }
    while buffer.len() - header_end < content_length {
        let remaining = content_length - (buffer.len() - header_end);
        let mut chunk = vec![0_u8; remaining.min(8_192)];
        let count = stream.read(&mut chunk).await?;
        if count == 0 {
            return Err(invalid("HTTP peer closed before body completed"));
        }
        buffer.extend_from_slice(&chunk[..count]);
    }
    if buffer.len() - header_end != content_length {
        return Err(invalid("HTTP connection contains bytes beyond one request"));
    }
    Ok(HttpRequest {
        body: buffer[header_end..].to_vec(),
        headers,
        method,
        target,
        wire: buffer,
    })
}

fn validate_request(
    request: &HttpRequest,
    expected_host: &str,
    surface: Surface,
    sample_ordinal: u8,
    call_id: &str,
    post_ordinal: u8,
) -> Result<Option<String>, QualificationError> {
    if request.method != "POST"
        || request.target != "/v1/responses"
        || request.headers.get("host").map(String::as_str) != Some(expected_host)
    {
        return Err(invalid("HTTP request method, target, or Host differs"));
    }
    let body: Value = serde_json::from_slice(&request.body)
        .map_err(|error| invalid(format!("invalid model request JSON: {error}")))?;
    if body.get("model").and_then(Value::as_str) != Some(FIXED_MODEL)
        || body.get("stream").and_then(Value::as_bool) != Some(true)
        || !contains_shell_tool(&body)
    {
        return Err(invalid(
            "model request differs from exact streamed shell-tool shape",
        ));
    }
    let outputs = function_outputs(&body);
    let expected_count = usize::from(sample_ordinal - 1) + usize::from(post_ordinal == 2);
    if outputs.len() != expected_count {
        return Err(invalid("function output history cardinality differs"));
    }
    let mut current_output = None;
    for (index, (actual_call_id, output)) in outputs.into_iter().enumerate() {
        let output_sample = u8::try_from(index + 1)
            .map_err(|_| invalid("function output sample ordinal overflow"))?;
        let expected_call_id = format!("{}-{output_sample}-call-v1", surface.as_str());
        if actual_call_id != Some(expected_call_id.as_str()) {
            return Err(invalid(
                "function output call_id differs from issued history",
            ));
        }
        let output = output
            .and_then(Value::as_str)
            .ok_or_else(|| invalid("function output payload is not a string"))?;
        validate_shell_output(output)?;
        if actual_call_id == Some(call_id) {
            current_output = Some(output.to_string());
        }
    }
    if (post_ordinal == 2) != current_output.is_some() {
        return Err(invalid("current function output differs from post ordinal"));
    }
    Ok(current_output)
}

fn contains_shell_tool(value: &Value) -> bool {
    value
        .get("tools")
        .and_then(Value::as_array)
        .is_some_and(|tools| {
            tools.iter().any(|tool| {
                tool.get("name").and_then(Value::as_str) == Some("shell_command")
                    || tool.pointer("/function/name").and_then(Value::as_str)
                        == Some("shell_command")
            })
        })
}

fn function_outputs(value: &Value) -> Vec<(Option<&str>, Option<&Value>)> {
    let mut outputs = Vec::new();
    collect_outputs(value, &mut outputs);
    outputs
}

fn collect_outputs<'a>(value: &'a Value, outputs: &mut Vec<(Option<&'a str>, Option<&'a Value>)>) {
    match value {
        Value::Array(items) => items.iter().for_each(|item| collect_outputs(item, outputs)),
        Value::Object(object) => {
            if object.get("type").and_then(Value::as_str) == Some("function_call_output") {
                outputs.push((
                    object.get("call_id").and_then(Value::as_str),
                    object.get("output"),
                ));
            }
            object
                .values()
                .for_each(|item| collect_outputs(item, outputs));
        }
        _ => {}
    }
}

fn validate_shell_output(output: &str) -> Result<(), QualificationError> {
    let rest = output
        .strip_prefix("Exit code: 0\nWall time: ")
        .ok_or_else(|| invalid("shell output did not report exit code zero"))?;
    let (wall_time, stdout) = rest
        .split_once(" seconds\nOutput:\n")
        .ok_or_else(|| invalid("shell output framing differs"))?;
    let wall_time = wall_time
        .parse::<f64>()
        .map_err(|error| invalid(format!("shell wall time is invalid: {error}")))?;
    if !wall_time.is_finite()
        || !(0.0..=60.0).contains(&wall_time)
        || stdout != "hepta-shadow-probe"
    {
        return Err(invalid(
            "shell output is outside exact qualification bounds",
        ));
    }
    Ok(())
}

fn function_call_sse(surface: Surface, sample: u8, call_id: &str) -> String {
    let response_id = format!("resp-{}-{sample}-tool", surface.as_str());
    sse(&[
        serde_json::json!({"type": "response.created", "response": {"id": response_id}}),
        serde_json::json!({
            "type": "response.output_item.done",
            "item": {
                "arguments": FUNCTION_ARGUMENTS,
                "call_id": call_id,
                "name": "shell_command",
                "type": "function_call",
            },
        }),
        completed_event(&response_id),
    ])
}

fn final_message_sse(surface: Surface, sample: u8) -> String {
    let response_id = format!("resp-{}-{sample}-final", surface.as_str());
    sse(&[
        serde_json::json!({"type": "response.created", "response": {"id": response_id}}),
        serde_json::json!({
            "type": "response.output_item.done",
            "item": {
                "content": [{"text": "controlled qualification completed", "type": "output_text"}],
                "id": format!("msg-{}-{sample}-final", surface.as_str()),
                "role": "assistant",
                "type": "message",
            },
        }),
        completed_event(&response_id),
    ])
}

fn completed_event(response_id: &str) -> Value {
    serde_json::json!({
        "type": "response.completed",
        "response": {
            "id": response_id,
            "usage": {
                "input_tokens": 0,
                "input_tokens_details": null,
                "output_tokens": 0,
                "output_tokens_details": null,
                "total_tokens": 0,
            },
        },
    })
}

fn sse(events: &[Value]) -> String {
    use std::fmt::Write as _;
    let mut body = String::new();
    for event in events {
        let kind = event
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("invalid");
        let _ = writeln!(&mut body, "event: {kind}");
        let _ = writeln!(&mut body, "data: {event}\n");
    }
    body
}

fn response_wire(body: &[u8]) -> Result<Vec<u8>, QualificationError> {
    if body.len() > MAX_BODY_BYTES {
        return Err(invalid("HTTP response body exceeds bound"));
    }
    let header = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let mut wire = header.into_bytes();
    wire.extend_from_slice(body);
    Ok(wire)
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}

fn state(message: impl Into<String>) -> QualificationError {
    QualificationError::State(message.into())
}
