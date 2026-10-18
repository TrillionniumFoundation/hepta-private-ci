//! Discover pending original identity on cold boot without a caller Goal hint.
use super::*;

#[test]
fn cold_current_round_preserves_unknown_model_identity_quota_and_original_bytes() {
    let directory = directory();
    let path = directory.path().join("iteration.json");
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    assert_eq!(rounds.current_status().expect("empty"), None);
    let goal = StableId::new("goal.before.restart").expect("id");
    let permit = rounds
        .reserve(goal.clone(), &canonical, &envelope, 1000)
        .expect("reserve");
    let request = request(&permit);
    rounds
        .begin(&permit, &request, 1001)
        .expect("original model intent");
    let before = rounds
        .status(&goal, canonical.digest())
        .expect("exact facts");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("owner");
    journal
        .persist_rounds(rounds)
        .expect("actual durable reservation");
    drop(journal);
    let file_before = std::fs::read(&path).expect("original bytes");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("cold sole owner");
    let rounds = journal.rounds.as_ref().expect("original round");
    let cold = rounds
        .current_status()
        .expect("original facts")
        .expect("reserved round");
    assert_eq!(cold.status, before);
    assert!(cold.has_pending_model_requests);
    assert!(!cold.can_admit_next_round());
    assert_eq!(std::fs::read(&path).expect("read-only bytes"), file_before);
    let mut rounds = journal.rounds.clone().expect("same reservation");
    assert!(
        rounds
            .reserve(
                StableId::new("goal.after.restart").expect("id"),
                &canonical,
                &envelope,
                2000
            )
            .is_err()
    );
    rounds
        .complete(&permit, &request, &assessment(&request))
        .expect("actual terminal");
    journal.persist_rounds(rounds).expect("terminal fact");
    drop(journal);
    let file_before = std::fs::read(&path).expect("completed bytes");
    let journal = journal::IterationJournal::open(path.clone()).expect("cold terminal");
    let current = journal
        .rounds
        .as_ref()
        .expect("round")
        .current_status()
        .expect("facts")
        .expect("round");
    assert_eq!(current.status.round, permit);
    assert!(!current.has_pending_model_requests);
    assert!(
        !current.can_admit_next_round(),
        "G terminal alone does not retire the round"
    );
    assert_eq!(current.status.admitted_policy_candidates, 2);
    assert_eq!(std::fs::read(path).expect("unchanged"), file_before);
}
