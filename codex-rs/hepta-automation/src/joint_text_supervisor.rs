//! Fixed Joint RPC transport. The concrete HC6 owner supplies the admitted
//! deployment and denial-only lease/root/source recheck; this is not authority.

use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_contracts::Sha256Digest;

use crate::fixed_job_supervisor::FixedProcessConfig;
use crate::fixed_job_supervisor::FixedProcessError;
use crate::fixed_job_supervisor::FixedProcessSupervisor;
use crate::joint_text_job::JointTextJobCommandV1;
use crate::joint_text_job::JointTextJobObservationV1;
use crate::joint_text_job::JointTextRootIdentityV1;
use crate::joint_text_job::JointTextSupervisor;
use crate::joint_text_job::JointTextSupervisorError;

#[derive(Clone, Debug)]
pub struct JointTextProcessSupervisorConfig {
    pub python_executable: PathBuf,
    pub python_sha256: Sha256Digest,
    pub repository_root: PathBuf,
    pub supervisor_sha256: Sha256Digest,
    pub durable_root: PathBuf,
    pub root_identity: JointTextRootIdentityV1,
    /// RPC bound only (at most 30 seconds), not the original training budget.
    pub deadline: Duration,
}

pub struct JointTextProcessSupervisor {
    process: FixedProcessSupervisor,
}

impl JointTextProcessSupervisor {
    /// A denial-only guard is required. It cannot synthesize a grant or replace
    /// the real registered owner/FinalUse checks. No default permit constructor.
    pub fn new_with_contact_guard(
        config: JointTextProcessSupervisorConfig,
        guard: impl Fn() -> Result<(), JointTextSupervisorError> + Send + Sync + 'static,
    ) -> Result<Self, JointTextSupervisorError> {
        let fixed = FixedProcessConfig {
            python_executable: config.python_executable,
            python_sha256: config.python_sha256,
            repository_root: config.repository_root,
            supervisor_sha256: config.supervisor_sha256,
            durable_root: config.durable_root,
            deadline: config.deadline,
        };
        let process = FixedProcessSupervisor::joint_text(fixed, config.root_identity, move || {
            guard().map_err(|_| FixedProcessError::BeforeContact)
        })
        .map_err(JointTextSupervisorError::from)?;
        Ok(Self { process })
    }
}

impl JointTextSupervisor for JointTextProcessSupervisor {
    fn exchange(
        &mut self,
        command: &JointTextJobCommandV1,
    ) -> Result<JointTextJobObservationV1, JointTextSupervisorError> {
        command.validate()?;
        let bytes = self
            .process
            .exchange(command)
            .map_err(JointTextSupervisorError::from)?;
        let observation: JointTextJobObservationV1 =
            serde_json::from_slice(&bytes).map_err(|_| JointTextSupervisorError::Unknown)?;
        observation
            .validate_for(command)
            .map_err(|_| JointTextSupervisorError::Unknown)?;
        Ok(observation)
    }
}

impl From<FixedProcessError> for JointTextSupervisorError {
    fn from(error: FixedProcessError) -> Self {
        match error {
            FixedProcessError::BeforeContact => Self::BeforeContact,
            FixedProcessError::Unknown => Self::Unknown,
        }
    }
}

#[cfg(test)]
#[path = "joint_text_supervisor_tests.rs"]
mod tests;
