use super::*;
use codex_api::Reasoning;
use codex_api::RequestedOutputLimit;
use codex_api::encode_request_with_requested_output_limit;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::config_types::Verbosity;
use codex_protocol::openai_models::ReasoningEffort;
use pretty_assertions::assert_eq;

#[test]
fn cap_witness_preserves_original_settings_and_binds_the_explicit_cap() -> Result<()> {
    let settings = ResponsesModelSettings {
        reasoning: Reasoning {
            effort: Some(ReasoningEffort::Max),
            summary: Some(ReasoningSummary::Auto),
            context: None,
        },
        verbosity: Some(Verbosity::High),
        service_tier: Some("priority".into()),
    };
    let request = prepare(
        "fixture-model",
        &StableId::new("fixture-cap-witness")?,
        settings,
    )?;
    let body =
        encode_request_with_requested_output_limit(&request, None, RequestedOutputLimit::new(32)?)?;
    let value: serde_json::Value = serde_json::from_slice(body.as_bytes())?;
    assert_eq!(value["model"], "fixture-model");
    assert_eq!(value["max_output_tokens"], 32);
    assert_eq!(value["reasoning"]["effort"], "max");
    assert_eq!(value["reasoning"]["summary"], "auto");
    assert_eq!(value["service_tier"], "priority");
    assert_eq!(value["text"]["verbosity"], "high");
    assert_eq!(value["tools"], json!([]));
    assert_eq!(value["tool_choice"], "auto");
    assert_eq!(value["parallel_tool_calls"], false);
    assert_eq!(value["store"], false);
    assert_eq!(
        value["input"][0]["content"][0]["text"],
        "List every integer from 1 through 256 inclusive, in increasing order, with exactly one integer on each line. Include all 256 lines and no other text."
    );
    Ok(())
}
