use super::*;
use pretty_assertions::assert_eq;

#[test]
fn unresolved_signed_recovery_blocks_pending_and_direct_process_start()
-> Result<(), SupervisorError> {
    let (fleet, control, supervisor, now) = ready_paired_supervisor("signed-restart-quarantine")?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    let intent = crate::SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"unresolved-signed-grant"),
        fleet.first.to_string(),
        crate::H7H89ProductionTransition::Upgrade,
        "signed-restart-quarantine",
        "signed-target",
        0,
        record.lifecycle.generation,
        1,
        crate::SignedIntentStatus::RecoveryRequired,
    )
    .expect("signed intent");
    crate::signed_intent::write_intent(record.layout.run_root(), &intent).expect("persist intent");
    crate::restart_budget::claim_restart(
        record.layout.run_root(),
        3,
        Duration::from_secs(300),
        Duration::from_millis(250),
    )
    .expect("persist pending restart before process loss");
    control.set_exit(&fleet.first);
    drop(supervisor);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert!(recovered.production_recovery_required(&fleet.first)?);
    let before = crate::restart_journal::read_main_restart_budget(record.layout.run_root())?;
    assert_eq!(
        recovered.tick(now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(
        control.spawn_count(&fleet.first),
        1,
        "a durable restart is not permission to bypass signed quarantine"
    );
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(record.layout.run_root())?,
        before
    );
    let release = AgentRelease::try_from(fleet.registry.resolve_release(
        &fleet.first,
        &ReleaseId::parse("signed-restart-quarantine")?,
    )?)?;
    assert!(
        matches!(recovered.start_release(&fleet.first, release, now),
        Err(SupervisorError::SignedIntentRecoveryRequired(agent)) if agent == fleet.first)
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert!(
        !recovered
            .snapshot(&fleet.first)
            .expect("quarantined")
            .active
    );
    assert!(recovered.snapshot(&fleet.second).expect("peer").active);
    Ok(())
}
