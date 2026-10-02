//! A failed startup probe cannot grant an unlimited process lifetime.

use super::*;
use pretty_assertions::assert_eq;
use std::time::Duration;

#[test]
fn initial_main_health_timeout_survives_persistent_poll_failure() -> Result<()> {
    let mut fixture = startup_fixture()?;
    fixture.faults.lock().expect("faults").main_poll_failures = u32::MAX;
    for millis in [0, 10, 20, 40] {
        let report = fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(millis));
        fixture.assert_faults(&report, &["one-shot main poll failure"]);
        let snapshot = fixture
            .supervisor
            .snapshot(&fixture.fleet.first)
            .expect("retained main");
        assert!(snapshot.active && !snapshot.healthy);
        let counts = {
            let faults = fixture.faults.lock().expect("faults");
            (faults.main_stops, faults.main_kills)
        };
        assert_eq!(
            counts,
            (usize::from(millis >= 10), usize::from(millis >= 20))
        );
    }
    Ok(())
}

fn startup_fixture() -> Result<Fixture> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let faults = Arc::new(Mutex::new(Faults::default()));
    let driver = Driver {
        inner: control.driver(),
        faults: Arc::clone(&faults),
    };
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), driver, config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start(&fleet.first, command()?, now)?;
    Ok(Fixture {
        fleet,
        control,
        supervisor,
        faults,
        now,
    })
}

#[test]
fn initial_main_health_budget_contains_owner_through_unavailable_fleet() -> Result<()> {
    let mut fixture = startup_fixture()?;
    let manifest = fixture
        .fleet
        .registry
        .layout()
        .agent(&fixture.fleet.second)
        .agent_config()
        .to_path_buf();
    let bytes = std::fs::read(&manifest)?;
    std::fs::write(&manifest, b"invalid = [")?;
    for millis in [10, 20, 40] {
        let report = fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(millis));
        fixture.assert_faults(&report, &["invalid agent manifest"]);
        let counts = {
            let faults = fixture.faults.lock().expect("faults");
            (faults.main_stops, faults.main_kills)
        };
        assert_eq!(counts, (1, usize::from(millis >= 20)));
    }
    std::fs::write(&manifest, bytes)?;
    assert_eq!(
        fixture
            .fleet
            .registry
            .load_agent(&fixture.fleet.first)?
            .lifecycle
            .lifecycle,
        AgentLifecycle::Starting
    );
    assert!(
        !fixture
            .supervisor
            .snapshot(&fixture.fleet.first)
            .expect("owner")
            .healthy
    );
    Ok(())
}

#[test]
fn failed_initial_health_stop_cannot_be_cancelled_by_recovered_health() -> Result<()> {
    let mut fixture = startup_fixture()?;
    {
        let mut faults = fixture.faults.lock().expect("faults");
        faults.main_poll_failures = 1;
        faults.main_stop_failures = 1;
    }
    let report = fixture
        .supervisor
        .tick(fixture.now + Duration::from_millis(10));
    fixture.assert_faults(
        &report,
        &["one-shot main stop failure", "one-shot main poll failure"],
    );
    fixture.control.set_healthy(&fixture.fleet.first);
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(11)),
        TickReport::default()
    );
    assert!(
        !fixture
            .supervisor
            .snapshot(&fixture.fleet.first)
            .expect("owner")
            .healthy
    );
    assert_eq!(
        fixture
            .supervisor
            .tick(fixture.now + Duration::from_millis(20)),
        TickReport::default()
    );
    let counts = {
        let faults = fixture.faults.lock().expect("faults");
        (faults.main_stops, faults.main_kills)
    };
    assert_eq!(counts, (2, 1));
    assert_eq!(
        fixture
            .fleet
            .registry
            .load_agent(&fixture.fleet.first)?
            .lifecycle
            .lifecycle,
        AgentLifecycle::Failed
    );
    Ok(())
}
