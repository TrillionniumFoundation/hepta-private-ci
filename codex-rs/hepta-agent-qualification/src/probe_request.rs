//! Ordinary fixed-marker body prepared before any provider admission.
//!
//! Share Core's empty-tools serialization and automatic tool selection. There
//! are no offered tools; the collector still rejects any unexpected tool call.
//! This narrow shape parity does not establish Core header or session parity.

use super::EXPECTED;
use anyhow::Result;
use anyhow::anyhow;
use codex_api::ResponsesApiRequest;
use codex_api::TextControls;
use codex_hepta_types::StableId;
use codex_model_provider::ResponsesModelSettings;
use codex_tools::create_tools_raw_json_for_responses_api;
use serde_json::json;

pub(super) fn prepare(
    model: &str,
    run_id: &StableId,
    settings: ResponsesModelSettings,
) -> Result<ResponsesApiRequest> {
    let tools = create_tools_raw_json_for_responses_api(&[])
        .map_err(|_| anyhow!("qualification empty-tools encoding failed"))?;
    Ok(ResponsesApiRequest {
        model: model.to_string(),
        instructions: "Run this harmless connectivity qualification. Return exactly the requested marker, without explanations or tool calls.".into(),
        input: vec![serde_json::from_value(json!({
            "type":"message", "role":"user",
            "content":[{"type":"input_text", "text":format!("Return only {EXPECTED}")}],
        }))?],
        tools: Some(tools.into()), tool_choice: "auto".into(), parallel_tool_calls: false,
        reasoning: Some(settings.reasoning),
        store: false, stream: true, stream_options: None,
        include: vec!["reasoning.encrypted_content".into()],
        service_tier: settings.service_tier, prompt_cache_key: Some(run_id.to_string()),
        text: settings.verbosity.map(|verbosity| TextControls { verbosity: Some(verbosity.into()), format: None }),
        client_metadata: None,
    })
}

#[cfg(test)]
#[path = "probe_request_tests.rs"]
mod tests;
