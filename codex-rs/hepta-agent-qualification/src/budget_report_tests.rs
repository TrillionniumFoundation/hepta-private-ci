#![allow(clippy::expect_used, reason = "fixed cap witness counterexamples")]

use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

fn retained() -> Value {
    json!({"terminal":"incomplete", "terminal_consistent":true, "reason":"max_output_tokens",
        "usage_status":"observed", "usage":{"input_tokens":7,"output_tokens":32,"total_tokens":39},
        "reservation_settlement":"retained_indeterminate",
        "retained_reservation":{"provider_input_tokens":8192,"output_tokens":32,"provider_calls":1},
        "echoed_max_output_tokens":32})
}

#[test]
fn only_original_incomplete_with_actual_usage_and_settled_owner_witness_qualifies() {
    let valid = retained();
    let result = decide(Some(&valid), 8192, 32, true, true, true, false);
    assert!(result.qualified);
    assert_eq!(result.status, "cap_witness_observed_for_this_exact_request");
    assert!(!decide(Some(&valid), 8192, 32, false, true, true, false).qualified);
    assert!(!decide(Some(&valid), 8192, 32, true, false, true, false).qualified);
    assert!(!decide(Some(&valid), 8192, 32, true, true, false, false).qualified);
    assert!(!decide(Some(&valid), 8192, 32, true, true, true, true).qualified);
}

#[test]
fn ordinary_completion_missing_usage_refusal_and_exceeded_cap_never_become_support() {
    assert!(!decide(None, 8192, 32, true, true, false, false).qualified);
    let ordinary = json!({"usage":{"input_tokens":7,"output_tokens":2,"total_tokens":9}});
    assert_eq!(
        decide(Some(&ordinary), 8192, 32, true, true, false, false).status,
        "inconclusive_completed_response"
    );
    for (path, changed) in [
        ("/reason", json!("content_filter")),
        ("/terminal_consistent", json!(false)),
        ("/usage_status", json!("missing")),
        ("/usage/output_tokens", json!(33)),
        ("/retained_reservation/output_tokens", json!(64)),
        ("/echoed_max_output_tokens", json!(64)),
        ("/reservation_settlement", json!("released")),
    ] {
        let mut invalid = retained();
        *invalid.pointer_mut(path).expect("fixture field") = changed;
        assert!(
            !decide(Some(&invalid), 8192, 32, true, true, true, false).qualified,
            "counterexample: {path}"
        );
    }
}
