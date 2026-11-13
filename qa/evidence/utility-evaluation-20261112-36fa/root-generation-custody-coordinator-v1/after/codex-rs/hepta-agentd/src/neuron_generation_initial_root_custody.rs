//! One original first-generation operation retained by the trusted Root host.
//!
//! This is local custody, not a remote CURRENT proxy or another grant issuer.
//! Preparation still comes from the original Root factory. Publication consumes
//! that original value once; a lost acknowledgement leaves only the same
//! operation's readback and the original explicit recovery path.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::PreparedAgentdGenerationInitialV1;
use super::recover_agentd_generation_initial_v1;
use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;
use crate::neuron_generation_initial_bootstrap::ReadyAgentdGenerationInitialV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

#[path = "neuron_generation_initial_root_task.rs"]
mod task;

pub use task::OriginalRootCircuitTaskCustodyV1;
pub use task::OriginalRootCircuitTaskInputsV1;
pub use task::OriginalRootCircuitTaskRuntimeV1;
pub use task::OriginalRootInitialInstallationErrorV1;

/// The actual original publication inputs, never a cached readiness flag.
enum InitialPhase<W: AnchorWitnessStore> {
    Prepared(Box<PreparedAgentdGenerationInitialV1<W>>),
    Ready(Box<ReadyAgentdGenerationInitialV1<W>>),
    ReadbackRequired,
}

/// A fixed protected operation and its actual existing owners. The concrete
/// CURRENT and authority Arcs never leave this module through a public getter.
struct OriginalInitialOperation {
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    recovery: AgentdGenerationUpdateRecoveryV1,
    binding: FinalUseBinding,
}

impl OriginalInitialOperation {
    fn read_original(&self) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        require_root()?;
        let original = self.current.recover_initial_operation(
            &self.recovery.operation_id,
            self.recovery.intent_digest,
        )?;
        if original.final_use_binding() != &self.binding {
            return Err(invalid("original initial operation binding changed"));
        }
        self.current.read_initial_operation(&original)
    }
}

/// Non-Clone custody for one original prepared initial generation. A protected
/// Prepared or Published readback is a fact with DENY_ALL posture, not permission
/// to redispatch a grant, replace a journal, or bypass the retained live owners.
pub struct OriginalRootInitialGenerationCustodyV1<W: AnchorWitnessStore> {
    operation: OriginalInitialOperation,
    phase: InitialPhase<W>,
}

impl<W: AnchorWitnessStore> OriginalRootInitialGenerationCustodyV1<W> {
    /// Consume the original result of `prepare_agentd_generation_initial_v1`.
    /// The supplied operation name is checked against the actual protected
    /// Current record and the original opaque preparation before it is retained.
    pub fn from_original_prepared(
        prepared: PreparedAgentdGenerationInitialV1<W>,
        operation_id: String,
    ) -> Result<Self, AgentdError> {
        require_root()?;
        StableId::new(&operation_id).map_err(invalid)?;
        let current = Arc::clone(&prepared.current);
        let intent_digest = prepared.intent_digest();
        let original = current.recover_initial_operation(&operation_id, intent_digest)?;
        if original.final_use_binding() != prepared.final_use_binding()
            || original.target() != prepared.prepared.target()
        {
            return Err(invalid("Root custody differs from the original preparation"));
        }
        let operation = OriginalInitialOperation {
            current,
            authorities: prepared.authorities.clone(),
            recovery: AgentdGenerationUpdateRecoveryV1 {
                operation_id,
                intent_digest,
            },
            binding: prepared.final_use_binding().clone(),
        };
        operation.read_original()?;
        Ok(Self {
            operation,
            phase: InitialPhase::Prepared(Box::new(prepared)),
        })
    }

    #[must_use]
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        &self.operation.binding
    }

    #[must_use]
    pub fn intent_digest(&self) -> Digest32 {
        self.operation.recovery.intent_digest
    }

    /// Query only this operation in the original protected store. Prepared does
    /// not establish NotApplied or an unused nonce. Published does not construct
    /// a Ready owner; recovery must still verify Artifact, FinalUse and journal.
    pub fn read_original_operation(
        &self,
    ) -> Result<NeuronGenerationInitialReadbackV1, AgentdError> {
        self.operation.read_original()
    }

    /// Consume the original Prepared value at most once. All errors leave the
    /// operation in ReadbackRequired, including failures after a real claim or
    /// publication CAS. This method never restores Prepared or issues a grant.
    pub fn publish(&mut self, signed: &SignedFinalUseGrant) -> Result<(), AgentdError> {
        if !matches!(self.phase, InitialPhase::Prepared(_)) {
            return Err(invalid("original publication was already consumed"));
        }
        let phase = std::mem::replace(&mut self.phase, InitialPhase::ReadbackRequired);
        require_root()?;
        let InitialPhase::Prepared(prepared) = phase else {
            return Err(invalid("original initial preparation is unavailable"));
        };
        // The original publish owns its Artifact lock scope and constructs the
        // original LiveGenerationCurrent only after that guard is released.
        let ready = (*prepared).publish(signed)?;
        self.phase = InitialPhase::Ready(Box::new(ready));
        Ok(())
    }

    /// Reopen only the existing published journal of the same operation. The
    /// same Current, Artifact, FinalUse and clock Arcs remain held. A pending
    /// protected record remains an error, with no prepare or publish fallback.
    pub fn recover_original(
        &mut self,
        selected: AgentdSelectedGenerationV1,
        target: AgentdGenerationUpdateTargetV1<W>,
    ) -> Result<(), AgentdError> {
        if !matches!(self.phase, InitialPhase::ReadbackRequired) {
            return Err(invalid("original publication recovery is not required"));
        }
        require_root()?;
        let ready = recover_agentd_generation_initial_v1(
            Arc::clone(&self.operation.current),
            self.operation.authorities.clone(),
            selected,
            target,
            AgentdGenerationUpdateRecoveryV1 {
                operation_id: self.operation.recovery.operation_id.clone(),
                intent_digest: self.operation.recovery.intent_digest,
            },
        )?;
        self.phase = InitialPhase::Ready(Box::new(ready));
        Ok(())
    }
}

fn require_root() -> Result<(), AgentdError> {
    // The existing Root directory/current factories remain authoritative.
    // This additional local boundary rejects a process that dropped Root UID.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(invalid("original generation custody requires the Root host"));
    }
    Ok(())
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
