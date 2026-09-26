//! Unix process driver with final-use runtime.fleet admission at the physical
//! child-process boundary.
//!
//! The established Unix implementation remains in `unix_core.rs`. This wrapper
//! captures one immutable admission profile from the daemon entry point and
//! verifies the exact Agent grant, host/lease fences and durable revocation cut
//! immediately before every spawn or adoption, including automatic recovery and
//! Matrix companion paths.

#[path = "unix_core.rs"]
mod raw;

pub use raw::UnixManagedProcess;

use std::future::Future;

use codex_hepta_contracts::AgentId;

use crate::AdoptSpec;
use crate::Adoption;
use crate::FleetStartAdmission;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::SpawnSpec;
use crate::SpawnedProcess;

tokio::task_local! {
    static FLEET_START_ADMISSION: FleetStartAdmission;
}

pub(crate) async fn with_fleet_start_admission<F, T>(
    admission: FleetStartAdmission,
    future: F,
) -> T
where
    F: Future<Output = T>,
{
    FLEET_START_ADMISSION.scope(admission, future).await
}

/// Product-facing Unix driver. Legacy library entry points that do not install
/// a fleet admission scope retain their historical behavior; the named
/// `hepta-supervisord` product always installs one before constructing this
/// driver.
pub struct UnixProcessDriver {
    inner: raw::UnixProcessDriver,
    admission: Option<FleetStartAdmission>,
}

impl UnixProcessDriver {
    pub fn new(log_channel_capacity: usize) -> Result<Self, ProcessDriverError> {
        let inner = raw::UnixProcessDriver::new(log_channel_capacity)?;
        let admission = FLEET_START_ADMISSION.try_with(Clone::clone).ok();
        Ok(Self { inner, admission })
    }

    fn verify_process_effect(&self, agent_id: &AgentId) -> Result<(), ProcessDriverError> {
        let Some(admission) = self.admission.as_ref() else {
            return Ok(());
        };
        admission.verify_agent_start(agent_id).map(|_witness| ()).map_err(|_error| {
            ProcessDriverError::new(
                "runtime.fleet final-use admission rejected the process effect",
            )
        })
    }
}

impl ProcessDriver for UnixProcessDriver {
    type Process = raw::UnixManagedProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.spawn(spec)
    }

    fn adopt(
        &mut self,
        spec: &AdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.adopt(spec)
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.spawn_matrixd(spec)
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.adopt_matrixd(spec)
    }
}
