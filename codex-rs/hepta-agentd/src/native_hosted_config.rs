//! Frozen execution configuration in the original Core provenance only.

use anyhow::Result;
use codex_hepta_native_agent::NativeAgent;
use codex_hepta_types::Digest32;
use serde_json::json;

pub(super) fn digest(agent: &NativeAgent) -> Result<String> {
    let limits = &agent.limits;
    let duration = |value: std::time::Duration| (value.as_secs(), value.subsec_nanos());
    Ok(Digest32::of_bytes(&serde_json::to_vec(&json!({
        "schema": "hepta.native.execution-config.v1",
        "context_policy": agent.context_policy()?.binding_value(),
        "model": agent.model_name,
        "instructions": agent.instructions,
        "tools": agent.tools,
        "store_responses": agent.store_responses,
        "limits": {
            "context_bytes": limits.context_bytes,
            "output_tokens": limits.output_tokens,
            "model_calls": limits.model_calls,
            "tool_calls": limits.tool_calls,
            "tool_output_bytes": limits.tool_output_bytes,
            "model_timeout_secs_nanos": duration(limits.model_timeout),
            "tool_timeout_secs_nanos": duration(limits.tool_timeout),
            "observation_interval_secs_nanos": duration(limits.observation_interval),
        },
    }))?)
    .to_string())
}
