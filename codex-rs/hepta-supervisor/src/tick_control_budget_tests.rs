//! Actual Instant capacity is checked before acquisition and Drain side effects.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::super::Fixture;
use super::super::ProcessSet;
use crate::AdoptSpec;
use crate::Adoption;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessObservation;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::SupervisorError;

struct AcquisitionDriver(Arc<Mutex<[usize; 4]>>);
struct UnexpectedProcess;

impl AcquisitionDriver {
    fn record(&self, index: usize) -> ProcessDriverError {
        self.0.lock().expect("driver calls")[index] += 1;
        ProcessDriverError::new("unexpected ownership acquisition")
    }
}

impl ProcessDriver for AcquisitionDriver {
    type Process = UnexpectedProcess;

    fn spawn(
        &mut self,
        _spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        Err(self.record(/*index*/ 0))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Err(self.record(/*index*/ 1))
    }

    fn spawn_matrixd(
        &mut self,
        _spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        Err(self.record(/*index*/ 2))
    }

    fn adopt_matrixd(
        &mut self,
        _spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Err(self.record(/*index*/ 3))
    }
}

impl ManagedProcess for UnexpectedProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        panic!("budget rejection cannot construct a process handle")
    }
    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        panic!("budget rejection cannot construct a process handle")
    }
    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        panic!("budget rejection cannot construct a process handle")
    }
    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        panic!("budget rejection cannot construct a process handle")
    }
}

#[test]
fn recovery_rejects_unrepresentable_drain_budget_before_driver_acquisition() -> Result<()> {
    let f = Fixture::new(ProcessSet::MainOnly)?;
    let lease = super::lease_bytes(&f)?;
    let snapshot = f.supervisor.snapshot(&f.fleet.first);
    let mut policy = f.supervisor.config.clone();
    policy.stop_grace = Duration::MAX;
    let calls = Arc::new(Mutex::new([0; 4]));
    let recovered = Supervisor::recover(
        f.fleet.registry.clone(),
        AcquisitionDriver(Arc::clone(&calls)),
        policy,
        f.now,
    );
    let error = match recovered {
        Ok(_) => panic!("unrepresentable budget admitted recovery"),
        Err(error) => error,
    };
    assert!(
        matches!(error, SupervisorError::Invalid(message) if message == "supervisor deadline overflow")
    );
    assert_eq!(*calls.lock().expect("driver calls"), [0; 4]);
    assert_eq!(super::lease_bytes(&f)?, lease);
    assert_eq!(f.supervisor.snapshot(&f.fleet.first), snapshot);
    Ok(())
}

#[test]
fn drain_rejects_unrepresentable_total_deadline_without_side_effects() -> Result<()> {
    let mut f = Fixture::new(ProcessSet::MainOnly)?;
    // Derive the host's actual Instant capacity instead of assuming Linux,
    // Darwin or Windows uses any particular integer/time representation.
    let mut low = 0_u64;
    let mut high = u64::MAX;
    while low < high {
        let middle = low + (high - low) / 2 + 1;
        if f.now.checked_add(Duration::from_secs(middle)).is_some() {
            low = middle;
        } else {
            high = middle - 1;
        }
    }
    let last_second = f
        .now
        .checked_add(Duration::from_secs(low))
        .expect("supported second");
    low = 0;
    high = 999_999_999;
    while low < high {
        let middle = low + (high - low) / 2 + 1;
        if last_second
            .checked_add(Duration::from_nanos(middle))
            .is_some()
        {
            low = middle;
        } else {
            high = middle - 1;
        }
    }
    let last = last_second
        .checked_add(Duration::from_nanos(low))
        .expect("supported fraction");
    let near_limit = last
        .checked_sub(f.supervisor.config.drain_timeout)
        .expect("drain fits before limit");
    let drain_limit = near_limit
        .checked_add(f.supervisor.config.drain_timeout)
        .expect("first phase fits");
    assert!(
        drain_limit
            .checked_add(f.supervisor.config.stop_grace)
            .is_none()
    );
    let lease = super::lease_bytes(&f)?;
    let snapshot = f.supervisor.snapshot(&f.fleet.first);
    let record = f.fleet.registry.load_agent(&f.fleet.first)?;
    let error = f
        .supervisor
        .drain(&f.fleet.first, near_limit)
        .expect_err("total budget must reject");
    assert!(
        matches!(error, SupervisorError::Invalid(message) if message == "supervisor deadline overflow")
    );
    assert_eq!(f.supervisor.snapshot(&f.fleet.first), snapshot);
    assert_eq!(f.fleet.registry.load_agent(&f.fleet.first)?, record);
    assert_eq!(super::lease_bytes(&f)?, lease);
    let faults = f.faults.lock().expect("faults");
    assert_eq!((faults.main_stops, faults.main_kills), (0, 0));
    let world = f.control.world.lock().expect("process world");
    assert_eq!(
        world
            .processes
            .values()
            .map(|process| (
                process.drain_requests,
                process.stop_requests,
                process.kill_requests
            ))
            .collect::<Vec<_>>(),
        vec![(0, 0, 0)]
    );
    Ok(())
}
