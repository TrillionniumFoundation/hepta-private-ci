//! Installed only in a separately pinned upstream qualification checkout.

use codex_exec_server_protocol::ExecParams;
use codex_exec_server_protocol::WireExecParams;

fn decode_params(value: serde_json::Value) -> Result<ExecParams, serde_json::Error> {
    serde_json::from_value::<WireExecParams>(value).map(ExecParams::from)
}

#[path = "../../../qualification/codex-exec-p2e/native_probe.rs"]
mod native_probe;
