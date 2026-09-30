use super::*;

fn message(id: &str, text: &str) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: id.to_string(),
        text: text.to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

#[test]
fn unicode_byte_limit_is_exact_and_rejection_never_splits_a_character() {
    let mut output = String::new();
    let mut collector = NativeOutputCollectorV1::default();
    let text = "🙂".repeat(MAX_OUTPUT_BYTES / 4);
    collector.completed(&mut output, "first", &text).unwrap();
    assert_eq!(output.len(), MAX_OUTPUT_BYTES);
    assert!(collector.completed(&mut output, "second", "你").is_err());
    assert_eq!(output, text);
    collector.completed(&mut output, "first", &text).unwrap();
    assert_eq!(output, text);
}

#[test]
fn empty_messages_have_bounded_item_identity_state() {
    let mut output = String::new();
    let mut collector = NativeOutputCollectorV1::default();
    assert!(collector.delta(&mut output, "", "").is_err());
    assert!(
        collector
            .delta(&mut output, &"x".repeat(MAX_OUTPUT_ITEM_ID_BYTES + 1), "")
            .is_err()
    );
    for index in 0..MAX_OUTPUT_ITEMS {
        collector
            .started(&mut output, &format!("item-{index}"), "")
            .unwrap();
    }
    assert!(
        collector
            .completed(&mut output, "one-too-many", "")
            .is_err()
    );
    assert!(output.is_empty());
    collector
        .completed(&mut output, "item-0", "retained")
        .unwrap();
    assert_eq!(output, "retained");
}

#[test]
fn contradictory_completion_and_duplicate_full_item_ids_fail_atomically() {
    let mut output = String::new();
    let mut collector = NativeOutputCollectorV1::default();
    collector
        .completed(&mut output, "first", "original")
        .unwrap();
    assert!(
        collector
            .completed(&mut output, "first", "contradiction")
            .is_err()
    );
    assert!(
        collector
            .turn_completed(
                &mut output,
                &[message("first", "contradiction")],
                TurnItemsView::Full,
            )
            .is_err()
    );
    assert!(
        collector
            .turn_completed(
                &mut output,
                &[message("first", "original"), message("first", "original")],
                TurnItemsView::Full,
            )
            .is_err()
    );
    assert_eq!(output, "original");
    collector
        .turn_completed(&mut output, &[], TurnItemsView::NotLoaded)
        .unwrap();
    assert_eq!(output, "original");
    collector
        .turn_completed(&mut output, &[], TurnItemsView::Full)
        .unwrap();
    assert!(output.is_empty());
}

#[test]
fn recovered_output_requires_a_full_history_view_and_rejects_partial_views_atomically() {
    let mut output = String::new();
    let mut collector = NativeOutputCollectorV1::default();
    collector
        .delta(&mut output, "partial", "retained partial")
        .unwrap();
    let final_items = [message("first", "complete "), message("second", "history")];
    for view in [TurnItemsView::Summary, TurnItemsView::NotLoaded] {
        assert!(
            collector
                .reconciled_turn(&mut output, &final_items, view)
                .is_err()
        );
        assert_eq!(output, "retained partial");
    }
    collector
        .reconciled_turn(&mut output, &final_items, TurnItemsView::Full)
        .unwrap();
    assert_eq!(output, "complete history");
}
