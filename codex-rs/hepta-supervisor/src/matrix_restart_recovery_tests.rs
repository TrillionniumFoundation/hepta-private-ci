use super::*;
use pretty_assertions::assert_eq;

#[test]
fn matrix_budget_restore_preserves_main_pending_claim() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor(
        "matrix-main-isolation",
    )?;
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    crate::restart_budget::claim_restart(
        record.layout.run_root(),
        3,
        Duration::from_secs(300),
        Duration::from_millis(250),
    )
    .expect("independent main claim");
    let before = crate::restart_journal::read_main_restart_budget(record.layout.run_root())?;
    drop(supervisor);

    let (recovered, report) = Supervisor::recover(
        fleet.registry,
        control.driver(),
        config(),
        now,
    )?;
    assert_eq!(report, TickReport::default());
    let state = recovered.snapshot(&fleet.first).expect("recovered");
    assert_eq!(state.restart_attempt, 1);
    assert!(!state.restart_pending);
    assert_eq!(state.matrix.restart_attempt, 1);
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(record.layout.run_root())?,
        before
    );
    Ok(())
}
