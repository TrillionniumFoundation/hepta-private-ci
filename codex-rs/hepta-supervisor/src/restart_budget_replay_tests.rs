use super::*;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::write_restart_journal;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

fn budget_state() -> RestartBudgetState {
    let now = unix_ms().expect("wall clock");
    RestartBudgetState {
        schema_version: RESTART_BUDGET_SCHEMA_VERSION,
        window_started_unix_ms: now - 120_000,
        attempts: 3,
        pending: true,
        next_eligible_unix_ms: now - 60_000,
    }
}

fn journal_bytes(root: &Path) -> Vec<u8> {
    std::fs::read(root.join(RESTART_JOURNAL_FILE)).expect("durable restart record")
}

#[test]
fn expired_pending_restart_replays_without_rewriting_either_budget_domain() {
    let dir = tempfile::tempdir().expect("private owner");
    let state = budget_state();
    write_restart_budget(dir.path(), &state).expect("persist main intent");
    let companion = RestartBudgetJournal::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        ReleaseId::parse("release-a").expect("release"),
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(state.window_started_unix_ms),
        },
    )
    .expect("companion budget");
    write_restart_journal(dir.path(), &companion).expect("persist companion");
    let before = journal_bytes(dir.path());

    for _ in 0..3 {
        let restored = pending_restart(dir.path(), 3)
            .expect("recover intent")
            .expect("pending intent");
        let replay = claim_restart(
            dir.path(),
            3,
            Duration::from_secs(1),
            Duration::from_secs(30),
        )
        .expect("replay expired pending intent");
        assert_eq!(
            (replay.attempt, replay.backoff),
            (restored.attempt, restored.backoff),
        );
        assert_eq!(
            read_restart_budget(dir.path()).expect("read"),
            Some(state.clone())
        );
        assert_eq!(journal_bytes(dir.path()), before);
        assert_eq!(
            read_restart_journal(dir.path()).expect("companion read"),
            Some(companion.clone()),
        );
    }
}

#[test]
fn expired_pending_restart_preserves_future_eligibility_not_new_policy_backoff() {
    let dir = tempfile::tempdir().expect("private owner");
    let mut state = budget_state();
    state.next_eligible_unix_ms = unix_ms().expect("clock") + 60_000;
    write_restart_budget(dir.path(), &state).expect("persist intent");
    let before = journal_bytes(dir.path());
    let started = unix_ms().expect("clock before");
    let replay = claim_restart(
        dir.path(),
        3,
        Duration::from_secs(1),
        Duration::from_secs(3_600),
    )
    .expect("replay original deadline");
    let finished = unix_ms().expect("clock after");
    assert_eq!(replay.attempt, state.attempts);
    assert!(replay.backoff <= Duration::from_millis(state.next_eligible_unix_ms - started));
    assert!(
        replay.backoff
            >= Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(finished))
    );
    assert_eq!(journal_bytes(dir.path()), before);
}

#[test]
fn completed_expired_window_can_start_a_new_budget() {
    let dir = tempfile::tempdir().expect("private owner");
    let pending = budget_state();
    write_restart_budget(dir.path(), &pending).expect("persist pending");
    complete_restart(dir.path()).expect("observed completion");
    let claim = claim_restart(dir.path(), 3, Duration::from_secs(1), Duration::ZERO)
        .expect("new window after completion");
    assert_eq!((claim.attempt, claim.backoff), (1, Duration::ZERO));
    let stored = read_restart_budget(dir.path())
        .expect("read")
        .expect("state");
    assert!(stored.window_started_unix_ms > pending.window_started_unix_ms);
    assert!(stored.pending);
}

#[test]
fn pending_at_limit_is_replayable_but_completion_exhausts_current_window() {
    let dir = tempfile::tempdir().expect("private owner");
    let mut state = budget_state();
    state.window_started_unix_ms = unix_ms().expect("clock");
    state.next_eligible_unix_ms = state.window_started_unix_ms;
    write_restart_budget(dir.path(), &state).expect("persist");
    let window = Duration::from_secs(3_600);
    assert!(restart_available(dir.path(), 3, window).expect("pending availability"));
    let claim = claim_restart(dir.path(), 3, window, Duration::ZERO).expect("existing claim");
    assert_eq!((claim.attempt, claim.backoff), (3, Duration::ZERO));
    complete_restart(dir.path()).expect("complete");
    assert!(!restart_available(dir.path(), 3, window).expect("exhaustion"));
    assert!(matches!(
        claim_restart(dir.path(), 3, window, Duration::ZERO),
        Err(RestartBudgetError::Exhausted)
    ));
}

#[test]
fn claim_rejects_clock_rollback_without_rewriting_the_record() {
    let dir = tempfile::tempdir().expect("private owner");
    let mut state = budget_state();
    state.window_started_unix_ms = unix_ms().expect("clock") + 3_600_000;
    state.next_eligible_unix_ms = state.window_started_unix_ms + 1_000;
    write_restart_budget(dir.path(), &state).expect("persist");
    let before = journal_bytes(dir.path());
    assert!(matches!(
        claim_restart(dir.path(), 3, Duration::from_secs(60), Duration::ZERO),
        Err(RestartBudgetError::Invalid(_))
    ));
    assert_eq!(journal_bytes(dir.path()), before);
}

#[test]
fn recovery_rejects_clock_rollback_without_rewriting_pending_intent() {
    let dir = tempfile::tempdir().expect("private owner");
    let mut state = budget_state();
    state.window_started_unix_ms = unix_ms().expect("clock") + 3_600_000;
    state.next_eligible_unix_ms = state.window_started_unix_ms + 1_000;
    write_restart_budget(dir.path(), &state).expect("persist");
    let before = journal_bytes(dir.path());
    assert!(matches!(
        pending_restart(dir.path(), 3),
        Err(RestartBudgetError::Invalid(_))
    ));
    assert_eq!(journal_bytes(dir.path()), before);
}

#[test]
fn availability_rejects_clock_rollback_for_pending_and_completed_windows() {
    for pending in [false, true] {
        let dir = tempfile::tempdir().expect("private owner");
        let mut state = budget_state();
        state.pending = pending;
        state.attempts = 1;
        state.window_started_unix_ms = unix_ms().expect("clock") + 3_600_000;
        state.next_eligible_unix_ms = state.window_started_unix_ms + 1_000;
        write_restart_budget(dir.path(), &state).expect("persist");
        let before = journal_bytes(dir.path());
        assert!(matches!(
            restart_available(dir.path(), 3, Duration::from_secs(60)),
            Err(RestartBudgetError::Invalid(_))
        ));
        assert_eq!(journal_bytes(dir.path()), before);
    }
}

#[test]
fn zero_attempt_budget_is_unavailable_before_any_journal_exists() {
    let dir = tempfile::tempdir().expect("private owner");
    assert!(!restart_available(dir.path(), 0, Duration::from_secs(60)).expect("disabled budget"));
    assert!(matches!(
        claim_restart(dir.path(), 0, Duration::from_secs(60), Duration::ZERO),
        Err(RestartBudgetError::Exhausted)
    ));
    assert!(!dir.path().join(RESTART_JOURNAL_FILE).exists());
}
