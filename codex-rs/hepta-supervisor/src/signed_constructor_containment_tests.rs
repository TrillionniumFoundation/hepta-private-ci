//! Failed exact-owner containment is diagnosed and retried, never acknowledged
//! as exit, and cannot suppress acquisition of the independent companion.

use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

struct FaultingProcess {
    inner: FakeProcess,
    fail: Arc<AtomicBool>,
    role: &'static str,
}

impl ManagedProcess for FaultingProcess {
    fn poll(&mut self, max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        self.inner.poll(max_logs)
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.request_drain()
    }
    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.request_stop()
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.inner.kill()?;
        if self.fail.swap(/*val*/ false, Ordering::SeqCst) {
            return Err(ProcessDriverError::new(format!(
                "{} containment failed after delivery",
                self.role
            )));
        }
        Ok(())
    }
}

struct FaultingDriver {
    inner: FakeDriver,
    main: Arc<AtomicBool>,
    matrix: Arc<AtomicBool>,
}

fn wrap_adoption(
    value: Adoption<FakeProcess>,
    fail: &Arc<AtomicBool>,
    role: &'static str,
) -> Adoption<FaultingProcess> {
    match value {
        Adoption::Adopted(inner) => Adoption::Adopted(FaultingProcess {
            inner,
            fail: Arc::clone(fail),
            role,
        }),
        Adoption::Missing => Adoption::Missing,
        Adoption::Rejected => Adoption::Rejected,
    }
}

impl ProcessDriver for FaultingDriver {
    type Process = FaultingProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let spawned = self.inner.spawn(spec)?;
        Ok(SpawnedProcess {
            identity: spawned.identity,
            process: FaultingProcess {
                inner: spawned.process,
                fail: Arc::clone(&self.main),
                role: "main",
            },
        })
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Ok(wrap_adoption(self.inner.adopt(spec)?, &self.main, "main"))
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let spawned = self.inner.spawn_matrixd(spec)?;
        Ok(SpawnedProcess {
            identity: spawned.identity,
            process: FaultingProcess {
                inner: spawned.process,
                fail: Arc::clone(&self.matrix),
                role: "matrix",
            },
        })
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Ok(wrap_adoption(
            self.inner.adopt_matrixd(spec)?,
            &self.matrix,
            "matrix",
        ))
    }
}

#[test]
fn signed_denial_containment_faults_retain_both_owners_and_retry_once() -> Result<()> {
    let mut s = Scenario::new(Plant::Paired)?;
    let failed =
        with_qualification_fault("release_transaction.file_write", ErrorKind::Other, || {
            s.apply()
        });
    assert!(
        matches!(failed, Err(SupervisorError::SignedMutationIndeterminate(ref agent)) if agent == &s.fleet.first)
    );
    let record = s.supervisor.record(&s.fleet.first)?;
    let tx = s.legacy_unsigned_prepared()?;
    crate::release_transaction::write_release_transaction(record.layout.run_root(), &tx)?;
    let main_path = record
        .layout
        .run_root()
        .join(crate::lease::PROCESS_LEASE_FILE);
    let main_lease = std::fs::read(&main_path)?;
    let matrix_lease = std::fs::read(record.layout.matrixd_process_lease())?;
    let budget = crate::restart_journal::read_restart_journal(record.layout.run_root())?;
    let spawns = (
        s.control.spawn_count(&s.fleet.first),
        s.control.matrix_spawn_count(&s.fleet.first),
    );
    drop(s.supervisor);
    let driver = FaultingDriver {
        inner: s.control.driver(),
        main: Arc::new(AtomicBool::new(/*v*/ true)),
        matrix: Arc::new(AtomicBool::new(/*v*/ true)),
    };
    let (mut recovered, report) =
        Supervisor::recover(s.fleet.registry.clone(), driver, config(), s.now)?;
    let snapshot = recovered
        .snapshot(&s.fleet.first)
        .expect("both retained owners");
    assert!(
        snapshot.active
            && snapshot.runtime_fenced
            && snapshot.matrix.active
            && !snapshot.matrix.healthy
    );
    assert_eq!(s.control.counts(&s.fleet.first), (0, 0, 1));
    assert_eq!(s.control.matrix_counts(&s.fleet.first), (0, 0, 1));
    assert!(snapshot.events.iter().any(|event| matches!(&event.kind, SupervisorEventKind::DriverFault(message) if message.contains("main containment failed after delivery"))));
    assert!(report.faults.iter().any(|fault| {
        fault
            .message
            .contains("matrix containment failed after delivery")
    }));
    assert_eq!(std::fs::read(&main_path)?, main_lease);
    assert_eq!(
        std::fs::read(record.layout.matrixd_process_lease())?,
        matrix_lease
    );
    assert!(recovered.production_recovery_required(&s.fleet.first)?);
    assert_eq!(recovered.tick(s.now), TickReport::default());
    assert_eq!(s.control.counts(&s.fleet.first), (0, 0, 2));
    assert_eq!(s.control.matrix_counts(&s.fleet.first), (0, 0, 2));
    assert_eq!(std::fs::read(&main_path)?, main_lease);
    assert_eq!(
        std::fs::read(record.layout.matrixd_process_lease())?,
        matrix_lease
    );
    assert_eq!(
        read_release_transaction(record.layout.run_root())?,
        Some(tx)
    );
    assert_eq!(
        crate::restart_journal::read_restart_journal(record.layout.run_root())?,
        budget
    );
    assert_eq!(
        (
            s.control.spawn_count(&s.fleet.first),
            s.control.matrix_spawn_count(&s.fleet.first)
        ),
        spawns
    );
    Ok(())
}
