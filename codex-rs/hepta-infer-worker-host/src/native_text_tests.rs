use super::*;

#[test]
fn completed_only_and_repeated_snapshots_keep_distinct_identical_messages() {
    let mut ledger = NativeTextObservation::default();
    let mut output = String::new();
    ledger.complete(&mut output, "first", "answer").unwrap();
    ledger.complete(&mut output, "first", "answer").unwrap();
    ledger.complete(&mut output, "second", "answer").unwrap();
    ledger.complete(&mut output, "second", "answer").unwrap();
    assert_eq!(output, "answeranswer");
}

#[test]
fn streamed_ranges_validate_each_item_and_append_only_missing_text() {
    let mut ledger = NativeTextObservation::default();
    let mut output = String::new();
    ledger.delta(&mut output, "first", "a").unwrap();
    ledger.delta(&mut output, "second", "b").unwrap();
    ledger.delta(&mut output, "first", "c").unwrap();
    ledger.complete(&mut output, "first", "acd").unwrap();
    ledger.complete(&mut output, "second", "be").unwrap();
    ledger.complete(&mut output, "first", "acd").unwrap();
    assert_eq!(output, "abcde");
    assert_eq!(ledger.items["first"].observed_bytes, 3);
}

#[test]
fn contradictions_and_post_completion_deltas_preserve_observed_text() {
    let mut ledger = NativeTextObservation::default();
    let mut output = String::new();
    ledger.delta(&mut output, "first", "雪").unwrap();
    assert!(ledger.complete(&mut output, "first", "rain").is_err());
    ledger.complete(&mut output, "first", "雪! ").unwrap();
    assert!(ledger.complete(&mut output, "first", "雪! more").is_err());
    assert!(ledger.delta(&mut output, "first", "later").is_err());
    assert_eq!(output, "雪! ");
}

#[test]
fn oversized_completed_text_retains_a_utf8_prefix_without_duplicate_append() {
    let mut ledger = NativeTextObservation::default();
    let mut output = String::new();
    ledger.delta(&mut output, "first", "prefix").unwrap();
    let completed = format!("prefix{}", "雪".repeat(MAX_OUTPUT_BYTES));
    assert!(ledger.complete(&mut output, "first", &completed).is_err());
    let retained = output.clone();
    assert!(output.len() <= MAX_OUTPUT_BYTES);
    assert_eq!(&completed[..output.len()], output);
    assert!(ledger.complete(&mut output, "first", &completed).is_err());
    assert_eq!(output, retained);
}

#[test]
fn opaque_ids_and_empty_item_flood_are_bounded_before_storage() {
    let mut ledger = NativeTextObservation::default();
    let mut output = String::new();
    ledger.complete(&mut output, "opaque id / 雪", "").unwrap();
    assert!(
        ledger
            .complete(&mut output, &"x".repeat(MAX_OUTPUT_BYTES), "")
            .is_err()
    );
    for index in 0..MAX_OUTPUT_BYTES {
        if ledger
            .complete(&mut output, &format!("item-{index}"), "")
            .is_err()
        {
            assert!(ledger.bookkeeping_bytes <= MAX_OUTPUT_BYTES);
            assert!(ledger.items.len() < MAX_OUTPUT_BYTES);
            return;
        }
    }
    panic!("empty message IDs must exhaust their bookkeeping budget");
}

#[test]
fn contiguous_deltas_use_one_range_and_overflow_preserves_the_prefix() {
    let mut ledger = NativeTextObservation::default();
    let mut output = String::new();
    for _ in 0..10_000 {
        ledger.delta(&mut output, "first", "a").unwrap();
    }
    assert_eq!(ledger.items["first"].ranges, vec![0..10_000]);
    let retained = output.clone();
    assert!(
        ledger
            .delta(&mut output, "first", &"x".repeat(MAX_OUTPUT_BYTES))
            .is_err()
    );
    assert_eq!(output, retained);
}
