//! Original whole live canary facts. Portable integrity does not grant authority.
use crate::AgentdError;
use crate::AgentdMethod;
use crate::CanaryOperationQueryV2;
use codex_hepta_agent_components::neuron::JournalScope;
use codex_hepta_agent_components::neuron::MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2;
use codex_hepta_agent_components::neuron::NeuronAcknowledgedOperationV2;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;

// The original binary owner defines the whole record limit. Only this finite
// method gets hex expansion plus a bounded query/response identity envelope.
pub(crate) const MAX_CANARY_RESPONSE_BYTES_V2: u64 =
    (2 * MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2 + 4096) as u64;

pub(crate) const MAX_COMPLETED_PROPOSAL_RESPONSE_BYTES_V1: u64 =
    (2 * codex_hepta_agent_components::plasticity::MAX_COMPLETED_PROPOSAL_BYTES_V1 + 8192) as u64;

pub(crate) fn response_limit(method: &AgentdMethod) -> u64 {
    match method {
        AgentdMethod::PrepareParameterDatasetWindowV3 { .. } => crate::plasticity_runtime::parameter_dataset::parameter_dataset_window::MAX_DATASET_WINDOW_RESPONSE_BYTES_V3,
        AgentdMethod::PreparedGenerationV2 { .. } => {
            crate::prepared_generation_response_limit(method)
        }
        AgentdMethod::CanaryOperationReceipt { .. } => MAX_CANARY_RESPONSE_BYTES_V2,
        AgentdMethod::PlasticityCompletedProposal { .. } => {
            MAX_COMPLETED_PROPOSAL_RESPONSE_BYTES_V1
        }
        _ => crate::MAX_CONTROL_FRAME_BYTES,
    }
}

pub(crate) fn digest(value: &str) -> Result<Digest32, AgentdError> {
    let digest: Digest32 = value
        .parse()
        .map_err(|_| AgentdError::Invalid("canary digest".into()))?;
    if digest.is_zero() || digest.to_string() != value {
        return Err(AgentdError::Invalid(
            "canary digest must be nonzero canonical hex".into(),
        ));
    }
    Ok(digest)
}

pub(crate) fn validate_query(query: &CanaryOperationQueryV2) -> Result<(), AgentdError> {
    if query.model_generation == 0 || query.tick_id.len() > 256 {
        return Err(AgentdError::Invalid("canary operation identity".into()));
    }
    StableId::new(&query.tick_id)
        .map_err(|_| AgentdError::Invalid("canary tick identity".into()))?;
    for value in [
        &query.configuration_digest,
        &query.body_digest,
        &query.scope_digest,
        &query.objective_digest,
        &query.input_semantic_digest,
    ] {
        digest(value)?;
    }
    Ok(())
}

pub(crate) fn decode_receipt(
    query: &CanaryOperationQueryV2,
    receipt_hex: &str,
    source_digest: &str,
) -> Result<NeuronAcknowledgedOperationV2, AgentdError> {
    validate_query(query)?;
    if receipt_hex.is_empty()
        || !receipt_hex.len().is_multiple_of(2)
        || receipt_hex.len() > 2 * MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2
        || !receipt_hex
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(AgentdError::Protocol(
            "canary receipt is not a whole bounded lowercase hex record".into(),
        ));
    }
    let bytes = receipt_hex
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            fn nibble(b: u8) -> u8 {
                if b <= b'9' { b - b'0' } else { b - b'a' + 10 }
            }
            (nibble(pair[0]) << 4) | nibble(pair[1])
        })
        .collect();
    let receipt = NeuronAcknowledgedOperationV2::from_bytes(bytes, digest(source_digest)?)
        .map_err(|_| AgentdError::Protocol("original canary receipt integrity rejected".into()))?;
    let scope = JournalScope {
        scope_digest: digest(&query.scope_digest)?,
        objective_digest: digest(&query.objective_digest)?,
    };
    if receipt.generation() != query.model_generation
        || receipt.scope() != scope
        || receipt.record().config_semantic_digest != digest(&query.configuration_digest)?
        || receipt.record().body_bundle_digest != digest(&query.body_digest)?
        || receipt.commit().key.tick_id.as_str() != query.tick_id
        || receipt.commit().key.input_semantic_digest != digest(&query.input_semantic_digest)?
    {
        return Err(AgentdError::Protocol(
            "original canary receipt does not match exact query".into(),
        ));
    }
    Ok(receipt)
}

#[cfg(feature = "server")]
impl crate::AgentdState {
    pub(crate) fn canary_operation_receipt(
        &self,
        query: CanaryOperationQueryV2,
    ) -> Result<crate::AgentdPayload, AgentdError> {
        validate_query(&query)?;
        let host = self
            .neuron_runtime_v2
            .get()
            .ok_or_else(|| AgentdError::Invalid("original canary owner unavailable".into()))?;
        let generation =
            crate::neuron_runtime_v2::AgentdNeuronGenerationIdV2::new(query.model_generation)
                .map_err(|_| AgentdError::Invalid("canary generation".into()))?;
        let operation = crate::neuron_runtime_v2::AgentdNeuronOperationIdentityV2::new(
            StableId::new(&query.tick_id)
                .map_err(|_| AgentdError::Invalid("canary tick".into()))?,
            digest(&query.input_semantic_digest)?,
        )
        .map_err(|_| AgentdError::Invalid("canary operation".into()))?;
        let receipt = host.export_current_operation_v2(
            generation,
            digest(&query.configuration_digest)?,
            digest(&query.body_digest)?,
            JournalScope {
                scope_digest: digest(&query.scope_digest)?,
                objective_digest: digest(&query.objective_digest)?,
            },
            &operation,
        )?;
        let source_digest = Digest32::of_bytes(receipt.bytes()).to_string();
        let receipt_hex = crate::client::encode_hex(receipt.bytes());
        Ok(crate::AgentdPayload::CanaryOperationReceipt {
            query,
            source_digest,
            receipt_hex,
        })
    }
}
