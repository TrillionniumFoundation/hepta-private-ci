use super::*;

fn candidate(
    generation: u64,
    sequence: u64,
    operation_id: &str,
    matches_previous: bool,
    retirement_ack: bool,
) -> Candidate {
    Candidate {
        order: (generation, sequence),
        operation_id: operation_id.into(),
        matches_previous,
        retirement_ack,
    }
}

#[test]
fn latest_uses_exact_previous_target_instead_of_global_latest() {
    let cut = [
        candidate(1, 1, "old-acked", false, true),
        candidate(2, 7, "previous", true, false),
        candidate(3, 9, "other-acked", false, true),
    ];
    assert_eq!(
        select(&cut, Selection::Latest).unwrap(),
        Some("previous".into())
    );
}

#[test]
fn empty_validated_cut_has_no_previous_operation() {
    assert_eq!(select(&[], Selection::Latest).unwrap(), None);
    assert!(select(&[], Selection::Exact("missing")).is_err());
}

#[test]
fn only_durable_acknowledged_other_targets_allow_no_selection() {
    let mut cut = [candidate(1, 1, "old", false, true)];
    assert_eq!(select(&cut, Selection::Latest).unwrap(), None);
    cut[0].retirement_ack = false;
    assert!(select(&cut, Selection::Latest).is_err());
}

#[test]
fn exact_selector_cannot_cross_previous_target_or_invent_operation() {
    let cut = [
        candidate(1, 1, "old", false, true),
        candidate(2, 1, "previous", true, false),
    ];
    assert!(select(&cut, Selection::Exact("old")).is_err());
    assert!(select(&cut, Selection::Exact("missing")).is_err());
    assert_eq!(
        select(&cut, Selection::Exact("previous")).unwrap(),
        Some("previous".into())
    );
}

#[test]
fn another_pending_target_blocks_latest_and_exact() {
    let cut = [
        candidate(1, 1, "older-pending", false, false),
        candidate(2, 1, "previous", true, false),
    ];
    assert!(select(&cut, Selection::Latest).is_err());
    assert!(select(&cut, Selection::Exact("previous")).is_err());
}

#[test]
fn two_pending_operations_on_same_target_cannot_fit_one_helper() {
    let cut = [
        candidate(2, 1, "previous-first", true, false),
        candidate(2, 2, "previous-second", true, false),
    ];
    assert!(select(&cut, Selection::Latest).is_err());
    assert!(select(&cut, Selection::Exact("previous-first")).is_err());
    assert!(select(&cut, Selection::Exact("previous-second")).is_err());
}

#[test]
fn acknowledged_prior_operation_allows_next_original_operation() {
    let cut = [
        candidate(1, 1, "first", false, true),
        candidate(2, 1, "second", true, true),
        candidate(2, 2, "third", true, false),
    ];
    assert_eq!(
        select(&cut, Selection::Latest).unwrap(),
        Some("third".into())
    );
    assert!(select(&cut, Selection::Exact("second")).is_err());
}

#[test]
fn original_order_is_generation_then_sequence_not_lexical_id() {
    let cut = [
        candidate(1, 999, "z", true, true),
        candidate(2, 1, "a", true, false),
    ];
    assert_eq!(select(&cut, Selection::Latest).unwrap(), Some("a".into()));
}

#[test]
fn already_acknowledged_selected_operation_remains_exact_and_idempotent() {
    let cut = [candidate(2, 1, "previous-acked", true, true)];
    assert_eq!(
        select(&cut, Selection::Latest).unwrap(),
        Some("previous-acked".into())
    );
    assert_eq!(
        select(&cut, Selection::Exact("previous-acked")).unwrap(),
        Some("previous-acked".into())
    );
}

#[test]
fn duplicate_order_and_duplicate_operation_are_never_none() {
    let same_order = [
        candidate(1, 1, "a", false, true),
        candidate(1, 1, "b", false, true),
    ];
    let same_operation = [
        candidate(1, 1, "a", false, true),
        candidate(1, 2, "a", false, true),
    ];
    for cut in [same_order, same_operation] {
        assert!(select(&cut, Selection::Latest).is_err());
        assert!(select(&cut, Selection::Exact("a")).is_err());
    }
}
