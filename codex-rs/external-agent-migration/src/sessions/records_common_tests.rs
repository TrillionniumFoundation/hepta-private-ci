use super::*;
use pretty_assertions::assert_eq;

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

#[test]
fn parses_rfc3339_offsets_and_fractions_as_unix_seconds() {
    for (timestamp, expected) in [
        ("1970-01-01T00:00:00Z", 0_i64),
        ("1970-01-01T01:30:00+01:30", 0),
        ("1969-12-31T19:00:01-05:00", 1),
        ("1969-12-31T23:59:59.500Z", -1),
        ("1970-01-01T00:00:00.999999999Z", 0),
        ("2000-02-29T12:34:56Z", 951_827_696),
        ("2026-11-20T00:00:00.123456789Z", 1_795_132_800),
    ] {
        assert_eq!(parse_timestamp(timestamp), Some(expected), "{timestamp}");
    }
}

#[test]
fn rejects_invalid_rfc3339_timestamps() {
    for timestamp in [
        "",
        "1970-01-01T00:00:00",
        "2024-02-30T00:00:00Z",
        "1970-01-01T00:00:00+25:00",
    ] {
        assert_eq!(parse_timestamp(timestamp), None, "{timestamp}");
    }
}

#[test]
fn preserves_chrono_rfc3339_edge_forms_before_parser_migration() {
    for (timestamp, expected) in [
        ("1970-01-01t00:00:00z", 0_i64),
        ("1970-01-01T00:00:00.123456789123456789Z", 0),
        ("1969-12-31T23:59:59.999999999Z", -1),
        ("1970-01-01T00:30:00+01:00", -1_800),
        ("1970-01-01T00:30:00-01:00", 5_400),
        ("1970-01-01T00:00:00+23:59", -86_340),
        ("2016-12-31T23:59:60Z", 1_483_228_799),
    ] {
        assert_eq!(parse_timestamp(timestamp), Some(expected), "{timestamp}");
    }
}

#[test]
fn rejects_out_of_range_rfc3339_edge_forms_before_parser_migration() {
    for timestamp in [
        "1970-01-01T00:00:00+24:00",
        "1970-01-01T00:00:00+23:60",
        "2016-12-31T23:59:61Z",
        "1970-01-01T00:00:00.",
        "1970-01-01T00:00:00.123",
        "1970-01-01T24:00:00Z",
        "1970-01-01T00:00:00Z trailing",
    ] {
        assert_eq!(parse_timestamp(timestamp), None, "{timestamp}");
    }
}

#[test]
fn matches_original_rfc3339_calendar_limits_and_complete_consumption() {
    for (timestamp, expected) in [
        ("0000-01-01T00:00:00Z", -62_167_219_200_i64),
        ("9999-12-31T23:59:59Z", 253_402_300_799),
        ("1970-01-01 00:00:00Z", 0),
        ("2016-12-31T23:59:60.123456789123Z", 1_483_228_799),
        ("1970-01-01T00:00:00-23:59", 86_340),
    ] {
        assert_eq!(parse_timestamp(timestamp), Some(expected), "{timestamp}");
    }
    for timestamp in [
        "1900-02-29T00:00:00Z",
        "2000-00-01T00:00:00Z",
        "1970-01-01T00:00:00+00",
        "1970-01-01T00:00:00+00:60",
        "1970-01-01T00:00:00.Z",
        "1970-01-01T00:00:00Z ",
    ] {
        assert_eq!(parse_timestamp(timestamp), None, "{timestamp}");
    }
}
