use super::*;

fn message(id: &str, text: &str) -> ThreadItem {
    serde_json::from_value(serde_json::json!({
        "type": "agentMessage", "id": id, "text": text
    }))
    .unwrap()
}

#[test]
fn completion_only_and_duplicate_summary_preserve_exact_output_once() {
    let mut assembly = NativeOutputAssembly::default();
    assembly
        .record("first", "fresh context accepted", true)
        .unwrap();
    assembly.record("second", " and retained", true).unwrap();
    let before = assembly.render();
    assembly
        .completed_items(&[message("second", " and retained")])
        .unwrap();
    assert_eq!(assembly.render(), before);
    assert_eq!(before, "fresh context accepted and retained");
}

#[test]
fn interleaved_deltas_complete_by_identity_without_duplicate_text() {
    let mut assembly = NativeOutputAssembly::default();
    assembly.record("first", "he", false).unwrap();
    assembly.record("second", "wo", false).unwrap();
    assembly.record("first", "llo", false).unwrap();
    assembly.record("second", "world", true).unwrap();
    assembly.record("first", "hello", true).unwrap();
    assert_eq!(assembly.render(), "helloworld");
    assert_eq!(assembly.total_bytes, 10);
    assert!(assembly.record("first", "changed", true).is_err());
    assert!(assembly.record("first", "late delta", false).is_err());
    assert_eq!(assembly.render(), "helloworld");
}

#[test]
fn conflicting_terminal_snapshot_is_atomic_and_never_rewrites_deltas() {
    let mut assembly = NativeOutputAssembly::default();
    assembly.record("first", "prefix", false).unwrap();
    let result = assembly.completed_items(&[
        message("new", "must not be retained"),
        message("first", "unrelated replacement"),
    ]);
    assert!(result.is_err());
    assert_eq!(assembly.render(), "prefix");
    assert_eq!(assembly.messages.len(), 1);
    assert!(!assembly.messages[0].completed);
}

#[test]
fn completion_and_delta_limits_reject_without_mutating_previous_state() {
    let mut assembly = NativeOutputAssembly::default();
    assembly.record("first", "x", false).unwrap();
    assert!(
        assembly
            .record("second", &"y".repeat(MAX_OUTPUT_BYTES), true)
            .is_err()
    );
    assert!(
        assembly
            .record("first", &"y".repeat(MAX_OUTPUT_BYTES), false)
            .is_err()
    );
    assert!(assembly.record("", "text", true).is_err());
    assert!(
        assembly
            .record(&"i".repeat(MAX_ITEM_ID_BYTES + 1), "text", true)
            .is_err()
    );
    assert_eq!(assembly.render(), "x");
    for index in 1..MAX_OUTPUT_ITEMS {
        assembly.record(&format!("item-{index}"), "", true).unwrap();
    }
    assert!(assembly.record("overflow", "", true).is_err());
    assert_eq!(assembly.render(), "x");
}
