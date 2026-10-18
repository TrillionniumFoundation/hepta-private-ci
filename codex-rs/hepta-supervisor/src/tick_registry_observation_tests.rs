use super::*;
use pretty_assertions::assert_eq;

fn retained_history(fleet: &TestFleet, agent: &AgentId) -> Result<(), SupervisorError> {
    let mut generation = fleet.registry.load_agent(agent)?.lifecycle.generation;
    for _ in 0..8 {
        for lifecycle in [
            AgentLifecycle::Starting,
            AgentLifecycle::Failed,
            AgentLifecycle::Stopped,
        ] {
            generation = fleet
                .registry
                .compare_and_transition(agent, generation, lifecycle)?
                .generation;
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
#[test]
fn one_tick_opens_each_agents_actual_retained_history_once() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let root = fleet.registry.layout().fleet_root();
    let third = register_agent(
        &fleet.registry,
        root,
        fleet._temp.path(),
        "01a153a4-3088-7e03-a56a-9b1964f75dd3",
        "workspace-c",
    )?;
    let fourth = register_agent(
        &fleet.registry,
        root,
        fleet._temp.path(),
        "01b153a4-3088-7e03-a56a-9b1964f75dd3",
        "workspace-d",
    )?;
    let agents = [fleet.first.clone(), fleet.second.clone(), third, fourth];
    for agent in &agents {
        retained_history(&fleet, agent)?;
    }
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, recovered) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    for agent in &agents {
        supervisor.start(agent, command()?, now)?;
        control.set_healthy(agent);
    }
    assert_eq!(supervisor.tick(now), TickReport::default());
    let mut opens = native_history_opens::HistoryOpens::new(&fleet.registry, &agents)?;
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
        let actual = opens.drain()?;
        // Generation zero, 24 historical transitions, Start and Running.
        let expected = agents.iter().cloned().map(|agent| (agent, 27)).collect();
        eprintln!("actual lifecycle file opens per maintenance pass: {actual:?}");
        assert_eq!(actual, expected);
    }
    Ok(())
}

#[test]
fn next_tick_rechecks_generation_and_never_reuses_a_ready_record() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    for agent in [&fleet.first, &fleet.second] {
        retained_history(&fleet, agent)?;
        supervisor.start(agent, command()?, now)?;
        control.set_healthy(agent);
    }
    assert_eq!(supervisor.tick(now), TickReport::default());
    let current = fleet.registry.load_agent(&fleet.first)?.lifecycle;
    fleet.registry.compare_and_transition(
        &fleet.first,
        current.generation,
        AgentLifecycle::Draining,
    )?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let first = supervisor
        .snapshot(&fleet.first)
        .expect("first remains owned");
    let second = supervisor
        .snapshot(&fleet.second)
        .expect("second remains owned");
    assert!(first.active && first.runtime_fenced && !first.healthy);
    assert!(second.active && !second.runtime_fenced && second.healthy);
    assert_eq!(control.counts(&fleet.first), (0, 0, 1));
    assert_eq!(control.counts(&fleet.second), (0, 0, 0));
    Ok(())
}

#[test]
fn control_after_tick_still_reads_the_current_registry_generation() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let current = fleet.registry.load_agent(&fleet.first)?.lifecycle;
    let changed = fleet.registry.compare_and_transition(
        &fleet.first,
        current.generation,
        AgentLifecycle::Draining,
    )?;
    assert!(matches!(
        supervisor.drain(&fleet.first, now),
        Err(SupervisorError::GenerationFence { runtime, registry, .. })
            if runtime == current.generation && registry == changed.generation
    ));
    assert_eq!(control.counts(&fleet.first), (0, 0, 1));
    Ok(())
}

#[test]
fn damaged_history_after_a_successful_tick_revokes_readiness() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    for agent in [&fleet.first, &fleet.second] {
        retained_history(&fleet, agent)?;
        supervisor.start(agent, command()?, now)?;
        control.set_healthy(agent);
    }
    assert_eq!(supervisor.tick(now), TickReport::default());
    let path = fleet
        .registry
        .layout()
        .agent(&fleet.first)
        .owner_run_root()
        .join("lifecycle-00000000000000000001.json");
    std::fs::write(path, b"damaged retained lifecycle\n")?;
    let report = supervisor.tick(now);
    assert_eq!(report.faults.len(), 2);
    for agent in [&fleet.first, &fleet.second] {
        let snapshot = supervisor
            .snapshot(agent)
            .expect("failed read retains ownership");
        assert!(snapshot.active && !snapshot.healthy);
        assert_eq!(control.counts(agent), (0, 0, 0));
    }
    Ok(())
}

#[cfg(target_os = "linux")]
#[path = "tick_registry_native_history_opens_tests.rs"]
mod native_history_opens;
