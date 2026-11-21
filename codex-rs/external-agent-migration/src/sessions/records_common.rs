use super::truncate;
use serde_json::Value as JsonValue;

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

pub(super) fn parse_timestamp(timestamp: &str) -> Option<i64> {
    // Match the original strict Chrono RFC3339 entry, including lower-case
    // separators, arbitrary fractional precision and leap-second flooring.
    // Only whole UNIX seconds are exposed by this importer.
    let bytes = timestamp.as_bytes();
    if bytes.len() < 20
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || !matches!(bytes[10], b'T' | b't' | b' ')
        || bytes[13] != b':'
        || bytes[16] != b':'
    {
        return None;
    }

    let year = rfc3339_digits(&bytes[..4])?;
    let month = rfc3339_digits(&bytes[5..7])?;
    let day = rfc3339_digits(&bytes[8..10])?;
    let hour = rfc3339_digits(&bytes[11..13])?;
    let minute = rfc3339_digits(&bytes[14..16])?;
    let second = rfc3339_digits(&bytes[17..19])?;
    let leap_year = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days_in_month = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap_year => 29,
        2 => 28,
        _ => return None,
    };
    if !(1..=days_in_month).contains(&day) || hour > 23 || minute > 59 || second > 60 {
        return None;
    }

    let mut index = 19;
    if bytes.get(index) == Some(&b'.') {
        index += 1;
        let first_digit = index;
        while bytes.get(index).is_some_and(u8::is_ascii_digit) {
            index += 1;
        }
        if index == first_digit {
            return None;
        }
    }

    let suffix = &bytes[index..];
    let offset_minutes = if suffix == b"Z" || suffix == b"z" {
        0
    } else if suffix.len() == 6 && matches!(suffix[0], b'+' | b'-') && suffix[3] == b':' {
        let offset_hours = rfc3339_digits(&suffix[1..3])?;
        let offset_mins = rfc3339_digits(&suffix[4..6])?;
        if offset_hours > 23 || offset_mins > 59 {
            return None;
        }
        let total = offset_hours * 60 + offset_mins;
        if suffix[0] == b'+' { total } else { -total }
    } else {
        return None;
    };

    // Proleptic Gregorian days since 1970-01-01. All RFC3339 four-digit
    // years and their allowed UTC offsets fit comfortably inside i64.
    let adjusted_year = year - i64::from(month <= 2);
    let era = adjusted_year.div_euclid(400);
    let year_of_era = adjusted_year - era * 400;
    let adjusted_month = month + if month > 2 { -3 } else { 9 };
    let day_of_year = (153 * adjusted_month + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    let days_since_epoch = era * 146_097 + day_of_era - 719_468;
    Some(
        days_since_epoch * 86_400 + hour * 3_600 + minute * 60 + second.min(59)
            - offset_minutes * 60,
    )
}

fn rfc3339_digits(bytes: &[u8]) -> Option<i64> {
    let mut number = 0_i64;
    for &digit in bytes {
        if !digit.is_ascii_digit() {
            return None;
        }
        number = number * 10 + i64::from(digit - b'0');
    }
    Some(number)
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
