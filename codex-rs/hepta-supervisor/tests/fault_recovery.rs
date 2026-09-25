#![cfg(test)]

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AdoptSpec;
use codex_hepta_supervisor::Adoption;
use codex_hepta_supervisor::ManagedProcess;
use codex_hepta_supervisor::ProcessDriver;
use codex_hepta_supervisor::ProcessDriverError;
use codex_hepta_supervisor::ProcessExit;
use codex_hepta_supervisor::ProcessIdentity;
use codex_hepta_supervisor::ProcessObservation;
use codex_hepta_supervisor::ProcessState;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::SpawnedProcess;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::SupervisorEventKind;
use codex_hepta_supervisor::TickReport;
use tempfile::TempDir;

#[path = "support/fault_process.rs"]
mod support;
use support::*;

#[test]
fn startup_crash_enters_durable_bounded_restart() -> Result<(), SupervisorError> {
    let mut fixture = fixture()?;
    fixture.control.crash(&fixture.agent_id);
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(1)),
        TickReport::default()
    );
    let snapshot = fixture
        .supervisor
        .snapshot(&fixture.agent_id)
        .expect("snapshot");
    assert!(snapshot.events.iter().any(|event| matches!(
        event.kind,
        SupervisorEventKind::AutomaticRestartQueued { attempt: 1 }
    )));
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(2)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent_id), 2);
    Ok(())
}

#[test]
fn startup_health_timeout_restarts_after_failed_child_exits() -> Result<(), SupervisorError> {
    let mut fixture = fixture()?;
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(11)),
        TickReport::default()
    );
    assert_eq!(fixture.control.counts(&fixture.agent_id), (0, 1, 0));
    fixture.control.crash(&fixture.agent_id);
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(12)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent_id), 2);
    Ok(())
}

#[test]
fn running_unhealthy_process_is_bounded_and_restarted() -> Result<(), SupervisorError> {
    let mut fixture = fixture()?;
    fixture.control.healthy(&fixture.agent_id);
    assert_eq!(fixture.supervisor.tick(fixture.now), TickReport::default());
    fixture.control.unhealthy(&fixture.agent_id);
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(1)),
        TickReport::default()
    );
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(12)),
        TickReport::default()
    );
    assert_eq!(fixture.control.counts(&fixture.agent_id), (0, 1, 0));
    fixture.control.crash(&fixture.agent_id);
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(13)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent_id), 2);
    Ok(())
}

#[test]
fn observation_errors_do_not_disable_drain_stop_kill_deadlines() -> Result<(), SupervisorError> {
    let mut fixture = fixture()?;
    fixture.control.healthy(&fixture.agent_id);
    assert_eq!(fixture.supervisor.tick(fixture.now), TickReport::default());
    fixture
        .supervisor
        .drain(&fixture.agent_id, fixture.now + Duration::from_millis(1))?;
    fixture.control.poll_error(&fixture.agent_id);

    let drain_fault = fixture
        .supervisor
        .tick(fixture.now + Duration::from_millis(12));
    assert_eq!(drain_fault.faults.len(), 1);
    assert_eq!(fixture.control.counts(&fixture.agent_id), (1, 1, 0));

    let stop_fault = fixture
        .supervisor
        .tick(fixture.now + Duration::from_millis(23));
    assert_eq!(stop_fault.faults.len(), 1);
    assert_eq!(fixture.control.counts(&fixture.agent_id), (1, 1, 1));
    Ok(())
}

#[test]
fn explicit_stop_cancels_automatic_restart_without_resurrection() -> Result<(), SupervisorError> {
    let mut fixture = fixture()?;
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(11)),
        TickReport::default()
    );
    fixture
        .supervisor
        .stop(&fixture.agent_id, fixture.now + Duration::from_millis(12))?;
    fixture.control.crash(&fixture.agent_id);
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(13)),
        TickReport::default()
    );
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent_id), 1);
    Ok(())
}

#[test]
fn explicit_kill_cancels_automatic_restart_without_resurrection() -> Result<(), SupervisorError> {
    let mut fixture = fixture()?;
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(11)),
        TickReport::default()
    );
    fixture.supervisor.kill(&fixture.agent_id)?;
    fixture.control.crash(&fixture.agent_id);
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(12)),
        TickReport::default()
    );
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent_id), 1);
    Ok(())
}

#[test]
fn repeated_pre_health_crashes_cannot_replay_one_restart_permit() -> Result<(), SupervisorError> {
    let mut f = fixture()?;
    let mut now = f.now;
    for attempt in 1..=3 {
        f.control.crash(&f.agent_id);
        assert_eq!(f.supervisor.tick(now), TickReport::default());
        now += Duration::from_millis(1 << (attempt - 1));
        assert_eq!(f.supervisor.tick(now), TickReport::default());
        assert_eq!(f.control.spawn_count(&f.agent_id), attempt + 1);
    }
    f.control.crash(&f.agent_id);
    assert_eq!(f.supervisor.tick(now).faults.len(), 1);
    assert!(!f.supervisor.snapshot(&f.agent_id).expect("snapshot").active);
    assert_eq!(
        f.supervisor.tick(now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(f.control.spawn_count(&f.agent_id), 4);
    Ok(())
}

#[test]
fn transient_unhealthy_observation_recovers_without_spawning() -> Result<(), SupervisorError> {
    let mut f = fixture()?;
    f.control.healthy(&f.agent_id);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    f.control.unhealthy(&f.agent_id);
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_millis(1)),
        TickReport::default()
    );
    f.control.healthy(&f.agent_id);
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_millis(2)),
        TickReport::default()
    );
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(f.control.counts(&f.agent_id), (0, 0, 0));
    assert_eq!(f.control.spawn_count(&f.agent_id), 1);
    Ok(())
}

#[test]
fn explicit_stop_and_kill_survive_daemon_recovery_without_resurrection()
-> Result<(), SupervisorError> {
    for kill in [false, true] {
        let mut f = fixture()?;
        assert_eq!(
            f.supervisor.tick(f.now + Duration::from_millis(11)),
            TickReport::default()
        );
        if kill {
            f.supervisor.kill(&f.agent_id)?;
        } else {
            f.supervisor
                .stop(&f.agent_id, f.now + Duration::from_millis(12))?;
        }
        f = reopen(f)?;
        f.control.crash(&f.agent_id);
        f = reopen(f)?;
        assert_eq!(
            f.supervisor.tick(f.now + Duration::from_secs(1)),
            TickReport::default()
        );
        assert_eq!(f.control.spawn_count(&f.agent_id), 1);
        assert!(!f.supervisor.snapshot(&f.agent_id).expect("snapshot").active);
    }
    Ok(())
}

#[test]
fn startup_timeout_pending_restart_survives_recovery_with_live_predecessor()
-> Result<(), SupervisorError> {
    let mut f = fixture()?;
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_millis(11)),
        TickReport::default()
    );
    f = reopen(f)?;
    f.control.crash(&f.agent_id);
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(f.control.spawn_count(&f.agent_id), 2);
    assert_eq!(durable_attempt(&f)?, 1);
    Ok(())
}

#[test]
fn missing_running_child_on_recovery_uses_a_new_bounded_claim() -> Result<(), SupervisorError> {
    let mut f = fixture()?;
    f.control.healthy(&f.agent_id);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    f.control.crash(&f.agent_id);
    f = reopen(f)?;
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_millis(10)),
        TickReport::default()
    );
    assert_eq!(f.control.spawn_count(&f.agent_id), 2);
    assert_eq!(durable_attempt(&f)?, 1);
    Ok(())
}

#[test]
fn corrupt_budget_cannot_leave_an_explicitly_killed_child_runnable() -> Result<(), SupervisorError>
{
    let mut f = fixture()?;
    f.control.healthy(&f.agent_id);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    let root = HeptaFleetRoot::parse(f._temp.path().join("fleet"))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    std::fs::write(
        root.layout()
            .agent(&f.agent_id)
            .run_root()
            .join("supervisor-restart-budget.json"),
        b"{",
    )?;
    assert!(f.supervisor.kill(&f.agent_id).is_err());
    let state = f.supervisor.snapshot(&f.agent_id).expect("fenced child");
    assert!(!state.healthy);
    assert!(state.active); // Retain the exact child until its exit is observed.
    assert_eq!(
        f.supervisor.tick(Instant::now() + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(f.control.counts(&f.agent_id).2, 1);
    assert_eq!(f.control.spawn_count(&f.agent_id), 1);
    Ok(())
}

#[test]
fn failed_explicit_kill_retains_handle_and_retries_at_the_control_deadline()
-> Result<(), SupervisorError> {
    let mut f = fixture()?;
    f.control.healthy(&f.agent_id);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    f.control.fail_next_kill(&f.agent_id);
    assert!(f.supervisor.kill(&f.agent_id).is_err());
    let state = f.supervisor.snapshot(&f.agent_id).expect("tracked child");
    assert!(state.active);
    assert!(!state.healthy);
    assert_eq!(
        f.supervisor.tick(Instant::now() + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(f.control.counts(&f.agent_id).2, 2);
    f.control.crash(&f.agent_id);
    assert_eq!(
        f.supervisor.tick(Instant::now() + Duration::from_secs(2)),
        TickReport::default()
    );
    assert!(!f.supervisor.snapshot(&f.agent_id).expect("stopped").active);
    assert_eq!(f.control.spawn_count(&f.agent_id), 1);
    Ok(())
}

#[test]
fn first_start_crash_before_health_recovers_release_identity() -> Result<(), SupervisorError> {
    let mut f = fixture()?;
    f.control.crash(&f.agent_id);
    f = reopen(f)?;
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_millis(2)),
        TickReport::default()
    );
    assert_eq!(f.control.spawn_count(&f.agent_id), 2);
    assert_eq!(durable_attempt(&f)?, 1);
    Ok(())
}

#[test]
fn lease_publication_and_kill_failure_retain_the_physical_child() -> Result<(), SupervisorError> {
    let mut f = fixture()?;
    f.supervisor.kill(&f.agent_id)?;
    f.control.crash(&f.agent_id);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    let root = HeptaFleetRoot::parse(f._temp.path().join("fleet"))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let registry = FleetRegistry::open_existing(root.clone())?;
    let release_id = codex_hepta_fleet::ReleaseId::parse("fault-recovery-agent")?;
    let release = codex_hepta_supervisor::AgentRelease::try_from(
        registry.resolve_release(&f.agent_id, &release_id)?,
    )?;
    f.control.fail_next_lease_publication();
    assert!(
        f.supervisor
            .start_release(&f.agent_id, release, f.now)
            .is_err()
    );
    let state = f
        .supervisor
        .snapshot(&f.agent_id)
        .expect("tracked uncertain child");
    // The public view cannot expose this uncertain child as healthy; cleanup
    // retains its handle and retries the failed kill below.
    assert!(state.active && !state.healthy);
    assert_eq!(f.control.counts(&f.agent_id).2, 1);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert_eq!(f.control.counts(&f.agent_id).2, 2);
    std::fs::remove_dir(
        root.layout()
            .agent(&f.agent_id)
            .run_root()
            .join("supervisor-process.json"),
    )?;
    f.control.crash(&f.agent_id);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert!(
        !f.supervisor
            .snapshot(&f.agent_id)
            .expect("exited child")
            .active
    );
    assert_eq!(f.control.spawn_count(&f.agent_id), 2);
    Ok(())
}

#[test]
fn first_start_finalized_exit_retains_retry_release_across_recovery() -> Result<(), SupervisorError>
{
    let mut f = fixture()?;
    f.control.crash(&f.agent_id);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    let before = f.supervisor.snapshot(&f.agent_id).expect("queued retry");
    assert!(!before.active && before.restart_pending());
    assert_eq!(durable_attempt(&f)?, 1);
    f = reopen(f)?;
    let after = f.supervisor.snapshot(&f.agent_id).expect("recovered retry");
    assert_eq!(
        after.active_release, before.active_release,
        "first-start failure lost the admitted release after its process lease was finalized"
    );
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(f.control.spawn_count(&f.agent_id), 2);
    assert_eq!(durable_attempt(&f)?, 1);
    Ok(())
}

#[test]
fn failed_adoption_stop_keeps_handle_for_deadline_escalation() -> Result<(), SupervisorError> {
    let mut f = fixture()?;
    assert_eq!(
        f.supervisor.tick(f.now + Duration::from_millis(11)),
        TickReport::default()
    );
    assert_eq!(f.control.counts(&f.agent_id).1, 1);
    f.control.fail_next_stop(&f.agent_id);
    let root = HeptaFleetRoot::parse(f._temp.path().join("fleet"))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let registry = FleetRegistry::open_existing(root)?;
    drop(f.supervisor);
    let (mut recovered, report) =
        Supervisor::recover(registry, f.control.driver(), config(), f.now)?;
    assert_eq!(report.faults.len(), 1);
    assert!(
        recovered
            .snapshot(&f.agent_id)
            .expect("adopted child")
            .active,
        "failed stop during adoption discarded the exact process handle"
    );
    assert_eq!(
        recovered.tick(f.now + Duration::from_secs(1)),
        TickReport::default()
    );
    assert_eq!(f.control.counts(&f.agent_id).2, 1);
    f.control.crash(&f.agent_id);
    assert_eq!(
        recovered.tick(f.now + Duration::from_secs(2)),
        TickReport::default()
    );
    assert_eq!(f.control.spawn_count(&f.agent_id), 2);
    Ok(())
}
