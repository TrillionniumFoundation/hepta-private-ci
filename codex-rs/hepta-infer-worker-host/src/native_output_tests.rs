use super::*;

#[test]
fn completion_without_deltas_and_identical_replay_preserve_one_message() {
    let mut messages = MessageOutput::default();
    assert!(
        messages
            .complete("message.1", "answer")
            .expect("completion")
    );
    assert!(
        !messages
            .complete("message.1", "answer")
            .expect("same completion")
    );
    assert_eq!(messages.render(), "answer");
    assert!(messages.complete("message.1", "different").is_err());
    assert!(messages.delta("message.1", "late").is_err());
    assert_eq!(messages.render(), "answer");
}

#[test]
fn completed_text_replaces_partial_deltas_without_collapsing_distinct_items() {
    let mut messages = MessageOutput::default();
    messages.delta("message.1", "par").expect("partial");
    messages.delta("message.2", "other").expect("interleaved");
    messages.delta("message.1", "tial").expect("more partial");
    messages.complete("message.1", "answer").expect("replace");
    messages
        .complete("message.2", "answer")
        .expect("distinct item");
    assert_eq!(messages.render(), "answeranswer");
}

#[test]
fn aggregate_limit_counts_replacements_and_refusals_preserve_prior_bytes() {
    let mut messages = MessageOutput::default();
    messages
        .delta("message.1", &"x".repeat(super::super::MAX_OUTPUT_BYTES))
        .expect("limit");
    assert!(messages.delta("message.2", "x").is_err());
    messages.complete("message.1", "x").expect("shrink");
    messages
        .complete("message.2", &"y".repeat(super::super::MAX_OUTPUT_BYTES - 1))
        .expect("remaining limit");
    let before = messages.render();
    assert_eq!(before.len(), super::super::MAX_OUTPUT_BYTES);
    assert!(messages.complete("message.3", "z").is_err());
    assert_eq!(messages.render(), before);
    let mut growing = MessageOutput::default();
    growing.delta("message.1", "x").expect("partial");
    growing.delta("message.2", "y").expect("other");
    assert!(
        growing
            .complete("message.1", &"x".repeat(super::super::MAX_OUTPUT_BYTES))
            .is_err()
    );
    assert_eq!(growing.render(), "xy");
}

#[test]
fn empty_messages_still_have_bounded_item_metadata() {
    let mut messages = MessageOutput::default();
    assert!(messages.complete("", "").is_err());
    assert!(
        messages
            .delta(&"x".repeat(MAX_ITEM_ID_BYTES + 1), "")
            .is_err()
    );
    for index in 0..MAX_ITEMS {
        messages
            .complete(&format!("message.{index}"), "")
            .expect("bounded empty item");
    }
    assert!(messages.complete("overflow", "").is_err());
    assert_eq!(messages.items.len(), MAX_ITEMS);
    assert!(messages.render().is_empty());
}
