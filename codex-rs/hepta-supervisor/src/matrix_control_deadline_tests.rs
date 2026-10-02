//! Failed companion control and probes cannot renew an admitted stop budget.

use super::*;
use crate::SupervisorEventKind;
use pretty_assertions::assert_eq;

fn counts(fixture: &Fixture) -> (usize, usize, usize) {
    let state = fixture.companion.lock().expect("state");
    (state.stops, state.kills, state.drops)
}

#[test]
fn failed_health_stop_escalates_at_original_deadline() -> Result<()> {
    for unhealthy in [false, true] {
        let mut fixture = Fixture::new()?;
        let now = Instant::now();
        fixture
            .slot
            .matrix
            .runtime
            .as_mut()
            .expect("companion")
            .phase = if unhealthy {
            MatrixRuntimePhase::Unhealthy { deadline: now }
        } else {
            MatrixRuntimePhase::AwaitingHealth { deadline: now }
        };
        fixture.companion.lock().expect("state").failure = Failure::Stop;
        assert!(fixture.tick(now).is_err());
        let limit = now + fixture.supervisor.config.stop_grace;
        assert!(
            fixture
                .tick(limit - std::time::Duration::from_nanos(1))
                .is_err()
        );
        fixture.tick(limit)?;
        assert_eq!(counts(&fixture), (2, 1, 0));
        assert!(matches!(
            fixture
                .slot
                .matrix
                .runtime
                .as_ref()
                .expect("companion")
                .phase,
            MatrixRuntimePhase::Killing
        ));
        assert!(
            !fixture
                .slot
                .events
                .items
                .iter()
                .any(|event| { event.kind == SupervisorEventKind::MatrixStopRequested })
        );
    }
    Ok(())
}

#[test]
fn due_companion_kill_precedes_failed_poll() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    fixture
        .slot
        .matrix
        .runtime
        .as_mut()
        .expect("companion")
        .phase = MatrixRuntimePhase::Stopping { deadline: now };
    fixture.companion.lock().expect("state").failure = Failure::Poll;
    assert!(fixture.tick(now).is_err());
    assert!(fixture.tick(now).is_err());
    fixture.assert_retained();
    assert_eq!(counts(&fixture).1, 1);
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::Killing
    ));
    Ok(())
}

#[test]
fn expired_companion_health_budget_survives_persistent_poll_failure() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    fixture
        .slot
        .matrix
        .runtime
        .as_mut()
        .expect("companion")
        .phase = MatrixRuntimePhase::AwaitingHealth { deadline: now };
    fixture.companion.lock().expect("state").failure = Failure::Poll;
    assert!(fixture.tick(now).is_err());
    assert!(
        fixture
            .tick(now + fixture.supervisor.config.stop_grace)
            .is_err()
    );
    fixture.assert_retained();
    assert_eq!(counts(&fixture), (1, 1, 0));
    Ok(())
}

#[test]
fn running_companion_poll_failure_starts_one_unhealthy_budget() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    let health_limit = now + fixture.supervisor.config.health_timeout;
    fixture.companion.lock().expect("state").failure = Failure::Poll;
    for instant in [
        now,
        health_limit,
        health_limit + fixture.supervisor.config.stop_grace,
    ] {
        assert!(fixture.tick(instant).is_err());
        fixture.assert_retained();
    }
    assert_eq!(counts(&fixture), (1, 1, 0));
    Ok(())
}

#[test]
fn running_companion_recovers_before_grace_and_next_fault_gets_new_budget() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    let first_limit = now + fixture.supervisor.config.health_timeout;
    fixture.companion.lock().expect("state").failure = Failure::Poll;
    assert!(fixture.tick(now).is_err());
    assert!(
        matches!(fixture.slot.matrix.runtime.as_ref().expect("companion").phase,
        MatrixRuntimePhase::Unhealthy { deadline } if deadline == first_limit)
    );
    {
        let mut state = fixture.companion.lock().expect("state");
        state.failure = Failure::None;
        state.observation = ProcessState::Running {
            healthy: true,
            drained: false,
        };
    }
    fixture.tick(now + fixture.supervisor.config.health_timeout / 2)?;
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::Running
    ));
    let second_failure = first_limit - std::time::Duration::from_nanos(1);
    fixture.companion.lock().expect("state").failure = Failure::Poll;
    assert!(fixture.tick(second_failure).is_err());
    assert!(fixture.tick(first_limit).is_err());
    assert_eq!(counts(&fixture), (0, 0, 0));
    let second_limit = second_failure + fixture.supervisor.config.health_timeout;
    assert!(
        matches!(fixture.slot.matrix.runtime.as_ref().expect("companion").phase,
        MatrixRuntimePhase::Unhealthy { deadline } if deadline == second_limit)
    );
    assert!(fixture.tick(second_limit).is_err());
    assert!(
        fixture
            .tick(second_limit + fixture.supervisor.config.stop_grace)
            .is_err()
    );
    assert_eq!(counts(&fixture), (1, 1, 0));
    Ok(())
}

#[test]
fn deferred_drain_retries_companion_stop_and_keeps_first_deadline() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    fixture.companion.lock().expect("state").observation = ProcessState::Running {
        healthy: true,
        drained: false,
    };
    fixture.companion.lock().expect("state").failure = Failure::Stop;
    assert!(
        fixture
            .supervisor
            .drain_slot(&fixture.agent, &mut fixture.slot, now)
            .is_err()
    );
    assert!(fixture.tick(now).is_err());
    fixture.tick(now + fixture.supervisor.config.stop_grace)?;
    fixture.assert_retained();
    assert_eq!(counts(&fixture), (2, 1, 0));
    let main_stops = fixture.main.lock().expect("main").stops;
    assert_eq!(main_stops, 0);
    assert!(fixture.slot.deferred_agent_action.is_some());
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::Killing
    ));
    Ok(())
}

#[test]
fn recovered_probe_health_does_not_cancel_pending_companion_stop() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    fixture
        .slot
        .matrix
        .runtime
        .as_mut()
        .expect("companion")
        .phase = MatrixRuntimePhase::Unhealthy { deadline: now };
    fixture.companion.lock().expect("state").failure = Failure::Stop;
    assert!(fixture.tick(now).is_err());
    {
        let mut state = fixture.companion.lock().expect("state");
        state.failure = Failure::None;
        state.observation = ProcessState::Running {
            healthy: true,
            drained: false,
        };
    }
    fixture.tick(now)?;
    let runtime = fixture.slot.matrix.runtime.as_ref().expect("companion");
    assert!(!runtime.healthy);
    assert!(matches!(runtime.phase, MatrixRuntimePhase::Stopping { .. }));
    fixture.tick(now + fixture.supervisor.config.stop_grace)?;
    assert_eq!(counts(&fixture).1, 1);
    Ok(())
}
