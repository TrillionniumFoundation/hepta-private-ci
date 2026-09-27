use crate::AdoptSpec;
use crate::Adoption;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::SharedProcessAdmission;
use crate::SpawnSpec;
use crate::SpawnedProcess;

/// Product wrapper that executes final-use admission immediately before the
/// underlying process-driver effect. The inner driver remains the sole process
/// owner; this wrapper owns no queue, process handle or retry loop.
pub struct AdmissionProcessDriver<D> {
    inner: D,
    admission: Option<SharedProcessAdmission>,
}

impl<D> AdmissionProcessDriver<D> {
    pub fn new(inner: D, admission: Option<SharedProcessAdmission>) -> Self {
        Self { inner, admission }
    }

    pub fn inner(&self) -> &D {
        &self.inner
    }
}

impl<D: ProcessDriver> ProcessDriver for AdmissionProcessDriver<D> {
    type Process = D::Process;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        if let Some(admission) = &self.admission {
            admission.verify_spawn(spec)?;
        }
        self.inner.spawn(spec)
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        if let Some(admission) = &self.admission {
            admission.verify_adopt(spec)?;
        }
        self.inner.adopt(spec)
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.inner.spawn_matrixd(spec)
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.inner.adopt_matrixd(spec)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AgentCommand;
    use crate::ManagedProcess;
    use crate::ProcessExit;
    use crate::ProcessIdentity;
    use crate::ProcessLog;
    use crate::ProcessObservation;
    use crate::ProcessState;
    use codex_hepta_contracts::AgentId;
    use std::path::PathBuf;
    use std::sync::Arc;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    #[derive(Debug)]
    struct DenyAdmission(AtomicU64);

    impl crate::ProcessAdmission for DenyAdmission {
        fn verify_spawn(&self, _spec: &SpawnSpec) -> Result<(), ProcessDriverError> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err(ProcessDriverError::new("denied before spawn"))
        }

        fn verify_adopt(&self, _spec: &AdoptSpec) -> Result<(), ProcessDriverError> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err(ProcessDriverError::new("denied before adopt"))
        }
    }

    #[derive(Debug)]
    struct NeverProcess;

    impl ManagedProcess for NeverProcess {
        fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
            Ok(ProcessObservation {
                state: ProcessState::Exited(ProcessExit {
                    success: false,
                    code: None,
                }),
                logs: Vec::<ProcessLog>::new(),
            })
        }

        fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn kill(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }
    }

    #[derive(Debug, Default)]
    struct CountingDriver {
        effects: u64,
    }

    impl ProcessDriver for CountingDriver {
        type Process = NeverProcess;

        fn spawn(
            &mut self,
            _spec: &SpawnSpec,
        ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
            self.effects += 1;
            Ok(SpawnedProcess {
                identity: ProcessIdentity::new(1, "never-spawned".into())
                    .map_err(|error| ProcessDriverError::new(error.to_string()))?,
                process: NeverProcess,
            })
        }

        fn adopt(
            &mut self,
            _spec: &AdoptSpec,
        ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
            self.effects += 1;
            Ok(Adoption::Missing)
        }
    }

    fn spawn_spec() -> SpawnSpec {
        SpawnSpec {
            agent_id: AgentId::parse("00000000-0000-0000-0000-000000000001")
                .expect("agent id"),
            generation: 1,
            fleet_root: PathBuf::from("/fleet"),
            workspace: PathBuf::from("/workspace"),
            home_root: PathBuf::from("/home"),
            run_root: PathBuf::from("/run"),
            control_socket: PathBuf::from("/run/control.sock"),
            logs_root: PathBuf::from("/logs"),
            command: AgentCommand {
                program: PathBuf::from("/bin/false"),
                args: Vec::new(),
            },
        }
    }

    #[test]
    fn rejected_admission_precedes_the_process_effect() {
        let admission = Arc::new(DenyAdmission(AtomicU64::new(0)));
        let mut driver = AdmissionProcessDriver::new(
            CountingDriver::default(),
            Some(admission.clone()),
        );
        assert!(driver.spawn(&spawn_spec()).is_err());
        assert_eq!(driver.inner().effects, 0);
        assert_eq!(admission.0.load(Ordering::SeqCst), 1);
    }
}
