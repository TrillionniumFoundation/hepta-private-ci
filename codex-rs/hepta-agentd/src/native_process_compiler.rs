//! Host-configured compilation of process proposals into the original runtime.
//!
//! This compiler supplies no execution authority. The existing production
//! writer, final-use gate and configured runtime policy still decide whether
//! these exact parameters may enter a process.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::Component;
use std::path::Path;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_native_agent::ToolCall;
use hepta_runtime::mcp::runtime::jobs::ProcessStartParams;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use crate::NativeToolCompiler;

const TOOL_NAME: &str = "process_start";
const MAX_PROPOSAL_BYTES: usize = 48 * 1024;
const MAX_ARGUMENT_BYTES: usize = 32 * 1024;
const MAX_STDIN_BYTES: usize = 16 * 1024;
// The original writer's payload ceiling also includes the operation key that
// NativeProductionAdmission inserts after compilation. Leave room for that key.
const MAX_COMPILED_BYTES: usize = 64 * 1024 - 256;

/// Immutable choices from the existing trusted product host. The model cannot
/// select a host, working directory, environment or resource policy. Allowing
/// an interpreter here does not constrain that interpreter's program semantics;
/// the runtime's configured execution policy remains the final host boundary.
#[derive(Clone, Debug)]
pub struct NativeProcessPolicy {
    pub host: String,
    pub cwd: String,
    pub executables: BTreeSet<String>,
    pub env: BTreeMap<String, String>,
    pub timeout_seconds: u64,
    pub nice: Option<u8>,
    pub cpu_quota_percent: Option<u16>,
    pub memory_max_bytes: Option<u64>,
}

/// A concrete product compiler for the process capability already supported by
/// the native runtime adapter. It does not advertise PTY, MCP or shell parsing.
pub struct NativeProcessToolCompiler {
    policy: NativeProcessPolicy,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProcessProposal {
    executable: String,
    args: Vec<String>,
    stdin: Option<String>,
}

impl NativeProcessToolCompiler {
    pub fn new(policy: NativeProcessPolicy) -> Result<Self> {
        ensure!(
            !policy.host.is_empty()
                && policy.host.len() <= 128
                && policy.host.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte)),
            "native process host must be an existing configured host name"
        );
        ensure!(
            absolute_owner_path(&policy.cwd)
                && !policy.executables.is_empty()
                && policy.executables.len() <= 64
                && policy.executables.iter().all(|path| absolute_owner_path(path)),
            "native process policy needs explicit absolute executable and working-directory paths"
        );
        ensure!(policy.timeout_seconds > 0 && policy.timeout_seconds <= 86_400, "native process timeout is outside the bounded host policy");
        ensure!(policy.nice.is_none_or(|nice| nice <= 19), "native process nice value is invalid");
        ensure!(policy.cpu_quota_percent.is_none_or(|quota| (1..=1000).contains(&quota)), "native process CPU quota is invalid");
        ensure!(policy.memory_max_bytes.is_none_or(|bytes| bytes > 0), "native process memory budget is invalid");
        ensure!(policy.env.iter().all(|(key, value)| !key.is_empty() && !key.contains(['=', '\0']) && !value.contains('\0')), "native process environment is invalid");
        Ok(Self { policy })
    }

    /// The advertised arguments contain only proposals. Every frozen owner
    /// field is inserted by `compile`, outside the model-controlled JSON.
    pub fn tool_definition(&self) -> Value {
        json!({
            "type": "function",
            "name": TOOL_NAME,
            "description": "Run a configured executable with explicit arguments in the assigned workspace.",
            "strict": true,
            "parameters": {
                "type": "object",
                "properties": {
                    "executable": {"type": "string", "enum": self.policy.executables},
                    "args": {"type": "array", "items": {"type": "string"}, "maxItems": 256},
                    "stdin": {"type": ["string", "null"]}
                },
                "required": ["executable", "args", "stdin"],
                "additionalProperties": false
            }
        })
    }
}

impl NativeToolCompiler for NativeProcessToolCompiler {
    fn compile(&self, call: &ToolCall) -> Result<ProcessStartParams> {
        ensure!(call.name == TOOL_NAME, "tool is not part of the native process capability");
        ensure!(call.arguments.len() <= MAX_PROPOSAL_BYTES, "native process proposal exceeds its byte budget");
        let proposal: ProcessProposal = serde_json::from_slice(&call.arguments)
            .context("native process arguments do not match the registered tool")?;
        ensure!(self.policy.executables.contains(&proposal.executable), "executable is outside the original host policy");
        ensure!(proposal.args.len() <= 256 && proposal.args.iter().all(|argument| !argument.contains('\0')), "native process arguments are invalid");
        let argument_bytes = proposal.args.iter().try_fold(0usize, |total, argument| total.checked_add(argument.len()))
            .context("native process argument length overflow")?;
        ensure!(argument_bytes <= MAX_ARGUMENT_BYTES, "native process arguments exceed their byte budget");
        ensure!(proposal.stdin.as_ref().is_none_or(|input| input.len() <= MAX_STDIN_BYTES), "native process input exceeds its byte budget");
        let params = ProcessStartParams {
            host: self.policy.host.clone(),
            executable: proposal.executable,
            args: proposal.args,
            cwd: Some(self.policy.cwd.clone()),
            env: self.policy.env.clone(),
            stdin: proposal.stdin,
            timeout_seconds: Some(self.policy.timeout_seconds),
            // Only the original admitted run assigns the durable operation key.
            idempotency_key: None,
            nice: self.policy.nice,
            cpu_quota_percent: self.policy.cpu_quota_percent,
            memory_max_bytes: self.policy.memory_max_bytes,
        };
        ensure!(serde_json::to_vec(&params)?.len() <= MAX_COMPILED_BYTES, "compiled process exceeds the original writer payload budget");
        Ok(params)
    }
}

fn absolute_owner_path(value: &str) -> bool {
    !value.contains('\0')
        && value.len() <= 4096
        && Path::new(value).is_absolute()
        && Path::new(value).components().all(|component| matches!(component, Component::RootDir | Component::Normal(_)))
}

#[cfg(test)]
#[path = "native_process_compiler_tests.rs"]
mod tests;
