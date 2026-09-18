//! V2 registry mutation, compatibility selection, and payload resolution.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::model::Error;
use crate::model::FactorSource;
use crate::model::Lifecycle;
use crate::model::MutationDisposition;
use crate::model::PromptRealization;
use crate::model::RegistryReceipt;
use crate::model::push_id;
use crate::registry::PromptRegistry;
use crate::v2::types::CompatibleRealizationSetV2;
use crate::v2::types::MAX_COMPATIBLE_REALIZATIONS_V2;
use crate::v2::types::MAX_REALIZATION_PAYLOAD_BYTES;
use crate::v2::types::MAX_TOTAL_REALIZATION_PAYLOAD_BYTES;
use crate::v2::types::PromptModelTupleV2;
use crate::v2::types::PromptPayloadResolutionV2;
use crate::v2::types::PromptRealizationBindingV2;
use crate::v2::types::PromptRegistrySnapshotV2;
use crate::v2::types::PromptRegistryV2Error;
use crate::v2::types::PromptRoleV2;
use crate::v2::types::ensure_digest;

impl PromptRegistry {
    /// Register a V2 realization together with the exact bounded payload bytes.
    /// An active realization with the same factor/profile may be replaced
    /// only when `predecessor_realization_id` names that exact active record.
    pub fn register_realization_v2(
        &mut self,
        binding: PromptRealizationBindingV2,
        payload: Vec<u8>,
    ) -> Result<RegistryReceipt, Error> {
        binding.validate().map_err(map_v2_registration_error)?;
        validate_payload(&binding, &payload)?;
        let Some(factor) = self.factors.get(&binding.factor_id) else {
            return Err(Error::FactorNotFound(binding.factor_id.to_string()));
        };
        if factor.source != FactorSource::GovernedInternal
            || factor.lifecycle != Lifecycle::Admitted
        {
            return Err(Error::FactorNotAdmitted(binding.factor_id.to_string()));
        }
        if self.admission(&binding.factor_id).is_none() {
            return Err(Error::FactorNotAdmitted(binding.factor_id.to_string()));
        }

        let legacy = PromptRealization {
            realization_id: binding.realization_id.clone(),
            factor_id: binding.factor_id.clone(),
            model_digest: binding.model_digest,
            tokenizer_digest: binding.tokenizer_digest,
            content_digest: binding.payload_digest,
            active: true,
        };
        let existing_legacy = self.realizations.get(&binding.realization_id);
        let existing_binding = self.realization_bindings.get(&binding.realization_id);
        let existing_payload = self.realization_payloads.get(&binding.realization_id);
        match (existing_legacy, existing_binding, existing_payload) {
            (Some(existing_legacy), Some(existing_binding), Some(existing_payload))
                if existing_legacy == &legacy
                    && existing_binding == &binding
                    && existing_payload == &payload =>
            {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            (None, None, None) => {}
            _ => {
                return Err(Error::RealizationConflict(
                    binding.realization_id.to_string(),
                ));
            }
        }

        let mut active_predecessors = self
            .realization_bindings
            .values()
            .filter(|candidate| {
                candidate.same_active_key(&binding)
                    && self
                        .realizations
                        .get(&candidate.realization_id)
                        .is_some_and(|record| record.active)
            })
            .map(|candidate| candidate.realization_id.clone());
        let active_predecessor = active_predecessors.next();
        if active_predecessors.next().is_some() {
            return Err(Error::IntegrityMismatch("multiple active realization keys"));
        }
        match (
            active_predecessor.as_ref(),
            &binding.predecessor_realization_id,
        ) {
            (None, None) => {}
            (Some(active), Some(predecessor)) if active == predecessor => {}
            (Some(active), _) => {
                return Err(Error::ActiveRealizationConflict(active.to_string()));
            }
            (None, Some(predecessor)) => {
                return Err(Error::InvalidSupersession(predecessor.to_string()));
            }
        }

        self.ensure_capacity(/*additional*/ 1)?;
        let current_payload_bytes = self
            .realization_payloads
            .values()
            .try_fold(0_usize, |total, value| total.checked_add(value.len()))
            .ok_or(Error::PayloadCapacityExceeded)?;
        if current_payload_bytes
            .checked_add(payload.len())
            .is_none_or(|total| total > MAX_TOTAL_REALIZATION_PAYLOAD_BYTES)
        {
            return Err(Error::PayloadCapacityExceeded);
        }
        let next_revision = self.next_revision()?;
        if let Some(predecessor) = &binding.predecessor_realization_id {
            let Some(record) = self.realizations.get_mut(predecessor) else {
                return Err(Error::InvalidSupersession(predecessor.to_string()));
            };
            record.active = false;
        }
        self.realizations
            .insert(binding.realization_id.clone(), legacy);
        self.realization_payloads
            .insert(binding.realization_id.clone(), payload);
        self.realization_revisions
            .insert(binding.realization_id.clone(), next_revision);
        self.realization_bindings
            .insert(binding.realization_id.clone(), binding);
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    pub fn snapshot_v2(
        &self,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
    ) -> Result<PromptRegistrySnapshotV2, PromptRegistryV2Error> {
        ensure_digest("generation_vector", generation_vector_digest)?;
        model_tuple.validate()?;
        self.validate_integrity()
            .map_err(|_| PromptRegistryV2Error::RegistryIntegrity)?;
        let mut snapshot = PromptRegistrySnapshotV2 {
            revision: self.revision,
            registry_digest: self.snapshot_digest(),
            lifecycle_frontier: self.lifecycle_frontier,
            revocation_frontier: self.revocation_frontier,
            generation_vector_digest,
            model_tuple_digest: model_tuple.digest(),
            snapshot_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        snapshot.snapshot_digest = snapshot.compute_snapshot_digest();
        snapshot.validate()?;
        Ok(snapshot)
    }

    pub fn read_compatible_v2(
        &self,
        expected_snapshot: &PromptRegistrySnapshotV2,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
        now_unix_ms: u64,
        mut required_factor_ids: Vec<StableId>,
        maximum_results: u32,
    ) -> Result<CompatibleRealizationSetV2, PromptRegistryV2Error> {
        expected_snapshot.validate()?;
        let current_snapshot = self.snapshot_v2(generation_vector_digest, model_tuple)?;
        if current_snapshot != *expected_snapshot {
            return Err(PromptRegistryV2Error::SnapshotStale);
        }
        let maximum_results = usize::try_from(maximum_results).unwrap_or(usize::MAX);
        if maximum_results == 0 || maximum_results > MAX_COMPATIBLE_REALIZATIONS_V2 {
            return Err(PromptRegistryV2Error::ReadLimitExceeded);
        }
        required_factor_ids.sort();
        if required_factor_ids
            .windows(2)
            .any(|pair| pair[0] == pair[1])
        {
            let duplicate = required_factor_ids
                .windows(2)
                .find(|pair| pair[0] == pair[1])
                .map(|pair| pair[0].to_string())
                .unwrap_or_else(|| "duplicate".to_string());
            return Err(PromptRegistryV2Error::DuplicateFactorFilter(duplicate));
        }
        if required_factor_ids.len() > maximum_results {
            return Err(PromptRegistryV2Error::RequiredFactorLimitExceeded);
        }
        let factor_filter = required_factor_ids.iter().cloned().collect::<BTreeSet<_>>();
        let mut compatible = self
            .realization_bindings
            .values()
            .filter(|binding| self.binding_is_live(binding, model_tuple, now_unix_ms))
            .filter(|binding| {
                factor_filter.is_empty() || factor_filter.contains(&binding.factor_id)
            })
            .cloned()
            .collect::<Vec<_>>();
        compatible.sort_by_key(binding_sort_key);

        let mut selected = Vec::new();
        let mut selected_ids = BTreeSet::new();
        if !required_factor_ids.is_empty() {
            for factor_id in &required_factor_ids {
                let Some(binding) = compatible
                    .iter()
                    .find(|binding| &binding.factor_id == factor_id)
                else {
                    return Err(PromptRegistryV2Error::RequiredFactorUnavailable);
                };
                if selected_ids.insert(binding.realization_id.clone()) {
                    selected.push(binding.clone());
                }
            }
        }
        for binding in &compatible {
            if selected.len() >= maximum_results {
                break;
            }
            if selected_ids.insert(binding.realization_id.clone()) {
                selected.push(binding.clone());
            }
        }
        selected.sort_by_key(binding_sort_key);
        let omitted_count = compatible.len().saturating_sub(selected.len());
        let mut result = CompatibleRealizationSetV2 {
            snapshot_digest: current_snapshot.snapshot_digest,
            model_tuple_digest: model_tuple.digest(),
            required_factor_ids,
            bindings: selected,
            omitted_count: u32::try_from(omitted_count).unwrap_or(u32::MAX),
            set_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        result.set_digest = result.compute_set_digest();
        result.validate()?;
        Ok(result)
    }

    pub fn resolve_payload_v2(
        &self,
        expected_snapshot: &PromptRegistrySnapshotV2,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
        now_unix_ms: u64,
        realization_id: &StableId,
    ) -> Result<PromptPayloadResolutionV2, PromptRegistryV2Error> {
        expected_snapshot.validate()?;
        let current_snapshot = self.snapshot_v2(generation_vector_digest, model_tuple)?;
        if current_snapshot != *expected_snapshot {
            return Err(PromptRegistryV2Error::SnapshotStale);
        }
        let binding = self
            .realization_bindings
            .get(realization_id)
            .ok_or_else(|| {
                PromptRegistryV2Error::RealizationUnavailable(realization_id.to_string())
            })?;
        if !self.binding_is_live(binding, model_tuple, now_unix_ms) {
            return Err(PromptRegistryV2Error::RealizationUnavailable(
                realization_id.to_string(),
            ));
        }
        let payload = self
            .realization_payloads
            .get(realization_id)
            .ok_or_else(|| PromptRegistryV2Error::PayloadUnavailable(realization_id.to_string()))?
            .clone();
        if payload.is_empty() || payload.len() > MAX_REALIZATION_PAYLOAD_BYTES {
            return Err(PromptRegistryV2Error::InvalidPayloadSize);
        }
        if Digest32::of_bytes(&payload) != binding.payload_digest {
            return Err(PromptRegistryV2Error::DigestMismatch("payload"));
        }
        let mut resolution = PromptPayloadResolutionV2 {
            realization_id: binding.realization_id.clone(),
            factor_id: binding.factor_id.clone(),
            payload,
            payload_digest: binding.payload_digest,
            binding_digest: binding.digest(),
            snapshot_digest: current_snapshot.snapshot_digest,
            model_tuple_digest: model_tuple.digest(),
            resolution_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        resolution.resolution_digest = resolution.compute_resolution_digest();
        resolution.validate()?;
        Ok(resolution)
    }

    fn binding_is_live(
        &self,
        binding: &PromptRealizationBindingV2,
        model_tuple: &PromptModelTupleV2,
        now_unix_ms: u64,
    ) -> bool {
        let factor_valid = self
            .factors
            .get(&binding.factor_id)
            .is_some_and(|factor| factor.lifecycle == Lifecycle::Admitted);
        let admitted = self.admissions.contains_key(&binding.factor_id);
        let realization_active = self
            .realizations
            .get(&binding.realization_id)
            .is_some_and(|realization| realization.active);
        let payload_valid = self
            .realization_payloads
            .get(&binding.realization_id)
            .is_some_and(|payload| Digest32::of_bytes(payload) == binding.payload_digest);
        let live = binding
            .expires_unix_ms
            .is_none_or(|expires| now_unix_ms < expires);
        factor_valid
            && admitted
            && realization_active
            && payload_valid
            && binding.compatible_with(model_tuple)
            && live
    }
}

pub(crate) fn validate_active_uniqueness(registry: &PromptRegistry) -> Result<(), Error> {
    let mut active_by_key = BTreeMap::<Vec<u8>, StableId>::new();
    for binding in registry.realization_bindings.values() {
        let active = registry
            .realizations
            .get(&binding.realization_id)
            .is_some_and(|record| record.active);
        if !active {
            continue;
        }
        let key = active_key_bytes(binding);
        if let Some(existing) = active_by_key.insert(key, binding.realization_id.clone()) {
            return Err(Error::ActiveRealizationConflict(existing.to_string()));
        }
    }
    Ok(())
}

fn active_key_bytes(binding: &PromptRealizationBindingV2) -> Vec<u8> {
    let mut bytes = Vec::new();
    push_id(&mut bytes, &binding.factor_id);
    for digest in [
        binding.model_digest,
        binding.tokenizer_digest,
        binding.template_digest,
        binding.tool_schema_digest,
        binding.context_profile_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_id(&mut bytes, &binding.locale_id);
    bytes
}

fn binding_sort_key(binding: &PromptRealizationBindingV2) -> (StableId, PromptRoleV2, StableId) {
    (
        binding.factor_id.clone(),
        binding.role,
        binding.realization_id.clone(),
    )
}

fn validate_payload(binding: &PromptRealizationBindingV2, payload: &[u8]) -> Result<(), Error> {
    if payload.is_empty() {
        return Err(Error::PayloadRequired);
    }
    if payload.len() > MAX_REALIZATION_PAYLOAD_BYTES {
        return Err(Error::PayloadTooLarge);
    }
    if Digest32::of_bytes(payload) != binding.payload_digest {
        return Err(Error::PayloadDigestMismatch);
    }
    Ok(())
}

fn map_v2_registration_error(error: PromptRegistryV2Error) -> Error {
    match error {
        PromptRegistryV2Error::EmptyDigest(name) => Error::EmptyDigest(name),
        PromptRegistryV2Error::InvalidSupersession(id) => Error::InvalidSupersession(id),
        _ => Error::InvalidTransition,
    }
}
