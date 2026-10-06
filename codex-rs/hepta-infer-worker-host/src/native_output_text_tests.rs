use super::*;

#[test]
fn completed_only_returns_text_exactly_once() {
    let mut text = NativeOutputText::new();
    text.item_started("a", "done-only").unwrap();
    text.item_completed("a", "done-only").unwrap();
    text.seal().unwrap();
    assert_eq!(text.into_output(), "done-only");
}

#[test]
fn completed_without_start_is_supported() {
    let mut text = NativeOutputText::new();
    text.item_completed("a", "done-only").unwrap();
    assert_eq!(text.into_output(), "done-only");
}

#[test]
fn seeded_start_plus_suffix_delta_and_final_preserves_all_text_once() {
    let mut text = NativeOutputText::new();
    text.item_started("a", "Hello ").unwrap();
    text.delta("a", "world").unwrap();
    text.item_completed("a", "Hello world!").unwrap();
    text.seal().unwrap();
    assert_eq!(text.into_output(), "Hello world!");
}

#[test]
fn repeated_full_start_is_idempotent_without_completing_item() {
    let mut text = NativeOutputText::new();
    text.item_started("a", "seed").unwrap();
    text.item_started("a", "seed").unwrap();
    text.delta("a", " suffix").unwrap();
    text.item_started("a", "seed suffix").unwrap();
    text.item_completed("a", "seed suffix").unwrap();
    assert_eq!(text.into_output(), "seed suffix");
}

#[test]
fn older_late_start_snapshot_is_noop_and_newer_snapshot_appends_only_suffix() {
    let mut text = NativeOutputText::new();
    text.delta("a", "Hello").unwrap();
    text.item_completed("b", " B").unwrap();
    text.item_started("a", "Hel").unwrap();
    text.item_started("a", "Hello A").unwrap();
    text.item_started("a", "").unwrap();
    assert_eq!(text.into_output(), "Hello A B");
}

#[test]
fn conflicting_late_start_rejects_without_altering_accepted_output() {
    let mut text = NativeOutputText::new();
    text.delta("a", "existing").unwrap();
    assert_eq!(
        text.item_started("a", "other"),
        Err(OutputTextError::ConflictingStart)
    );
    assert_eq!(
        text.item_started("a", "existing"),
        Err(OutputTextError::ConflictingStart)
    );
    assert_eq!(text.into_output(), "existing");
}

#[test]
fn completed_item_allows_only_prefix_consistent_start_snapshots() {
    for initial_text in ["Hello world!", "different"] {
        let mut text = NativeOutputText::new();
        text.item_completed("a", "Hello world").unwrap();
        text.item_started("a", "Hello").unwrap();
        text.item_started("a", "Hello world").unwrap();
        assert_eq!(
            text.item_started("a", initial_text),
            Err(OutputTextError::ConflictingStart)
        );
        assert_eq!(text.into_output(), "Hello world");
    }
}

#[test]
fn seeded_start_enforces_text_bound_atomically_on_new_and_existing_items() {
    for item_id in ["a", "new"] {
        let mut text = NativeOutputText::new();
        text.delta("a", "x").unwrap();
        assert_eq!(
            text.item_started(item_id, &"x".repeat(MAX_OUTPUT_BYTES + 1)),
            Err(OutputTextError::TextBudget)
        );
        assert_eq!(text.items.len(), 1);
        assert_eq!(text.into_output(), "x");
    }
}

#[test]
fn seeded_start_budget_counts_only_new_suffix_and_all_items() {
    let mut text = NativeOutputText::new();
    let full = "x".repeat(MAX_OUTPUT_BYTES - 1);
    text.item_started("a", &full[..full.len() - 1]).unwrap();
    text.item_started("b", "B").unwrap();
    text.item_started("a", &full).unwrap();
    text.item_started("a", &full).unwrap();
    assert_eq!(
        text.item_started("a", &format!("{full}!")),
        Err(OutputTextError::TextBudget)
    );
    assert_eq!(text.into_output(), format!("{full}B"));
}

#[test]
fn streamed_prefix_plus_completion_adds_only_missing_suffix() {
    let mut text = NativeOutputText::new();
    text.delta("a", "hel").unwrap();
    text.delta("a", "lo").unwrap();
    text.item_completed("a", "hello world").unwrap();
    assert_eq!(text.into_output(), "hello world");
}

#[test]
fn identical_duplicate_completion_is_idempotent() {
    let mut text = NativeOutputText::new();
    text.delta("a", "hello").unwrap();
    text.item_completed("a", "hello").unwrap();
    text.item_completed("a", "hello").unwrap();
    assert_eq!(text.into_output(), "hello");
}

#[test]
fn repeated_equal_text_with_distinct_ids_is_not_deduplicated() {
    let mut text = NativeOutputText::new();
    text.item_completed("a", "same").unwrap();
    text.item_completed("b", "same").unwrap();
    assert_eq!(text.into_output(), "samesame");
}

#[test]
fn started_order_wins_over_interleaved_text_arrival() {
    let mut text = NativeOutputText::new();
    text.item_started("a", "").unwrap();
    text.item_started("b", "").unwrap();
    text.delta("b", "B").unwrap();
    text.delta("a", "A").unwrap();
    text.delta("b", "2").unwrap();
    text.item_completed("c", "C").unwrap();
    text.item_completed("b", "B2").unwrap();
    text.item_completed("a", "A1").unwrap();
    assert_eq!(text.into_output(), "A1B2C");
}

#[test]
fn missing_and_late_starts_keep_first_observation_order() {
    let mut text = NativeOutputText::new();
    text.delta("b", "B").unwrap();
    text.item_started("a", "").unwrap();
    text.item_started("b", "").unwrap();
    text.item_completed("a", "A").unwrap();
    text.item_started("a", "").unwrap();
    text.item_started("b", "").unwrap();
    text.item_completed("b", "B").unwrap();
    assert_eq!(text.into_output(), "BA");
}

#[test]
fn started_after_completion_does_not_reopen_item() {
    let mut text = NativeOutputText::new();
    text.item_completed("a", "A").unwrap();
    text.item_started("a", "").unwrap();
    assert_eq!(
        text.delta("a", "B"),
        Err(OutputTextError::DeltaAfterCompletion)
    );
    assert_eq!(text.into_output(), "A");
}

#[test]
fn duplicate_deltas_append_because_no_sequence_identity_exists() {
    let mut text = NativeOutputText::new();
    text.delta("a", "ha").unwrap();
    text.delta("a", "ha").unwrap();
    text.item_completed("a", "haha").unwrap();
    assert_eq!(text.into_output(), "haha");
}

#[test]
fn duplicated_or_out_of_order_deltas_can_conflict_with_final_text() {
    for fragments in [["ha", "ha"], ["world", "hello"]] {
        let mut text = NativeOutputText::new();
        for fragment in fragments {
            text.delta("a", fragment).unwrap();
        }
        assert_eq!(
            text.item_completed("a", "hello world"),
            Err(OutputTextError::ConflictingCompletion)
        );
        assert_eq!(text.into_output(), fragments.concat());
    }
}

#[test]
fn final_must_match_the_whole_streamed_prefix() {
    for full_text in ["ab", "abXdef", "zabcdef", ""] {
        let mut text = NativeOutputText::new();
        text.delta("a", "abc").unwrap();
        assert_eq!(
            text.item_completed("a", full_text),
            Err(OutputTextError::ConflictingCompletion)
        );
        assert_eq!(text.into_output(), "abc");
    }
}

#[test]
fn conflicting_repeated_final_cannot_extend_or_replace_text() {
    for full_text in ["AB", "different", ""] {
        let mut text = NativeOutputText::new();
        text.item_completed("a", "A").unwrap();
        assert_eq!(
            text.item_completed("a", full_text),
            Err(OutputTextError::ConflictingCompletion)
        );
        assert_eq!(text.into_output(), "A");
    }
}

#[test]
fn empty_delta_after_final_is_harmless_but_nonempty_delta_is_rejected() {
    let mut text = NativeOutputText::new();
    text.item_completed("a", "A").unwrap();
    text.delta("a", "").unwrap();
    text.delta("a", "").unwrap();
    assert!(!text.is_rejected());
    assert_eq!(
        text.delta("a", "A"),
        Err(OutputTextError::DeltaAfterCompletion)
    );
    assert_eq!(text.into_output(), "A");
}

#[test]
fn empty_delta_for_unknown_item_reserves_a_bounded_order_slot() {
    let mut text = NativeOutputText::new();
    text.delta("a", "").unwrap();
    text.item_completed("b", "B").unwrap();
    text.item_completed("a", "A").unwrap();
    assert_eq!(text.items.len(), 2);
    assert_eq!(text.into_output(), "AB");
}

#[test]
fn first_error_is_sticky_and_preserves_partial_output() {
    let mut text = NativeOutputText::new();
    text.delta("a", "accepted").unwrap();
    assert_eq!(text.delta("", "bad"), Err(OutputTextError::EmptyItemId));
    assert_eq!(
        text.delta("b", "ignored"),
        Err(OutputTextError::EmptyItemId)
    );
    assert_eq!(
        text.item_completed("a", "accepted"),
        Err(OutputTextError::EmptyItemId)
    );
    assert_eq!(text.seal(), Err(OutputTextError::EmptyItemId));
    assert_eq!(text.into_output(), "accepted");
}

#[test]
fn named_completion_preserves_earlier_items() {
    let mut text = NativeOutputText::new();
    text.item_completed("earlier", "first ").unwrap();
    text.delta("last", "sec").unwrap();
    // A later named completion must not replace previously assembled items.
    text.item_completed("last", "second").unwrap();
    text.seal().unwrap();
    assert_eq!(text.into_output(), "first second");
}

#[test]
fn named_completion_can_add_an_item_and_repeat_an_existing_final() {
    let mut text = NativeOutputText::new();
    text.item_completed("earlier", "first ").unwrap();
    text.item_completed("earlier", "first ").unwrap();
    text.item_completed("last", "second").unwrap();
    text.seal().unwrap();
    assert_eq!(text.into_output(), "first second");
}

#[test]
fn all_text_event_kinds_are_rejected_after_terminal_sealing() {
    for event in [
        TextEvent::Started(""),
        TextEvent::Delta("B"),
        TextEvent::Delta(""),
        TextEvent::Completed("A"),
    ] {
        let mut text = NativeOutputText::new();
        text.item_completed("a", "A").unwrap();
        text.seal().unwrap();
        text.seal().unwrap();
        assert_eq!(
            text.observe("a", event),
            Err(OutputTextError::AfterTerminal)
        );
        assert_eq!(text.into_output(), "A");
    }
}

#[test]
fn abort_returns_partial_items_in_reserved_order_without_requiring_finals() {
    let mut text = NativeOutputText::new();
    text.item_started("a", "").unwrap();
    text.delta("b", "partial B").unwrap();
    text.delta("a", "partial A ").unwrap();
    text.item_started("empty", "").unwrap();
    assert_eq!(text.into_output(), "partial A partial B");
}

#[test]
fn empty_turn_and_empty_final_are_valid() {
    assert_eq!(NativeOutputText::new().into_output(), "");
    let mut text = NativeOutputText::new();
    text.item_completed("empty", "").unwrap();
    text.item_completed("empty", "").unwrap();
    text.seal().unwrap();
    assert_eq!(text.into_output(), "");
}

#[test]
fn opaque_unicode_ids_and_text_use_byte_budgets() {
    let mut text = NativeOutputText::new();
    text.delta("消息", "你").unwrap();
    text.item_completed("消息", "你好🙂").unwrap();
    assert_eq!(text.into_output(), "你好🙂");
    let mut text = NativeOutputText::new();
    assert_eq!(
        text.item_started(&"é".repeat(MAX_ITEM_ID_BYTES / 2 + 1), ""),
        Err(OutputTextError::ItemIdTooLong)
    );
    assert_eq!(text.into_output(), "");
}

#[test]
fn each_event_kind_rejects_empty_and_oversized_ids() {
    for event in [
        TextEvent::Started(""),
        TextEvent::Delta("A"),
        TextEvent::Completed("A"),
    ] {
        let mut text = NativeOutputText::new();
        assert_eq!(text.observe("", event), Err(OutputTextError::EmptyItemId));
        assert_eq!(text.into_output(), "");
    }
    for event in [
        TextEvent::Started(""),
        TextEvent::Delta("A"),
        TextEvent::Completed("A"),
    ] {
        let mut text = NativeOutputText::new();
        assert_eq!(
            text.observe(&"x".repeat(MAX_ITEM_ID_BYTES + 1), event),
            Err(OutputTextError::ItemIdTooLong)
        );
        assert_eq!(text.into_output(), "");
    }
}

#[test]
fn empty_messages_cannot_bypass_item_count_bound() {
    let mut text = NativeOutputText::new();
    for index in 0..MAX_ASSISTANT_ITEMS {
        text.item_started(&index.to_string(), "").unwrap();
    }
    text.item_completed("0", "existing identity still works")
        .unwrap();
    assert_eq!(
        text.item_started("overflow", ""),
        Err(OutputTextError::ItemCountLimit)
    );
    assert_eq!(text.items.len(), MAX_ASSISTANT_ITEMS);
    assert_eq!(text.into_output(), "existing identity still works");
}

#[test]
fn aggregate_id_bytes_are_bounded_independently_of_item_count() {
    let mut text = NativeOutputText::new();
    for index in 0..MAX_TOTAL_ITEM_ID_BYTES / MAX_ITEM_ID_BYTES {
        let id = format!("{index:0MAX_ITEM_ID_BYTES$}");
        text.item_completed(&id, "").unwrap();
        text.item_completed(&id, "").unwrap();
    }
    assert_eq!(
        text.item_started("overflow", ""),
        Err(OutputTextError::ItemIdBudget)
    );
    assert_eq!(text.item_id_bytes, MAX_TOTAL_ITEM_ID_BYTES);
    assert_eq!(text.into_output(), "");
}

#[test]
fn delta_cannot_exceed_aggregate_text_bound_across_items() {
    let mut text = NativeOutputText::new();
    let first = "a".repeat(MAX_OUTPUT_BYTES - 1);
    text.item_completed("a", &first).unwrap();
    text.delta("b", "b").unwrap();
    assert_eq!(text.delta("c", "c"), Err(OutputTextError::TextBudget));
    assert_eq!(text.items.len(), 2);
    assert_eq!(text.into_output(), format!("{first}b"));
}

#[test]
fn completed_suffix_budget_charges_only_additional_bytes() {
    let mut text = NativeOutputText::new();
    let full = "x".repeat(MAX_OUTPUT_BYTES);
    text.delta("a", &full[..MAX_OUTPUT_BYTES - 1]).unwrap();
    text.item_completed("a", &full).unwrap();
    text.item_completed("a", &full).unwrap();
    assert_eq!(text.into_output(), full);
}

#[test]
fn oversized_completion_is_atomic_for_existing_and_new_items() {
    for item_id in ["a", "new"] {
        let mut text = NativeOutputText::new();
        text.delta("a", "x").unwrap();
        assert_eq!(
            text.item_completed(item_id, &"x".repeat(MAX_OUTPUT_BYTES + 1)),
            Err(OutputTextError::TextBudget)
        );
        assert_eq!(text.items.len(), 1);
        assert_eq!(text.into_output(), "x");
    }
}

#[test]
fn unicode_text_limit_is_bytes_not_character_count() {
    let mut text = NativeOutputText::new();
    let full = "🙂".repeat(MAX_OUTPUT_BYTES / 4);
    text.delta("a", &full).unwrap();
    assert_eq!(text.delta("a", "é"), Err(OutputTextError::TextBudget));
    assert_eq!(text.into_output(), full);
}

#[test]
fn abort_snapshot_does_not_reset_state_before_interrupt_grace() {
    let mut text = NativeOutputText::new();
    text.item_started("a", "").unwrap();
    text.delta("a", "partial").unwrap();
    let abort_output = text.snapshot_output();
    assert!(!text.is_rejected());
    assert!(!text.is_sealed());
    text.item_completed("a", "partial final").unwrap();
    text.seal().unwrap();
    assert!(!text.is_rejected());
    assert!(text.is_sealed());
    assert_eq!(
        (abort_output, text.into_output()),
        ("partial".into(), "partial final".into())
    );
}

#[test]
fn rejected_accumulator_remains_rejected_for_interrupt_grace() {
    let mut text = NativeOutputText::new();
    text.delta("a", "partial").unwrap();
    assert_eq!(
        text.item_completed("a", "conflict"),
        Err(OutputTextError::ConflictingCompletion)
    );
    assert!(text.is_rejected());
    assert!(!text.is_sealed());
    let abort_output = text.snapshot_output();
    assert_eq!(
        text.delta("a", "ignored"),
        Err(OutputTextError::ConflictingCompletion)
    );
    assert!(text.is_rejected());
    assert_eq!(
        (abort_output, text.into_output()),
        ("partial".into(), "partial".into())
    );
}
