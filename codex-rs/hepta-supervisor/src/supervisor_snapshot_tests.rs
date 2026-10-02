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

#[test]
fn exact_adopted_stale_companion_remains_observable_but_cannot_claim_health()
-> Result<(), SupervisorError> {
    let (fleet, control, supervisor, now) =
        ready_paired_supervisor("snapshot-quarantined-companion")?;
    let record = supervisor.record(&fleet.first)?;
    let path = record.layout.matrixd_process_lease();
    let mut lease = crate::lease::read_matrix_lease(path)?
        .ok_or_else(|| SupervisorError::Invalid("paired lease is missing".to_string()))?;
    lease.attached_agent_generation += 1;
    std::fs::write(
        path,
        serde_json::to_vec(&lease).map_err(|error| SupervisorError::Invalid(error.to_string()))?,
    )?;
    drop(supervisor);
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    // A proved owner on a stale attachment is a rejected serving admission,
    // not a failed acquisition. Its eligibility check returns Ok(None), and
    // successful containment does not add a recovery fault.
    assert_eq!(report, TickReport::default());
    recovered.with_slot(&fleet.first, |_supervisor, slot| {
        let runtime = slot.matrix.runtime.as_ref().ok_or_else(|| {
            SupervisorError::Invalid("recovered Matrix owner is missing".to_string())
        })?;
        assert_eq!(runtime.identity, lease.identity);
        assert_eq!(
            runtime.attached_agent_generation,
            lease.attached_agent_generation
        );
        assert!(runtime.fenced && !runtime.healthy);
        assert!(matches!(
            runtime.phase,
            crate::runtime::MatrixRuntimePhase::Killing
        ));
        Ok(())
    })?;
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 1));
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert_eq!(crate::lease::read_matrix_lease(path)?, Some(lease));
    let full = recovered
        .snapshot(&fleet.first)
        .ok_or_else(|| SupervisorError::UnknownAgent(fleet.first.clone()))?;
    assert!(
        full.events
            .iter()
            .any(|event| event.kind == SupervisorEventKind::MatrixKillRequested)
    );
    assert!(
        full.events
            .iter()
            .any(|event| event.kind == SupervisorEventKind::MatrixOrphanRejected)
    );
    assert!(
        full.events
            .iter()
            .any(|event| matches!(event.kind, SupervisorEventKind::MatrixDegraded(_)))
    );
    let snapshot = recovered
        .metadata_snapshot(&fleet.first)
        .ok_or_else(|| SupervisorError::UnknownAgent(fleet.first.clone()))?;
    assert!(snapshot.matrix.active);
    assert!(!snapshot.matrix.healthy);
    assert!(snapshot.matrix.degraded);
    assert!(snapshot.matrix.last_error.as_ref().is_some_and(|message| {
        !message.is_empty() && message.len() <= crate::runtime::MAX_FAULT_BYTES
    }));
    assert_ne!(
        snapshot.matrix.attached_agent_generation,
        snapshot.spawn_generation
    );
    let mut status = crate::daemon::status_from(
        &crate::SupervisorEpoch::new(),
        &recovered.record(&fleet.first)?,
        Some(snapshot),
    )?;
    crate::robrix_protocol::validate_agent_status(&status)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    // The exact retained handle is observable; it cannot serve on a stale binding.
    status.matrix.degraded = false;
    status.matrix.healthy = true;
    assert!(crate::robrix_protocol::validate_agent_status(&status).is_err());
    Ok(())
}

#[test]
fn real_paired_kill_and_retained_matrix_exit_observations_validate() -> Result<(), SupervisorError>
{
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor("snapshot-paired-kill")?;
    let epoch = crate::SupervisorEpoch::new();
    supervisor.kill(&fleet.first)?;
    for main_exited in [false, true] {
        if main_exited {
            control.set_exit(&fleet.first);
            assert_eq!(supervisor.tick(now), TickReport::default());
        }
        let record = supervisor.record(&fleet.first)?;
        let snapshot = supervisor
            .metadata_snapshot(&fleet.first)
            .ok_or_else(|| SupervisorError::UnknownAgent(fleet.first.clone()))?;
        assert!(snapshot.matrix.active);
        assert!(!snapshot.matrix.healthy);
        assert_eq!(snapshot.active, !main_exited);
        let status = crate::daemon::status_from(&epoch, &record, Some(snapshot))?;
        let response = crate::RobrixSupervisordResponse::try_from(crate::SupervisordResponse {
            schema_version: crate::SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id: 41,
            payload: crate::SupervisordPayload::Agent(status),
        })
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        response
            .validate_for(&crate::RobrixSupervisordRequest::new(
                /*request_id*/ 41,
                crate::RobrixSupervisordMethod::Snapshot {
                    agent_id: fleet.first.clone(),
                },
            ))
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    }
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let stopped = supervisor
        .metadata_snapshot(&fleet.first)
        .ok_or_else(|| SupervisorError::UnknownAgent(fleet.first.clone()))?;
    assert!(!stopped.active);
    assert!(!stopped.matrix.active);
    Ok(())
}

#[test]
fn live_registry_drift_masks_serving_without_erasing_owned_runtime_or_cas()
-> Result<(), SupervisorError> {
    let (fleet, _control, supervisor, _now) =
        ready_paired_supervisor("snapshot-live-registry-drift")?;
    let snapshot = supervisor
        .metadata_snapshot(&fleet.first)
        .ok_or_else(|| SupervisorError::UnknownAgent(fleet.first.clone()))?;
    assert!(snapshot.healthy && snapshot.matrix.healthy);
    let record = supervisor.record(&fleet.first)?;
    fleet.registry.compare_and_transition(
        &fleet.first,
        record.lifecycle.generation,
        AgentLifecycle::Draining,
    )?;
    let drifted = supervisor.record(&fleet.first)?;
    let epoch = crate::SupervisorEpoch::new();
    let status = crate::daemon::status_from(&epoch, &drifted, Some(snapshot.clone()))?;
    crate::robrix_protocol::validate_agent_status(&status)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    assert!(status.active && status.matrix.active);
    assert!(!status.healthy && !status.matrix.healthy);
    assert_eq!(status.runtime_generation, snapshot.runtime_generation);
    assert_eq!(
        status.matrix.attached_agent_generation,
        snapshot.matrix.attached_agent_generation
    );
    // A display mask must not remove raw eligibility facts from the CAS digest.
    let mut changed = snapshot.clone();
    changed.healthy = false;
    changed.matrix.healthy = false;
    let masked = crate::daemon::status_from(&epoch, &drifted, Some(changed))?;
    let mut same_display = status.clone();
    same_display.control_fence.state_digest = masked.control_fence.state_digest.clone();
    assert_eq!(same_display, masked);
    assert_ne!(
        status.control_fence.state_digest,
        masked.control_fence.state_digest
    );
    assert_eq!(supervisor.metadata_snapshot(&fleet.first), Some(snapshot));
    Ok(())
}
