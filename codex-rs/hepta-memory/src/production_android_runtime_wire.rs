//! Runtime v1 response validation. Only actual job bytes are receiver evidence.

use rmcp::model::CallToolResult;
use serde_json::Value;

use super::ARGS;
use super::EXECUTABLE;
use super::HOST;
use super::MAX_OUTPUT;

const MAX_ENVELOPE: usize = 65536;

pub(super) fn result_json(result: CallToolResult) -> Result<Value, String> {
    if result.is_error == Some(true) {
        return Err("original Runtime returned a tool error".into());
    }
    let text = match result.content.as_slice() {
        [] => None,
        [content] => {
            let text = &content.as_text().ok_or("unexpected Runtime content")?.text;
            if text.len() > MAX_ENVELOPE {
                return Err("Runtime reply exceeds its bound".into());
            }
            Some(serde_json::from_str::<Value>(text).map_err(|_| "invalid Runtime JSON")?)
        }
        _ => return Err("ambiguous Runtime content".into()),
    };
    let value = match (result.structured_content, text) {
        (Some(structured), Some(text)) if structured != text => {
            return Err("Runtime structured and text replies disagree".into());
        }
        (Some(value), _) | (None, Some(value)) => value,
        (None, None) => return Err("missing Runtime JSON".into()),
    };
    if serde_json::to_vec(&value)
        .map_err(|error| error.to_string())?
        .len()
        > MAX_ENVELOPE
        || value.get("audit_recorded") != Some(&Value::Bool(true))
    {
        return Err("Runtime reply is oversized or lacks original audit acknowledgement".into());
    }
    Ok(value)
}

pub(super) fn started(value: &Value, request: &Value) -> Result<(String, bool), String> {
    let job = &value["job"];
    let id = job["id"].as_str().ok_or("missing original Runtime job")?;
    let reused = value["reused"]
        .as_bool()
        .ok_or("missing Runtime reuse state")?;
    if id.is_empty()
        || id.len() > 128
        || !id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
        || job["host"] != HOST
        || job["executable"] != EXECUTABLE
        || job["args"] != serde_json::json!(ARGS)
        || job.get("cwd") != Some(&Value::Null)
        || job["env_keys"] != serde_json::json!([])
        || job["idempotency_key"] != request["idempotency_key"]
        || job["launch_state"] != "launched"
        || job.get("launch_error") != Some(&Value::Null)
        || value["launch"]["ok"] != true
        || value["local_record_pending"] != false
    {
        return Err("Runtime start did not bind the original fixed helper job".into());
    }
    Ok((id.to_string(), reused))
}

pub(super) fn completed(value: &Value, job: &str) -> Result<Option<[usize; 2]>, String> {
    if value["job_id"] != job || value["cancelled"] != false || value["timed_out"] != false {
        return Err("Runtime status changed job, timed out or was cancelled".into());
    }
    if value["state"] == "running" && value.get("exit_code") == Some(&Value::Null) {
        return Ok(None);
    }
    let mut lengths = [0; 2];
    for (index, stream) in ["stdout", "stderr"].into_iter().enumerate() {
        let bytes = &value["log_bytes"][stream];
        let seen = bytes["seen"].as_u64().ok_or("missing Runtime log length")?;
        let stored = bytes["stored"]
            .as_u64()
            .ok_or("missing Runtime stored length")?;
        if seen != stored
            || seen > MAX_OUTPUT as u64
            || value["log_truncated"][stream] != false
            || value["log_errors"].get(stream) != Some(&Value::Null)
        {
            return Err("Runtime output is truncated, oversized or unavailable".into());
        }
        lengths[index] = stored as usize;
    }
    match value["state"].as_str() {
        Some("succeeded") if value["exit_code"] == 0 && value["output_complete"] == true => {
            Ok(Some(lengths))
        }
        _ => Err("original helper has no confirmed successful complete exit".into()),
    }
}

pub(super) fn output(value: &Value, job: &str, lengths: [usize; 2]) -> Result<Vec<u8>, String> {
    if value["job_id"] != job {
        return Err("Runtime output belongs to another job".into());
    }
    let mut stdout = Vec::new();
    for (index, stream) in ["stdout", "stderr"].into_iter().enumerate() {
        let output = &value[stream];
        let expected = lengths[index];
        let hex = output["bytes_hex"]
            .as_str()
            .ok_or("missing lossless Runtime bytes")?;
        if output["offset"] != 0
            || output["next_offset"].as_u64() != Some(expected as u64)
            || output["size"].as_u64() != Some(expected as u64)
            || output["eof"] != true
            || hex.len() != expected * 2
            || !hex.bytes().all(|byte| byte.is_ascii_hexdigit())
        {
            return Err("Runtime output is incomplete or has inconsistent byte cursors".into());
        }
        let bytes = (0..hex.len())
            .step_by(2)
            .map(|offset| u8::from_str_radix(&hex[offset..offset + 2], 16))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| "invalid lossless Runtime bytes")?;
        let text = std::str::from_utf8(&bytes).map_err(|_| "non-UTF-8 Runtime output")?;
        if output["text"] != text {
            return Err("Runtime text and lossless bytes disagree".into());
        }
        if index == 0 {
            stdout = bytes;
        }
    }
    if stdout.is_empty() {
        return Err("original helper returned empty stdout".into());
    }
    Ok(stdout)
}
