//! Real shared journals at deterministic wall-clock crash boundaries.
use super::*;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::write_restart_journal;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

#[test]
fn expired_failed_chain_preserves_charge_companion_and_replay_eligibility() {
    let directory = tempfile::tempdir().expect("directory");
    let companion = RestartBudgetJournal::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        ReleaseId::parse("same-release").expect("release"),
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(1_000),
        },
    )
    .expect("companion");
    write_restart_journal(directory.path(), &companion).expect("companion write");
    let first = claim_restart_at(
        directory.path(),
        /*maximum_attempts*/ 3,
        Duration::from_millis(100),
        Duration::from_millis(10),
        /*now_ms*/ 1_000,
    )
    .expect("original claim");
    let second = continue_failed_restart_at(
        directory.path(),
        /*maximum_attempts*/ 3,
        Duration::from_millis(10),
        first.window_started_unix_ms,
        first.attempt,
        /*now_ms*/ 100_000,
    )
    .expect("expired continuation");
    assert_eq!(
        read_restart_budget(directory.path()).expect("reopen"),
        Some(RestartBudgetState {
            schema_version: RESTART_BUDGET_SCHEMA_VERSION,
            window_started_unix_ms: 1_000,
            attempts: 2,
            pending: true,
            next_eligible_unix_ms: 100_020,
        })
    );
    assert_eq!(
        read_restart_journal(directory.path()).expect("companion"),
        Some(companion)
    );
    let path = directory.path().join(RESTART_JOURNAL_FILE);
    let committed = std::fs::read(&path).expect("committed bytes");
    let replay = continue_failed_restart_at(
        directory.path(),
        /*maximum_attempts*/ 3,
        Duration::from_millis(10),
        first.window_started_unix_ms,
        first.attempt,
        /*now_ms*/ 100_010,
    )
    .expect("claim-before-lineage crash replay");
    assert_eq!(
        (
            replay.attempt,
            replay.window_started_unix_ms,
            replay.backoff
        ),
        (2, 1_000, Duration::from_millis(10))
    );
    assert_eq!(std::fs::read(&path).expect("same bytes"), committed);
    let third = continue_failed_restart_at(
        directory.path(),
        /*maximum_attempts*/ 3,
        Duration::from_millis(10),
        second.window_started_unix_ms,
        second.attempt,
        /*now_ms*/ 200_000,
    )
    .expect("last paid attempt");
    for now in [300_000, 500_000] {
        assert!(matches!(
            continue_failed_restart_at(
                directory.path(),
                /*maximum_attempts*/ 3,
                Duration::from_millis(10),
                third.window_started_unix_ms,
                third.attempt,
                now
            ),
            Err(RestartBudgetError::Exhausted)
        ));
        let state = read_restart_budget(directory.path())
            .expect("reopen")
            .expect("state");
        assert_eq!(
            (state.window_started_unix_ms, state.attempts, state.pending),
            (1_000, 3, false)
        );
    }
}

#[test]
fn cancelled_pending_bit_crash_keeps_the_expired_original_operation() {
    let directory = tempfile::tempdir().expect("directory");
    let original = claim_restart_at(
        directory.path(),
        /*maximum_attempts*/ 3,
        Duration::from_millis(100),
        Duration::from_millis(10),
        /*now_ms*/ 1_000,
    )
    .expect("claim");
    cancel_restart(directory.path()).expect("old owner cancellation cut");
    let next = continue_failed_restart_at(
        directory.path(),
        /*maximum_attempts*/ 3,
        Duration::from_millis(10),
        original.window_started_unix_ms,
        original.attempt,
        /*now_ms*/ 100_000,
    )
    .expect("continue");
    assert_eq!((next.window_started_unix_ms, next.attempt), (1_000, 2));
    let bytes = std::fs::read(directory.path().join(RESTART_JOURNAL_FILE)).expect("bytes");
    for (window, attempt, now) in [(2_000, 1, 100_000), (1_000, 3, 100_000), (1_000, 1, 999)] {
        assert!(
            continue_failed_restart_at(
                directory.path(),
                /*maximum_attempts*/ 3,
                Duration::from_millis(10),
                window,
                attempt,
                now
            )
            .is_err()
        );
        assert_eq!(
            std::fs::read(directory.path().join(RESTART_JOURNAL_FILE)).expect("unchanged"),
            bytes
        );
    }
}
