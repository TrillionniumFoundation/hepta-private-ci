use super::*;
use pretty_assertions::assert_eq;

#[test]
fn matrix_restart_budget_survives_repeated_supervisor_recovery() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, mut now) =
        ready_paired_supervisor("matrix-budget-recovery")?;
    let primary = supervisor
        .snapshot(&fleet.first)
        .expect("primary")
        .process_system_id;
    let peer = supervisor
        .snapshot(&fleet.second)
        .expect("peer")
        .matrix
        .process_system_id;
    for attempt in 1..=3 {
        now += Duration::from_millis(1);
        control.set_matrix_exit(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .expect("scheduled")
                .matrix
                .restart_attempt,
            attempt
        );
        now += Duration::from_millis(250 * (1 << (attempt - 1)));
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            control.matrix_spawn_count(&fleet.first),
            attempt as usize + 1
        );
        control.set_matrix_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        drop(supervisor);
        let (recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        supervisor = recovered;
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .expect("recovered")
                .matrix
                .restart_attempt,
            attempt
        );
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            supervisor
                .snapshot(&fleet.first)
                .expect("primary unchanged")
                .process_system_id,
            primary
        );
        assert_eq!(
            supervisor
                .snapshot(&fleet.second)
                .expect("peer unchanged")
                .matrix
                .process_system_id,
            peer
        );
    }
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("exhausted")
            .events
            .iter()
            .any(|event| {
                matches!(
                    event.kind,
                    SupervisorEventKind::MatrixRestartBudgetExhausted { attempts: 3 }
                )
            })
    );
    drop(supervisor);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(
        recovered.tick(now + Duration::from_secs(10)),
        TickReport::default()
    );
    let final_state = recovered.snapshot(&fleet.first).expect("final state");
    assert_eq!(final_state.matrix.restart_attempt, 3);
    assert!(!final_state.matrix.active);
    assert!(final_state.active);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 4);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.second), 1);
    Ok(())
}

#[test]
fn matrix_budget_restore_preserves_main_pending_claim() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor("matrix-main-isolation")?;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    crate::restart_budget::claim_restart(
        record.layout.owner_run_root(),
        3,
        Duration::from_secs(300),
        Duration::from_millis(250),
    )
    .expect("independent main claim");
    let before = crate::restart_journal::read_main_restart_budget(record.layout.owner_run_root())?;
    drop(supervisor);
    let (recovered, report) = Supervisor::recover(fleet.registry, control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let state = recovered.snapshot(&fleet.first).expect("recovered");
    assert_eq!(state.restart_attempt, 1);
    assert!(
        state.restart_pending,
        "a legacy budget-only claim retains its adopted predecessor; Matrix recovery cannot invent a replacement witness"
    );
    assert_eq!(state.matrix.restart_attempt, 1);
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(record.layout.owner_run_root())?,
        before
    );
    Ok(())
}

#[test]
fn matrix_recovery_preserves_backoff_before_start() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor("matrix-recovery-delay")?;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    drop(supervisor);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry, control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert_eq!(recovered.tick(now), TickReport::default());
    assert_eq!(
        recovered.tick(now + Duration::from_millis(249)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert_eq!(
        recovered.tick(now + Duration::from_millis(250)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 2);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    Ok(())
}
