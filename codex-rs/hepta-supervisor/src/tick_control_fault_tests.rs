//! Concurrent diagnostics over existing fake processes and real owner files.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use pretty_assertions::assert_eq;

use super::FakeControl;
use super::FakeDriver;
use super::FakeProcess;
use super::FakeRole;
use super::TestFleet;
use super::command;
use super::config;
use super::write_matrix_binding;
use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentRelease;
use crate::ManagedProcess;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessObservation;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::TickReport;

#[derive(Default)]
struct Faults {
    main_kill_failures: u32,
    main_poll_failures: u32,
    matrix_kill_failures: u32,
    main_kills: usize,
    matrix_kills: usize,
}

struct Driver {
    inner: FakeDriver,
    faults: Arc<Mutex<Faults>>,
}

struct Process {
    inner: FakeProcess,
    role: FakeRole,
    faults: Arc<Mutex<Faults>>,
}

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        let spawned = self.inner.spawn(spec)?;
        Ok(SpawnedProcess {
            identity: spawned.identity,
            process: Process {
                inner: spawned.process,
                role: FakeRole::Agentd,
                faults: Arc::clone(&self.faults),
            },
        })
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        let spawned = self.inner.spawn_matrixd(spec)?;
        Ok(SpawnedProcess {
            identity: spawned.identity,
            process: Process {
                inner: spawned.process,
                role: FakeRole::Matrixd,
                faults: Arc::clone(&self.faults),
            },
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected adoption in fresh-owner fixture",
        ))
    }
}

impl ManagedProcess for Process {
    fn poll(&mut self, max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let mut faults = self.faults.lock().expect("fault state");
        if self.role == FakeRole::Agentd && faults.main_poll_failures > 0 {
            faults.main_poll_failures -= 1;
            return Err(ProcessDriverError::new("one-shot main poll failure"));
        }
        drop(faults);
        self.inner.poll(max_logs)
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.request_drain()
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.request_stop()
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut faults = self.faults.lock().expect("fault state");
        let remaining = match self.role {
            FakeRole::Agentd => {
                faults.main_kills += 1;
                &mut faults.main_kill_failures
            }
            FakeRole::Matrixd => {
                faults.matrix_kills += 1;
                &mut faults.matrix_kill_failures
            }
        };
        if *remaining > 0 {
            *remaining -= 1;
            return Err(ProcessDriverError::new(match self.role {
                FakeRole::Agentd => "one-shot main kill failure",
                FakeRole::Matrixd => "one-shot Matrix kill failure",
            }));
        }
        drop(faults);
        self.inner.kill()
    }
}

enum ProcessSet {
    MainOnly,
    WithMatrix,
}

struct Fixture {
    fleet: TestFleet,
    control: FakeControl,
    supervisor: Supervisor<Driver>,
    faults: Arc<Mutex<Faults>>,
    now: Instant,
}

impl Fixture {
    fn new(processes: ProcessSet) -> Result<Self> {
        let fleet = TestFleet::new()?;
        let control = FakeControl::default();
        let faults = Arc::new(Mutex::new(Faults::default()));
        let driver = Driver {
            inner: control.driver(),
            faults: Arc::clone(&faults),
        };
        let now = Instant::now();
        let mut policy = config();
        policy.event_capacity = 64;
        let (mut supervisor, report) =
            Supervisor::recover(fleet.registry.clone(), driver, policy, now)?;
        assert_eq!(report, TickReport::default());
        match processes {
            ProcessSet::MainOnly => supervisor.start(&fleet.first, command()?, now)?,
            ProcessSet::WithMatrix => {
                let source = fleet.write_release_source()?;
                let release = ReleaseId::parse("tick-control-cuts")?;
                fleet.registry.install_release_bundle(
                    release.clone(),
                    &source,
                    Vec::new(),
                    Some(&source),
                    Vec::new(),
                )?;
                fleet.registry.allow_release(&fleet.first, &release)?;
                write_matrix_binding(&fleet.registry, &fleet.first, /*revision*/ 1)?;
                supervisor.start_release(
                    &fleet.first,
                    AgentRelease::try_from(
                        fleet.registry.resolve_release(&fleet.first, &release)?,
                    )?,
                    now,
                )?;
            }
        }
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        if let ProcessSet::WithMatrix = processes {
            control.set_matrix_healthy(&fleet.first);
            assert_eq!(supervisor.tick(now), TickReport::default());
        }
        Ok(Self {
            fleet,
            control,
            supervisor,
            faults,
            now,
        })
    }

    fn fence(&self) -> Result<()> {
        let record = self.supervisor.record(&self.fleet.first)?;
        self.fleet.registry.compare_and_transition(
            &self.fleet.first,
            record.lifecycle.generation,
            AgentLifecycle::Draining,
        )?;
        Ok(())
    }

    fn assert_faults(&self, report: &TickReport, expected: &[&str]) {
        assert_eq!(report.faults.len(), expected.len());
        assert!(
            report
                .faults
                .iter()
                .all(|fault| fault.agent_id == self.fleet.first
                    && fault.message.len() <= crate::runtime::MAX_FAULT_BYTES)
        );
        for message in expected {
            assert_eq!(
                report
                    .faults
                    .iter()
                    .filter(|fault| fault.message.contains(message))
                    .count(),
                1,
                "{message}"
            );
        }
        assert_eq!(self.control.spawn_count(&self.fleet.first), 1);
    }
}

#[test]
fn main_signal_error_survives_poll_failure_without_duplicate_report() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.faults.lock().expect("faults").main_kill_failures = 2;
    assert!(f.supervisor.kill(&f.fleet.first).is_err());
    f.faults.lock().expect("faults").main_poll_failures = 1;
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &["one-shot main kill failure", "one-shot main poll failure"],
    );
    let retained = f.supervisor.snapshot(&f.fleet.first).expect("owner");
    assert!(retained.active && !retained.healthy);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert_eq!(f.faults.lock().expect("faults").main_kills, 3);
    Ok(())
}

#[test]
fn first_companion_signal_error_survives_poll_failure_and_successful_retry() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::WithMatrix)?;
    f.fence()?;
    {
        let mut faults = f.faults.lock().expect("faults");
        faults.matrix_kill_failures = 1;
        faults.main_poll_failures = 1;
    }
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &["one-shot Matrix kill failure", "one-shot main poll failure"],
    );
    let retained = f.supervisor.snapshot(&f.fleet.first).expect("owners");
    assert!(retained.active && retained.matrix.active);
    assert!(!retained.healthy && !retained.matrix.healthy);
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 2);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 2);
    Ok(())
}

#[test]
fn first_companion_signal_error_survives_main_control_failure() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::WithMatrix)?;
    f.fence()?;
    {
        let mut faults = f.faults.lock().expect("faults");
        faults.main_kill_failures = 1;
        faults.matrix_kill_failures = 1;
    }
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &["one-shot Matrix kill failure", "one-shot main kill failure"],
    );
    assert!(f.supervisor.snapshot(&f.fleet.first).expect("owner").active);
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 2);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    Ok(())
}

#[test]
fn companion_signal_error_survives_exact_main_exit_cleanup_failure() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::WithMatrix)?;
    f.fence()?;
    f.faults.lock().expect("faults").matrix_kill_failures = 1;
    let record = f.supervisor.record(&f.fleet.first)?;
    let lease = crate::lease::read_lease(record.layout.run_root())?.expect("exact lease");
    crate::lease::remove_lease(record.layout.run_root(), &lease)?;
    f.control.set_exit(&f.fleet.first);
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &[
            "one-shot Matrix kill failure",
            "active process lease is missing",
        ],
    );
    let retained = f.supervisor.snapshot(&f.fleet.first).expect("owners");
    assert!(retained.active && retained.matrix.active);
    assert_eq!(retained.spawn_generation, Some(lease.spawn_generation));
    assert_eq!(f.faults.lock().expect("faults").matrix_kills, 2);
    crate::lease::write_lease(record.layout.run_root(), &lease)?;
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert!(
        !f.supervisor
            .snapshot(&f.fleet.first)
            .expect("cleaned main")
            .active
    );
    f.control.set_matrix_exit(&f.fleet.first);
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert!(
        !f.supervisor
            .snapshot(&f.fleet.first)
            .expect("cleaned pair")
            .matrix
            .active
    );
    assert_eq!(f.control.matrix_spawn_count(&f.fleet.first), 1);
    Ok(())
}

#[test]
fn already_fenced_termination_error_survives_poll_failure() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    f.fence()?;
    f.faults.lock().expect("faults").main_kill_failures = 1;
    let first = f.supervisor.tick(f.now);
    f.assert_faults(&first, &["one-shot main kill failure"]);
    {
        let mut faults = f.faults.lock().expect("faults");
        faults.main_kill_failures = 1;
        faults.main_poll_failures = 1;
    }
    let report = f.supervisor.tick(f.now);
    f.assert_faults(
        &report,
        &["one-shot main kill failure", "one-shot main poll failure"],
    );
    assert!(
        f.supervisor
            .snapshot(&f.fleet.first)
            .expect("retained owner")
            .active
    );
    assert_eq!(f.supervisor.tick(f.now), TickReport::default());
    assert_eq!(f.faults.lock().expect("faults").main_kills, 3);
    Ok(())
}
