//! Filesystem-backed restart cancellation and deterministic clock regressions.
//! These exercise the production codec, not a second persistence implementation.

use super::*;
use std::time::Instant;

use crate::ProcessIdentity;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::write_restart_journal;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;

fn claim(root: &Path, now: u64) -> Result<RestartClaim, RestartBudgetError> {
    claim_restart_at(
        root,
        3,
        Duration::from_millis(100),
        Duration::from_millis(10),
        now,
    )
}

#[test]
fn pending_window_rollover_preserves_original_attempt_and_bytes() {
    let dir = tempfile::tempdir().expect("temp");
    assert_eq!(claim(dir.path(), 1_000).expect("claim").attempt, 1);
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let original = std::fs::read(&path).expect("original");
    for now in [1_100, 1_101, 10_000] {
        let replay = claim(dir.path(), now).expect("same pending claim");
        assert_eq!(replay.attempt, 1);
        assert_eq!(replay.backoff, Duration::ZERO);
        assert_eq!(std::fs::read(&path).expect("unchanged"), original);
    }
}

#[test]
fn recovery_uses_remaining_eligibility_without_restarting_backoff() {
    let dir = tempfile::tempdir().expect("temp");
    claim(dir.path(), 1_000).expect("claim");
    for (now, remaining) in [(1_000, 10), (1_007, 3), (1_010, 0), (2_000, 0)] {
        let recovered = pending_restart_at(dir.path(), 3, now)
            .expect("read")
            .expect("pending");
        assert_eq!(recovered.attempt, 1);
        assert_eq!(recovered.backoff, Duration::from_millis(remaining));
    }
}

#[test]
fn clock_rollback_rejects_claim_preflight_and_recovery_without_rewrite() {
    let dir = tempfile::tempdir().expect("temp");
    claim(dir.path(), 1_000).expect("claim");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let original = std::fs::read(&path).expect("original");
    assert!(claim(dir.path(), 999).is_err());
    assert!(restart_available_at(dir.path(), 3, Duration::from_millis(100), 999).is_err());
    assert!(pending_restart_at(dir.path(), 3, 999).is_err());
    assert_eq!(std::fs::read(&path).expect("unchanged"), original);
}

#[test]
fn cancellation_reopens_without_pending_and_preserves_consumed_budget() {
    let dir = tempfile::tempdir().expect("temp");
    claim(dir.path(), 1_000).expect("claim");
    let mut expected = read_restart_budget(dir.path())
        .expect("read")
        .expect("state");
    expected.pending = false;
    cancel_restart(dir.path()).expect("cancel");
    assert_eq!(
        read_restart_budget(dir.path()).expect("reopen"),
        Some(expected)
    );
    assert!(
        pending_restart_at(dir.path(), 3, 1_005)
            .expect("recover")
            .is_none()
    );
    assert_eq!(
        claim(dir.path(), 1_005)
            .expect("new explicit claim")
            .attempt,
        2
    );
}

#[test]
fn cancellation_does_not_replenish_an_exhausted_window() {
    let dir = tempfile::tempdir().expect("temp");
    for (now, attempt) in [(1_000, 1), (1_001, 2), (1_002, 3)] {
        assert_eq!(claim(dir.path(), now).expect("claim").attempt, attempt);
        cancel_restart(dir.path()).expect("cancel");
    }
    assert!(matches!(
        claim(dir.path(), 1_003),
        Err(RestartBudgetError::Exhausted)
    ));
    assert!(
        !restart_available_at(dir.path(), 3, Duration::from_millis(100), 1_003).expect("preflight")
    );
}

#[test]
fn a_terminal_window_can_replenish_for_a_new_claim() {
    let dir = tempfile::tempdir().expect("temp");
    claim(dir.path(), 1_000).expect("claim");
    cancel_restart(dir.path()).expect("cancel");
    let next = claim(dir.path(), 1_100).expect("new window");
    assert_eq!(next.attempt, 1);
    assert_eq!(next.backoff, Duration::from_millis(10));
    let state = read_restart_budget(dir.path())
        .expect("read")
        .expect("state");
    assert_eq!(state.window_started_unix_ms, 1_100);
    assert_eq!(state.next_eligible_unix_ms, 1_110);
}

#[test]
fn missing_or_already_cancelled_state_is_an_idempotent_noop() {
    let dir = tempfile::tempdir().expect("temp");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    cancel_restart(dir.path()).expect("absent cancel");
    assert!(!path.exists());
    claim(dir.path(), 1_000).expect("claim");
    cancel_restart(dir.path()).expect("cancel");
    let bytes = std::fs::read(&path).expect("read");
    #[cfg(unix)]
    let inode = {
        use std::os::unix::fs::MetadataExt;
        std::fs::metadata(&path).expect("metadata").ino()
    };
    cancel_restart(dir.path()).expect("replay");
    assert_eq!(std::fs::read(&path).expect("read"), bytes);
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        assert_eq!(std::fs::metadata(&path).expect("metadata").ino(), inode);
    }
}

#[test]
fn cancellation_preserves_companion_state_and_companion_write_preserves_cancellation() {
    let dir = tempfile::tempdir().expect("temp");
    let companion = RestartBudgetJournal::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        ReleaseId::parse("release-a").expect("release"),
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(1_000),
        },
    )
    .expect("companion");
    write_restart_journal(dir.path(), &companion).expect("write companion");
    claim(dir.path(), 1_000).expect("claim");
    cancel_restart(dir.path()).expect("cancel");
    assert_eq!(
        read_restart_journal(dir.path()).expect("companion"),
        Some(companion.clone())
    );
    let cancelled = read_restart_budget(dir.path()).expect("main");
    write_restart_journal(dir.path(), &companion).expect("companion replay");
    assert_eq!(
        read_restart_budget(dir.path()).expect("main preserved"),
        cancelled
    );
    assert!(
        pending_restart_at(dir.path(), 3, 1_010)
            .expect("reopen")
            .is_none()
    );
}

#[test]
fn corrupt_state_cannot_be_erased_by_cancellation() {
    let dir = tempfile::tempdir().expect("temp");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let corrupt = b"{\"schema_version\":2,\"main\":";
    std::fs::write(&path, corrupt).expect("corrupt fixture");
    assert!(cancel_restart(dir.path()).is_err());
    assert_eq!(std::fs::read(&path).expect("not erased"), corrupt);
}

#[test]
fn invalid_policy_does_not_publish_a_restart_claim() {
    let dir = tempfile::tempdir().expect("temp");
    for (maximum, window, backoff) in [
        (0, Duration::from_secs(1), Duration::from_millis(1)),
        (3, Duration::ZERO, Duration::from_millis(1)),
        (3, Duration::from_secs(1), Duration::ZERO),
    ] {
        assert!(claim_restart_at(dir.path(), maximum, window, backoff, 1_000).is_err());
    }
    assert!(!dir.path().join(RESTART_JOURNAL_FILE).exists());
}

fn process(system_id: u64, incarnation: &str) -> ProcessIdentity {
    ProcessIdentity::new(system_id, incarnation).expect("process identity")
}

fn bound_claim(
    root: &Path,
    predecessor: Option<(u64, &ProcessIdentity)>,
    now: u64,
) -> Result<RestartClaim, RestartBudgetError> {
    claim_restart_bound_at(
        root,
        3,
        Duration::from_secs(300),
        Duration::from_millis(10),
        &ReleaseId::parse("release-a").expect("release"),
        predecessor,
        Duration::from_millis(30),
        Duration::from_millis(20),
        now,
    )
}

#[test]
fn replacement_requires_exact_predecessor_exit_and_exact_healthy_identity() {
    let dir = tempfile::tempdir().expect("temp");
    let predecessor = process(41, "predecessor");
    let replacement = process(42, "replacement");
    let foreign = process(43, "foreign");
    bound_claim(dir.path(), Some((7, &predecessor)), 1_000).expect("claim");

    assert!(
        bind_restart_replacement_at(
            dir.path(),
            &ReleaseId::parse("release-a").expect("release"),
            8,
            &replacement,
            1_001,
        )
        .is_err()
    );
    assert_eq!(
        observe_restart_process_exit_at(
            dir.path(),
            &ReleaseId::parse("release-a").expect("release"),
            7,
            &predecessor,
            1_010,
        )
        .expect("predecessor exit"),
        RestartExitObservation::Predecessor
    );
    assert!(
        bind_restart_replacement_at(
            dir.path(),
            &ReleaseId::parse("release-a").expect("release"),
            8,
            &replacement,
            1_011,
        )
        .expect("bind replacement")
    );
    assert!(complete_restart_for_replacement_at(dir.path(), 9, &foreign, 1_012).is_err());
    assert!(
        complete_restart_for_replacement_at(dir.path(), 8, &replacement, 1_012)
            .expect("complete exact replacement")
    );
    let state = read_restart_budget(dir.path())
        .expect("read")
        .expect("state");
    assert!(!state.pending);
    assert_eq!(state.terminal, Some(RestartTerminal::Completed));
    assert_eq!(state.replacement_healthy_unix_ms, Some(1_012));
}

#[test]
fn replacement_exit_is_failure_not_restart_completion() {
    let dir = tempfile::tempdir().expect("temp");
    let predecessor = process(51, "predecessor");
    let replacement = process(52, "replacement");
    bound_claim(dir.path(), Some((10, &predecessor)), 2_000).expect("claim");
    observe_restart_process_exit_at(
        dir.path(),
        &ReleaseId::parse("release-a").expect("release"),
        10,
        &predecessor,
        2_010,
    )
    .expect("predecessor exit");
    bind_restart_replacement_at(
        dir.path(),
        &ReleaseId::parse("release-a").expect("release"),
        11,
        &replacement,
        2_011,
    )
    .expect("bind replacement");
    assert_eq!(
        observe_restart_process_exit_at(
            dir.path(),
            &ReleaseId::parse("release-a").expect("release"),
            11,
            &replacement,
            2_012,
        )
        .expect("replacement exit"),
        RestartExitObservation::Replacement
    );
    let state = read_restart_budget(dir.path())
        .expect("read")
        .expect("state");
    assert!(!state.pending);
    assert_eq!(state.terminal, Some(RestartTerminal::Failed));
    assert!(state.replacement_healthy_unix_ms.is_none());
}

#[test]
fn recovered_predecessor_control_never_refreshes_original_deadlines() {
    let dir = tempfile::tempdir().expect("temp");
    let predecessor = process(61, "predecessor");
    bound_claim(dir.path(), Some((20, &predecessor)), 3_000).expect("claim");
    let origin = Instant::now();

    match recover_predecessor_control_at(dir.path(), 20, &predecessor, origin, 3_010)
        .expect("drain")
        .expect("control")
    {
        PendingControl::Drain { deadline, .. } => {
            assert_eq!(
                deadline.checked_duration_since(origin),
                Some(Duration::from_millis(20))
            );
        }
        _ => panic!("expected Drain"),
    }
    match recover_predecessor_control_at(dir.path(), 20, &predecessor, origin, 3_040)
        .expect("stop")
        .expect("control")
    {
        PendingControl::Stop { deadline, .. } => {
            assert_eq!(
                deadline.checked_duration_since(origin),
                Some(Duration::from_millis(10))
            );
        }
        _ => panic!("expected Stop"),
    }
    assert!(matches!(
        recover_predecessor_control_at(dir.path(), 20, &predecessor, origin, 3_050)
            .expect("kill")
            .expect("control"),
        PendingControl::Kill {
            spawn_generation: 20
        }
    ));
}

#[test]
fn absent_predecessor_claim_can_bind_only_one_fresh_replacement() {
    let dir = tempfile::tempdir().expect("temp");
    let replacement = process(71, "replacement");
    let other = process(72, "other");
    bound_claim(dir.path(), None, 4_000).expect("claim without predecessor");
    bind_restart_replacement_at(
        dir.path(),
        &ReleaseId::parse("release-a").expect("release"),
        30,
        &replacement,
        4_001,
    )
    .expect("first replacement");
    assert!(
        bind_restart_replacement_at(
            dir.path(),
            &ReleaseId::parse("release-a").expect("release"),
            31,
            &other,
            4_002,
        )
        .is_err()
    );
}
