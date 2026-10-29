//! Bounded text from actual App Server terminal items or reconciled history.

use codex_app_server_protocol::ThreadItem;

use super::MAX_OUTPUT_BYTES;

pub(super) fn collect_agent_output(items: &[ThreadItem]) -> Result<Option<String>, String> {
    let mut output = None;
    for item in items {
        if let ThreadItem::AgentMessage { text, .. } = item {
            let accumulated = output.get_or_insert_with(String::new);
            if text.len() > MAX_OUTPUT_BYTES.saturating_sub(accumulated.len()) {
                return Err("output byte limit exceeded".to_string());
            }
            accumulated.push_str(text);
        }
    }
    Ok(output)
}
