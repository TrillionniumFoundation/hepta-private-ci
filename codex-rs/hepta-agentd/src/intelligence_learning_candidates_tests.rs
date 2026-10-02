use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

#[test]
fn action_projection_is_canonical_and_reserves_intrinsic_abstain() {
    let actions = vec![id("action.read"), id("action.noop")];
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
    assert_eq!(actions, vec![id("action.read"), id("action.noop")]);
    for invalid in [
        vec![],
        vec![id("abstain")],
        vec![id("action.read"), id("action.read")],
    ] {
        assert!(learning_candidate_ids_v1(&invalid).is_err());
    }
}

#[test]
fn action_projection_preserves_the_ledger_capacity_bound() {
    let mut actions = (0..127)
        .map(|index| id(&format!("action.{index}")))
        .collect::<Vec<_>>();
    let complete = learning_candidate_ids_v1(&actions).expect("maximum inclusive set");
    assert_eq!(complete.len(), 128);
    assert_eq!(
        complete
            .iter()
            .filter(|value| value.as_str() == "abstain")
            .count(),
        1
    );
    actions.push(id("action.127"));
    assert!(learning_candidate_ids_v1(&actions).is_err());
}
