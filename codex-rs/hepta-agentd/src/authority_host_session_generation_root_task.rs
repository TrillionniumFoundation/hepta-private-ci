//! The original Root host retains its one actual task factory and retirement
//! custody. Config, daemon state and AutomationStore are not created or moved.

#[path = "authority_host_session_generation_task_service.rs"]
mod original_service;

#[path = "authority_host_task_source_ready.rs"]
mod original_source_ready;

#[path = "authority_host_session_generation_task_handoff.rs"]
mod ordinary_handoff;

#[path = "authority_host_session_task_followups.rs"]
mod loaded_followups;
pub(crate) use loaded_followups::OriginalLoadedTaskFollowups;

use std::sync::Arc;
use codex_hepta_neuron::AnchorWitnessStore;

#[path = "authority_host_session_material_source.rs"]
pub(crate) mod material_source;
pub use material_source::PreparedRootMaterialSourceHostV1;
pub use material_source::OriginalRootMaterialSourceRegistrationV1;
pub use material_source::OriginalRootPrefreezeSourceRegistrationV1;

use super::InitialHostPhase;
use super::OriginalInstallationFailure;
use super::PreparedRootHostInitialGenerationV1;
use super::RootHostInitialTaskInstallationErrorV1;
use super::invalid;
use super::require_original_session;
use crate::AgentdError;
use crate::CircuitQ24TaskRuntimeV1;
use crate::OriginalRootCircuitTaskCustodyV1;
use crate::OriginalRootCircuitTaskInputsV1;
use crate::OriginalRootInitialGenerationCustodyV1;
use crate::PreparedHostAuthoritySession;
use crate::PublishedCircuitFeatureCompletionV1;
use crate::authority_host_service::OriginalHostInitialOperation;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;

/// Non-Clone Root custody for the factory's same task, Cell and Source. It is
/// not a daemon bootstrap descriptor and does not make the in-memory lane a
/// cross-process connection. Only the later purpose-fixed service may consume
/// the private runtime; callers receive no owner, Config or writer getter.
pub struct PreparedRootHostCircuitTaskV1<SW: AnchorWitnessStore, CW: AnchorWitnessStore> {
    session: Arc<PreparedHostAuthoritySession>,
    operation: Arc<OriginalHostInitialOperation>,
    runtime: CircuitQ24TaskRuntimeV1<SW, CW>,
    custody: Arc<OriginalRootCircuitTaskCustodyV1<SW, CW>>,
    material_source_taken: bool,
    source_ready: Arc<original_source_ready::Hint>,
    end: std::time::Instant,
}

impl<SW, CW> PreparedRootHostCircuitTaskV1<SW, CW>
where
    SW: AnchorWitnessStore + Send + 'static,
    CW: AnchorWitnessStore + Send + 'static,
{
    /// Read the actual published operation through the same Current and live
    /// original host checks. This does not imply that any task has run.
    pub fn read_original_root_task_generation(
        &self,
    ) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        require_original_session(&self.session, self.end)?;
        let observed = OriginalRootCircuitTaskCustodyV1::read_original_operation(&self.custody)?;
        OriginalHostInitialOperation::require_observed(&self.operation, &observed)?;
        require_original_session(&self.session, self.end)?;
        Ok(observed)
    }

    /// Count the original in-memory lane only. Zero is not a readiness,
    /// completion, durable drain or process-termination assertion.
    pub fn pending_original_root_task_operations(&self) -> Result<usize, AgentdError> {
        self.read_original_root_task_generation()?;
        let pending = self.runtime.bootstrap.handle().pending_count();
        require_original_session(&self.session, self.end)?;
        Ok(pending)
    }

    /// Call the original same-Arc retirement path. The original Source must
    /// already contain a real completed task. A post-drain failure remains
    /// Unknown; it neither restores execution nor proves that drain did nothing.
    pub fn drain_completed_original_root_task(
        &self,
    ) -> Result<PublishedCircuitFeatureCompletionV1, AgentdError> {
        self.read_original_root_task_generation()?;
        let completion = OriginalRootCircuitTaskCustodyV1::drain_completed_task(&self.custody)?;
        self.read_original_root_task_generation()?;
        Ok(completion)
    }
}

impl<W: AnchorWitnessStore + Send + 'static> PreparedRootHostInitialGenerationV1<W> {
    /// Consume the actual Ready into the existing Config-free Q24 factory.
    /// The registered identity supplies the scope; no caller profile can replace
    /// the sealed PublishedTask. Source and Cell creation may precede a later
    /// refusal, so errors retain only same-operation readback, never Create retry.
    pub fn prepare_original_root_task<SW, CW>(
        self,
        inputs: OriginalRootCircuitTaskInputsV1<SW, CW>,
    ) -> Result<PreparedRootHostCircuitTaskV1<SW, CW>, RootHostInitialTaskInstallationErrorV1>
    where
        SW: AnchorWitnessStore + Send + 'static,
        CW: AnchorWitnessStore + Send + 'static,
    {
        let Self { session, operation, phase, end } = self;
        let install = (|| -> Result<_, OriginalInstallationFailure> {
            require_original_session(&session, end)?;
            let identity = session.registration.registered_identity.identity()
                .map_err(AgentdError::from)?;
            let InitialHostPhase::Ready(custody) = phase else {
                return Err(invalid("the original host generation is not Ready").into());
            };
            OriginalHostInitialOperation::require_observed(
                &operation,
                &OriginalRootInitialGenerationCustodyV1::read_original_operation(&custody)?,
            )?;
            let (runtime, custody) = OriginalRootInitialGenerationCustodyV1::into_original_root_task_channel(
                custody, &identity, inputs,
            ).map_err(OriginalInstallationFailure::Factory)?;
            OriginalHostInitialOperation::require_observed(
                &operation,
                &OriginalRootCircuitTaskCustodyV1::read_original_operation(&custody)?,
            )?;
            require_original_session(&session, end)?;
            Ok((runtime, custody))
        })();
        match install {
            Ok((runtime, custody)) => Ok(PreparedRootHostCircuitTaskV1 {
                session: Arc::new(session), operation: Arc::new(operation), runtime,
                custody: Arc::new(custody), material_source_taken: false,
                source_ready: Arc::new(original_source_ready::Hint::new()), end,
            }),
            Err(failure) => Err(RootHostInitialTaskInstallationErrorV1 {
                session, operation, end, failure,
            }),
        }
    }
}
