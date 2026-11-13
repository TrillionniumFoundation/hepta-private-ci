//! One original Root session and one initial-generation operation. This is a
//! typed host entry, never an after-drop daemon callback or a JSON registration.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_neuron::AnchorWitnessStore;

use super::PreparedHostAuthoritySession;
use crate::AgentdError;
use crate::OriginalRootInitialGenerationCustodyV1;
use crate::authority_host_runtime::verify_pinned_process;
use crate::authority_host_service::OriginalHostInitialOperation;
use crate::authority_host_service::RootHostInitialGenerationInputsV1;
use crate::authority_host_service::RootHostInitialGenerationRecoveryV1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

#[path = "authority_host_session_generation_task.rs"]
mod task;
pub use task::RootHostInitialTaskInstallationErrorV1;
pub use task::PreparedRootHostCircuitTaskV1;
pub use task::PreparedRootMaterialSourceHostV1;
pub use task::OriginalRootMaterialSourceRegistrationV1;
pub use task::OriginalRootPrefreezeSourceRegistrationV1;
pub use task::PreparedRootHostLoadedQ24TaskV1;
pub use task::RootHostOriginalTaskLearningFilesV1;

enum InitialHostPhase<W: AnchorWitnessStore> {
    Fresh(RootHostInitialGenerationInputsV1<W>),
    Ready(OriginalRootInitialGenerationCustodyV1<W>),
    ReadbackRequired,
}

/// Non-Clone ownership of the actual session, original inputs and original
/// Ready custody. No owner, writer, client or grant can be extracted from it.
pub struct PreparedRootHostInitialGenerationV1<W: AnchorWitnessStore> {
    session: PreparedHostAuthoritySession,
    operation: OriginalHostInitialOperation,
    phase: InitialHostPhase<W>,
    end: Instant,
}

#[path = "authority_host_session_generation_input_loader.rs"]
mod input_loader;

impl PreparedHostAuthoritySession {
    /// Bind the same original Root/lease/issuer/clock to actual Artifact,
    /// selected generation, target journal/witness and FinalUse consumer.
    /// The supplied complete grant is checked, never issued or renewed here.
    /// This entry writes no CURRENT or generation journal. The immutable end
    /// comes from this session's existing timeout, with no recovery extension.
    pub fn bind_original_initial_generation<W: AnchorWitnessStore>(
        self,
        inputs: RootHostInitialGenerationInputsV1<W>,
    ) -> Result<PreparedRootHostInitialGenerationV1<W>, AgentdError> {
        let end = Instant::now() + Duration::from_millis(self.config.timeout_ms);
        require_original_session(&self, end)?;
        let operation = crate::HostAuthorityService::bind_original_initial_operation(
            &self.service, &inputs, end,
        )?;
        require_original_session(&self, end)?;
        Ok(PreparedRootHostInitialGenerationV1 {
            session: self,
            operation,
            phase: InitialHostPhase::Fresh(inputs),
            end,
        })
    }

    /// Open the actual protected CURRENT under this same original Root and
    /// recover only the published operation supplied by the trusted host.
    /// Missing/pending/foreign state never creates a new preparation or grant.
    /// A failure may follow original journal recovery and is not NotApplied.
    pub fn recover_original_initial_generation<W: AnchorWitnessStore>(
        self,
        inputs: RootHostInitialGenerationRecoveryV1<W>,
    ) -> Result<PreparedRootHostInitialGenerationV1<W>, AgentdError> {
        let end = Instant::now() + Duration::from_millis(self.config.timeout_ms);
        require_original_session(&self, end)?;
        let (operation, custody) = crate::HostAuthorityService::recover_original_initial_operation(
            &self.service, inputs, end,
        )?;
        require_original_session(&self, end)?;
        Ok(PreparedRootHostInitialGenerationV1 {
            session: self,
            operation,
            phase: InitialHostPhase::Ready(custody),
            end,
        })
    }
}

impl<W: AnchorWitnessStore> PreparedRootHostInitialGenerationV1<W> {
    /// Consume the held actual inputs once through the unchanged original
    /// prepare, opaque custody and signed publication. Any error, including a
    /// post-CAS head/lease/peer/deadline error, leaves only same-op readback or
    /// explicit original recovery. This is not a continuous Registry lease
    /// transaction; FinalUse keeps its own original atomic nonce/revocation fence.
    pub fn publish_original_generation(&mut self) -> Result<(), AgentdError> {
        if !matches!(self.phase, InitialHostPhase::Fresh(_)) {
            return Err(invalid("this original generation attempt was already consumed"));
        }
        let phase = std::mem::replace(&mut self.phase, InitialHostPhase::ReadbackRequired);
        require_original_session(&self.session, self.end)?;
        let InitialHostPhase::Fresh(inputs) = phase else {
            return Err(invalid("the original generation inputs are unavailable"));
        };
        let custody = OriginalHostInitialOperation::publish(&self.operation, inputs)?;
        require_original_session(&self.session, self.end)?;
        self.phase = InitialHostPhase::Ready(custody);
        Ok(())
    }

    /// A protected fact about this operation only. Prepared is not a proof of
    /// an unused nonce; Published is not a new permission or a fresh Ready value.
    pub fn read_original_generation(&self) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        require_original_session(&self.session, self.end)?;
        let readback = match &self.phase {
            InitialHostPhase::Ready(custody) =>
                OriginalRootInitialGenerationCustodyV1::read_original_operation(custody)?,
            InitialHostPhase::Fresh(_) | InitialHostPhase::ReadbackRequired =>
                OriginalHostInitialOperation::read_original(&self.operation)?,
        };
        OriginalHostInitialOperation::require_observed(&self.operation, &readback)?;
        require_original_session(&self.session, self.end)?;
        Ok(readback)
    }

    /// Explicit recovery after an uncertain attempt. New arguments must be
    /// the original selection and existing target; the original factory checks
    /// their complete binding, journal, Artifact, consumed FinalUse and CURRENT.
    /// The original absolute end is retained and no prepare fallback exists.
    pub fn recover_original_generation(
        &mut self,
        selected: AgentdSelectedGenerationV1,
        target: AgentdGenerationUpdateTargetV1<W>,
    ) -> Result<(), AgentdError> {
        if !matches!(self.phase, InitialHostPhase::ReadbackRequired) {
            return Err(invalid("original generation readback recovery is not required"));
        }
        require_original_session(&self.session, self.end)?;
        let custody = OriginalHostInitialOperation::recover(&self.operation, selected, target)?;
        require_original_session(&self.session, self.end)?;
        self.phase = InitialHostPhase::Ready(custody);
        Ok(())
    }
}

fn require_original_session(
    session: &PreparedHostAuthoritySession,
    end: Instant,
) -> Result<(), AgentdError> {
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0
        || Instant::now() >= end
    {
        return Err(invalid("original Root generation session ended"));
    }
    verify_pinned_process(
        &session.registration,
        session.config.peer_uid,
        session.config.peer_gid,
        &session.owner_pidfd,
        end,
    )?;
    Ok(())
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

impl PreparedHostAuthoritySession {
    /// Derive the full original request for an existing authorized issuer.
    /// This is data, not material authorization or a promise of publication.
    /// The target and selected generation stay with their original caller;
    /// no CURRENT, Prepared value, owner, grant or writer is returned.
    pub fn original_initial_generation_request<W: AnchorWitnessStore>(
        &self,
        selected: &AgentdSelectedGenerationV1,
        target: &AgentdGenerationUpdateTargetV1<W>,
        request: &AgentdGenerationUpdateRequestV1,
    ) -> Result<codex_hepta_contracts::FinalUseBinding, AgentdError> {
        let end = Instant::now() + Duration::from_millis(self.config.timeout_ms);
        require_original_session(self, end)?;
        let binding = crate::HostAuthorityService::read_original_initial_request(
            &self.service, selected, target, request, end,
        )?;
        require_original_session(self, end)?;
        Ok(binding)
    }
}
