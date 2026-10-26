//! Fixed harmless request deliberately requiring more than the tiny test cap.

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
        .map_err(|_| anyhow!("cap-witness empty-tools encoding failed"))?;
    Ok(ResponsesApiRequest {
        model: model.into(),
        instructions: "Perform this harmless fixed text-generation qualification. Follow the user's full requested enumeration. Do not call tools, abbreviate, summarize, or use ellipses.".into(),
        input: vec![serde_json::from_value(json!({"type":"message", "role":"user", "content":[{
            "type":"input_text", "text":"List every integer from 1 through 256 inclusive, in increasing order, with exactly one integer on each line. Include all 256 lines and no other text.",
        }]}))?],
        tools: Some(tools.into()), tool_choice: "auto".into(), parallel_tool_calls: false,
        reasoning: Some(settings.reasoning), store: false, stream: true, stream_options: None,
        include: vec!["reasoning.encrypted_content".into()], service_tier: settings.service_tier,
        prompt_cache_key: Some(run_id.to_string()),
        text: settings.verbosity.map(|verbosity| TextControls { verbosity: Some(verbosity.into()), format: None }),
        client_metadata: None,
    })
}

#[cfg(test)]
#[path = "budget_request_tests.rs"]
mod tests;
