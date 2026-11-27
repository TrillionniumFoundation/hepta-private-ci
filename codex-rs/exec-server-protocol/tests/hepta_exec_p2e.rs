//! Qualification-only tests of the repository's actual Codex protocol.

use codex_exec_server_protocol::ExecParams;

fn decode_params(value: serde_json::Value) -> Result<ExecParams, serde_json::Error> {
    serde_json::from_value(value)
}

#[path = "../../../qualification/codex-exec-p2e/native_probe.rs"]
mod native_probe;
