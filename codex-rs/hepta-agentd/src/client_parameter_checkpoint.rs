use super::*;
use codex_hepta_agent_components::neuron::JournalScope;
use codex_hepta_agent_components::neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_agent_components::neuron::decode_neuron_generation_material_v2;
use codex_hepta_agent_components::types::Digest32;
impl AgentdClient {
    /// Inspect the actual serving Goal independently of registered training material.
    pub async fn inspect_parameter_serving_scope_v1(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
    ) -> Result<(u64, crate::ParameterServingScopeV1), AgentdError> {
        let (generation, scope, _bytes) = self
            .inspect_parameter_serving_scope_source_v1(round)
            .await?;
        Ok((generation, scope))
    }

    /// Exact validated original neutral response frame from the same one query.
    /// Bytes retain the original request identity and newline; they are never rebuilt.
    pub async fn inspect_parameter_serving_scope_source_v1(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
    ) -> Result<(u64, crate::ParameterServingScopeV1, Vec<u8>), AgentdError> {
        let round_hex = encode_hex(&round.canonical_bytes()?);
        let (response, response_bytes) = self
            .send_original_response(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::InspectParameterServingScopeV1 {
                    round_hex: round_hex.clone(),
                },
            })
            .await?;
        let parse = |value: &str| {
            value
                .parse::<Digest32>()
                .map_err(|e| AgentdError::Protocol(format!("{e}")))
        };
        let result = match response.payload {
            AgentdPayload::ParameterServingScopeV1(
                codex_hepta_contracts::ParameterServingScopeV1 {
                    round_hex: actual_round,
                    neuron_generation,
                    configuration_digest,
                    body_bundle_digest,
                    scope_digest,
                    objective_digest,
                    goal_ordinal,
                },
            ) if actual_round == round_hex => {
                let result = crate::ParameterServingScopeV1 {
                    round,
                    neuron_generation,
                    configuration_digest: parse(&configuration_digest)?,
                    body_bundle_digest: parse(&body_bundle_digest)?,
                    scope: JournalScope {
                        scope_digest: parse(&scope_digest)?,
                        objective_digest: parse(&objective_digest)?,
                    },
                    goal_ordinal,
                };
                if result.neuron_generation == 0
                    || result.configuration_digest.is_zero()
                    || result.body_bundle_digest.is_zero()
                    || result.scope.scope_digest.is_zero()
                    || result.scope.objective_digest.is_zero()
                    || result.goal_ordinal == Some(0)
                {
                    return Err(AgentdError::Protocol("scope original tuple invalid".into()));
                }
                result
            }
            payload => return unexpected(payload),
        };
        Ok((response.current_generation, result, response_bytes))
    }
    /// Actual Root-only original-owner observation. Whole material is pinned
    /// independently; returned hashes grant no custody or execution authority.
    pub async fn prepare_parameter_checkpoint_v1(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        material_source: PathBuf,
        pin: Digest32,
    ) -> Result<(u64, crate::PreparedParameterCheckpointV1), AgentdError> {
        let (generation, checkpoint, _bytes) = self
            .prepare_parameter_checkpoint_source_v1(round, material_source, pin)
            .await?;
        Ok((generation, checkpoint))
    }

    /// Retain the exact bounded original response from the same single query.
    /// The original request identity and frame bytes are never reconstructed.
    pub async fn prepare_parameter_checkpoint_source_v1(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        material_source: PathBuf,
        pin: Digest32,
    ) -> Result<(u64, crate::PreparedParameterCheckpointV1, Vec<u8>), AgentdError> {
        let bytes = crate::plasticity_process_bootstrap::protected_context_bytes(
            &material_source,
            pin,
            MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
        )?;
        let material = decode_neuron_generation_material_v2(&bytes)
            .map_err(|e| AgentdError::Protocol(e.to_string()))?;
        let round_hex = encode_hex(&round.canonical_bytes()?);
        let (_response, response_bytes) = self
            .send_original_response(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::PrepareParameterCheckpointV1 {
                    round_hex: round_hex.clone(),
                    material_source: material_source.clone(),
                    material_digest: pin.to_string(),
                },
            })
            .await?;
        let (generation, result) = crate::decode_prepared_parameter_checkpoint_response_v3(
            &response_bytes,
            &self.expected_agent_id,
            self.spawn_generation,
            &round,
            &material,
        )?;
        if crate::plasticity_process_bootstrap::protected_context_bytes(
            &material_source,
            pin,
            MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64,
        )? != bytes
        {
            return Err(AgentdError::Protocol(
                "checkpoint client material changed".into(),
            ));
        }
        Ok((generation, result, response_bytes))
    }
}
