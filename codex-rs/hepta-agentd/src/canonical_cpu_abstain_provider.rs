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
