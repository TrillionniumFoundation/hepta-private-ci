//! Root-only transport of factual state from the original Round/Neuron owners.
use super::*;
impl AgentdState {
    fn checkpoint_generation(&self) -> Result<u64, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || !runtime.critical_stores_ready
            || !runtime.revocation_ready
            || !runtime.required_ports_ready
            || !runtime.admission_open
            || runtime.draining
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "checkpoint requires healthy actual Running Agent".into(),
            ));
        }
        Ok(runtime.current_generation)
    }
    pub(crate) async fn inspect_parameter_serving_scope(
        &self,
        expected_generation: u64,
        round_hex: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let generation = self.checkpoint_generation()?;
        if generation != expected_generation {
            return Err(AgentdError::GenerationFenced(
                "scope prior runtime generation changed".into(),
            ));
        }
        let round = crate::AgentdSelfIterationRoundV1::decode(
            &crate::parameter_checkpoint::decode_hex(&round_hex, 4096)?,
        )?;
        let host = self
            .neuron_runtime_v2
            .get()
            .cloned()
            .ok_or_else(|| AgentdError::Invalid("same held Neuron unavailable".into()))?;
        let handle = self
            .self_iteration_handle
            .get()
            .ok_or_else(|| AgentdError::Invalid("same original Round owner unavailable".into()))?;
        let result = handle.inspect_parameter_serving_scope(host, round).await?;
        if self.checkpoint_generation()? != generation {
            return Err(AgentdError::GenerationFenced(
                "scope runtime generation changed".into(),
            ));
        }
        Ok(crate::AgentdPayload::ParameterServingScopeV1(
            codex_hepta_contracts::ParameterServingScopeV1 {
                round_hex: crate::client::encode_hex(&result.round.canonical_bytes()?),
                neuron_generation: result.neuron_generation,
                configuration_digest: result.configuration_digest.to_string(),
                body_bundle_digest: result.body_bundle_digest.to_string(),
                scope_digest: result.scope.scope_digest.to_string(),
                objective_digest: result.scope.objective_digest.to_string(),
                goal_ordinal: result.goal_ordinal,
            },
        ))
    }
    pub(crate) async fn prepare_parameter_checkpoint(
        &self,
        expected_generation: u64,
        round_hex: String,
        path: std::path::PathBuf,
        material_digest: String,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        let generation = self.checkpoint_generation()?;
        if generation != expected_generation {
            return Err(AgentdError::GenerationFenced(
                "checkpoint prior runtime generation changed".into(),
            ));
        }
        let round = crate::AgentdSelfIterationRoundV1::decode(
            &crate::parameter_checkpoint::decode_hex(&round_hex, 4096)?,
        )?;
        let pin: Digest32 = material_digest
            .parse()
            .map_err(|e| AgentdError::Invalid(format!("{e}")))?;
        let host = self
            .neuron_runtime_v2
            .get()
            .cloned()
            .ok_or_else(|| AgentdError::Invalid("same held Neuron unavailable".into()))?;
        let handle = self
            .self_iteration_handle
            .get()
            .ok_or_else(|| AgentdError::Invalid("same original Round owner unavailable".into()))?;
        let result = handle
            .prepare_parameter_checkpoint(host, round, path, pin)
            .await?;
        if self.checkpoint_generation()? != generation {
            return Err(AgentdError::GenerationFenced(
                "checkpoint runtime generation changed".into(),
            ));
        }
        let payload = crate::AgentdPayload::PreparedParameterCheckpointV1 {
            round_hex: crate::client::encode_hex(&result.round.canonical_bytes()?),
            neuron_generation: result.neuron_generation,
            configuration_digest: result.configuration_digest.to_string(),
            body_bundle_digest: result.body_bundle_digest.to_string(),
            scope_digest: result.scope.scope_digest.to_string(),
            objective_digest: result.scope.objective_digest.to_string(),
            goal_ordinal: result.goal_ordinal,
            anchor_sequence: result.anchor.sequence,
            anchor_checkpoint_digest: result.anchor.checkpoint_digest.to_string(),
            baseline_material_digest: result.baseline_material_digest.to_string(),
            checkpoint_hex: crate::client::encode_hex(&result.checkpoint_bytes),
            checkpoint_source_digest: result.checkpoint_source_digest.to_string(),
        };
        if serde_json::to_vec(&payload)?.len() as u64 > crate::MAX_CONTROL_FRAME_BYTES {
            return Err(AgentdError::Protocol(
                "whole checkpoint exceeds original control frame".into(),
            ));
        }
        Ok(payload)
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "state_parameter_checkpoint_tests.rs"]
mod tests;
