//! Strict response parsing for the pinned runtime qualification bridge.
use std::collections::BTreeMap;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_types::Digest32;
use codex_hepta_types::RuntimeToolIntentV1;
use hepta_runtime::mcp::runtime::HostConfig;
use hepta_runtime::mcp::runtime::jobs::ProcessStartParams;
use serde::Serialize;
use serde_json::Value;

use super::AdmittedTool;

pub(super) fn validate_admission(
    admitted: &AdmittedTool,
    intent: &RuntimeToolIntentV1,
    submitted: Option<&[u8]>,
) -> Result<()> {
    intent.validate()?;
    if admitted.intent != *intent
        || intent.tool_id.as_str() != "process_start"
        || Digest32::of_bytes(&admitted.arguments) != intent.arguments_digest
        || serde_json::to_vec(&admitted.params)? != admitted.arguments
        || submitted.is_some_and(|bytes| bytes != admitted.arguments)
        || admitted.params.idempotency_key.as_deref() != Some(intent.idempotency_key.as_str())
        || admitted.params.host != intent.host_scope.as_str()
    {
        bail!("native tool admission does not match the original full compiled payload");
    }
    Ok(())
}

// Match the pinned runtime's canonical complete SHA256 request binding. This
// is an extra response check; runtime::observe_request independently verifies
// the same digest inside the existing durable jobs registry.
#[derive(Serialize)]
struct RequestBinding<'a> {
    args: &'a [String],
    cpu_quota_percent: Option<u16>,
    cwd: Option<&'a str>,
    env: &'a BTreeMap<String, String>,
    executable: &'a str,
    host: &'a str,
    memory_max_bytes: Option<u64>,
    nice: Option<u8>,
    stdin: Option<&'a str>,
    timeout_seconds: Option<u64>,
}

fn runtime_request_digest(params: &ProcessStartParams) -> Result<String> {
    Ok(Digest32::of_bytes(&serde_json::to_vec(&RequestBinding {
        args: &params.args,
        cpu_quota_percent: params.cpu_quota_percent,
        cwd: params.cwd.as_deref(),
        env: &params.env,
        executable: &params.executable,
        host: &params.host,
        memory_max_bytes: params.memory_max_bytes,
        nice: params.nice,
        stdin: params.stdin.as_deref(),
        timeout_seconds: params.timeout_seconds,
    })?)
    .to_string())
}

pub(super) fn validate_job(
    envelope: &Value,
    admitted: &AdmittedTool,
    host: &HostConfig,
) -> Result<String> {
    let job = envelope
        .get("job")
        .context("runtime original job record missing")?;
    let id = job["id"]
        .as_str()
        .context("runtime original job ID missing")?;
    let expected_directory = format!("{}/jobs/{id}", host.remote_state_dir.trim_end_matches('/'));
    let params = &admitted.params;
    if !hepta_runtime::mcp::runtime::config::valid_name(id)
        || job["host"] != params.host
        || job["idempotency_key"] != params.idempotency_key.as_deref().unwrap_or("")
        || job["request_digest"] != runtime_request_digest(params)?
        || job["ssh_target"] != host.ssh_target
        || job["remote_job_dir"] != expected_directory
        || job["execution_mode"] != serde_json::to_value(host.execution_mode)?
        || job["executable"] != params.executable
        || job["args"] != serde_json::to_value(&params.args)?
        || job["cwd"] != serde_json::to_value(&params.cwd)?
        || job["env_keys"] != serde_json::to_value(params.env.keys().collect::<Vec<_>>())?
    {
        bail!("runtime record is not bound to the original host and full request");
    }
    Ok(id.to_owned())
}

pub(super) fn validate_observation_envelope(envelope: &Value) -> Result<()> {
    if envelope["observation_only"] != true
        || envelope["reused"] != true
        || envelope["retried_launch"] != false
        || envelope.get("launch") != Some(&Value::Null)
    {
        bail!("runtime request observation did not preserve its no-launch contract");
    }
    Ok(())
}

pub(super) fn require_job_id(value: &Value, job_id: &str) -> Result<()> {
    if value["job_id"].as_str() != Some(job_id) {
        bail!("runtime observation does not identify the original job");
    }
    Ok(())
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct TerminalProof {
    pub(super) state: String,
    pub(super) exit_code: i32,
    launch_nonce: String,
    at_unix_ms: u64,
    pub(super) stdout_bytes: u64,
    pub(super) stderr_bytes: u64,
}

pub(super) fn terminal_proof(status: &Value, job_id: &str) -> Result<Option<TerminalProof>> {
    require_job_id(status, job_id)?;
    let state = status["state"]
        .as_str()
        .context("runtime status state missing")?;
    if !matches!(state, "succeeded" | "failed" | "cancelled" | "timed_out")
        || status["status_authoritative"] == false
        || status["effect_outcome"] == "unknown"
        || status["outcome"] == "unknown"
    {
        return Ok(None);
    }
    if status["terminal_publication_protocol"] != 1
        || status["terminal_publication_confirmed"] != true
        || status["output_complete"] != true
        || status["output_durable"] != true
    {
        bail!("runtime terminal output has no complete durable publication witness");
    }
    let nonce = status["launch_nonce"]
        .as_str()
        .context("runtime launch nonce missing")?;
    if nonce.len() != 32 || !nonce.bytes().all(|b| b.is_ascii_hexdigit()) {
        bail!("runtime terminal launch nonce invalid");
    }
    let exit_code = i32::try_from(
        status["exit_code"]
            .as_i64()
            .context("terminal exit code missing")?,
    )?;
    let timed_out = status["timed_out"]
        .as_bool()
        .context("terminal timeout flag missing")?;
    let cancelled = status["cancelled"]
        .as_bool()
        .context("terminal cancellation flag missing")?;
    let expected_state = if timed_out {
        "timed_out"
    } else if cancelled {
        "cancelled"
    } else if exit_code == 0 {
        "succeeded"
    } else {
        "failed"
    };
    if state != expected_state {
        bail!("runtime terminal state and original exit outcome disagree");
    }
    let stream_bytes = |name: &str| -> Result<u64> {
        let bytes = status["log_bytes"][name]["stored"]
            .as_u64()
            .context("terminal stored-byte count missing")?;
        if status["log_bytes"][name]["seen"].as_u64() != Some(bytes)
            || status["log_truncated"][name] != false
            || status["log_errors"].get(name) != Some(&Value::Null)
            || status["log_synced"][name] != true
        {
            bail!("runtime terminal stream is incomplete, truncated or not durable");
        }
        Ok(bytes)
    };
    Ok(Some(TerminalProof {
        state: state.to_owned(),
        exit_code,
        launch_nonce: nonce.to_owned(),
        at_unix_ms: status["at_unix_ms"]
            .as_u64()
            .context("terminal publication time missing")?,
        stdout_bytes: stream_bytes("stdout")?,
        stderr_bytes: stream_bytes("stderr")?,
    }))
}

pub(super) struct ReadPage {
    pub(super) bytes: Vec<u8>,
    pub(super) next_offset: u64,
    pub(super) eof: bool,
}

pub(super) fn decode_page(
    value: &Value,
    offset: u64,
    expected_size: u64,
    limit: u64,
) -> Result<ReadPage> {
    let next_offset = value["next_offset"]
        .as_u64()
        .context("runtime output cursor missing")?;
    let eof = value["eof"]
        .as_bool()
        .context("runtime output EOF flag missing")?;
    let count = next_offset
        .checked_sub(offset)
        .context("runtime output cursor moved backward")?;
    let encoded = value["bytes_hex"]
        .as_str()
        .context("runtime lossless output bytes missing")?;
    if value["offset"].as_u64() != Some(offset)
        || value["size"].as_u64() != Some(expected_size)
        || next_offset > expected_size
        || count > limit
        || encoded.len() as u128 != u128::from(count) * 2
        || eof != (next_offset == expected_size)
        || (!eof && count == 0)
    {
        bail!("runtime output page does not preserve its original byte cursor and length");
    }
    let digit = |b: u8| -> Result<u8> {
        match b {
            b'0'..=b'9' => Ok(b - b'0'),
            b'a'..=b'f' => Ok(b - b'a' + 10),
            b'A'..=b'F' => Ok(b - b'A' + 10),
            _ => bail!("runtime lossless output contains invalid hex"),
        }
    };
    let bytes = encoded
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| Ok((digit(pair[0])? << 4) | digit(pair[1])?))
        .collect::<Result<Vec<_>>>()?;
    Ok(ReadPage {
        bytes,
        next_offset,
        eof,
    })
}

#[cfg(test)]
#[path = "runtime_bridge_tests.rs"]
mod tests;
