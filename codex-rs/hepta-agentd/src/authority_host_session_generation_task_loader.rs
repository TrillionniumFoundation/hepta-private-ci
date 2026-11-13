//! The same Ready, session and absolute end feed the original task factory.
//! Loading failure retains only same-operation readback, never Create retry.

use std::path::Path;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;

use super::InitialHostPhase;
use super::OriginalInstallationFailure;
use super::PreparedRootHostCircuitTaskV1;
use super::PreparedRootHostInitialGenerationV1;
use super::RootHostInitialTaskInstallationErrorV1;
use super::invalid;
use super::require_original_session;
use crate::AgentdError;
use crate::HostAuthorityService;
use crate::OriginalRootInitialGenerationCustodyV1;
use crate::RootHostQ24TaskFilesV1;
use crate::authority_host_service::OriginalHostInitialOperation;
use crate::authority_host_service::OriginalTaskFilePurpose;
use crate::authority_host_service::OriginalTaskClockStatus;

#[path = "authority_host_loaded_task_service.rs"]
mod original_service;
pub use original_service::RootHostOriginalTaskLearningFilesV1;

/// The original task plus its same callback's first-error observation. There
/// is no task/owner getter and no way to clear a failed clock or obtain a new
/// factory lane. Normal serving is provided only by the fixed later assembly.
pub struct PreparedRootHostLoadedQ24TaskV1 {
    task: PreparedRootHostCircuitTaskV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    clock_status: OriginalTaskClockStatus,
}

impl PreparedRootHostLoadedQ24TaskV1 {
    pub fn read_loaded_original_root_task_generation(
        &self,
    ) -> Result<crate::neuron_generation_current::NeuronGenerationInitialReadbackV1, AgentdError> {
        self.clock_status.require_healthy()?;
        let result = PreparedRootHostCircuitTaskV1::read_original_root_task_generation(&self.task);
        self.require_original_result(result)
    }

    fn require_original_result<T>(&self, result: Result<T, AgentdError>) -> Result<T, AgentdError> {
        match (result, self.clock_status.require_healthy()) {
            (Ok(value), Ok(())) => Ok(value),
            (Err(error), Ok(())) | (Ok(_), Err(error)) => Err(error),
            (Err(error), Err(clock)) => Err(AgentdError::Protocol(format!(
                "original task refused: {error}; retained clock cause: {clock}"
            ))),
        }
    }
}

impl<W: AnchorWitnessStore + Send + 'static> PreparedRootHostInitialGenerationV1<W> {
    /// Consume this actual Ready and existing supervisor files for one Create
    /// assembly. Model, registry and exact Source/Cell authentication remain in
    /// the unchanged factory. This does not execute an ingress or claim a task.
    pub fn prepare_original_root_task_from_files(
        self,
        deployment: &Path,
        files: RootHostQ24TaskFilesV1,
    ) -> Result<PreparedRootHostLoadedQ24TaskV1, RootHostInitialTaskInstallationErrorV1> {
        self.load_original_task_files(deployment, files, OriginalTaskFilePurpose::Create)
    }

    /// Consume this actual Ready and recover the original Source/Cell history.
    /// Missing or empty journals/witnesses are refused before original opening;
    /// there is no Create fallback, different operation or deadline extension.
    pub fn recover_original_root_task_from_files(
        self,
        deployment: &Path,
        files: RootHostQ24TaskFilesV1,
    ) -> Result<PreparedRootHostLoadedQ24TaskV1, RootHostInitialTaskInstallationErrorV1> {
        self.load_original_task_files(deployment, files, OriginalTaskFilePurpose::Recover)
    }

    fn load_original_task_files(
        self,
        deployment: &Path,
        files: RootHostQ24TaskFilesV1,
        purpose: OriginalTaskFilePurpose,
    ) -> Result<PreparedRootHostLoadedQ24TaskV1, RootHostInitialTaskInstallationErrorV1> {
        let loaded = (|| -> Result<_, AgentdError> {
            require_original_session(&self.session, self.end)?;
            let InitialHostPhase::Ready(custody) = &self.phase else {
                return Err(invalid("original generation must be Ready before opening task state"));
            };
            OriginalHostInitialOperation::require_observed(
                &self.operation,
                &OriginalRootInitialGenerationCustodyV1::read_original_operation(custody)?,
            )?;
            let loaded = HostAuthorityService::load_original_root_q24_task_inputs(
                &self.session.service, deployment, files, purpose, self.end,
            )?;
            OriginalHostInitialOperation::require_observed(
                &self.operation,
                &OriginalRootInitialGenerationCustodyV1::read_original_operation(custody)?,
            )?;
            require_original_session(&self.session, self.end)?;
            Ok(loaded)
        })();
        match loaded {
            Ok(loaded) => {
                let task = PreparedRootHostInitialGenerationV1::prepare_original_root_task(self, loaded.inputs)?;
                Ok(PreparedRootHostLoadedQ24TaskV1 { task, clock_status: loaded.clock_status })
            }
            Err(error) => {
                let Self { session, operation, end, phase: _ } = self;
                Err(RootHostInitialTaskInstallationErrorV1 {
                    session, operation, end, failure: OriginalInstallationFailure::Host(error),
                })
            }
        }
    }
}
