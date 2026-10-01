use pretty_assertions::assert_eq;

use super::*;

#[test]
fn metadata_snapshot_preserves_all_control_fields_without_copying_diagnostic_rings()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "snapshot-v1")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    control.push_logs(&fleet.first, /*count*/ 8);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let full = supervisor
        .snapshot(&fleet.first)
        .ok_or_else(|| SupervisorError::UnknownAgent(fleet.first.clone()))?;
    assert!(!full.events.is_empty());
    assert_eq!(full.logs.len(), config().log_capacity);
    assert!(
        full.logs
            .iter()
            .all(|log| log.bytes.len() <= config().max_log_bytes)
    );
    let mut expected_metadata = full.clone();
    expected_metadata.events.clear();
    expected_metadata.logs.clear();
    assert_eq!(
        supervisor.metadata_snapshot(&fleet.first),
        Some(expected_metadata)
    );
    // Observation capture must neither drain nor alter the public buffers.
    assert_eq!(supervisor.snapshot(&fleet.first), Some(full));
    Ok(())
}
