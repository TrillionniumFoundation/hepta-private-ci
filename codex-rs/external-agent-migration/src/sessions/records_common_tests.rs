use super::*;
use pretty_assertions::assert_eq;

#[test]
fn timestamp_import_preserves_offsets_separators_and_negative_epoch_floor() {
    for (timestamp, expected) in [
        ("1970-01-01T00:00:00Z", 0),
        ("1970-01-01t00:00:00z", 0),
        ("1970-01-01 01:30:00+01:30", 0),
        ("1970-01-01T00:00:00-00:00", 0),
        ("1970-01-01T00:00:00−00:01", 60),
        ("1970-01-01T00:00:00+23:59", -86_340),
        ("1970-01-01T00:00:00-23:59", 86_340),
        ("1970-01-01T00:00:00.123456789123Z", 0),
        ("1969-12-31T23:59:59.999999999999Z", -1),
        ("2000-02-29T00:00:00Z", 951_782_400),
    ] {
        assert_eq!(parse_timestamp(timestamp), Some(expected), "{timestamp}");
    }
}

#[test]
fn timestamp_import_preserves_leap_second_integer_values() {
    for (timestamp, expected) in [
        ("1970-01-01T00:00:60Z", 59),
        ("1970-01-01T01:00:60.125+01:00", 59),
        ("1969-12-31T23:59:60.125Z", -1),
        ("1970-01-01T00:00:60.999999999−00:01", 119),
    ] {
        assert_eq!(parse_timestamp(timestamp), Some(expected), "{timestamp}");
    }
}

#[test]
fn timestamp_import_keeps_rejecting_invalid_dates_and_relaxed_separators() {
    for timestamp in [
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01_00:00:00Z",
        "1970-01-01\n00:00:00Z",
        "1970-01-01é00:00:00Z",
        "1970−01-01T00:00:00−00:01",
        "1970-01-01T00:00:00.Z",
        "1970-01-01T00:00:00+00:60",
        "1970-01-01T00:00:00+24:00",
        "1970-01-01T00:00:00−24:00",
        "1970-01-01T00:00:00+01:00:00",
        "1970-01-01T00:00:61Z",
        "1970-01-01T24:00:00Z",
        "1900-02-29T00:00:00Z",
        "1970-01-01T00:00:00Z ",
    ] {
        assert_eq!(parse_timestamp(timestamp), None, "{timestamp}");
    }
}

#[test]
fn converts_tool_use_blocks_to_bounded_external_agent_tags() {
    let block = serde_json::json!({
        "type": "tool_use",
        "name": "Bash",
        "input": {
            "description": "Check repo status",
            "command": "git status --short"
        }
    });

    assert_eq!(
        tool_call_note(&block),
        "[external_agent_tool_call: Bash]\n\
         description: Check repo status\n\
         command: git status --short\n\
         [/external_agent_tool_call]"
    );
}

#[test]
fn converts_tool_result_blocks_to_bounded_external_agent_tags() {
    let block = serde_json::json!({
        "type": "tool_result",
        "content": "codex-rs/external-agent-migration/src/sessions/records_common.rs"
    });

    assert_eq!(
        tool_result_note(&block),
        "[external_agent_tool_result]\n\
         codex-rs/external-agent-migration/src/sessions/records_common.rs\n\
         [/external_agent_tool_result]"
    );
}

#[test]
fn converts_error_tool_result_blocks_to_bounded_external_agent_tags() {
    let block = serde_json::json!({
        "type": "tool_result",
        "is_error": true,
        "content": "command failed"
    });

    assert_eq!(
        tool_result_note(&block),
        "[external_agent_tool_result: error]\n\
         command failed\n\
         [/external_agent_tool_result]"
    );
}
