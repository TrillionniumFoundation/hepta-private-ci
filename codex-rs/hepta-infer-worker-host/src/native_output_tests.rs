use super::*;

fn message(id: &str, text: String) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: id.to_string(),
        text,
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

#[test]
fn completed_items_supply_missing_text_without_repeating_deltas() {
    let mut projection = NativeOutputProjection::default();
    projection.append_delta("first", "par").unwrap();
    projection.complete_item("first", "partial answer").unwrap();
    projection.complete_item("second", " final answer").unwrap();
    projection
        .complete_items(&[
            message("first", "partial answer".to_string()),
            message("second", " final answer".to_string()),
        ])
        .unwrap();
    assert_eq!(projection.text(), "partial answer final answer");
    assert!(projection.complete_item("first", "changed answer").is_err());
    assert!(projection.append_delta("first", "late text").is_err());
    assert_eq!(projection.text(), "partial answer final answer");
}

#[test]
fn interleaved_item_deltas_keep_first_observed_message_order() {
    let mut projection = NativeOutputProjection::default();
    projection.append_delta("first", "a").unwrap();
    projection.append_delta("second", "b").unwrap();
    projection.append_delta("first", "c").unwrap();
    assert_eq!(projection.text(), "acb");
    projection.complete_item("second", "beta").unwrap();
    projection.complete_item("first", "alpha").unwrap();
    assert_eq!(projection.text(), "alphabeta");
}

#[test]
fn complete_snapshot_overflow_is_atomic_and_counts_utf8_bytes() {
    let mut projection = NativeOutputProjection::default();
    projection.append_delta("first", "original").unwrap();
    assert!(
        projection
            .complete_items(&[
                message("first", "replacement".to_string()),
                message("second", "é".repeat(MAX_OUTPUT_BYTES / 2)),
            ])
            .is_err()
    );
    assert_eq!(projection.text(), "original");
    projection
        .complete_item("first", &"é".repeat(MAX_OUTPUT_BYTES / 2))
        .unwrap();
    assert_eq!(projection.text().len(), MAX_OUTPUT_BYTES);
    assert!(projection.complete_item("second", "x").is_err());
    assert_eq!(projection.text().len(), MAX_OUTPUT_BYTES);
}

#[test]
fn empty_output_items_and_their_identities_are_bounded() {
    let mut projection = NativeOutputProjection::default();
    assert!(projection.complete_item("", "x").is_err());
    assert!(
        projection
            .complete_item(&"i".repeat(MAX_ITEM_ID_BYTES + 1), "x")
            .is_err()
    );
    for index in 0..MAX_OUTPUT_ITEMS {
        projection
            .complete_item(&format!("item-{index}"), "")
            .unwrap();
    }
    assert!(projection.complete_item("one-too-many", "").is_err());
    projection.complete_item("item-0", "").unwrap();
    assert!(projection.text().is_empty());
}
