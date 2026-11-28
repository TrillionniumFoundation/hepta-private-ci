use super::truncate;
use serde_json::Value as JsonValue;
use time::Date;
use time::Month;

const NOTE_MAX_LEN: usize = 2_000;
const TOOL_RESULT_MAX_LEN: usize = 4_000;
const EXTERNAL_AGENT_TOOL_CALL_TAG: &str = "external_agent_tool_call";
const EXTERNAL_AGENT_TOOL_RESULT_TAG: &str = "external_agent_tool_result";

pub(super) struct ExtractedMessage {
    pub text: String,
    pub only_tool_result: bool,
}

pub(super) fn extract_message_text(content: &JsonValue) -> Option<ExtractedMessage> {
    let blocks = content_blocks(content);
    let mut parts = Vec::new();
    let mut only_tool_result = !blocks.is_empty();

    for block in &blocks {
        let block_type = block.get("type").and_then(JsonValue::as_str);
        match block_type {
            Some("text") => {
                if let Some(text) = block.get("text").and_then(JsonValue::as_str)
                    && !text.is_empty()
                {
                    parts.push(text.to_string());
                    only_tool_result = false;
                }
            }
            Some("tool_use") => {
                parts.push(tool_call_note(block));
                only_tool_result = false;
            }
            Some("tool_result") => {
                parts.push(tool_result_note(block));
            }
            Some("thinking") => {}
            Some(other) => {
                parts.push(format!("[external unsupported block: {other}]"));
                only_tool_result = false;
            }
            None => {}
        }
    }

    let text = parts
        .into_iter()
        .filter(|part| !part.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n\n");
    if text.is_empty() {
        None
    } else {
        Some(ExtractedMessage {
            text,
            only_tool_result,
        })
    }
}

fn decimal(bytes: &[u8]) -> Option<u32> {
    bytes.iter().try_fold(0, |n, &b| {
        b.is_ascii_digit().then(|| n * 10 + u32::from(b - b'0'))
    })
}

// The migration consumer retains only integral Unix seconds. Preserve the
// accepted legacy grammar, including fractional input and leap-second folding.
pub(super) fn parse_timestamp(input: &str) -> Option<i64> {
    let b = input.as_bytes();
    let fixed = b.get(..19)?;
    if fixed[4] != b'-'
        || fixed[7] != b'-'
        || !matches!(fixed[10], b'T' | b't' | b' ')
        || fixed[13] != b':'
        || fixed[16] != b':'
    {
        return None;
    }
    let year = i32::try_from(decimal(&fixed[..4])?).ok()?;
    let month = Month::try_from(u8::try_from(decimal(&fixed[5..7])?).ok()?).ok()?;
    let day = u8::try_from(decimal(&fixed[8..10])?).ok()?;
    let hour = u8::try_from(decimal(&fixed[11..13])?).ok()?;
    let minute = u8::try_from(decimal(&fixed[14..16])?).ok()?;
    let second = u8::try_from(decimal(&fixed[17..19])?).ok()?;
    if second > 60 {
        return None;
    }
    let mut zone = &b[19..];
    if let Some(tail) = zone.strip_prefix(b".") {
        let digits = tail.iter().take_while(|b| b.is_ascii_digit()).count();
        if digits == 0 {
            return None;
        }
        zone = &tail[digits..];
    }
    let offset = if matches!(zone, b"Z" | b"z") {
        0
    } else {
        let (sign, tail) = if let Some(t) = zone.strip_prefix(b"+") {
            (1_i64, t)
        } else if let Some(t) = zone.strip_prefix(b"-") {
            (-1_i64, t)
        } else {
            (-1_i64, zone.strip_prefix("−".as_bytes())?)
        };
        if tail.len() != 5 || tail[2] != b':' {
            return None;
        }
        let h = decimal(&tail[..2])?;
        let m = decimal(&tail[3..])?;
        if h > 23 || m > 59 {
            return None;
        }
        sign * (i64::from(h) * 3600 + i64::from(m) * 60)
    };
    let date = Date::from_calendar_date(year, month, day).ok()?;
    let local = date.with_hms(hour, minute, second.min(59)).ok()?;
    Some(local.assume_utc().unix_timestamp() - offset)
}

fn content_blocks(content: &JsonValue) -> Vec<JsonValue> {
    if let Some(text) = content.as_str() {
        return vec![serde_json::json!({
            "type": "text",
            "text": text,
        })];
    }
    content
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter(|item| item.is_object())
                .cloned()
                .collect()
        })
        .unwrap_or_default()
}

fn tool_call_note(block: &JsonValue) -> String {
    let name = block
        .get("name")
        .and_then(JsonValue::as_str)
        .unwrap_or("unknown");
    let mut lines = vec![format!("[{EXTERNAL_AGENT_TOOL_CALL_TAG}: {name}]")];
    if let Some(input) = block.get("input").and_then(JsonValue::as_object) {
        if let Some(description) = input.get("description").and_then(JsonValue::as_str) {
            lines.push(format!("description: {description}"));
        }
        if let Some(command) = input.get("command").and_then(JsonValue::as_str) {
            lines.push(format!("command: {command}"));
        }
        if let Some(file) = input
            .get("file_path")
            .or_else(|| input.get("file"))
            .and_then(JsonValue::as_str)
        {
            lines.push(format!("file: {file}"));
        }
        if lines.len() == 1 {
            lines.push(format!(
                "input: {}",
                truncate(&JsonValue::Object(input.clone()).to_string(), NOTE_MAX_LEN)
            ));
        }
    } else if let Some(input) = block.get("input") {
        lines.push(format!(
            "input: {}",
            truncate(&input.to_string(), NOTE_MAX_LEN)
        ));
    }
    lines.push(format!("[/{EXTERNAL_AGENT_TOOL_CALL_TAG}]"));
    lines.join("\n")
}

fn tool_result_note(block: &JsonValue) -> String {
    let label = if block.get("is_error").and_then(JsonValue::as_bool) == Some(true) {
        format!("[{EXTERNAL_AGENT_TOOL_RESULT_TAG}: error]")
    } else {
        format!("[{EXTERNAL_AGENT_TOOL_RESULT_TAG}]")
    };
    let text = tool_result_text(block.get("content"));
    if text.is_empty() {
        format!("{label}\n[/{EXTERNAL_AGENT_TOOL_RESULT_TAG}]")
    } else {
        format!(
            "{label}\n{}\n[/{EXTERNAL_AGENT_TOOL_RESULT_TAG}]",
            truncate(&text, TOOL_RESULT_MAX_LEN)
        )
    }
}

fn tool_result_text(content: Option<&JsonValue>) -> String {
    match content {
        Some(JsonValue::String(text)) => text.clone(),
        Some(JsonValue::Array(items)) => items
            .iter()
            .filter_map(|item| item.get("text").and_then(JsonValue::as_str))
            .filter(|text| !text.is_empty())
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    }
}

#[cfg(test)]
#[path = "records_common_tests.rs"]
mod tests;
