//! Durable source lease and final-use currentness for the existing Agentd owner.
use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct PromptRegistryLeaseItemV1 {
    pub(super) factor_id: StableId,
    pub(super) realization_id: StableId,
    pub(super) binding_digest: Digest32,
    pub(super) payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct PromptRegistryDeliveryLeaseV1 {
    pub(super) compile_snapshot_digest: Digest32,
    pub(super) compatible_set_digest: Digest32,
    pub(super) portfolio_receipt_digest: Digest32,
    pub(super) generation_vector_digest: Digest32,
    pub(super) model_tuple: PromptModelTupleV2,
    pub(super) valid_until_unix_ms: u64,
    pub(super) attachment_source_binding_digest: Digest32,
    pub(super) selected: Vec<PromptRegistryLeaseItemV1>,
    pub(super) lease_digest: Digest32,
}

impl PromptRegistryDeliveryLeaseV1 {
    pub(super) fn from_compiled(
        portfolio: &SelectedPromptPortfolioV1,
        compiled: &PromptRegistryCompiledContextV2,
        attachment: &PromptRuntimeAttachmentV1,
    ) -> Result<Self, AgentdPromptRuntimeError> {
        compiled
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        if portfolio.receipt.valid_until_unix_ms == 0
            || portfolio.receipt.receipt_digest.is_zero()
            || portfolio.model_tuple_digest != portfolio.model_tuple.digest()
            || portfolio.generation_vector_digest.is_zero()
            || compiled.portfolio_receipt_digest != portfolio.receipt.receipt_digest
        {
            return Err(AgentdPromptRuntimeError::SourceValidationFailed);
        }
        let expected = portfolio
            .selected
            .iter()
            .map(|binding| {
                (
                    binding.realization.realization_id.clone(),
                    (
                        binding.factor_id.clone(),
                        binding.binding_digest,
                        binding.realization.payload_digest,
                    ),
                )
            })
            .collect::<BTreeMap<_, _>>();
        if expected.len() != portfolio.selected.len()
            || compiled.selected_deliveries.len() != portfolio.selected.len()
        {
            return Err(AgentdPromptRuntimeError::SourceValidationFailed);
        }
        let mut selected = Vec::with_capacity(compiled.selected_deliveries.len());
        for delivery in &compiled.selected_deliveries {
            let Some((factor_id, binding_digest, payload_digest)) =
                expected.get(&delivery.binding.realization_id)
            else {
                return Err(AgentdPromptRuntimeError::SourceValidationFailed);
            };
            if factor_id != &delivery.binding.factor_id
                || *binding_digest != delivery.binding.digest()
                || *payload_digest != delivery.binding.payload_digest
            {
                return Err(AgentdPromptRuntimeError::SourceValidationFailed);
            }
            selected.push(PromptRegistryLeaseItemV1 {
                factor_id: factor_id.clone(),
                realization_id: delivery.binding.realization_id.clone(),
                binding_digest: *binding_digest,
                payload_digest: *payload_digest,
            });
        }
        selected.sort_by(|left, right| {
            left.factor_id
                .cmp(&right.factor_id)
                .then_with(|| left.realization_id.cmp(&right.realization_id))
        });
        let mut lease = Self {
            compile_snapshot_digest: compiled.compatible.snapshot_digest,
            compatible_set_digest: compiled.compatible.set_digest,
            portfolio_receipt_digest: portfolio.receipt.receipt_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            model_tuple: portfolio.model_tuple.clone(),
            valid_until_unix_ms: attachment.deadline_ms,
            attachment_source_binding_digest: attachment.source_binding_digest,
            selected,
            lease_digest: Digest32::ZERO,
        };
        lease.lease_digest = lease.compute_digest();
        lease.validate()?;
        Ok(lease)
    }

    pub(super) fn validate(&self) -> Result<(), AgentdPromptRuntimeError> {
        self.model_tuple
            .validate()
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        if self.compile_snapshot_digest.is_zero()
            || self.compatible_set_digest.is_zero()
            || self.portfolio_receipt_digest.is_zero()
            || self.generation_vector_digest.is_zero()
            || self.attachment_source_binding_digest.is_zero()
            || self.lease_digest.is_zero()
            || self.valid_until_unix_ms == 0
            || self.selected.is_empty()
            || self.selected.len() > 128
        {
            return Err(AgentdPromptRuntimeError::SourceValidationFailed);
        }
        let mut factor_ids = BTreeSet::new();
        for item in &self.selected {
            if item.binding_digest.is_zero()
                || item.payload_digest.is_zero()
                || !factor_ids.insert(item.factor_id.clone())
            {
                return Err(AgentdPromptRuntimeError::SourceValidationFailed);
            }
        }
        if self.selected.windows(2).any(|pair| {
            (&pair[0].factor_id, &pair[0].realization_id)
                >= (&pair[1].factor_id, &pair[1].realization_id)
        }) || self.lease_digest != self.compute_digest()
        {
            return Err(AgentdPromptRuntimeError::SourceValidationFailed);
        }
        Ok(())
    }

    pub(super) fn validate_current(
        &self,
        registry: &DurablePromptRegistry,
        attachment: &PromptRuntimeAttachmentV1,
        now_unix_ms: u64,
    ) -> Result<(), AgentdPromptRuntimeError> {
        self.validate()?;
        if attachment.source_binding_digest != self.attachment_source_binding_digest
            || now_unix_ms == 0
            || now_unix_ms >= self.valid_until_unix_ms
        {
            return Err(AgentdPromptRuntimeError::SourceValidationFailed);
        }
        let snapshot = registry
            .snapshot_v2(self.generation_vector_digest, &self.model_tuple)
            .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
        for item in &self.selected {
            let delivery = registry
                .dereference_realization_v2(
                    &item.realization_id,
                    &snapshot,
                    self.generation_vector_digest,
                    &self.model_tuple,
                    now_unix_ms,
                )
                .map_err(|_| AgentdPromptRuntimeError::SourceValidationFailed)?;
            if delivery.binding.factor_id != item.factor_id
                || delivery.binding.realization_id != item.realization_id
                || delivery.binding.digest() != item.binding_digest
                || delivery.binding.payload_digest != item.payload_digest
                || Digest32::of_bytes(&delivery.payload) != item.payload_digest
            {
                return Err(AgentdPromptRuntimeError::SourceValidationFailed);
            }
        }
        Ok(())
    }

    pub(super) fn compute_digest(&self) -> Digest32 {
        let mut bytes = REGISTRY_LEASE_DOMAIN.to_vec();
        for digest in [
            self.compile_snapshot_digest,
            self.compatible_set_digest,
            self.portfolio_receipt_digest,
            self.generation_vector_digest,
            self.model_tuple.digest(),
            self.attachment_source_binding_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.valid_until_unix_ms.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(self.selected.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for item in &self.selected {
            push_runtime_id(&mut bytes, &item.factor_id);
            push_runtime_id(&mut bytes, &item.realization_id);
            bytes.extend_from_slice(item.binding_digest.as_array());
            bytes.extend_from_slice(item.payload_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}
