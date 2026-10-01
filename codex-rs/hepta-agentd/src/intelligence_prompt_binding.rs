//! Exact binding between Prompt Registry realization, context compilation and
//! the physical App Server payload retained by a prepared intelligence run.

use std::collections::BTreeSet;

use codex_hepta_intelligence::PreparedPromptDeliveryV1;
use codex_hepta_types::Digest32;

use super::CanonicalIntelligenceError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct PromptDeliveryBindingV1 {
    pub(crate) prompt_stage_digest: Digest32,
    pub(crate) context_attachment_digest: Digest32,
    pub(crate) payload_digest: Digest32,
}

pub(crate) fn validate_prompt_delivery_v1(
    delivery: &PreparedPromptDeliveryV1,
) -> Result<PromptDeliveryBindingV1, CanonicalIntelligenceError> {
    delivery
        .validate()
        .map_err(|_| CanonicalIntelligenceError::InvalidSnapshot("prompt owner lineage"))?;
    delivery
        .materialization
        .validate()
        .map_err(|_| CanonicalIntelligenceError::InvalidSnapshot("prompt materialization"))?;
    delivery
        .serialization_proof
        .validate()
        .map_err(|_| CanonicalIntelligenceError::InvalidSnapshot("prompt serialization proof"))?;

    if delivery.serialized_payload.is_empty() || delivery.serialized_payload.len() > 32_768 {
        return Err(CanonicalIntelligenceError::InvalidSnapshot(
            "physical prompt payload",
        ));
    }
    let payload_digest = Digest32::of_bytes(&delivery.serialized_payload);
    if delivery.serialized_context.payload() != delivery.serialized_payload.as_slice()
        || delivery.serialized_context.receipt() != &delivery.serialization
        || delivery.serialization.payload_digest() != payload_digest
        || delivery.attachment.payload_digest() != payload_digest
        || delivery.serialization_proof.serialized_payload_digest != payload_digest
        || delivery.serialization_proof.materialization_bundle_digest
            != delivery.materialization.bundle_digest
        || delivery.exercise.receipt_digest.is_zero()
        || delivery.serialization.receipt_digest().is_zero()
        || delivery.attachment.attachment_digest().is_zero()
        || delivery.exercise.authority.grants_any()
        || delivery.serialization.authority().grants_any()
        || delivery.attachment.authority().grants_any()
    {
        return Err(CanonicalIntelligenceError::InvalidSnapshot(
            "prompt/context physical binding",
        ));
    }

    let selected = delivery
        .attachment
        .selected_item_ids()
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let materialized = delivery
        .materialization
        .payloads
        .iter()
        .map(|value| value.binding.realization_id.clone())
        .collect::<BTreeSet<_>>();
    if !materialized.is_subset(&selected) {
        return Err(CanonicalIntelligenceError::InvalidSnapshot(
            "prompt realization membership",
        ));
    }

    let mut bytes = b"hepta.agentd.intelligence-prompt-stage.v1\0".to_vec();
    bytes.extend_from_slice(delivery.exercise.receipt_digest.as_array());
    bytes.extend_from_slice(delivery.serialization_proof.proof_digest.as_array());
    bytes.extend_from_slice(delivery.materialization.bundle_digest.as_array());
    bytes.extend_from_slice(delivery.serialization.receipt_digest().as_array());
    bytes.extend_from_slice(delivery.attachment.attachment_digest().as_array());
    bytes.extend_from_slice(payload_digest.as_array());
    Ok(PromptDeliveryBindingV1 {
        prompt_stage_digest: Digest32::of_bytes(&bytes),
        context_attachment_digest: delivery.attachment.attachment_digest(),
        payload_digest,
    })
}

pub(crate) fn prompt_conditioned_state_digest_v1(
    neural_digest: Digest32,
    prompt_stage_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.intelligence-prompt-conditioned-state.v1\0".to_vec();
    bytes.extend_from_slice(neural_digest.as_array());
    bytes.extend_from_slice(prompt_stage_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prompt_conditioned_state_rejects_either_stage_substitution() {
        let neural = Digest32::of_bytes(b"neural");
        let prompt = Digest32::of_bytes(b"prompt");
        let baseline = prompt_conditioned_state_digest_v1(neural, prompt);
        assert_ne!(
            baseline,
            prompt_conditioned_state_digest_v1(Digest32::of_bytes(b"other-neural"), prompt)
        );
        assert_ne!(
            baseline,
            prompt_conditioned_state_digest_v1(neural, Digest32::of_bytes(b"other-prompt"))
        );
    }
}
