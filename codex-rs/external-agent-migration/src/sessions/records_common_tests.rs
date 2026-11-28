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
fn retains_integral_seconds_and_legacy_rfc3339_grammar() {
    let cases = [
        ("1970-01-01T00:00:00Z", Some(0)),
        ("1969-12-31T23:59:59.999999999999Z", Some(-1)),
        ("1970-01-01t05:30:00+05:30", Some(0)),
        ("1969-12-31 18:30:00−05:30", Some(0)),
        ("1970-01-01T00:00:00-00:00", Some(0)),
        ("1970-01-01T23:59:00+23:59", Some(0)),
        ("1969-12-31T00:01:00-23:59", Some(0)),
        ("2016-12-31T23:59:60.123456789123z", Some(1483228799)),
        ("1970-01-01T00:00:60Z", Some(59)),
        ("1970-01-01T00:00:61Z", None),
        ("1970-01-01T24:00:00Z", None),
        ("1970-01-01T00:00:00+24:00", None),
        ("1970-01-01T00:00:00+00:60", None),
        ("1970-01-01T00:00:00+0000", None),
        ("1970-01-01T00:00:00.Z", None),
        ("1970-01-01T00:00:00Z ", None),
        ("1900-02-29T00:00:00Z", None),
        ("1970-01-01\t00:00:00Z", None),
        ("1970-01-01T00:00:00", None),
        ("1970-01-01T00:00:00.１２Z", None),
        ("é", None),
    ];
    for (input, expected) in cases {
        assert_eq!(parse_timestamp(input), expected, "{input:?}");
    }
}
