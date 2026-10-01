//! Emergency Kill reaches the main driver before any companion driver call.
//! The shared ordering witness records entry, including failed signal attempts.

use super::*;
use crate::control_intent;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::lease::write_lease;
use pretty_assertions::assert_eq;

fn publish_owned_leases(fixture: &Fixture) -> Result<(ProcessLease, MatrixProcessLease)> {
    let layout = fixture.registry.layout().agent(&fixture.agent);
    let main = fixture.slot.runtime.as_ref().expect("main owner");
    let main_lease = ProcessLease {
        schema_version: PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: fixture.agent.clone(),
        spawn_generation: main.spawn_generation,
        release_id: main.release_id.clone(),
        identity: main.identity.clone(),
    };
    let matrix = fixture.slot.matrix.runtime.as_ref().expect("Matrix owner");
    let matrix_lease = MatrixProcessLease {
        schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: fixture.agent.clone(),
        attached_agent_generation: matrix.attached_agent_generation,
        release_id: matrix.release_id.clone(),
        binding_revision: matrix.binding_revision,
        binding_digest: matrix.binding_digest.clone(),
        process_incarnation: matrix.process_incarnation.clone(),
        plane_epoch: matrix.plane_epoch,
        identity: matrix.identity.clone(),
    };
    write_lease(layout.run_root(), &main_lease)?;
    write_matrix_lease(layout.matrixd_process_lease(), &matrix_lease)?;
    Ok((main_lease, matrix_lease))
}

fn assert_owned_kill_order(
    fixture: &Fixture,
    expected_leases: &(ProcessLease, MatrixProcessLease),
) -> Result<()> {
    let main = fixture.main.lock().expect("main state");
    let matrix = fixture.companion.lock().expect("Matrix state");
    assert_eq!(
        *main.kill_order.lock().expect("kill order"),
        vec!["main", "matrix"]
    );
    assert_eq!(
        (main.kills, matrix.kills, main.drops, matrix.drops),
        (1, 1, 0, 0)
    );
    let layout = fixture.registry.layout().agent(&fixture.agent);
    assert_eq!(
        (
            read_lease(layout.run_root())?,
            read_matrix_lease(layout.matrixd_process_lease())?
        ),
        (
            Some(expected_leases.0.clone()),
            Some(expected_leases.1.clone())
        )
    );
    Ok(())
}

#[test]
fn emergency_kill_signals_main_before_matrix_and_retains_unresolved_control() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let leases = publish_owned_leases(&fixture)?;
    fixture
        .supervisor
        .kill_slot(&fixture.agent, &mut fixture.slot)?;
    assert_owned_kill_order(&fixture, &leases)?;
    assert!(control_intent::has_unresolved(
        fixture.registry.layout().agent(&fixture.agent).run_root()
    )?);
    assert!(matches!(
        fixture.slot.runtime.as_ref().expect("main").phase,
        RuntimePhase::Killing
    ));
    assert!(matches!(
        fixture.slot.matrix.runtime.as_ref().expect("Matrix").phase,
        MatrixRuntimePhase::Killing
    ));
    Ok(())
}

#[test]
fn emergency_kill_keeps_main_first_when_main_signal_fails() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let leases = publish_owned_leases(&fixture)?;
    fixture.main.lock().expect("main state").failure = Failure::Kill;
    assert!(
        fixture
            .supervisor
            .kill_slot(&fixture.agent, &mut fixture.slot)
            .is_err()
    );
    assert_owned_kill_order(&fixture, &leases)?;
    assert!(fixture.slot.pending_control.is_some());
    assert!(control_intent::has_unresolved(
        fixture.registry.layout().agent(&fixture.agent).run_root()
    )?);
    assert!(matches!(
        fixture.slot.matrix.runtime.as_ref().expect("Matrix").phase,
        MatrixRuntimePhase::Killing
    ));
    Ok(())
}

#[test]
fn emergency_kill_keeps_main_first_when_matrix_signal_fails() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let leases = publish_owned_leases(&fixture)?;
    fixture.companion.lock().expect("Matrix state").failure = Failure::Kill;
    assert!(
        fixture
            .supervisor
            .kill_slot(&fixture.agent, &mut fixture.slot)
            .is_err()
    );
    assert_owned_kill_order(&fixture, &leases)?;
    assert!(matches!(
        fixture.slot.runtime.as_ref().expect("main").phase,
        RuntimePhase::Killing
    ));
    let matrix = fixture.slot.matrix.runtime.as_ref().expect("Matrix");
    assert!(matrix.fenced && !matrix.healthy);
    assert!(!matches!(matrix.phase, MatrixRuntimePhase::Killing));
    Ok(())
}

#[test]
fn emergency_kill_keeps_main_first_when_registry_and_intent_preparation_fail() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let leases = publish_owned_leases(&fixture)?;
    let layout = fixture.registry.layout().agent(&fixture.agent);
    std::fs::rename(
        layout.agent_root().join("agent.toml"),
        layout.agent_root().join("agent.saved"),
    )?;
    assert!(
        fixture
            .supervisor
            .kill_slot(&fixture.agent, &mut fixture.slot)
            .is_err()
    );
    assert_owned_kill_order(&fixture, &leases)?;
    assert!(
        !layout
            .run_root()
            .join(control_intent::CONTROL_INTENT_FILE)
            .exists()
    );
    assert!(fixture.slot.runtime.as_ref().expect("main").fenced);
    assert!(fixture.slot.matrix.runtime.as_ref().expect("Matrix").fenced);
    Ok(())
}
