//! Consume one original Ready into the unchanged task factory. The session
//! and unique configuration remain typed local values; nothing crosses UID or
//! recreates the task, Source, Cell, grant, writer or original journal.

use codex_hepta_neuron::AnchorWitnessStore;

use super::InitialHostPhase;
use super::PreparedRootHostInitialGenerationV1;
use super::invalid;
use super::require_original_session;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::OriginalRootCircuitTaskCustodyV1;
use crate::OriginalRootCircuitTaskInputsV1;
use crate::OriginalRootCircuitTaskRuntimeV1;
use crate::OriginalRootInitialGenerationCustodyV1;
use crate::OriginalRootInitialInstallationErrorV1;
use crate::PreparedHostAuthoritySession;
use crate::authority_host_service::OriginalHostInitialOperation;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;

enum OriginalInstallationFailure {
    Host(AgentdError),
    Factory(OriginalRootInitialInstallationErrorV1),
}

impl From<AgentdError> for OriginalInstallationFailure {
    fn from(error: AgentdError) -> Self {
        Self::Host(error)
    }
}

/// A refused installation retains only its same original host and operation.
/// Source/Cell installation may already have had effects. No Ready, Config,
/// Create retry or mutable owner is returned through this error.
pub struct RootHostInitialTaskInstallationErrorV1 {
    session: PreparedHostAuthoritySession,
    operation: OriginalHostInitialOperation,
    end: std::time::Instant,
    failure: OriginalInstallationFailure,
}

impl RootHostInitialTaskInstallationErrorV1 {
    pub fn generation_error(&self) -> &AgentdError {
        match &self.failure {
            OriginalInstallationFailure::Host(error) => error,
            OriginalInstallationFailure::Factory(error) => error.original_error(),
        }
    }

    /// Read the same operation, not a new execution permission or a proof that
    /// installation had no effect. A later cold entry must use original files.
    pub fn read_original_generation_after_installation_failure(
        &self,
    ) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        require_original_session(&self.session, self.end)?;
        let readback = OriginalHostInitialOperation::read_original(&self.operation)?;
        require_original_session(&self.session, self.end)?;
        Ok(readback)
    }
}

impl std::fmt::Debug for RootHostInitialTaskInstallationErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RootHostInitialTaskInstallationErrorV1")
            .field("error", self.generation_error())
            .finish_non_exhaustive()
    }
}

impl std::fmt::Display for RootHostInitialTaskInstallationErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        std::fmt::Display::fmt(self.generation_error(), f)
    }
}

impl std::error::Error for RootHostInitialTaskInstallationErrorV1 {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(self.generation_error())
    }
}

impl<W: AnchorWitnessStore + Send + 'static> PreparedRootHostInitialGenerationV1<W> {
    /// Install the original Ready using the same registered Agentd identity
    /// and the caller's one Config writer. The unchanged factory supplies the
    /// exact task/Cell/Source and their same-Arc retirement custody.
    ///
    /// Return the original session for its original serving lifecycle. This
    /// is a Root-local assembly result, not a descriptor for a non-Root daemon
    /// or evidence that RunStart, task completion or process recovery occurred.
    pub fn into_original_q24_task<SW, CW>(
        self,
        config: AgentdConfig,
        inputs: OriginalRootCircuitTaskInputsV1<SW, CW>,
    ) -> Result<
        (PreparedHostAuthoritySession, OriginalRootCircuitTaskRuntimeV1<SW, CW>),
        RootHostInitialTaskInstallationErrorV1,
    >
    where
        SW: AnchorWitnessStore + Send + 'static,
        CW: AnchorWitnessStore + Send + 'static,
    {
        let Self { session, operation, phase, end } = self;
        let install = (|| -> Result<_, OriginalInstallationFailure> {
            require_original_session(&session, end)?;
            if session.registration.registered_identity.identity().map_err(AgentdError::from)?
                != *config.identity()
            {
                return Err(invalid("task Config differs from the original registered identity").into());
            }
            let InitialHostPhase::Ready(custody) = phase else {
                return Err(invalid("the original host generation is not Ready").into());
            };
            OriginalHostInitialOperation::require_observed(
                &operation,
                &OriginalRootInitialGenerationCustodyV1::read_original_operation(&custody)?,
            )?;
            let runtime = OriginalRootInitialGenerationCustodyV1::into_q24_task(custody, config, inputs)
                .map_err(OriginalInstallationFailure::Factory)?;
            OriginalHostInitialOperation::require_observed(
                &operation,
                &OriginalRootCircuitTaskCustodyV1::read_original_operation(&runtime.custody)?,
            )?;
            require_original_session(&session, end)?;
            Ok(runtime)
        })();
        match install {
            Ok(runtime) => Ok((session, runtime)),
            Err(failure) => Err(RootHostInitialTaskInstallationErrorV1 {
                session,
                operation,
                end,
                failure,
            }),
        }
    }
}
