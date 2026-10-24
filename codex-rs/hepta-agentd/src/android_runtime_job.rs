//! The original Runtime process_start/wait/read wire contract. No shell lane.

use std::sync::atomic::Ordering;
use std::collections::BTreeMap;
use std::time::Duration;
use std::time::Instant;

use serde_json::Value;
use serde_json::json;
use codex_hepta_contracts::Sha256Digest;

use super::AgentdAndroidTextDevice;

const HOST: &str = "pocket4";
const EXECUTABLE: &str = "/usr/bin/sudo";
const ARGS: [&str; 2] = ["-n", "/usr/local/libexec/android-digitalis-observe-helper"];
const MAX_REPLY: usize = 8192;
const MAX_ENVELOPE: usize = 65536;

#[derive(Clone, Copy)]
pub(super) enum Invocation {
    Effect,
    Readback,
}

pub(super) async fn invoke(
    device: &AgentdAndroidTextDevice,
    request: &[u8],
    invocation: Invocation,
    deadline: Instant,
) -> Result<Vec<u8>, String> {
    let effect = matches!(invocation, Invocation::Effect);
    let budget = remaining(deadline)?;
    let mut arguments = json!({
        "host": HOST,
        "executable": EXECUTABLE,
        "args": ARGS,
        "stdin": std::str::from_utf8(request).map_err(|_| "Android helper input is not UTF-8")?,
        "timeout_seconds": budget.as_secs().clamp(1, 30),
    });
    if effect {
        if device.invalidated.load(Ordering::Acquire) {
            return Err("Android effect was invalidated before start".to_string());
        }
        arguments["idempotency_key"] = Value::String(device.idempotency_key.clone());
        device
            .attempt
            .lock()
            .map_err(|_| "Android original job correlation is unavailable")?
            .start_attempted = true;
    }
    // e023ce671650's original request_digest covers all ProcessStartParams
    // except the idempotency key, using serde_json's sorted object keys. Bind
    // stdin and timeout too: argv metadata alone cannot identify our request.
    let binding = BTreeMap::from([
        ("host", arguments["host"].clone()),
        ("executable", arguments["executable"].clone()),
        ("args", arguments["args"].clone()),
        ("cwd", Value::Null),
        ("env", json!({})),
        ("stdin", arguments["stdin"].clone()),
        ("timeout_seconds", arguments["timeout_seconds"].clone()),
        ("nice", Value::Null),
        ("cpu_quota_percent", Value::Null),
        ("memory_max_bytes", Value::Null),
    ]);
    let digest = Sha256Digest::for_bytes(
        &serde_json::to_vec(&binding).map_err(|_| "Runtime request binding cannot be encoded")?,
    );
    // This is the only effect start. A lost response is never followed by a
    // second process_start, including one with the same idempotency key.
    let started = call(device, "process_start", arguments, deadline).await?;
    let job = &started["job"];
    let job_id = job["id"]
        .as_str()
        .filter(|id| {
            !id.is_empty()
                && id.len() <= 128
                && id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
        })
        .ok_or("Runtime start has no valid original job ID")?;
    if job["host"] != HOST {
        return Err("Runtime start changed the original host".to_string());
    }
    if effect {
        device
            .attempt
            .lock()
            .map_err(|_| "Android original job correlation is unavailable")?
            .job_id = Some(job_id.to_string());
    }
    if job["executable"] != EXECUTABLE
        || job["args"] != json!(ARGS)
        || !job["cwd"].is_null()
        || job["env_keys"] != json!([])
        || job["launch_state"] != "launched"
        // The original Linux operator backend intentionally does not use the
        // isolated system jobctl. It retains the existing SSH account rights.
        || job["execution_mode"] != "operator"
        || job["system_jobctl"] != false
        || job["request_digest"] != digest.as_str()
        || started["reused"] != false
        || started["audit_recorded"] != true
        || started["local_record_pending"] != false
        || started["launch"]["ok"] != true
        || started["launch"]["reused_remote"] == true
        || !matches!(started["launch"]["backend"].as_str(), Some("systemd" | "detached"))
        || (effect && job["idempotency_key"] != device.idempotency_key)
        || (!effect && !job["idempotency_key"].is_null())
    {
        return Err("Runtime start did not bind the original fixed helper request".to_string());
    }
    for _ in 0..32 {
        if effect && device.invalidated.load(Ordering::Acquire) {
            return Err(
                "Android effect was invalidated while awaiting its original job".to_string(),
            );
        }
        let status = call(
            device,
            "process_wait",
            json!({
                "host": HOST, "job_id": job_id, "timeout_seconds": 1,
            }),
            deadline,
        )
        .await?;
        if status["job_id"] != job_id {
            return Err("Runtime status changed the original job".to_string());
        }
        match status["state"].as_str() {
            Some("succeeded") if status["exit_code"] == 0 && status["output_complete"] == true => {
                let stored = status["log_bytes"]["stdout"]["stored"]
                    .as_u64()
                    .ok_or("Runtime terminal status lacks original output accounting")?;
                if status["cancelled"] != false
                    || status["timed_out"] != false
                    || status["audit_recorded"] != true
                    || status["log_bytes"]["stdout"]["seen"] != stored
                    || !status["log_bytes"]["stderr"]["stored"].is_u64()
                    || status["log_bytes"]["stderr"]["seen"] != status["log_bytes"]["stderr"]["stored"]
                    || status["log_truncated"]["stdout"] != false
                    || status["log_truncated"]["stderr"] != false
                    || !status
                        .get("log_errors")
                        .and_then(|errors| errors.get("stdout"))
                        .is_some_and(Value::is_null)
                    || !status
                        .get("log_errors")
                        .and_then(|errors| errors.get("stderr"))
                        .is_some_and(Value::is_null)
                {
                    return Err(
                        "Runtime original job output is truncated, failed or unaudited".to_string(),
                    );
                }
                let output = call(
                    device,
                    "process_read",
                    json!({
                        "host": HOST, "job_id": job_id,
                        "stdout_offset": 0, "stderr_offset": 0, "limit": MAX_REPLY + 1,
                    }),
                    deadline,
                )
                .await?;
                remaining(deadline)?;
                if effect && device.invalidated.load(Ordering::Acquire) {
                    return Err("Android acknowledgement arrived after invalidation".to_string());
                }
                return exact_stdout(&output, job_id, stored);
            }
            Some("running" | "activating" | "finalizing" | "completed_unknown") => {
                tokio::time::sleep(Duration::from_millis(25).min(remaining(deadline)?)).await;
            }
            _ => {
                return Err("Runtime original job has no successful authoritative exit".to_string());
            }
        }
    }
    Err("Runtime original job exceeded the bounded poll count".to_string())
}

fn remaining(deadline: Instant) -> Result<Duration, String> {
    let value = deadline.saturating_duration_since(Instant::now());
    if value.is_zero() {
        Err("Android original exchange deadline expired".to_string())
    } else {
        Ok(value)
    }
}

async fn call(
    device: &AgentdAndroidTextDevice,
    tool: &str,
    arguments: Value,
    deadline: Instant,
) -> Result<Value, String> {
    let Value::Object(arguments) = arguments else {
        return Err("invalid Runtime arguments".to_string());
    };
    let response = device
        .session
        .call_tool_once(tool, arguments, remaining(deadline)?)
        .await
        .map_err(|_| "original retained Runtime call failed or expired".to_string())?;
    remaining(deadline)?;
    if response.is_error == Some(true) || response.content.len() != 1 {
        return Err("Runtime returned an error or ambiguous content".to_string());
    }
    let text = response.content[0]
        .as_text()
        .ok_or("Runtime returned a non-text process envelope")?;
    if text.text.is_empty() || text.text.len() > MAX_ENVELOPE {
        return Err("Runtime process envelope exceeds its bound".to_string());
    }
    let parsed: Value =
        serde_json::from_str(&text.text).map_err(|_| "Runtime process envelope is invalid JSON")?;
    if response
        .structured_content
        .as_ref()
        .is_some_and(|value| value != &parsed)
    {
        return Err("Runtime structured and text process results disagree".to_string());
    }
    Ok(parsed)
}

fn exact_stdout(output: &Value, job_id: &str, terminal_size: u64) -> Result<Vec<u8>, String> {
    let stdout = &output["stdout"];
    let size = stdout["size"]
        .as_u64()
        .ok_or("Runtime output lacks its byte size")?;
    if output["job_id"] != job_id
        || output["audit_recorded"] != true
        || size == 0
        || size > MAX_REPLY as u64
        || size != terminal_size
        || stdout["offset"] != 0
        || stdout["next_offset"] != size
        || stdout["eof"] != true
    {
        return Err(
            "Runtime output is incomplete, oversized or belongs to another job".to_string(),
        );
    }
    // Runtime's text field is lossy. Only its lossless bytes can establish an
    // exact receiver acknowledgement; older text-only Runtime versions fail.
    let hex = stdout["bytes_hex"]
        .as_str()
        .ok_or("Runtime output lacks lossless byte encoding")?;
    if hex.len() != size as usize * 2 || !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("Runtime output has invalid lossless byte encoding".to_string());
    }
    let bytes = hex
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let digit = |b: u8| {
                if b.is_ascii_digit() {
                    b - b'0'
                } else {
                    b.to_ascii_lowercase() - b'a' + 10
                }
            };
            digit(pair[0]) * 16 + digit(pair[1])
        })
        .collect::<Vec<_>>();
    let text = std::str::from_utf8(&bytes).map_err(|_| "Runtime receiver output is not UTF-8")?;
    if stdout["text"].as_str() != Some(text) {
        return Err("Runtime text and original output bytes disagree".to_string());
    }
    Ok(bytes)
}
