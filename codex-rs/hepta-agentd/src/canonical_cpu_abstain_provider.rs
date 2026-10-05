//! Conservative canonical owners with the actual installed CPU generation.
//! Physical features are built only by the attached durable V2 neural stage.
use super::*;
use codex_hepta_agent_components::neuron::SparseConfig;

#[derive(Clone)]
pub struct AgentdDurableCpuAbstainInvocationProviderV2 {
    base: AgentdDurableAbstainInvocationProviderV1,
    native: SparseConfig,
    runtime_config_digest: Digest32,
    runtime_body_digest: Digest32,
    inactive_state: Option<InactiveStateSource>,
}

#[derive(Clone)]
enum InactiveStateSource {
    Fixed(crate::ConservativeCpuStateV1),
    Current(Arc<dyn Fn() -> Result<crate::ConservativeCpuStateV1, AgentdError> + Send + Sync>),
}

/// Read-only facts, not an objective or model-use admission capability.
pub struct ConservativeCpuGoalBindingsV1 {
    pub state: crate::ConservativeCpuStateV1,
    pub model_tuple_digest: Digest32,
    pub runtime_body_digest: Digest32,
    pub authority_epoch: u64,
    pub owners: Vec<OwnerBindingV1>,
    pub revocation_frontier_digest: Digest32,
}

impl AgentdDurableCpuAbstainInvocationProviderV2 {
    /// The installed composition supplies the configuration of its actual
    /// handle. Current signed owner records independently pin that same handle.
    pub fn new(
        authority_file: PathBuf,
        authority_verifier: IntelligenceAuthorityVerifierV1,
        native: SparseConfig,
        runtime_config_digest: Digest32,
        runtime_body_digest: Digest32,
    ) -> Result<Self, AgentdError> {
        native
            .digest()
            .map_err(|error| invalid(&error.to_string()))?;
        if runtime_config_digest.is_zero() || runtime_body_digest.is_zero() {
            return Err(invalid("installed CPU configuration or body is absent"));
        }
        Ok(Self {
            base: AgentdDurableAbstainInvocationProviderV1::new(
                authority_file,
                authority_verifier,
            )?,
            native,
            runtime_config_digest,
            runtime_body_digest,
            inactive_state: None,
        })
    }

    /// Explicit new mode: the native zero-utility genesis and empty prompt
    /// registry are inactive. Legacy V2 input bindings remain unchanged.
    pub fn with_inactive_state(mut self, state: crate::ConservativeCpuStateV1) -> Self {
        self.inactive_state = Some(InactiveStateSource::Fixed(state));
        self
    }

    /// Borrow the installed factory's existing sealed CURRENT admission. The
    /// callback is read-only and is refreshed for every actual invocation.
    pub fn with_current_inactive_state(
        mut self,
        reader: Arc<dyn Fn() -> Result<crate::ConservativeCpuStateV1, AgentdError> + Send + Sync>,
    ) -> Self {
        self.inactive_state = Some(InactiveStateSource::Current(reader));
        self
    }

    pub fn current_goal_bindings(
        &self,
        expected_epoch: u64,
    ) -> Result<ConservativeCpuGoalBindingsV1, AgentdError> {
        let state = match &self.inactive_state {
            Some(InactiveStateSource::Fixed(state)) => state.clone(),
            Some(InactiveStateSource::Current(reader)) => reader()?,
            None => {
                return Err(invalid(
                    "legacy CPU profile has no closed inactive bindings",
                ));
            }
        };
        let (owners, frontier) = current_owner_bindings(
            self.base.authority_file.clone(),
            self.base.authority_verifier.clone(),
            expected_epoch,
        )?;
        let neuron = owners
            .iter()
            .find(|owner| owner.owner_id.as_str() == "neuron.runtime")
            .ok_or_else(|| invalid("current CPU owner is absent"))?;
        if neuron.generation != self.native.generation
            || neuron.implementation_digest != self.runtime_config_digest
        {
            return Err(invalid(
                "current signed CPU owner differs from installed handle",
            ));
        }
        Ok(ConservativeCpuGoalBindingsV1 {
            state,
            model_tuple_digest: self.native.model_digest,
            runtime_body_digest: self.runtime_body_digest,
            authority_epoch: expected_epoch,
            owners,
            revocation_frontier_digest: frontier,
        })
    }
}

impl AgentdIntelligenceInvocationProviderV1 for AgentdDurableCpuAbstainInvocationProviderV2 {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        // Retain the existing durable RunStart/process fence and deadline gates.
        let mut invocation = self.base.build(identity, record)?;
        if record.runtime_body_digest != self.runtime_body_digest
            || record.snapshot.model_tuple_digest != self.native.model_digest
        {
            return Err(invalid(
                "RunStart does not describe this installed CPU body/model",
            ));
        }
        let current_bindings = self
            .inactive_state
            .as_ref()
            .map(|_| self.current_goal_bindings(record.snapshot.authority_epoch))
            .transpose()?;
        if let Some(binding) = &current_bindings
            && (binding.state.subject_id().as_str() != identity.agent_id.as_str()
                || record.snapshot.preference_state_digest
                    != binding.state.preference_state_digest()
                || record.snapshot.prompt_registry_digest != binding.state.prompt_registry_digest()
                || record.snapshot.artifact_set_digest != binding.state.artifact_set_digest())
        {
            return Err(invalid("RunStart differs from actual inactive CPU state"));
        }
        let (owners, frontier) = current_owner_bindings(
            self.base.authority_file.clone(),
            self.base.authority_verifier.clone(),
            record.snapshot.authority_epoch,
        )?;
        let neuron = owners
            .iter()
            .find(|owner| owner.owner_id.as_str() == "neuron.runtime")
            .ok_or_else(|| invalid("current CPU owner is absent"))?;
        if neuron.generation != self.native.generation
            || neuron.implementation_digest != self.runtime_config_digest
        {
            return Err(invalid(
                "current signed CPU owner differs from the installed handle",
            ));
        }
        let mut bytes = b"hepta.agentd.cpu-safe-abstain.configuration.v2\0".to_vec();
        bytes.extend_from_slice(configuration_digest(identity, record, frontier).as_array());
        bytes.extend_from_slice(
            self.native
                .digest()
                .map_err(|error| invalid(&error.to_string()))?
                .as_array(),
        );
        bytes.extend_from_slice(self.runtime_config_digest.as_array());
        bytes.extend_from_slice(self.runtime_body_digest.as_array());
        let snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
            objective_digest: record.snapshot.objective_digest,
            authority_epoch: record.snapshot.authority_epoch,
            body_generation: self.native.generation,
            configuration_digest: Digest32::of_bytes(&bytes),
            revocation_frontier_digest: frontier,
            owner_bindings: owners,
        })
        .map_err(|error| invalid(&format!("installed CPU snapshot: {error}")))?;
        let support = bound_digest(
            b"hepta.agentd.safe-abstain.candidate.v1\0",
            record,
            snapshot.digest(),
        );
        invocation.request.legal_candidates.grammar_digest = bound_digest(
            b"hepta.agentd.safe-abstain.grammar.v1\0",
            record,
            snapshot.digest(),
        );
        invocation
            .request
            .legal_candidates
            .candidates
            .first_mut()
            .ok_or_else(|| invalid("conservative candidate is absent"))?
            .support_digest = support;
        let mut inputs = owner_inputs(
            record,
            &snapshot,
            id("abstain")?,
            support,
            wall_clock_micros()?,
        )?;
        inputs.run_identity = invocation.inputs.run_identity;
        inputs.neural_config = self.native.clone();
        if self.inactive_state.is_some() {
            // The empty native registry owns no admitted factors. Do not invent
            // a prompt candidate or claim an active registry in this mode.
            inputs.prompt_request.candidates.clear();
        }
        // The durable stage replaces the pure SDK tick. Empty drives cannot be
        // accidentally dispatched as a fabricated physical input by a pure port.
        inputs.neural_tick.drive_q24.clear();
        inputs.neural_tick.prediction_q24.clear();
        invocation.request.snapshot = snapshot;
        invocation.inputs = inputs;
        Ok(invocation)
    }
}

#[cfg(test)]
#[path = "canonical_cpu_abstain_provider_tests.rs"]
mod tests;
