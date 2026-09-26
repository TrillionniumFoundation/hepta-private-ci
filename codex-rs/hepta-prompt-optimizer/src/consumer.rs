//! Consumer-capability-bound prompt candidate enumeration.
//!
//! A registry realization may be semantically valid while remaining impossible
//! for a concrete runtime consumer to install safely. This module filters the
//! compatible registry view before candidate selection and binds the exact
//! consumer capability digest into the resulting candidate receipt.

use std::collections::BTreeMap;
use std::fmt;

use codex_hepta_prompt_registry::MAX_REALIZATION_PAYLOAD_BYTES;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::PromptRegistry;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::canonical::EnumeratedPromptCandidatesV1;
use crate::canonical::MAX_CANONICAL_PROMPT_FACTORS;
use crate::canonical::PromptCandidateBindingV1;
use crate::canonical::PromptCandidateSetReceiptV1;
use crate::canonical::PromptEnumerationRequestV1;

const CAPABILITY_DOMAIN: &[u8] = b"hepta.prompt-consumer-capabilities.v1";
const CAPABILITY_GRAMMAR_DOMAIN: &[u8] = b"hepta.prompt-consumer-selection-grammar.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptConsumerCapabilitiesV1 {
    pub capability_id: StableId,
    pub supported_roles: Vec<PromptRoleV2>,
    pub maximum_token_cost: u32,
    pub maximum_payload_bytes: u64,
}

impl PromptConsumerCapabilitiesV1 {
    pub fn developer_instruction_runtime() -> Self {
        Self {
            capability_id: StableId::new("consumer:runtime-codex-developer-v1")
                .expect("static capability id"),
            supported_roles: vec![PromptRoleV2::DeveloperInstruction],
            maximum_token_cost: u32::MAX,
            maximum_payload_bytes: MAX_REALIZATION_PAYLOAD_BYTES as u64,
        }
    }

    pub fn validate(&self) -> Result<(), ConsumerEnumerationError> {
        if self.supported_roles.is_empty()
            || self.maximum_token_cost == 0
            || self.maximum_payload_bytes == 0
            || self.maximum_payload_bytes > MAX_REALIZATION_PAYLOAD_BYTES as u64
            || self
                .supported_roles
                .windows(2)
                .any(|window| window[0] >= window[1])
        {
            return Err(ConsumerEnumerationError::InvalidCapabilities);
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Digest32, ConsumerEnumerationError> {
        self.validate()?;
        let mut bytes = CAPABILITY_DOMAIN.to_vec();
        push_id(&mut bytes, &self.capability_id);
        push_len(&mut bytes, self.supported_roles.len());
        for role in &self.supported_roles {
            bytes.push(role_code(*role));
        }
        bytes.extend_from_slice(&self.maximum_token_cost.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_payload_bytes.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    fn supports_role(&self, role: PromptRoleV2) -> bool {
        self.supported_roles.binary_search(&role).is_ok()
    }
}

pub fn enumerate_factors_for_consumer_v1(
    registry: &PromptRegistry,
    request: PromptEnumerationRequestV1,
    capabilities: &PromptConsumerCapabilitiesV1,
) -> Result<EnumeratedPromptCandidatesV1, ConsumerEnumerationError> {
    capabilities.validate()?;
    for digest in [
        request.objective_digest,
        request.state_digest,
        request.generation_vector_digest,
        request.selection_grammar_digest,
    ] {
        if digest.is_zero() {
            return Err(ConsumerEnumerationError::InvalidRequest);
        }
    }
    if request.now_unix_ms == 0 {
        return Err(ConsumerEnumerationError::InvalidRequest);
    }
    let maximum_candidates = usize::try_from(request.maximum_candidates)
        .map_err(|_| ConsumerEnumerationError::InvalidRequest)?;
    if maximum_candidates == 0 || maximum_candidates > MAX_CANONICAL_PROMPT_FACTORS {
        return Err(ConsumerEnumerationError::InvalidRequest);
    }

    let capability_digest = capabilities.digest()?;
    let selection_grammar_digest = bind_selection_grammar(
        request.selection_grammar_digest,
        capability_digest,
    );
    let snapshot = registry
        .snapshot_v2(request.generation_vector_digest, &request.model_tuple)
        .map_err(|error| ConsumerEnumerationError::Registry(format!("{error:?}")))?;
    let compatible = registry
        .read_compatible_v2(
            &snapshot,
            request.generation_vector_digest,
            &request.model_tuple,
            request.now_unix_ms,
            request.required_factor_ids,
            MAX_CANONICAL_PROMPT_FACTORS as u32,
        )
        .map_err(|error| ConsumerEnumerationError::Registry(format!("{error:?}")))?;
    if compatible.omitted_count != 0 {
        return Err(ConsumerEnumerationError::RegistryReadIncomplete(
            compatible.omitted_count,
        ));
    }

    let mut per_factor = BTreeMap::<StableId, PromptRealizationBindingV2>::new();
    for binding in compatible.bindings {
        if !capabilities.supports_role(binding.role)
            || binding.token_cost > capabilities.maximum_token_cost
        {
            continue;
        }
        let delivery = registry
            .dereference_realization_v2(
                &binding.realization_id,
                &snapshot,
                request.generation_vector_digest,
                &request.model_tuple,
                request.now_unix_ms,
            )
            .map_err(|error| ConsumerEnumerationError::Registry(format!("{error:?}")))?;
        if u64::try_from(delivery.payload.len()).unwrap_or(u64::MAX)
            > capabilities.maximum_payload_bytes
        {
            continue;
        }
        match per_factor.get(&binding.factor_id) {
            None => {
                per_factor.insert(binding.factor_id.clone(), binding);
            }
            Some(current)
                if binding.token_cost < current.token_cost
                    || (binding.token_cost == current.token_cost
                        && binding.realization_id < current.realization_id) =>
            {
                per_factor.insert(binding.factor_id.clone(), binding);
            }
            Some(_) => {}
        }
    }

    let total = per_factor.len();
    let omitted = total.saturating_sub(maximum_candidates);
    let mut candidates = per_factor
        .into_values()
        .take(maximum_candidates)
        .map(|realization| PromptCandidateBindingV1 {
            factor_id: realization.factor_id.clone(),
            binding_digest: realization.digest(),
            realization,
        })
        .collect::<Vec<_>>();
    candidates.sort_by(|left, right| left.factor_id.cmp(&right.factor_id));

    let candidates_digest = digest_candidates(&candidates);
    let canonical_order_digest = digest_candidate_order(&candidates);
    let factor_ids = candidates
        .iter()
        .map(|candidate| candidate.factor_id.clone())
        .collect::<Vec<_>>();
    let omitted_count = u32::try_from(omitted).unwrap_or(u32::MAX);
    let receipt = PromptCandidateSetReceiptV1 {
        set_id: request.set_id.clone(),
        objective_digest: request.objective_digest,
        state_digest: request.state_digest,
        registry_digest: snapshot.registry_digest,
        candidate_factor_ids: factor_ids.clone(),
        selection_grammar_digest,
        receipt_digest: digest_candidate_receipt(
            &request.set_id,
            request.objective_digest,
            request.state_digest,
            snapshot.registry_digest,
            snapshot.snapshot_digest,
            request.model_tuple.digest(),
            selection_grammar_digest,
            &factor_ids,
            candidates_digest,
            canonical_order_digest,
            omitted_count,
        ),
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(EnumeratedPromptCandidatesV1 {
        registry_snapshot: snapshot,
        model_tuple: request.model_tuple,
        generation_vector_digest: request.generation_vector_digest,
        candidates_digest,
        canonical_order_digest,
        omitted_count,
        candidates,
        receipt,
    })
}

fn bind_selection_grammar(grammar_digest: Digest32, capability_digest: Digest32) -> Digest32 {
    let mut bytes = CAPABILITY_GRAMMAR_DOMAIN.to_vec();
    bytes.extend_from_slice(grammar_digest.as_array());
    bytes.extend_from_slice(capability_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_candidates(candidates: &[PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidates.v1".to_vec();
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
        bytes.extend_from_slice(candidate.binding_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn digest_candidate_order(candidates: &[PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-order.v1".to_vec();
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_candidate_receipt(
    set_id: &StableId,
    objective_digest: Digest32,
    state_digest: Digest32,
    registry_digest: Digest32,
    registry_snapshot_digest: Digest32,
    model_tuple_digest: Digest32,
    grammar_digest: Digest32,
    factor_ids: &[StableId],
    candidates_digest: Digest32,
    order_digest: Digest32,
    omitted_count: u32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set-receipt.v1".to_vec();
    push_id(&mut bytes, set_id);
    for digest in [
        objective_digest,
        state_digest,
        registry_digest,
        registry_snapshot_digest,
        model_tuple_digest,
        grammar_digest,
        candidates_digest,
        order_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, factor_ids.len());
    for factor_id in factor_ids {
        push_id(&mut bytes, factor_id);
    }
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

const fn role_code(role: PromptRoleV2) -> u8 {
    match role {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ConsumerEnumerationError {
    InvalidCapabilities,
    InvalidRequest,
    Registry(String),
    RegistryReadIncomplete(u32),
}

impl fmt::Display for ConsumerEnumerationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ConsumerEnumerationError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capability_digest_is_ordered_and_nonzero() {
        let capabilities = PromptConsumerCapabilitiesV1::developer_instruction_runtime();
        assert!(!capabilities.digest().expect("capability digest").is_zero());
    }

    #[test]
    fn duplicate_or_noncanonical_roles_fail_closed() {
        let capabilities = PromptConsumerCapabilitiesV1 {
            capability_id: StableId::new("consumer:invalid").expect("id"),
            supported_roles: vec![
                PromptRoleV2::DeveloperInstruction,
                PromptRoleV2::DeveloperInstruction,
            ],
            maximum_token_cost: 1,
            maximum_payload_bytes: 1,
        };
        assert_eq!(
            capabilities.validate(),
            Err(ConsumerEnumerationError::InvalidCapabilities)
        );
    }
}
