//! Exact encoded-body regression without installed authentication or transport.

use super::*;
use crate::request_wire::PreparedOrdinaryWire;
use codex_api::Reasoning;
use codex_hepta_types::Digest32;
use codex_http_client::EncodedJsonBody;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::config_types::Verbosity;
use codex_protocol::openai_models::ReasoningEffort;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use serde_json::Value;

#[test]
fn encoded_marker_preserves_owner_settings_and_binds_the_new_ordinary_shape() -> Result<()> {
    for (index, settings) in [
        ResponsesModelSettings {
            reasoning: Reasoning {
                effort: Some(ReasoningEffort::Max),
                summary: Some(ReasoningSummary::Auto),
                context: None,
            },
            verbosity: None,
            service_tier: None,
        },
        ResponsesModelSettings {
            reasoning: Reasoning {
                effort: Some(ReasoningEffort::Low),
                summary: None,
                context: None,
            },
            verbosity: Some(Verbosity::High),
            service_tier: Some("priority".into()),
        },
    ]
    .into_iter()
    .enumerate()
    {
        let model = format!("fixture-model-{index}");
        let run_id = StableId::new(format!("fixture-run:{index}"))?;
        let mut expected = json!({
            "model":model,
            "instructions":"Run this harmless connectivity qualification. Return exactly the requested marker, without explanations or tool calls.",
            "input":[{"type":"message", "role":"user", "content":[{
                "type":"input_text", "text":"Return only HEPTA_NATIVE_STREAM_OK",
            }]}],
            "tools":[], "tool_choice":"auto", "parallel_tool_calls":false,
            "reasoning":settings.reasoning, "store":false, "stream":true,
            "include":["reasoning.encrypted_content"], "prompt_cache_key":run_id.to_string(),
        });
        if let Some(tier) = &settings.service_tier {
            expected["service_tier"] = json!(tier);
        }
        if let Some(verbosity) = settings.verbosity {
            expected["text"] = json!({"verbosity":verbosity});
        }
        let mut request = prepare(&model, &run_id, settings)?;
        let encoded = EncodedJsonBody::encode(&request)?;
        assert_eq!(serde_json::from_slice::<Value>(encoded.as_bytes())?, expected);

        let body_digest = Digest32::of_bytes(encoded.as_bytes());
        let settings_digest = Digest32::of_bytes(format!("owner-settings:{index}").as_bytes());
        let wire = PreparedOrdinaryWire::new(body_digest, settings_digest)?;
        assert_eq!(wire.body_digest(), body_digest);
        // The pre-parity probe is an independent request identity. Its receipt
        // cannot be reused to admit this new body, even with identical settings.
        request.tools = None;
        request.tool_choice = "none".into();
        let old_body = EncodedJsonBody::encode(&request)?;
        let old_wire = PreparedOrdinaryWire::new(
            Digest32::of_bytes(old_body.as_bytes()),
            settings_digest,
        )?;
        assert_ne!(wire.semantic_digest(), old_wire.semantic_digest());
        assert!(!wire.dispatch_metadata().transport_invoked());
    }
    Ok(())
}
