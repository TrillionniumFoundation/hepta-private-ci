//! Return-correlation fixtures only. These JSON values are not Root grants,
//! typed application receipts, or evidence of an actual application effect.
use super::*;

#[test]
fn a_later_application_cannot_inherit_the_first_applications_success() {
    for (first_tool, later_tool, destination) in [
        (REPLACE_TOOL, CALCULATOR_EVALUATE_TOOL, "trill.notes:first"),
        (
            CALCULATOR_EVALUATE_TOOL,
            REPLACE_TOOL,
            "trill.calculator:first",
        ),
    ] {
        let reference = json!({"tool":first_tool,"turn_id":"same-original-turn",
            "call_id":"first-original-call","callback_sha256":"1".repeat(64)});
        let original = json!({"source_domain":"original_protected_sender_reference",
            "provenance":reference,"operation_id":"original-operation",
            "original_destination":destination,"original_target":{"incarnation":"first"},
            "state":"Committed","receipt_utf8":"explicit protocol fixture"});
        assert!(response_succeeded(first_tool, &original));
        assert!(!response_succeeded(later_tool, &original));
        let callback = json!({"tool":later_tool,"turn_id":"same-original-turn",
            "call_id":"later-original-call"});
        let refused = fenced_response(callback.clone(), reference.clone(), original.clone());
        assert!(!response_succeeded(later_tool, &refused));
        assert!(!response_succeeded(first_tool, &refused));
        assert_eq!(refused["requested_effect_performed"], false);
        assert_eq!(refused["callback"], callback);
        assert_eq!(refused["original_reference"], reference);
        assert_eq!(refused["original_operation"], original);
        assert!(refused.get("receipt_utf8").is_none());
        assert!(refused.get("state").is_none());
        assert_eq!(
            refused["original_operation"]["original_destination"],
            destination
        );
    }
}

#[test]
fn missing_history_and_current_state_do_not_manufacture_an_effect_success() {
    for tool in [
        REPLACE_TOOL,
        CALCULATOR_EVALUATE_TOOL,
        STATUS_TOOL,
        CALCULATOR_STATUS_TOOL,
    ] {
        for value in [
            json!({"status":"unknown","reason":"original_request_not_observed"}),
            json!({"current_state":{"revision":1,"result":"42"}}),
            json!({"status":"fenced","state":"Committed","receipt_utf8":"nested-success"}),
        ] {
            assert!(!response_succeeded(tool, &value));
        }
    }
    for (tool, other) in [
        (READ_TOOL, CALCULATOR_READ_TOOL),
        (CALCULATOR_READ_TOOL, READ_TOOL),
    ] {
        let state = json!({"provenance":{"tool":tool},"current_state":{"revision":3}});
        assert!(response_succeeded(tool, &state));
        assert!(!response_succeeded(other, &state));
        assert!(!response_succeeded(REPLACE_TOOL, &state));
        assert!(!response_succeeded(CALCULATOR_EVALUATE_TOOL, &state));
    }
}
