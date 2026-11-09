//! Bounded transport to the original fixed HCSN Python supervisor.

use crate::fixed_job_supervisor::FixedProcessConfig;
use crate::fixed_job_supervisor::FixedProcessError;
use crate::fixed_job_supervisor::FixedProcessSupervisor;
use crate::hcsn_job::HcsnJobObservationV1;
use crate::hcsn_job::HcsnSupervisor;
use crate::hcsn_job::HcsnSupervisorCommandV1;
use crate::hcsn_job::HcsnSupervisorError;
use codex_hepta_contracts::Sha256Digest;
use std::path::PathBuf;
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct HcsnProcessSupervisorConfig {
    /// Absolute path; a venv symlink is retained when launching its interpreter.
    pub python_executable: PathBuf,
    pub python_sha256: Sha256Digest,
    /// Canonical repository directory containing the fixed supervisor module.
    pub repository_root: PathBuf,
    pub supervisor_sha256: Sha256Digest,
    /// Existing, initialized, canonical store owned by the supervisor.
    pub durable_root: PathBuf,
    /// Only the short supervision RPC, not the lifetime of the training job.
    pub deadline: Duration,
}

pub struct HcsnProcessSupervisor {
    process: FixedProcessSupervisor,
}

impl HcsnProcessSupervisor {
    pub fn new(config: HcsnProcessSupervisorConfig) -> Result<Self, HcsnSupervisorError> {
        Self::new_with_contact_guard(config, || Ok(()))
    }

    /// Denial-only contact check. The existing owner supplies actual authority.
    pub fn new_with_contact_guard(
        config: HcsnProcessSupervisorConfig,
        guard: impl Fn() -> Result<(), HcsnSupervisorError> + Send + Sync + 'static,
    ) -> Result<Self, HcsnSupervisorError> {
        let config = FixedProcessConfig {
            python_executable: config.python_executable,
            python_sha256: config.python_sha256,
            repository_root: config.repository_root,
            supervisor_sha256: config.supervisor_sha256,
            durable_root: config.durable_root,
            deadline: config.deadline,
        };
        let process = FixedProcessSupervisor::hcsn(config, move || {
            guard().map_err(|_| FixedProcessError::BeforeContact)
        })
        .map_err(HcsnSupervisorError::from)?;
        Ok(Self { process })
    }
}

impl HcsnSupervisor for HcsnProcessSupervisor {
    fn exchange(
        &mut self,
        command: &HcsnSupervisorCommandV1,
    ) -> Result<HcsnJobObservationV1, HcsnSupervisorError> {
        command.validate()?;
        let bytes = self
            .process
            .exchange(command)
            .map_err(HcsnSupervisorError::from)?;
        let observation: HcsnJobObservationV1 =
            serde_json::from_slice(&bytes).map_err(|_| HcsnSupervisorError::Unknown)?;
        observation
            .validate_for(command)
            .map_err(|_| HcsnSupervisorError::Unknown)?;
        Ok(observation)
    }
}

impl From<FixedProcessError> for HcsnSupervisorError {
    fn from(error: FixedProcessError) -> Self {
        match error {
            FixedProcessError::BeforeContact => Self::BeforeContact,
            FixedProcessError::Unknown => Self::Unknown,
        }
    }
}

#[cfg(all(test, unix))]
use crate::fixed_job_supervisor::MAX_RESPONSE_BYTES;
#[cfg(all(test, unix))]
use crate::fixed_job_supervisor::file_digest;
#[cfg(all(test, unix))]
use std::path::Path;
#[cfg(all(test, unix))]
use std::sync::atomic::Ordering;
#[cfg(all(test, unix))]
use std::time::Instant;
#[cfg(test)]
#[path = "hcsn_supervisor_tests.rs"]
mod tests;
