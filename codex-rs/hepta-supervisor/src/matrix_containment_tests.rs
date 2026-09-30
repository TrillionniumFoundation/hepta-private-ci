//! Extend the existing filesystem/driver fixture without duplicating its tests.
//! These assertions are source regressions, not executed host qualifications.

use super::*;
use crate::lease::read_matrix_lease;
use pretty_assertions::assert_eq;

fn current_lease(fixture: &Fixture) -> MatrixProcessLease {
    let runtime = fixture.slot.matrix.runtime.as_ref().expect("owned Matrix");
    MatrixProcessLease {
        schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: fixture.agent.clone(),
        attached_agent_generation: runtime.attached_agent_generation,
        release_id: runtime.release_id.clone(),
        binding_revision: runtime.binding_revision,
        binding_digest: runtime.binding_digest.clone(),
        process_incarnation: runtime.process_incarnation.clone(),
        plane_epoch: runtime.plane_epoch,
        identity: runtime.identity.clone(),
    }
}

fn observe_exit(fixture: &Fixture) {
    fixture.companion.lock().expect("state").observation = ProcessState::Exited(ProcessExit {
        success: false,
        code: None,
    });
}

#[test]
fn main_emergency_kill_is_attempted_despite_companion_failure() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.companion.lock().expect("state").failure = Failure::Kill;
    assert!(fixture.supervisor.kill_slot(&fixture.agent, &mut fixture.slot).is_err());
    assert_eq!(fixture.main.lock().expect("main").kills, 1);
    assert_eq!(fixture.companion.lock().expect("companion").kills, 1);
    assert_eq!(fixture.main.lock().expect("main").drops, 0);
    assert_eq!(fixture.companion.lock().expect("companion").drops, 0);
    assert!(matches!(fixture.slot.runtime.as_ref().expect("main").phase, RuntimePhase::Killing));
    let companion = fixture.slot.matrix.runtime.as_ref().expect("companion");
    assert!(companion.fenced && !companion.healthy);
    assert!(!matches!(companion.phase, MatrixRuntimePhase::Killing));
    Ok(())
}

#[test]
fn failed_main_kill_does_not_skip_companion_containment() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.main.lock().expect("state").failure = Failure::Kill;
    assert!(fixture.supervisor.kill_slot(&fixture.agent, &mut fixture.slot).is_err());
    assert_eq!(fixture.main.lock().expect("main").kills, 1);
    assert_eq!(fixture.companion.lock().expect("companion").kills, 1);
    assert!(fixture.slot.pending_control.is_some());
    assert!(!fixture.slot.runtime.as_ref().expect("main").healthy);
    assert!(matches!(fixture.slot.matrix.runtime.as_ref().expect("companion").phase,
        MatrixRuntimePhase::Killing));
    Ok(())
}

#[test]
fn failed_registry_preparation_preserves_and_terminates_both_owned_handles() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let layout = fixture.registry.layout().agent(&fixture.agent);
    std::fs::rename(layout.agent_root().join("agent.toml"), layout.agent_root().join("agent.saved"))?;
    assert!(fixture.supervisor.kill_slot(&fixture.agent, &mut fixture.slot).is_err());
    assert_eq!(fixture.main.lock().expect("main").kills, 1);
    assert_eq!(fixture.companion.lock().expect("companion").kills, 1);
    assert!(fixture.slot.runtime.as_ref().expect("main").fenced);
    assert!(fixture.slot.matrix.runtime.as_ref().expect("companion").fenced);
    assert_eq!(fixture.main.lock().expect("main").drops, 0);
    assert_eq!(fixture.companion.lock().expect("companion").drops, 0);
    Ok(())
}

#[test]
fn failed_fenced_companion_signal_cannot_hide_exact_exit() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    let layout = fixture.registry.layout().agent(&fixture.agent);
    let lease = current_lease(&fixture);
    write_matrix_lease(layout.matrixd_process_lease(), &lease)?;
    let runtime = fixture.slot.matrix.runtime.as_mut().expect("companion");
    runtime.fenced = true;
    runtime.phase = MatrixRuntimePhase::Stopping { deadline: now };
    fixture.companion.lock().expect("state").failure = Failure::Kill;
    observe_exit(&fixture);
    fixture.tick(now)?;
    assert!(fixture.slot.matrix.runtime.is_none());
    assert!(read_matrix_lease(layout.matrixd_process_lease())?.is_none());
    assert_eq!(fixture.companion.lock().expect("state").drops, 1);
    assert_eq!(fixture.main.lock().expect("main").kills, 0);
    Ok(())
}

#[test]
fn fenced_companion_cannot_regain_health_from_a_later_probe() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    let runtime = fixture.slot.matrix.runtime.as_mut().expect("companion");
    runtime.fenced = true;
    runtime.phase = MatrixRuntimePhase::AwaitingHealth { deadline: now };
    {
        let mut state = fixture.companion.lock().expect("state");
        state.failure = Failure::Kill;
        state.observation = ProcessState::Running { healthy: true, drained: false };
    }
    assert!(fixture.tick(now).is_err());
    fixture.assert_retained();
    fixture.companion.lock().expect("state").failure = Failure::None;
    fixture.tick(now)?;
    let runtime = fixture.slot.matrix.runtime.as_ref().expect("companion");
    assert!(runtime.fenced && !runtime.healthy);
    assert!(matches!(runtime.phase, MatrixRuntimePhase::Killing));
    assert_eq!(fixture.companion.lock().expect("state").kills, 2);
    Ok(())
}

#[test]
fn failed_matrix_publication_retains_partial_lease_until_observed_exit() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    let layout = fixture.registry.layout().agent(&fixture.agent);
    let path = layout.matrixd_process_lease();
    let lease = current_lease(&fixture);
    write_matrix_lease(path, &lease)?;
    fixture.companion.lock().expect("state").failure = Failure::Kill;
    assert!(fixture.supervisor.publish_owned_matrix_launch(
        &fixture.agent, &mut fixture.slot, path, &lease, now,
    ).is_err());
    fixture.assert_retained();
    assert_eq!(read_matrix_lease(path)?, Some(lease));
    assert!(fixture.slot.matrix.runtime.as_ref().expect("companion").fenced);
    observe_exit(&fixture);
    fixture.tick(now)?;
    assert!(fixture.slot.matrix.runtime.is_none());
    assert!(read_matrix_lease(path)?.is_none());
    assert_eq!(fixture.companion.lock().expect("state").drops, 1);
    Ok(())
}

#[test]
fn unpublished_matrix_absence_is_reconciled_only_by_retained_launch_owner() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    let layout = fixture.registry.layout().agent(&fixture.agent);
    let path = layout.matrixd_process_lease();
    let lease = current_lease(&fixture);
    std::fs::create_dir(path)?;
    fixture.companion.lock().expect("state").failure = Failure::Kill;
    assert!(fixture.supervisor.publish_owned_matrix_launch(
        &fixture.agent, &mut fixture.slot, path, &lease, now,
    ).is_err());
    fixture.assert_retained();
    std::fs::remove_dir(path)?;
    observe_exit(&fixture);
    fixture.tick(now)?;
    assert!(fixture.slot.matrix.runtime.is_none());
    assert!(read_matrix_lease(path)?.is_none());
    assert_eq!(fixture.companion.lock().expect("state").drops, 1);
    Ok(())
}

#[test]
fn normal_missing_matrix_lease_retains_immutable_exit_without_repolling() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    observe_exit(&fixture);
    assert!(fixture.tick(now).is_err());
    assert!(fixture.slot.matrix.observed_exit.is_some());
    fixture.assert_retained();
    {
        let mut state = fixture.companion.lock().expect("state");
        state.failure = Failure::Poll;
        state.observation = ProcessState::Running { healthy: true, drained: false };
    }
    assert!(fixture.tick(now).is_err());
    assert!(fixture.slot.matrix.observed_exit.is_some());
    assert_eq!(fixture.companion.lock().expect("state").kills, 0);
    assert_eq!(fixture.companion.lock().expect("state").drops, 0);
    Ok(())
}
