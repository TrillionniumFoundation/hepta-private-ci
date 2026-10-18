use super::*;
use crate::restart_budget::claim_restart;
use crate::restart_budget::complete_restart;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_restart_journal;
use pretty_assertions::assert_eq;

#[test]
fn matrix_budget_survives_repeated_recovery_without_changing_main_budget()
-> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, mut now) =
        ready_paired_supervisor("matrix-budget-recovery")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered agent");
    claim_restart(
        record.layout.run_root(),
        config().restart_max_attempts,
        config().restart_window,
        config().restart_backoff_base,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    complete_restart(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let main_budget = read_main_restart_budget(record.layout.run_root())?;

    for (attempt, delay) in [
        (1, Duration::from_millis(250)),
        (2, Duration::from_millis(500)),
        (3, Duration::from_secs(1)),
    ] {
        control.set_matrix_exit(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .expect("queued snapshot")
                .matrix
                .restart_attempt,
            attempt
        );
        now += delay;
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_matrix_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            control.matrix_spawn_count(&fleet.first),
            attempt as usize + 1
        );
        drop(supervisor);

        let (recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        supervisor = recovered;
        assert_eq!(report, TickReport::default());
        let recovered_matrix = supervisor
            .snapshot(&fleet.first)
            .expect("recovered snapshot")
            .matrix;
        assert!(recovered_matrix.active);
        assert_eq!(recovered_matrix.restart_attempt, attempt);
        assert_eq!(
            read_main_restart_budget(record.layout.run_root())?,
            main_budget
        );
        assert_eq!(supervisor.tick(now), TickReport::default());
    }

    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("exhausted snapshot")
            .events
            .iter()
            .any(|event| matches!(
                event.kind,
                SupervisorEventKind::MatrixRestartBudgetExhausted { attempts: 3 }
            ))
    );
    drop(supervisor);
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let exhausted = supervisor
        .snapshot(&fleet.first)
        .expect("exhausted recovery")
        .matrix;
    assert!(exhausted.configured);
    assert!(exhausted.degraded);
    assert!(!exhausted.active);
    assert_eq!(exhausted.restart_attempt, 3);
    assert_eq!(
        supervisor.tick(now + Duration::from_secs(2)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 4);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(
        read_main_restart_budget(record.layout.run_root())?,
        main_budget
    );
    Ok(())
}

#[test]
fn missing_matrix_recovery_preserves_charges_and_backoff_before_spawning()
-> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor("matrix-pending-recovery")?;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    drop(supervisor);

    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(249)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(250)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 2);
    assert_eq!(
        supervisor
            .snapshot(&fleet.first)
            .expect("replacement")
            .matrix
            .restart_attempt,
        1
    );
    Ok(())
}

#[test]
fn companion_budget_for_another_agent_fails_before_process_adoption() -> Result<(), SupervisorError>
{
    let (fleet, control, supervisor, now) = ready_paired_supervisor("matrix-foreign-journal")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    write_restart_journal(
        record.layout.run_root(),
        &RestartBudgetJournal::new(
            fleet.second.clone(),
            ReleaseId::parse("matrix-foreign-journal")?,
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts: 2,
                window_started_unix_millis: Some(unix_millis_now()?),
            },
        )?,
    )?;
    drop(supervisor);
    assert!(matches!(
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now),
        Err(SupervisorError::CorruptLease(_))
    ));
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 0));
    Ok(())
}
