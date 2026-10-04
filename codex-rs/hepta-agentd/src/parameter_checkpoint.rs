//! Whole current checkpoint facts. Public pins verify integrity; actual Root
//! peer authentication and the installed original owner supply origin.
use crate::AgentdError;
use crate::AgentdSelfIterationRoundV1;
use codex_hepta_agent_components::neuron::JournalAnchor;
use codex_hepta_agent_components::neuron::JournalScope;
use codex_hepta_agent_components::neuron::NeuronGenerationMaterialV2;
use codex_hepta_agent_components::neuron::SparseCheckpoint;
use codex_hepta_agent_components::types::Digest32;

/// Actual Serving facts are independent of the registered training scope.
/// The observation supplies no artifact, policy or execution authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParameterServingScopeV1 {
    pub round: AgentdSelfIterationRoundV1,
    pub neuron_generation: u64,
    pub configuration_digest: Digest32,
    pub body_bundle_digest: Digest32,
    pub scope: JournalScope,
    pub goal_ordinal: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedParameterCheckpointV1 {
    pub round: AgentdSelfIterationRoundV1,
    pub neuron_generation: u64,
    pub configuration_digest: Digest32,
    pub body_bundle_digest: Digest32,
    pub scope: JournalScope,
    pub goal_ordinal: Option<u64>,
    pub anchor: JournalAnchor,
    pub baseline_material_digest: Digest32,
    pub checkpoint_bytes: Vec<u8>,
    pub checkpoint_source_digest: Digest32,
}
impl PreparedParameterCheckpointV1 {
    /// The caller independently selects the whole baseline material. Parsing
    /// this observation grants no writer or current-use capability.
    pub fn checkpoint(
        &self,
        material: &NeuronGenerationMaterialV2,
    ) -> Result<SparseCheckpoint, AgentdError> {
        codex_hepta_agent_components::neuron::validate_neuron_generation_material_v2(material)
            .map_err(|e| AgentdError::Protocol(e.to_string()))?;
        let full_material =
            codex_hepta_agent_components::neuron::encode_neuron_generation_material_v2(material)
                .map_err(|e| AgentdError::Protocol(e.to_string()))?;
        if Digest32::of_bytes(&full_material) != self.baseline_material_digest
            || self.neuron_generation != material.runtime.generation.get()
            || material.runtime.semantic_digest().ok() != Some(self.configuration_digest)
            || material.body.semantic_digest().ok() != Some(self.body_bundle_digest)
            || self.scope != material.scope
            || self.baseline_material_digest.is_zero()
            || self.goal_ordinal == Some(0)
        {
            return Err(AgentdError::Protocol(
                "checkpoint whole baseline tuple".into(),
            ));
        }
        SparseCheckpoint::decode_observation_v1(
            &self.checkpoint_bytes,
            self.checkpoint_source_digest,
            &material.native,
            self.scope,
            self.body_bundle_digest,
            self.anchor,
        )
        .map_err(|e| AgentdError::Protocol(e.to_string()))
    }
}

pub(crate) fn decode_hex(value: &str, max: usize) -> Result<Vec<u8>, AgentdError> {
    if value.is_empty() || !value.len().is_multiple_of(2) || value.len() > max.saturating_mul(2) {
        return Err(AgentdError::Protocol("whole checkpoint hex bound".into()));
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let digit = |b| match b {
                b'0'..=b'9' => Ok(b - b'0'),
                b'a'..=b'f' => Ok(b - b'a' + 10),
                _ => Err(AgentdError::Protocol("checkpoint lowercase hex".into())),
            };
            Ok((digit(pair[0])? << 4) | digit(pair[1])?)
        })
        .collect()
}

/// Decode the sole whole original response envelope and checkpoint DTO against
/// independently supplied identity, Round and full actual Goal material. The
/// bytes authenticate no peer or custody by themselves.
pub fn decode_prepared_parameter_checkpoint_response_v3(
    bytes: &[u8],
    agent: &codex_hepta_contracts::AgentId,
    spawn_generation: u64,
    round: &AgentdSelfIterationRoundV1,
    goal_material: &NeuronGenerationMaterialV2,
) -> Result<(u64, PreparedParameterCheckpointV1), AgentdError> {
    if bytes.is_empty()
        || bytes.len() as u64 > crate::MAX_CONTROL_FRAME_BYTES
        || !bytes.ends_with(b"\n")
        || spawn_generation == 0
    {
        return Err(AgentdError::Protocol(
            "whole checkpoint response frame bound".into(),
        ));
    }
    let response: crate::AgentdResponse = serde_json::from_slice(bytes)?;
    let mut canonical = serde_json::to_vec(&response)?;
    canonical.push(b'\n');
    if canonical != bytes
        || response.schema_version != crate::AGENTD_CONTROL_SCHEMA_VERSION
        || response.agent_id != *agent
        || response.spawn_generation != spawn_generation
        || response.request_id == 0
        || response.current_generation == 0
    {
        return Err(AgentdError::Protocol(
            "checkpoint original frame identity/canonical bytes".into(),
        ));
    }
    let parse = |value: &str| {
        value
            .parse::<Digest32>()
            .map_err(|e| AgentdError::Protocol(e.to_string()))
    };
    let expected_round = crate::client::encode_hex(&round.canonical_bytes()?);
    let result = match response.payload {
        crate::AgentdPayload::PreparedParameterCheckpointV1 {
            round_hex,
            neuron_generation,
            configuration_digest,
            body_bundle_digest,
            scope_digest,
            objective_digest,
            goal_ordinal,
            anchor_sequence,
            anchor_checkpoint_digest,
            baseline_material_digest,
            checkpoint_hex,
            checkpoint_source_digest,
        } if round_hex == expected_round => PreparedParameterCheckpointV1 {
            round: round.clone(),
            neuron_generation,
            configuration_digest: parse(&configuration_digest)?,
            body_bundle_digest: parse(&body_bundle_digest)?,
            scope: JournalScope {
                scope_digest: parse(&scope_digest)?,
                objective_digest: parse(&objective_digest)?,
            },
            goal_ordinal,
            anchor: JournalAnchor {
                sequence: anchor_sequence,
                checkpoint_digest: parse(&anchor_checkpoint_digest)?,
            },
            baseline_material_digest: parse(&baseline_material_digest)?,
            checkpoint_bytes: decode_hex(
                &checkpoint_hex,
                codex_hepta_agent_components::neuron::MAX_SPARSE_CHECKPOINT_OBSERVATION_BYTES_V1,
            )?,
            checkpoint_source_digest: parse(&checkpoint_source_digest)?,
        },
        crate::AgentdPayload::Error { code, message } => {
            return Err(AgentdError::Protocol(format!(
                "agentd rejected request ({code}): {message}"
            )));
        }
        _ => {
            return Err(AgentdError::Protocol(
                "checkpoint original payload/Round differs".into(),
            ));
        }
    };
    if result.anchor.sequence == 0
        || result.anchor.checkpoint_digest.is_zero()
        || result.checkpoint_source_digest.is_zero()
    {
        return Err(AgentdError::Protocol(
            "checkpoint original acknowledged anchor invalid".into(),
        ));
    }
    result.checkpoint(goal_material)?;
    Ok((response.current_generation, result))
}
