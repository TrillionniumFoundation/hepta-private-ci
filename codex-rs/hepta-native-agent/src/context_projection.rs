//! Deterministic request-only excerpts. The owner retains every original item.

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_types::Digest32;
use serde_json::Value;

/// Hosts bind this version into their frozen model/context policy digest.
pub const CONTEXT_PROJECTION_VERSION: &str = "hepta-native-request-projection-v1";

fn excerpt(text: &str, item: &Value, index: usize) -> Result<String> {
    let bytes = serde_json::to_vec(item)?;
    let mut prefix = text.len().min(192);
    while !text.is_char_boundary(prefix) {
        prefix -= 1;
    }
    let mut suffix = text.len().saturating_sub(128).max(prefix);
    while !text.is_char_boundary(suffix) {
        suffix += 1;
    }
    Ok(format!(
        "[Historical request excerpt; owner context index={index}; item_sha256={}; original_item_bytes={}; projection={CONTEXT_PROJECTION_VERSION}. Omitted content remains in host history and is not evidence supplied in this request.]\n{}\n[... omitted ...]\n{}",
        Digest32::of_bytes(&bytes),
        bytes.len(),
        &text[..prefix],
        &text[suffix..],
    ))
}

/// Preserve all user/system/developer inputs, every function call and its
/// pairing, pending calls, and the newest full tool exchange. Older completed
/// output text may become a visibly marked excerpt; no item is removed.
pub(crate) fn project(context: &[Value], budget: usize) -> Result<Vec<Value>> {
    let mut projected = context.to_vec();
    let mut bytes = serde_json::to_vec(&projected)?.len();
    if bytes <= budget {
        return Ok(projected);
    }
    // The loop appends a complete model response before executing any of its
    // calls. Walk back across that whole response (including parallel calls,
    // reasoning and assistant messages), not just to its final call. The prior
    // tool output or host input ends the preceding exchange. Without a known
    // boundary, retain the full prefix rather than infer one from provider IDs.
    let protect_from = if let Some(last_call) = context
        .iter()
        .rposition(|item| item["type"] == "function_call")
    {
        context[..last_call]
            .iter()
            .rposition(|item| {
                item["type"] == "function_call_output"
                    || matches!(item["role"].as_str(), Some("user" | "system" | "developer"))
            })
            .map_or(0, |index| index + 1)
    } else {
        context
            .iter()
            .rposition(|item| item["role"] == "assistant")
            .unwrap_or(0)
    };
    for (index, original) in context.iter().enumerate().take(protect_from) {
        let mut replacement = original.clone();
        match original["type"].as_str() {
            Some("function_call_output") => {
                let call_id = original["call_id"]
                    .as_str()
                    .context("historical tool output has no call id")?;
                if !context[..index].iter().any(|item| {
                    item["type"] == "function_call" && item["call_id"].as_str() == Some(call_id)
                }) {
                    bail!("historical tool output has no preceding paired call");
                }
                let text = original["output"]
                    .as_str()
                    .context("historical tool output is not text")?;
                replacement["output"] = Value::String(excerpt(text, original, index)?);
            }
            Some("message") if original["role"] == "assistant" => {
                let parts = replacement["content"]
                    .as_array_mut()
                    .context("historical message content missing")?;
                for part in parts {
                    if part["type"] == "output_text" {
                        let text = part["text"]
                            .as_str()
                            .context("historical message text missing")?;
                        part["text"] = Value::String(excerpt(text, original, index)?);
                        // Original annotation offsets cannot describe an excerpt.
                        if part.get("annotations").is_some() {
                            part["annotations"] = serde_json::json!([]);
                        }
                    }
                }
            }
            _ => continue,
        }
        let before = serde_json::to_vec(original)?.len();
        let after = serde_json::to_vec(&replacement)?.len();
        if after >= before {
            continue;
        }
        bytes = bytes
            .checked_sub(before - after)
            .context("context projection size underflow")?;
        projected[index] = replacement;
        if bytes <= budget {
            return Ok(projected);
        }
    }
    bail!("retained native context exceeds context byte budget")
}
