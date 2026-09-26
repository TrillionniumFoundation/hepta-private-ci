//! Send-time final-use lease for prompt-registry materializations.
//!
//! Compilation and staging do not authorize a provider effect. A lease binds
//! the exact registry snapshot, model tuple, selected realization bindings and
//! payload digests. Agentd revalidates it while holding the durable registry
//! owner immediately before recording the provider dispatch claim.

use std::fmt;

use codex_hepta_intelligence::PromptRegistryCompiledContextV2;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const LEASE_DOMAIN: &[u8] = b"hepta.prompt-registry.send-final-use-lease.v1";
pub const PROMPT_FINAL_USE_LEASE_SCHEMA: u32 = 1;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct PromptFinalUseSelectionV1 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub binding_digest: Digest32,
    pub payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFinalUseLeaseV1 {
    pub schema_version: u32,
    pub compilation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub issued_unix_ms: u64,
    pub valid_until_unix_ms: u64,
    pub selections: Vec<PromptFinalUseSelectionV1>,
    pub lease_digest: Digest32,
}

impl PromptFinalUseLeaseV1 {
    pub fn from_compiled(
        portfolio: &SelectedPromptPortfolioV1,
        compiled: &PromptRegistryCompiledContextV2,
        issued_unix_ms: u64,
        requested_deadline_ms: u64,
    ) -> Result<Self, PromptFinalUseLeaseError> {
        compiled
            .validate()
            .map_err(|error| PromptFinalUseLeaseError::Compiled(error.to_string()))?;
        if issued_unix_ms == 0
            || requested_deadline_ms <= issued_unix_ms
            || compiled.compatible.snapshot_digest.is_zero()
            || compiled.compatible.model_tuple_digest != portfolio.model_tuple.digest()
            || portfolio.generation_vector_digest.is_zero()
            || compiled.selected_deliveries.is_empty()
        {
            return Err(PromptFinalUseLeaseError::InvalidShape);
        }
        let mut valid_until_unix_ms = requested_deadline_ms;
        let mut selections = Vec::with_capacity(compiled.selected_deliveries.len());
        for delivery in &compiled.selected_deliveries {
            if let Some(expires_unix_ms) = delivery.binding.expires_unix_ms {
                valid_until_unix_ms = valid_until_unix_ms.min(expires_unix_ms);
            }
            selections.push(PromptFinalUseSelectionV1 {
                factor_id: delivery.binding.factor_id.clone(),
                realization_id: delivery.binding.realization_id.clone(),
                binding_digest: delivery.binding.digest(),
                payload_digest: delivery.binding.payload_digest,
            });
        }
        selections.sort();
        if selections.windows(2).any(|window| window[0] >= window[1])
            || valid_until_unix_ms <= issued_unix_ms
        {
            return Err(PromptFinalUseLeaseError::InvalidShape);
        }
        let mut lease = Self {
            schema_version: PROMPT_FINAL_USE_LEASE_SCHEMA,
            compilation_id: compiled.compiled.receipt().compilation_id().clone(),
            context_attachment_digest: compiled.attachment.attachment_digest(),
            context_payload_digest: compiled.attachment.payload_digest(),
            registry_snapshot_digest: compiled.compatible.snapshot_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            model_tuple: portfolio.model_tuple.clone(),
            issued_unix_ms,
            valid_until_unix_ms,
            selections,
            lease_digest: Digest32::ZERO,
        };
        lease.lease_digest = lease.compute_digest();
        lease.validate_shape()?;
        Ok(lease)
    }

    pub fn validate_shape(&self) -> Result<(), PromptFinalUseLeaseError> {
        if self.schema_version != PROMPT_FINAL_USE_LEASE_SCHEMA
            || self.context_attachment_digest.is_zero()
            || self.context_payload_digest.is_zero()
            || self.registry_snapshot_digest.is_zero()
            || self.generation_vector_digest.is_zero()
            || self.issued_unix_ms == 0
            || self.valid_until_unix_ms <= self.issued_unix_ms
            || self.selections.is_empty()
            || self.selections.windows(2).any(|window| window[0] >= window[1])
        {
            return Err(PromptFinalUseLeaseError::InvalidShape);
        }
        self.model_tuple
            .validate()
            .map_err(|_| PromptFinalUseLeaseError::InvalidShape)?;
        if self.selections.iter().any(|selection| {
            selection.binding_digest.is_zero() || selection.payload_digest.is_zero()
        }) || self.lease_digest != self.compute_digest()
        {
            return Err(PromptFinalUseLeaseError::DigestMismatch);
        }
        Ok(())
    }

    pub fn validate_current(
        &self,
        registry: &DurablePromptRegistry,
        now_unix_ms: u64,
    ) -> Result<(), PromptFinalUseLeaseError> {
        self.validate_shape()?;
        if now_unix_ms < self.issued_unix_ms || now_unix_ms >= self.valid_until_unix_ms {
            return Err(PromptFinalUseLeaseError::Expired);
        }
        let snapshot = registry
            .snapshot_v2(self.generation_vector_digest, &self.model_tuple)
            .map_err(|error| PromptFinalUseLeaseError::Registry(error.to_string()))?;
        if snapshot.snapshot_digest != self.registry_snapshot_digest {
            return Err(PromptFinalUseLeaseError::RegistrySnapshotChanged);
        }
        for selection in &self.selections {
            let delivery = registry
                .dereference_realization_v2(
                    &selection.realization_id,
                    &snapshot,
                    self.generation_vector_digest,
                    &self.model_tuple,
                    now_unix_ms,
                )
                .map_err(|error| PromptFinalUseLeaseError::Registry(error.to_string()))?;
            if delivery.binding.factor_id != selection.factor_id
                || delivery.binding.digest() != selection.binding_digest
                || delivery.binding.payload_digest != selection.payload_digest
                || Digest32::of_bytes(&delivery.payload) != selection.payload_digest
            {
                return Err(PromptFinalUseLeaseError::SelectionChanged);
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = LEASE_DOMAIN.to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.context_attachment_digest,
            self.context_payload_digest,
            self.registry_snapshot_digest,
            self.generation_vector_digest,
            self.model_tuple.digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.issued_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.valid_until_unix_ms.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(self.selections.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for selection in &self.selections {
            push_id(&mut bytes, &selection.factor_id);
            push_id(&mut bytes, &selection.realization_id);
            bytes.extend_from_slice(selection.binding_digest.as_array());
            bytes.extend_from_slice(selection.payload_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptFinalUseLeaseError {
    InvalidShape,
    DigestMismatch,
    Expired,
    RegistrySnapshotChanged,
    SelectionChanged,
    Registry(String),
    Compiled(String),
}

impl fmt::Display for PromptFinalUseLeaseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptFinalUseLeaseError {}
