use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

#[test]
fn action_projection_is_canonical_without_changing_policy_actions() {
    let actions = vec![id("action.read"), id("action.noop")];
    let before = actions.clone();
    let expected = vec![id("abstain"), id("action.noop"), id("action.read")];
    assert_eq!(
        learning_candidate_ids_v1(&actions).expect("projection"),
        expected
    );
    let mut reversed = actions.clone();
    reversed.reverse();
    assert_eq!(
        learning_candidate_ids_v1(&reversed).expect("projection"),
        expected
    );
    assert_eq!(actions, before);
}

#[test]
fn action_projection_rejects_empty_duplicate_and_reserved_actions() {
    for (actions, reason) in [
        (vec![], "learning candidate capacity including abstain"),
        (vec![id("abstain")], "reserved intrinsic abstain action"),
        (
            vec![id("action.read"), id("abstain")],
            "reserved intrinsic abstain action",
        ),
        (
            vec![id("action.read"), id("action.noop"), id("action.read")],
            "duplicate learning action",
        ),
    ] {
        let before = actions.clone();
        assert_eq!(
            learning_candidate_ids_v1(&actions),
            Err(CanonicalIntelligenceError::InvalidCandidateSet(reason))
        );
        assert_eq!(actions, before);
    }
}

#[test]
fn action_projection_preserves_the_ledger_capacity_bound() {
    let mut actions = (0..127)
        .map(|index| id(&format!("action.{index}")))
        .collect::<Vec<_>>();
    let mut expected = actions.clone();
    expected.push(id("abstain"));
    expected.sort();
    assert_eq!(
        learning_candidate_ids_v1(&actions).expect("maximum inclusive set"),
        expected
    );
    actions.push(id("action.127"));
    assert_eq!(
        learning_candidate_ids_v1(&actions),
        Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "learning candidate capacity including abstain"
        ))
    );
}
