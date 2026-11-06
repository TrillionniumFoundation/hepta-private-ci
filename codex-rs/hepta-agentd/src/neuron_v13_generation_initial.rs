//! Safe first V13 guarded runtime with an explicit initial FinalUse grant.
//!
//! The original actual-file, Linux boot, prepared-worker and cost checks stay
//! closed over the same owner capabilities from admission through publication.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_initial::PreparedAgentdGenerationInitialV1;
use crate::neuron_generation_initial::prepare_agentd_generation_initial_v1;
use crate::neuron_generation_initial::recover_agentd_generation_initial_v1;
use crate::neuron_generation_initial_bootstrap::AgentdGenerationInitialRuntimeV1;
use crate::neuron_generation_initial_bootstrap::ReadyAgentdGenerationInitialV1;
use crate::neuron_generation_initial_forward::prepare_agentd_generation_initial_forward_recovery_v1;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_update_forward::AgentdGenerationForwardRecoveryV1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;
use crate::neuron_v13_generation_bootstrap::V13GenerationOwnerModeV1;
use crate::neuron_v13_generation_bootstrap::owners::V13BackendOwner;
use crate::neuron_v13_generation_update::AgentdV13GenerationUpdateInputsV1;

/// Only the original initial signature binding is exposed before publication.
pub struct PreparedAgentdV13GenerationInitialV1 {
    initial: PreparedAgentdGenerationInitialV1<FileAnchorWitnessStore>,
    backend: V13BackendOwner,
}

impl PreparedAgentdV13GenerationInitialV1 {
    pub(crate) fn from_parts(
        initial: PreparedAgentdGenerationInitialV1<FileAnchorWitnessStore>,
        backend: V13BackendOwner,
    ) -> Self {
        Self { initial, backend }
    }

    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.initial.final_use_binding()
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.initial.intent_digest()
    }

    pub fn publish(
        self,
        signed: &SignedFinalUseGrant,
    ) -> Result<ReadyAgentdV13GenerationInitialV1, AgentdError> {
        let ready = self.initial.publish(signed)?;
        Ok(ReadyAgentdV13GenerationInitialV1 {
            ready,
            backend: self.backend,
        })
    }
}

/// Retains the published first journal and its preflighted V13 control owner.
pub struct ReadyAgentdV13GenerationInitialV1 {
    ready: ReadyAgentdGenerationInitialV1<FileAnchorWitnessStore>,
    backend: V13BackendOwner,
}

impl ReadyAgentdV13GenerationInitialV1 {
    /// Recheck the actual runtime identity before charging or starting an
    /// actor. An exact same-preparation recovery appends no duplicate cost.
    pub fn into_runtime(
        mut self,
        config: AgentdConfig,
        options: AgentdGenerationUpdateRuntimeOptionsV1,
    ) -> Result<AgentdGenerationInitialRuntimeV1, AgentdError> {
        config.require_neuron_generation_profile()?;
        self.backend.validate_identity(config.identity())?;
        let binding = CellGenerationOwnerBindingV1::new(
            &self.backend.configuration().generation,
            self.backend.configuration().max_records,
        )
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        if options.queue_capacity != self.backend.configuration().queue_capacity {
            return Err(AgentdError::Invalid(
                "V13 initial runtime queue differs from its configuration".into(),
            ));
        }
        self.ready
            .record_backend_preparation(&binding, self.backend.preparation_cost()?)?;
        let (port, clock) = self.backend.spawn()?;
        self.ready
            .into_runtime(config, port, move || clock(), options)
    }
}

/// Create a first guarded owner directly in Preparing under the existing root
/// directory. This never creates an active floor before its signed publication.
pub fn prepare_agentd_v13_generation_initial_v1(
    root: Arc<RootAuthorityDirectory>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdV13GenerationInitialV1, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
    let initial = prepare_agentd_generation_initial_v1(
        root,
        authorities,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationInitialV1::from_parts(initial, backend))
}

/// Reopen an actual signed initial publication without claiming its grant again.
pub fn recover_agentd_v13_generation_initial_v1(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    expected: AgentdGenerationUpdateRecoveryV1,
) -> Result<ReadyAgentdV13GenerationInitialV1, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::Reopen)?;
    let ready = recover_agentd_generation_initial_v1(
        current,
        authorities,
        selected,
        target,
        expected,
    )?;
    Ok(ReadyAgentdV13GenerationInitialV1 { ready, backend })
}

/// Explicit operator recovery retains the actual genesis and obtains a new
/// externally signed operation; it cannot turn an uncertain claim into success.
pub fn prepare_agentd_v13_generation_initial_forward_recovery_v1(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationForwardRecoveryV1,
) -> Result<PreparedAgentdV13GenerationInitialV1, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::Reopen)?;
    let initial = prepare_agentd_generation_initial_forward_recovery_v1(
        current,
        authorities,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationInitialV1::from_parts(initial, backend))
}
