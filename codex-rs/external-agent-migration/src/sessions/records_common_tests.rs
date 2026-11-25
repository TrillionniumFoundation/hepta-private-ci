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
fn timestamp_parser_preserves_unix_seconds_across_epoch_offsets_and_fraction() {
    for (input, expected) in [
        ("1970-01-01T00:00:00Z", 0),
        ("1970-01-01t00:00:00z", 0),
        ("1970-01-01 00:00:00Z", 0),
        ("1970-01-01T00:00:00.99999999999999999999Z", 0),
        ("1970-01-01T00:00:01.00000000000000000001Z", 1),
        ("1969-12-31T23:59:59.99999999999999999999Z", -1),
        ("1969-12-31T23:59:59.000000001Z", -1),
        ("1970-01-01T01:00:00+01:00", 0),
        ("1969-12-31T23:00:00-01:00", 0),
        ("1970-01-01T00:00:00-00:30", 1_800),
        ("1970-01-01T00:00:00+23:59", -86_340),
        ("1970-01-01T00:00:00-23:59", 86_340),
        ("2000-02-29T00:00:00Z", 951_782_400),
        ("0000-01-01T00:00:00+23:59", -62_167_305_540),
        ("9999-12-31T23:59:59-23:59", 253_402_387_139),
    ] {
        assert_eq!(parse_timestamp(input), Some(expected), "{input}");
    }
}

#[test]
fn timestamp_parser_preserves_original_leap_second_integer_mapping() {
    for (input, expected) in [
        ("1970-01-01T00:00:60Z", 59),
        ("1970-01-01T00:01:60.123456789123Z", 119),
        ("1969-12-31T23:59:60.999999999Z", -1),
        ("1970-01-01T01:00:60+01:00", 59),
        ("1969-12-31T23:00:60.123456789123\u{2212}01:00", 59),
        ("2016-12-31T23:59:60Z", 1_483_228_799),
    ] {
        assert_eq!(parse_timestamp(input), Some(expected), "{input}");
    }
}

#[test]
fn timestamp_parser_preserves_unicode_offset_minus_and_negative_zero() {
    for (input, expected) in [
        ("1970-01-01T00:00:00-00:00", 0),
        ("1970-01-01T00:00:00\u{2212}00:00", 0),
        ("1969-12-31T23:00:00.123456789123\u{2212}01:00", 0),
        ("1970-01-01T00:00:00\u{2212}23:59", 86_340),
    ] {
        assert_eq!(parse_timestamp(input), Some(expected), "{input}");
    }
}

#[test]
fn timestamp_parser_preserves_original_syntax_and_range_refusals() {
    for input in [
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01X00:00:00Z",
        "1970-01-01\t00:00:00Z",
        "1970-01-01\n00:00:00Z",
        "1970-01-01_00:00:00Z",
        "1970-01-01000:00:00Z",
        "1970-01-01\u{2212}00:00:00Z",
        "1970\u{2212}01-01T00:00:00Z",
        "1970-01-01T00:00:00\u{ff0d}01:00",
        "1970-01-01T00:00:00\u{2212}24:00",
        "1970-01-01T00:00:00+24:00",
        "1970-01-01T00:00:00+00:60",
        "1970-01-01T00:00:00+0100",
        "1970-01-01T00:00:00+01",
        "1970-01-01T00:00:00+01:00:00",
        "1970-01-01T00:00:00.Z",
        "1970-01-01T00:00:00,1Z",
        "1970-01-01T00:00:00UTC",
        "1970-01-01T00:00:00ZZ",
        "1970-01-01T00:00:00Z ",
        " 1970-01-01T00:00:00Z",
        "1970-01-01T00:00:61Z",
        "1970-01-01T24:00:00Z",
        "1970-01-01T00:60:00Z",
        "1900-02-29T00:00:00Z",
        "1970-02-30T00:00:00Z",
        "1970-00-01T00:00:00Z",
        "1970-01-00T00:00:00Z",
        "+1970-01-01T00:00:00Z",
        "10000-01-01T00:00:00Z",
        "1970-1-01T00:00:00Z",
    ] {
        assert_eq!(parse_timestamp(input), None, "{input:?}");
    }
}
