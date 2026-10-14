//! Read-only, non-authorizing Codex Exec Server process/start preflight.
//!
//! Frozen upstream: openai/codex rust-v0.162.1, whose Exec Server RPC
//! dialect omits a "jsonrpc":"2.0" field. The process/start method is
//! separate from process/write, fs/remove and http/request.
//!
//! These checks define a deliberately tiny experimental profile. They are
//! NOT a complete upstream protocol implementation, sandbox, authorization,
//! provider identity attestation, or physical-effect adapter.

use std::collections::BTreeMap;
use std::fmt;

use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;

use crate::Sha256Digest;
use crate::execution_contract_v1::ExecutionIntentV1;
use crate::execution_contract_v1::ExecutionTargetV1;

pub const CODEX_EXEC_SERVER_P2C_UPSTREAM_TAG: &str = "rust-v0.162.1";
pub const CODEX_EXEC_SERVER_P2C_START_METHOD: &str = "process/start";
pub const CODEX_EXEC_SERVER_P2C_DESTINATION: &str = "codex:exec-server";
pub const CODEX_EXEC_SERVER_P2C_MAX_WIRE_BYTES: usize = 16 * 1024;
pub const CODEX_EXEC_SERVER_P2C_MAX_ARGV_ENTRIES: usize = 32;
pub const CODEX_EXEC_SERVER_P2C_MAX_TOTAL_ARGV_BYTES: usize = 8 * 1024;
pub const CODEX_EXEC_SERVER_P2C_EFFECT_AUTHORITY: bool = false;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RequestWire {
    id: String,
    method: String,
    params: ProcessStartParams,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
struct ProcessStartParams {
    process_id: String,
    argv: Vec<String>,
    cwd: String,
    env: BTreeMap<String, String>,
    tty: bool,
    pipe_stdin: bool,
    arg0: Option<String>,
}

/// Digest-only description of an inspected wire payload.
/// It cannot authorize, send, replay or complete an effect.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexExecServerStartInspectionV1 {
    pub operation_id: String,
    pub request_sha256: [u8; 32],
    pub original_wire_sha256: Sha256Digest,
    pub argv_sha256: [u8; 32],
    pub argv_count: u16,
    pub method: &'static str,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CodexExecServerStartPreflightErrorV1 {
    NotExecServerProcess,
    WrongDestination,
    InvalidIntentOrPhysicalBytes,
    OversizedWire,
    MalformedOrUnknownRpc,
    ForbiddenRpcMethod,
    WrongOperationIdentity,
    InvalidProcessProfile,
}

impl fmt::Display for CodexExecServerStartPreflightErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for CodexExecServerStartPreflightErrorV1 {}

/// Inspect an already frozen exact physical Exec Server request.
/// The result is diagnostic only, not a token or an alternative to signed
/// independent Final-use. The original owner must still validate the live
/// sandbox, principal, time, nonce, revocation, exact wire at entry, durable
/// dispatch identity and original provider status. None are implemented here.
pub fn inspect_codex_exec_server_start_v1(
    intent: &ExecutionIntentV1,
    wire: &[u8],
) -> Result<CodexExecServerStartInspectionV1, CodexExecServerStartPreflightErrorV1> {
    if intent.target != ExecutionTargetV1::CodexExecServerProcess {
        return Err(CodexExecServerStartPreflightErrorV1::NotExecServerProcess);
    }
    if intent.destination_id != CODEX_EXEC_SERVER_P2C_DESTINATION {
        return Err(CodexExecServerStartPreflightErrorV1::WrongDestination);
    }
    if wire.len() > CODEX_EXEC_SERVER_P2C_MAX_WIRE_BYTES {
        return Err(CodexExecServerStartPreflightErrorV1::OversizedWire);
    }
    intent
        .verify_payload(wire)
        .map_err(|_| CodexExecServerStartPreflightErrorV1::InvalidIntentOrPhysicalBytes)?;

    // Parse closed Rust structures, not an untyped generic Value.
    // serde rejects duplicate, unknown and absent critical fields.
    // A future upstream extension requires a new admitted profile.
    let request: RequestWire = serde_json::from_slice(wire)
        .map_err(|_| CodexExecServerStartPreflightErrorV1::MalformedOrUnknownRpc)?;
    if request.method != CODEX_EXEC_SERVER_P2C_START_METHOD {
        return Err(CodexExecServerStartPreflightErrorV1::ForbiddenRpcMethod);
    }
    if request.id != intent.operation_id || request.params.process_id != intent.operation_id {
        return Err(CodexExecServerStartPreflightErrorV1::WrongOperationIdentity);
    }

    let params = request.params;
    let mut total_argv_bytes = 0_usize;
    if params.argv.is_empty()
        || params.argv.len() > CODEX_EXEC_SERVER_P2C_MAX_ARGV_ENTRIES
        || !params.env.is_empty()
        || params.tty
        || params.pipe_stdin
        || params.arg0.is_some()
        || !canonical_pilot_cwd(&params.cwd)
    {
        return Err(CodexExecServerStartPreflightErrorV1::InvalidProcessProfile);
    }

    let mut argv_hasher = Sha256::new();
    argv_hasher.update(b"hepta.exec-server.p2c.argv.v1\0");
    for argument in &params.argv {
        if argument.is_empty() || argument.len() > 4096 || argument.chars().any(char::is_control) {
            return Err(CodexExecServerStartPreflightErrorV1::InvalidProcessProfile);
        }
        total_argv_bytes = total_argv_bytes
            .checked_add(argument.len())
            .ok_or(CodexExecServerStartPreflightErrorV1::InvalidProcessProfile)?;
        if total_argv_bytes > CODEX_EXEC_SERVER_P2C_MAX_TOTAL_ARGV_BYTES {
            return Err(CodexExecServerStartPreflightErrorV1::InvalidProcessProfile);
        }
        argv_hasher.update((argument.len() as u64).to_be_bytes());
        argv_hasher.update(argument.as_bytes());
    }

    let proposed = intent
        .binding_proposal()
        .map_err(|_| CodexExecServerStartPreflightErrorV1::InvalidIntentOrPhysicalBytes)?;
    Ok(CodexExecServerStartInspectionV1 {
        operation_id: intent.operation_id.clone(),
        request_sha256: proposed.request_sha256,
        original_wire_sha256: intent.payload_sha256.clone(),
        argv_sha256: argv_hasher.finalize().into(),
        argv_count: u16::try_from(params.argv.len())
            .map_err(|_| CodexExecServerStartPreflightErrorV1::InvalidProcessProfile)?,
        method: CODEX_EXEC_SERVER_P2C_START_METHOD,
    })
}

// A conservative Linux-like lexical subset. This prevents obvious path
// ambiguity at the wire boundary, but does NOT verify filesystem identity,
// symlinks, mount policy or sandbox custody. Only the original owner can do so.
fn canonical_pilot_cwd(cwd: &str) -> bool {
    if cwd.len() > 2048 {
        return false;
    }
    let Some(path) = cwd.strip_prefix("file:///") else {
        return false;
    };
    !path.is_empty()
        && path.split('/').all(|part| {
            !part.is_empty()
                && part != "."
                && part != ".."
                && part
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
        })
}

#[cfg(test)]
#[path = "exec_server_start_p2c_tests.rs"]
mod tests;
