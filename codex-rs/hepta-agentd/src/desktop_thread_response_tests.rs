//! Return-correlation fixtures only. These JSON values are not Root grants,
//! typed application receipts, or evidence of an actual application effect.
use super::*;

fn confirmed_fixture(tool: &str, destination: &str) -> Value {
    let target = json!({"session_instance":"1".repeat(32),"task_id":1,
        "incarnation":"2".repeat(32)});
    let reference = json!({"tool":tool,"turn_id":"same-original-turn",
        "call_id":"first-original-call","callback_sha256":"1".repeat(64)});
    let digest = "3".repeat(64);
    let state = json!({"left":"20","operator":"add","right":"22","result":"42"});
    let mut result = json!({"status":"applied","previous_revision":7,"revision":8});
    let mut current = json!({"target":target,"revision":8,"receipt_pending":false});
    if tool == REPLACE_TOOL {
        result["text_sha256"] = json!(digest);
        current["text_sha256"] = json!(digest);
    } else {
        result["state_sha256"] = json!(digest);
        result["state"] = state.clone();
        current["state_sha256"] = json!(digest);
        current["state"] = state;
    }
    let receipt = json!({"schema_version":1,"operation_id":"original-operation",
        "target":target,"payload_sha256":"4".repeat(64),"result":result})
    .to_string();
    json!({"source_domain":"original_protected_sender_reference",
        "provenance":reference,"operation_id":"original-operation",
        "original_destination":destination,"original_target":target,
        "state":"Committed","receipt_utf8":receipt,
        "current_state_readback_available":true,"current_state":current})
}

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
        let original = confirmed_fixture(first_tool, destination);
        let reference = original["provenance"].clone();
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
fn committed_desktop_receipt_requires_the_current_goal_for_both_applications() {
    for (effect, status, digest_field) in [
        (REPLACE_TOOL, STATUS_TOOL, "text_sha256"),
        (
            CALCULATOR_EVALUATE_TOOL,
            CALCULATOR_STATUS_TOOL,
            "state_sha256",
        ),
    ] {
        let original = confirmed_fixture(effect, "fixture-destination");
        for tool in [effect, status] {
            assert!(response_succeeded(tool, &original));
            let mut lost = original.clone();
            lost["current_state_readback_available"] = json!(false);
            lost["current_state"] = Value::Null;
            let mut changed = original.clone();
            changed["current_state"][digest_field] = json!("5".repeat(64));
            let mut later = original.clone();
            later["current_state"]["revision"] = json!(9);
            let mut older = original.clone();
            older["current_state"]["revision"] = json!(7);
            let mut replaced = original.clone();
            replaced["current_state"]["target"]["incarnation"] = json!("6".repeat(32));
            for unresolved in [lost, changed, later, older, replaced] {
                assert_eq!(unresolved["state"], original["state"]);
                assert_eq!(unresolved["receipt_utf8"], original["receipt_utf8"]);
                assert!(!response_succeeded(tool, &unresolved));
            }
        }
    }
}

#[test]
fn desktop_confirmation_preserves_receipt_retirement_and_rejects_missing_bindings() {
    for tool in [REPLACE_TOOL, CALCULATOR_EVALUATE_TOOL] {
        let mut original = confirmed_fixture(tool, "fixture-destination");
        original["current_state"]["receipt_pending"] = json!(true);
        assert!(response_succeeded(tool, &original));
        for field in ["target", "revision", "text_sha256", "state_sha256", "state"] {
            if original["current_state"].get(field).is_none() {
                continue;
            }
            let mut missing = original.clone();
            missing["current_state"]
                .as_object_mut()
                .unwrap()
                .remove(field);
            assert!(!response_succeeded(tool, &missing));
        }
        let mut other_operation = original.clone();
        other_operation["operation_id"] = json!("different-operation");
        assert!(!response_succeeded(tool, &other_operation));
        let mut invalid_receipt = original.clone();
        invalid_receipt["receipt_utf8"] = json!("missing original receipt");
        assert!(!response_succeeded(tool, &invalid_receipt));
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
