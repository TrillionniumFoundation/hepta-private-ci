//! A stable installed read port borrows the actual retained composition owner.
use super::AgentdConfig;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdState;
use codex_hepta_agent_components::types::Digest32;
use std::sync::Arc;

pub trait AgentdPreparedGenerationReaderV2: Send + Sync {
    /// Missing is unknown. This port never constructs or restores a generation.
    fn read(
        &self,
        generation: u64,
        configuration: Digest32,
        body: Digest32,
    ) -> Result<Option<Vec<u8>>, AgentdError>;
}
impl AgentdConfig {
    pub fn with_prepared_generation_reader(
        mut self,
        reader: Arc<dyn AgentdPreparedGenerationReaderV2>,
    ) -> Result<Self, AgentdError> {
        if self.prepared_generation_reader.is_some() {
            return Err(AgentdError::Invalid(
                "original prepared reader already installed".into(),
            ));
        }
        self.prepared_generation_reader = Some(reader);
        Ok(self)
    }
    pub(crate) fn take_prepared_generation_reader(
        &mut self,
    ) -> Option<Arc<dyn AgentdPreparedGenerationReaderV2>> {
        self.prepared_generation_reader.take()
    }
}
impl AgentdState {
    pub(crate) fn prepared_generation(
        &self,
        generation: u64,
        configuration_digest: String,
        body_digest: String,
    ) -> Result<AgentdPayload, AgentdError> {
        if generation == 0 {
            return Err(AgentdError::Invalid("prepared generation identity".into()));
        }
        let configuration: Digest32 = configuration_digest
            .parse()
            .map_err(|e| AgentdError::Invalid(format!("{e}")))?;
        let body: Digest32 = body_digest
            .parse()
            .map_err(|e| AgentdError::Invalid(format!("{e}")))?;
        if configuration.is_zero() || body.is_zero() {
            return Err(AgentdError::Invalid("prepared generation tuple".into()));
        }
        let reader = self
            .prepared_generation_reader
            .get()
            .ok_or_else(|| AgentdError::Invalid("original prepared reader unavailable".into()))?;
        let prepared = reader.read(generation, configuration, body)?;
        let prepared_hex = prepared
            .map(|bytes| {
                if bytes.len()
                    > codex_hepta_agent_components::neuron::MAX_NEURON_PREPARED_GENERATION_BYTES_V2
                {
                    return Err(AgentdError::Protocol(
                        "whole prepared generation exceeds bound".into(),
                    ));
                }
                let packet =
                    codex_hepta_agent_components::neuron::NeuronPreparedGenerationV2::from_bytes(
                        bytes.clone(),
                        Digest32::of_bytes(&bytes),
                    )
                    .map_err(|e| AgentdError::Protocol(format!("original prepared packet: {e}")))?;
                if packet.material().runtime.generation.get() != generation
                    || packet.material().runtime.semantic_digest().ok() != Some(configuration)
                    || packet.material().body.semantic_digest().ok() != Some(body)
                {
                    return Err(AgentdError::Protocol(
                        "original prepared packet tuple changed".into(),
                    ));
                }
                Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
            })
            .transpose()?;
        Ok(AgentdPayload::PreparedGenerationV2 {
            generation,
            configuration_digest,
            body_digest,
            prepared_hex,
        })
    }
}

// The final Canary selector delegates this finite case to the same whole slot.
pub(crate) fn response_limit(method: &crate::AgentdMethod) -> u64 {
    if matches!(method, crate::AgentdMethod::PreparedGenerationV2 { .. }) {
        2 * codex_hepta_agent_components::neuron::MAX_NEURON_PREPARED_GENERATION_BYTES_V2 as u64
            + 8192
    } else {
        crate::MAX_CONTROL_FRAME_BYTES
    }
}
