use super::rollback_citation_decision_matches;
use codex_hepta_types::Digest32;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

#[test]
fn rollback_citation_must_use_the_current_selection_census() {
    let selection = digest("selection");
    assert!(rollback_citation_decision_matches(selection, selection));
    assert!(!rollback_citation_decision_matches(
        digest("different-selection"),
        selection,
    ));
}
