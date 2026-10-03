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
