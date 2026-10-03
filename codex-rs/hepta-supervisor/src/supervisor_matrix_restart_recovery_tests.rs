use super::*;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_restart_journal;
use crate::restart_policy::RESTART_ATTEMPT_BUDGET;
use crate::restart_policy::RESTART_BACKOFF_MIN;
use crate::restart_policy::RESTART_RECOVERY_WINDOW;
use pretty_assertions::assert_eq;

fn paired_release(fleet: &TestFleet) -> Result<AgentRelease, SupervisorError> {
    let release_id = ReleaseId::parse("matrix-budget-recovery-v1")?;
    let source = fleet.write_release_source()?;
    fleet.registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    fleet.registry.allow_release(&fleet.first, &release_id)?;
    write_matrix_binding(&fleet.registry, &fleet.first, /*revision*/ 1)?;
    AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)
}

#[test]
fn companion_budget_survives_supervisor_recovery_without_resetting_main()
-> Result<(), Box<dyn std::error::Error>> {
    for rollback in [false, true] {
        let fleet = TestFleet::new()?;
        let release = paired_release(&fleet)?;
        let release_id = release.release_id().clone();
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut supervisor, _) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        supervisor.start_release(&fleet.first, release, now)?;
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_matrix_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        let record = fleet.registry.load()?.agents[&fleet.first].clone();
        let run_root = record.layout.run_root();
        crate::restart_budget::claim_restart(
            run_root,
            RESTART_ATTEMPT_BUDGET,
            RESTART_RECOVERY_WINDOW,
            RESTART_BACKOFF_MIN,
        )?;
        crate::restart_budget::complete_restart(run_root)?;
        let main = read_main_restart_budget(run_root)?;
        let wall = unix_millis_now()?;
        let matrix = DurableRestartWindow {
            attempts: if rollback { 1 } else { RESTART_ATTEMPT_BUDGET },
            window_started_unix_millis: Some(wall + if rollback { 10_000 } else { 0 }),
        };
        write_restart_journal(
            run_root,
            &RestartBudgetJournal::new(
                fleet.first.clone(),
                release_id,
                DurableRestartWindow::empty(),
                matrix,
            )?,
        )?;
        drop(supervisor);
        let (recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        let slot = &recovered.slots[&fleet.first];
        assert_eq!(slot.matrix.restart_attempt, RESTART_ATTEMPT_BUDGET);
        assert!(slot.matrix.restart_exhausted);
        assert_eq!(read_main_restart_budget(run_root)?, main);
        let retained = read_restart_journal(run_root)?.ok_or("missing companion journal")?;
        assert_eq!(retained.matrix.attempts, RESTART_ATTEMPT_BUDGET);
        let recovered_wall = unix_millis_now()?;
        assert!(
            retained
                .matrix
                .window_started_unix_millis
                .is_some_and(|started| started <= recovered_wall)
        );
    }
    Ok(())
}

#[test]
fn recovery_rejects_companion_journal_bound_to_another_agent()
-> Result<(), Box<dyn std::error::Error>> {
    let fleet = TestFleet::new()?;
    let release = paired_release(&fleet)?;
    let record = fleet.registry.load()?.agents[&fleet.first].clone();
    write_restart_journal(
        record.layout.run_root(),
        &RestartBudgetJournal::new(
            fleet.second.clone(),
            release.release_id().clone(),
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts: 1,
                window_started_unix_millis: Some(unix_millis_now()?),
            },
        )?,
    )?;
    let result = Supervisor::recover(
        fleet.registry,
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    );
    assert!(matches!(result, Err(SupervisorError::CorruptLease(_))));
    Ok(())
}
