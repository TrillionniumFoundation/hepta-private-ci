use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::*;
use crate::SupervisordMutation;

#[cfg(unix)]
#[test]
fn emergency_kill_preserves_the_ambiguous_request_and_both_are_queryable() {
    let dir = tempfile::tempdir().expect("owner directory");
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("Agent id");
    let state = "00".repeat(32);
    let first = crate::prepare_mutation(
        dir.path(),
        /*request_id*/ 7,
        &agent,
        "epoch",
        SupervisordMutation::Start,
        &state,
        /*intent_sequence*/ 1,
    )
    .expect("start intent");
    crate::mark_mutation_effect_started(dir.path(), &first.idempotency_key)
        .expect("start effect boundary");
    let ambiguous = crate::mark_mutation_ambiguous(
        dir.path(),
        &first.idempotency_key,
        Some(&state),
        "driver outcome unknown",
    )
    .expect("ambiguous start");

    let emergency = admission_root(dir.path(), SupervisordMutation::Kill)
        .expect("independent emergency journal");
    let kill = crate::prepare_mutation(
        &emergency,
        /*request_id*/ 8,
        &agent,
        "epoch",
        SupervisordMutation::Kill,
        &state,
        /*intent_sequence*/ 2,
    )
    .expect("emergency kill remains admissible");
    assert_eq!(
        lookup(dir.path(), /*request_id*/ 7)
            .expect("query old request")
            .expect("preserved start")
            .status,
        ambiguous,
    );
    assert_eq!(
        lookup(dir.path(), /*request_id*/ 8)
            .expect("query kill")
            .expect("kill intent")
            .status,
        kill,
    );
}

#[cfg(unix)]
#[test]
fn emergency_admission_cannot_follow_a_replaced_owner_directory() {
    let dir = tempfile::tempdir().expect("owner directory");
    let peer = tempfile::tempdir().expect("other owner");
    std::os::unix::fs::symlink(peer.path(), dir.path().join(EMERGENCY_DIRECTORY))
        .expect("replace journal directory");
    assert!(matches!(
        admission_root(dir.path(), SupervisordMutation::Kill),
        Err(MutationJournalError::Invalid(_)),
    ));
    assert!(matches!(
        lookup(dir.path(), /*request_id*/ 1),
        Err(MutationJournalError::Invalid(_)),
    ));
    assert_eq!(
        std::fs::read_dir(peer.path())
            .expect("peer directory")
            .count(),
        0
    );
}
