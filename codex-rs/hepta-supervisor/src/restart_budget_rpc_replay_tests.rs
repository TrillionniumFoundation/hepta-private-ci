use super::*;
use crate::restart_budget::RESTART_BUDGET_SCHEMA_VERSION;
use crate::restart_budget::RestartBudgetState;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_main_restart_budget;
use pretty_assertions::assert_eq;

#[test]
fn recovered_expired_restart_rpc_preserves_pending_claim_until_replacement_is_healthy()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "pending-replay-v1")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered owner");
    let wall = unix_millis_now()?;
    let state = RestartBudgetState {
        schema_version: RESTART_BUDGET_SCHEMA_VERSION,
        window_started_unix_ms: wall - 3_600_000,
        attempts: config().restart_max_attempts,
        pending: true,
        next_eligible_unix_ms: wall - 1_000,
    };
    write_main_restart_budget(record.layout.run_root(), &state)?;
    let journal_path = record.layout.run_root().join(RESTART_JOURNAL_FILE);
    let before = std::fs::read(&journal_path)?;
    control.set_exit(&fleet.first);
    drop(supervisor);

    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let snapshot = recovered.snapshot(&fleet.first).expect("recovered owner");
    assert!(!snapshot.active);
    assert!(snapshot.restart_pending);
    assert_eq!(snapshot.restart_attempt, state.attempts);

    // Replaying an operator restart after daemon recovery is the same durable
    // attempt, even though its accounting window elapsed while it was pending.
    recovered.restart(&fleet.first, now)?;
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .expect("replayed owner")
            .restart_attempt,
        state.attempts,
    );
    assert_eq!(std::fs::read(&journal_path)?, before);
    assert_eq!(recovered.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 2);
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        Some(state.clone())
    );
    assert_eq!(recovered.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 2);

    control.set_healthy(&fleet.first);
    assert_eq!(recovered.tick(now), TickReport::default());
    let completed = read_main_restart_budget(record.layout.run_root())?.expect("completed attempt");
    assert!(!completed.pending);
    assert_eq!(completed.attempts, state.attempts);
    assert_eq!(
        completed.window_started_unix_ms,
        state.window_started_unix_ms
    );
    drop(recovered);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(recovered.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 2);
    assert!(
        !recovered
            .snapshot(&fleet.first)
            .expect("settled owner")
            .restart_pending
    );
    Ok(())
}
