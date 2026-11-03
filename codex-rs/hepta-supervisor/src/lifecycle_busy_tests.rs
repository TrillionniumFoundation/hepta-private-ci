use pretty_assertions::assert_eq;

use super::*;
use crate::release_transaction::ReleaseTransactionPhase;

enum StartFault {
    Spawn,
    Lease,
}

#[derive(Default)]
struct StartBoundary {
    fault: Option<StartFault>,
    entry: Option<codex_hepta_fleet::FleetEntryGuard>,
    attempts: usize,
}

#[derive(Clone, Default)]
struct BusyStartControl(Arc<Mutex<StartBoundary>>);

impl BusyStartControl {
    fn driver(&self, registry: FleetRegistry, control: &FakeControl) -> BusyStartDriver {
        BusyStartDriver { inner: control.driver(), registry, control: self.clone() }
    }

    fn arm(&self, fault: StartFault) -> Result<(), SupervisorError> {
        self.0.lock().map_err(|error| SupervisorError::Invalid(error.to_string()))?.fault = Some(fault);
        Ok(())
    }

    fn release(&self) -> Result<(), SupervisorError> {
        drop(self.0.lock().map_err(|error| SupervisorError::Invalid(error.to_string()))?.entry.take());
        Ok(())
    }

    fn attempts(&self) -> Result<usize, SupervisorError> {
        Ok(self.0.lock().map_err(|error| SupervisorError::Invalid(error.to_string()))?.attempts)
    }
}

struct BusyStartDriver {
    inner: FakeDriver,
    registry: FleetRegistry,
    control: BusyStartControl,
}

impl ProcessDriver for BusyStartDriver {
    type Process = FakeProcess;

    fn spawn(&mut self, spec: &SpawnSpec) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let fault = {
            let mut boundary = self.control.0.lock().map_err(|error| ProcessDriverError::new(error.to_string()))?;
            boundary.attempts += 1;
            boundary.fault.take()
        };
        let Some(fault) = fault else {
            return self.inner.spawn(spec);
        };
        // Starting is already durable. Keep a real effect-entry fence alive
        // across this injected failure, so only its cleanup CAS becomes Busy.
        let entry = self.registry.try_enter_generation(&spec.agent_id, spec.generation)
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        self.control.0.lock().map_err(|error| ProcessDriverError::new(error.to_string()))?.entry = Some(entry);
        match fault {
            StartFault::Spawn => Err(ProcessDriverError::new("injected boundary spawn failure")),
            StartFault::Lease => {
                std::fs::create_dir(spec.run_root.join("supervisor-process.json"))?;
                self.inner.spawn(spec)
            }
        }
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.inner.adopt(spec)
    }
}

#[test]
fn lifecycle_busy_preserves_health_and_the_original_restart_intent() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) = Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    let starting = fleet.registry.try_enter_generation(&fleet.first, /*expected_generation*/ 1)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(fleet.registry.load_agent(&fleet.first)?.lifecycle.generation, 1);
    drop(starting);
    assert_eq!(supervisor.tick(now), TickReport::default());

    let entering = fleet.registry.try_enter_generation(&fleet.first, /*expected_generation*/ 2)?;
    assert!(supervisor.drain(&fleet.first, now).unwrap_err().is_lifecycle_busy());
    assert!(supervisor.stop(&fleet.first, now).unwrap_err().is_lifecycle_busy());
    assert!(supervisor.kill(&fleet.first).unwrap_err().is_lifecycle_busy());
    supervisor.restart(&fleet.first, now)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let pending = supervisor.snapshot(&fleet.first).expect("original slot");
    assert_eq!((pending.restart_pending, pending.restart_attempt, control.counts(&fleet.first)), (true, 1, (0, 0, 0)));
    drop(entering);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!((fleet.registry.load_agent(&fleet.first)?.lifecycle.lifecycle, control.counts(&fleet.first)),
        (AgentLifecycle::Draining, (1, 0, 0)));
    Ok(())
}

#[test]
fn lifecycle_busy_keeps_prepared_upgrade_instead_of_rolling_back() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) = Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start_release(&fleet.first, admitted_release(&fleet, &fleet.first, "busy-v1")?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let entering = fleet.registry.try_enter_generation(&fleet.first, /*expected_generation*/ 2)?;
    supervisor.upgrade(&fleet.first, admitted_release(&fleet, &fleet.first, "busy-v2")?, now)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert_eq!((slot.release_transaction.as_ref().expect("original transaction").phase, control.counts(&fleet.first)),
        (ReleaseTransactionPhase::Prepared, (0, 0, 0)));
    assert!(slot.release_change.is_some());
    drop(entering);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert_eq!((slot.release_transaction.as_ref().expect("original transaction").phase, control.counts(&fleet.first)),
        (ReleaseTransactionPhase::Draining, (1, 0, 0)));
    assert!(slot.events.items.iter().all(|event| !matches!(event.kind,
        SupervisorEventKind::AutomaticRollbackQueued { .. }
        | SupervisorEventKind::AutomaticRollbackFailed { .. }
        | SupervisorEventKind::DriverFault(_))));
    Ok(())
}

#[test]
fn lifecycle_busy_during_exit_keeps_the_original_process_lease() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) = Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let run_root = fleet.registry.layout().agent(&fleet.first).run_root().to_path_buf();
    let original = crate::lease::read_lease(&run_root)?;
    let entering = fleet.registry.try_enter_generation(&fleet.first, /*expected_generation*/ 2)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(crate::lease::read_lease(&run_root)?, original);
    assert!(supervisor.snapshot(&fleet.first).expect("retained process").active);
    // Model a one-shot exit source (including waitpid after adoption). Its
    // next poll would report Running; the supervisor must not poll again.
    control.update(&fleet.first, |state| state.exit = None);
    drop(entering);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(crate::lease::read_lease(&run_root)?.is_none());
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert!(supervisor.snapshot(&fleet.first).expect("completed exit").events.iter().any(|event| {
        matches!(event.kind, SupervisorEventKind::Exited(ProcessExit { success: true, code: Some(0) }))
    }));
    Ok(())
}

#[test]
fn exhausted_restart_decision_survives_busy_exit_once() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let mut limits = config();
    limits.restart_max_attempts = 1;
    limits.event_capacity = 64;
    let mut now = Instant::now();
    let (mut supervisor, _) = Supervisor::recover(fleet.registry.clone(), control.driver(), limits, now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    // Spend the single allowed attempt through the original crash/restart
    // path, then observe one further exit while Fleet publication is busy.
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    now += Duration::from_millis(10);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 2);
    let record = fleet.registry.load_agent(&fleet.first)?;
    let original_lease = crate::lease::read_lease(record.layout.run_root())?;
    let entering = fleet.registry.try_enter_generation(&fleet.first, record.lifecycle.generation)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.update(&fleet.first, |state| state.exit = None);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(crate::lease::read_lease(record.layout.run_root())?, original_lease);
    let pending = supervisor.snapshot(&fleet.first).expect("pending exact exit");
    assert_eq!(pending.events.iter().filter(|event| matches!(event.kind,
        SupervisorEventKind::AutomaticRestartBudgetExhausted { attempts: 1 })).count(), 1);

    drop(entering);
    let completed = supervisor.tick(now);
    assert_eq!(completed.faults.len(), 1);
    assert!(completed.faults[0].message.contains("exhausted its restart budget"));
    assert!(crate::lease::read_lease(record.layout.run_root())?.is_none());
    assert_eq!(supervisor.tick(now + Duration::from_secs(10)), TickReport::default());
    let terminal = supervisor.snapshot(&fleet.first).expect("finalized original exit");
    assert!(!terminal.active);
    assert_eq!(terminal.events.iter().filter(|event| matches!(event.kind,
        SupervisorEventKind::AutomaticRestartBudgetExhausted { attempts: 1 })).count(), 1);
    assert_eq!(terminal.events.iter().filter(|event| matches!(event.kind,
        SupervisorEventKind::Exited(ProcessExit { success: true, code: Some(0) }))).count(), 2);
    assert_eq!(control.spawn_count(&fleet.first), 2);
    Ok(())
}

#[test]
fn lifecycle_busy_after_spawn_failure_retries_only_original_cleanup() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let boundary = BusyStartControl::default();
    let now = Instant::now();
    let (mut supervisor, _) = Supervisor::recover(
        fleet.registry.clone(), boundary.driver(fleet.registry.clone(), &control), config(), now,
    )?;
    boundary.arm(StartFault::Spawn)?;
    assert!(supervisor.start(&fleet.first, command()?, now).unwrap_err().is_lifecycle_busy());
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert!(matches!(&slot.deferred_start_failure.as_ref().expect("original failure").error,
        SupervisorError::Driver { message, .. } if message == "injected boundary spawn failure"));
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
    }
    assert_eq!((fleet.registry.load_agent(&fleet.first)?.lifecycle.lifecycle,
        boundary.attempts()?, control.spawn_count(&fleet.first)), (AgentLifecycle::Starting, 1, 0));
    boundary.release()?;
    let completed = supervisor.tick(now);
    assert_eq!(completed.faults.len(), 1);
    assert!(completed.faults[0].message.contains("injected boundary spawn failure"));
    assert_eq!(fleet.registry.load_agent(&fleet.first)?.lifecycle.lifecycle, AgentLifecycle::Failed);
    assert!(supervisor.slots.get(&fleet.first).expect("original slot").deferred_start_failure.is_none());
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!((boundary.attempts()?, control.spawn_count(&fleet.first)), (1, 0));
    Ok(())
}

#[test]
fn lifecycle_busy_after_lease_failure_never_repeats_kill_or_invents_exit() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let boundary = BusyStartControl::default();
    let now = Instant::now();
    let (mut supervisor, _) = Supervisor::recover(
        fleet.registry.clone(), boundary.driver(fleet.registry.clone(), &control), config(), now,
    )?;
    boundary.arm(StartFault::Lease)?;
    assert!(supervisor.start(&fleet.first, command()?, now).unwrap_err().is_lifecycle_busy());
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert!(matches!(&slot.deferred_start_failure.as_ref().expect("original failure").error,
        SupervisorError::UnresolvedLease(agent_id) if agent_id == &fleet.first));
    assert!(slot.runtime.is_none());
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
    }
    assert_eq!((boundary.attempts()?, control.spawn_count(&fleet.first), control.counts(&fleet.first)),
        (1, 1, (0, 0, 1)));
    control.update(&fleet.first, |state| assert!(state.exit.is_none()));
    let run_root = fleet.registry.layout().agent(&fleet.first).run_root().to_path_buf();
    std::fs::remove_dir(run_root.join("supervisor-process.json"))?;
    boundary.release()?;
    let completed = supervisor.tick(now);
    assert_eq!(completed.faults.len(), 1);
    assert!(completed.faults[0].message.contains("unresolved process lease"));
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(crate::lease::read_lease(&run_root)?.is_none());
    assert_eq!((fleet.registry.load_agent(&fleet.first)?.lifecycle.lifecycle,
        boundary.attempts()?, control.counts(&fleet.first)), (AgentLifecycle::Failed, 1, (0, 0, 1)));
    assert!(supervisor.snapshot(&fleet.first).expect("original slot").events.iter()
        .all(|event| !matches!(event.kind, SupervisorEventKind::Exited(_))));
    Ok(())
}

#[test]
fn lifecycle_busy_after_restart_spawn_failure_keeps_same_pending_attempt() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let boundary = BusyStartControl::default();
    let mut now = Instant::now();
    let mut limits = config();
    limits.event_capacity = 64;
    let maximum_attempts = limits.restart_max_attempts;
    let (mut supervisor, _) = Supervisor::recover(
        fleet.registry.clone(), boundary.driver(fleet.registry.clone(), &control), limits, now,
    )?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let run_root = fleet.registry.layout().agent(&fleet.first).run_root().to_path_buf();
    let pending = crate::restart_budget::pending_restart(&run_root, maximum_attempts)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?.expect("original pending claim");
    boundary.arm(StartFault::Spawn)?;
    now += Duration::from_millis(10);
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
    }
    let retained = crate::restart_budget::pending_restart(&run_root, maximum_attempts)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?.expect("retained pending claim");
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert_eq!((slot.restart_pending, slot.restart_attempt, retained.attempt, boundary.attempts()?),
        (true, pending.attempt, pending.attempt, 2));
    assert!(slot.deferred_start_failure.is_some());
    boundary.release()?;
    let completed = supervisor.tick(now);
    assert_eq!(completed.faults.len(), 1);
    assert!(completed.faults[0].message.contains("injected boundary spawn failure"));
    assert!(crate::restart_budget::pending_restart(&run_root, maximum_attempts)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?.is_none());
    assert!(!supervisor.snapshot(&fleet.first).expect("original slot").restart_pending);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!((boundary.attempts()?, control.spawn_count(&fleet.first)), (2, 1));
    assert_eq!(supervisor.snapshot(&fleet.first).expect("original slot").events.iter()
        .filter(|event| matches!(event.kind, SupervisorEventKind::AutomaticRestartQueued { .. })).count(), 1);
    Ok(())
}

#[test]
fn lifecycle_busy_prepared_rollback_never_requeues_or_rewrites_journal() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let mut limits = config();
    limits.event_capacity = 64;
    let (mut supervisor, _) = Supervisor::recover(fleet.registry.clone(), control.driver(), limits, now)?;
    // Resume at the existing prepared-rollback boundary: the source/target
    // bindings and durable phase already exist; no rollback child exists yet.
    let origin = admitted_release(&fleet, &fleet.first, "retry-origin")?;
    let target = admitted_release(&fleet, &fleet.first, "retry-target")?;
    let starting = fleet.registry.compare_and_transition(&fleet.first, /*expected_generation*/ 0, AgentLifecycle::Starting)?;
    let failed = fleet.registry.compare_and_transition(&fleet.first, starting.generation, AgentLifecycle::Failed)?;
    let transaction = crate::release_transaction::DurableReleaseTransaction::new(
        fleet.first.to_string(), crate::release_transaction::ReleaseTransactionKind::Upgrade,
        origin.identity(), target.identity(), /*rollback_predecessor*/ None,
        Some(fleet.registry.resolve_release_binding(&fleet.first, origin.release_id())?),
        Some(fleet.registry.resolve_release_binding(&fleet.first, target.release_id())?),
        /*expected_release_state_generation*/ 0,
        failed.generation,
    ).and_then(|transaction| transaction.with_phase(ReleaseTransactionPhase::AutomaticRollbackStarting))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let run_root = fleet.registry.layout().agent(&fleet.first).run_root().to_path_buf();
    crate::release_transaction::write_release_transaction(&run_root, &transaction)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let slot = supervisor.slots.get_mut(&fleet.first).expect("original slot");
    slot.release_transaction = Some(transaction);
    slot.release_change = Some(crate::runtime::ReleaseChange {
        origin, target, prior_previous: None,
        phase: crate::runtime::ReleaseChangePhase::AutomaticRollbackStarting, explicit_rollback: false,
    });
    let journal_path = run_root.join(crate::release_transaction::RELEASE_TRANSACTION_FILE);
    let journal = std::fs::OpenOptions::new().write(true).open(&journal_path)?;
    journal.set_times(std::fs::FileTimes::new().set_modified(
        std::time::SystemTime::UNIX_EPOCH + Duration::from_secs(946_684_800),
    ))?;
    drop(journal);
    let original_bytes = std::fs::read(&journal_path)?;
    let original_modified = std::fs::metadata(&journal_path)?.modified()?;
    let entry = fleet.registry.try_enter_generation(&fleet.first, failed.generation)?;
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!((std::fs::read(&journal_path)?, std::fs::metadata(&journal_path)?.modified()?),
            (original_bytes.clone(), original_modified));
    }
    assert_eq!(control.spawn_count(&fleet.first), 0);
    assert!(supervisor.snapshot(&fleet.first).expect("original slot").events.iter()
        .all(|event| !matches!(event.kind, SupervisorEventKind::AutomaticRollbackQueued { .. })));
    drop(entry);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!((std::fs::read(&journal_path)?, std::fs::metadata(&journal_path)?.modified()?),
        (original_bytes, original_modified));
    Ok(())
}

#[test]
fn lifecycle_busy_target_failure_finishes_cleanup_before_one_rollback() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let boundary = BusyStartControl::default();
    let now = Instant::now();
    let mut limits = config();
    limits.event_capacity = 64;
    let (mut supervisor, _) = Supervisor::recover(
        fleet.registry.clone(), boundary.driver(fleet.registry.clone(), &control), limits, now,
    )?;
    let origin = admitted_release(&fleet, &fleet.first, "target-fail-origin")?;
    let target = admitted_release(&fleet, &fleet.first, "target-fail-target")?;
    supervisor.start_release(&fleet.first, origin, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    supervisor.upgrade(&fleet.first, target, now)?;
    control.set_exit(&fleet.first);
    boundary.arm(StartFault::Spawn)?;
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
    }
    assert_eq!((boundary.attempts()?, control.spawn_count(&fleet.first)), (2, 1));
    boundary.release()?;
    let completed = supervisor.tick(now);
    assert_eq!(completed.faults.len(), 1);
    assert!(completed.faults[0].message.contains("injected boundary spawn failure"));
    assert_eq!((boundary.attempts()?, control.spawn_count(&fleet.first)), (3, 2));
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert_eq!(slot.release_transaction.as_ref().expect("original transaction").phase,
        ReleaseTransactionPhase::RolledBack);
    assert_eq!(slot.events.items.iter()
        .filter(|event| matches!(event.kind, SupervisorEventKind::AutomaticRollbackQueued { .. })).count(), 1);
    assert!(slot.deferred_start_failure.is_none());
    Ok(())
}

#[test]
fn lifecycle_busy_rollback_failure_retains_cleanup_without_requeue_or_respawn() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let boundary = BusyStartControl::default();
    let now = Instant::now();
    let mut limits = config();
    limits.event_capacity = 64;
    let (mut supervisor, _) = Supervisor::recover(
        fleet.registry.clone(), boundary.driver(fleet.registry.clone(), &control), limits, now,
    )?;
    let origin = admitted_release(&fleet, &fleet.first, "rollback-fail-origin")?;
    let target = admitted_release(&fleet, &fleet.first, "rollback-fail-target")?;
    supervisor.start_release(&fleet.first, origin, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    supervisor.upgrade(&fleet.first, target, now)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    // The target exits before readiness. The automatic rollback is queued
    // once, then its failed spawn cannot publish Failed until the guard drops.
    control.set_exit(&fleet.first);
    boundary.arm(StartFault::Spawn)?;
    assert_eq!(supervisor.tick(now), TickReport::default());
    let run_root = fleet.registry.layout().agent(&fleet.first).run_root().to_path_buf();
    let journal_path = run_root.join(crate::release_transaction::RELEASE_TRANSACTION_FILE);
    let before = std::fs::read(&journal_path)?;
    for _ in 0..3 {
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(std::fs::read(&journal_path)?, before);
    }
    assert_eq!((boundary.attempts()?, control.spawn_count(&fleet.first)), (3, 2));
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert!(slot.deferred_start_failure.is_some());
    assert_eq!(slot.events.items.iter()
        .filter(|event| matches!(event.kind, SupervisorEventKind::AutomaticRollbackQueued { .. })).count(), 1);
    boundary.release()?;
    let completed = supervisor.tick(now);
    assert_eq!(completed.faults.len(), 1);
    assert!(completed.faults[0].message.contains("injected boundary spawn failure"));
    let slot = supervisor.slots.get(&fleet.first).expect("original slot");
    assert_eq!(slot.release_transaction.as_ref().expect("original transaction").phase,
        ReleaseTransactionPhase::RecoveryRequired);
    assert!(slot.release_change.is_none());
    assert!(slot.deferred_start_failure.is_none());
    assert_eq!(slot.events.items.iter()
        .filter(|event| matches!(event.kind, SupervisorEventKind::AutomaticRollbackFailed { .. })).count(), 1);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!((boundary.attempts()?, control.spawn_count(&fleet.first)), (3, 2));
    Ok(())
}
