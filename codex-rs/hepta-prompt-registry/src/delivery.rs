//! Prompt realization payload storage, supersession and dereference.
//!
//! Registration binds exact bytes to the realization digest. Dereference
//! revalidates the frozen snapshot, exact model tuple, lifecycle, expiry and
//! payload digest immediately before handing bytes to a consumer.

use std::collections::BTreeSet;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::Error;
use crate::FactorSource;
use crate::Lifecycle;
use crate::MutationDisposition;
use crate::PromptModelTupleV2;
use crate::PromptRealization;
use crate::PromptRealizationBindingV2;
use crate::PromptRegistry;
use crate::PromptRegistrySnapshotV2;
use crate::PromptRegistryV2Error;
use crate::RegistryReceipt;
use crate::v2::same_profile;

pub const MAX_REALIZATION_PAYLOAD_BYTES: usize = 64 * 1024;
const DELIVERY_DOMAIN: &[u8] = b"hepta.prompt-realization-delivery.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RealizationDeliveryV2 {
    pub snapshot_digest: Digest32,
    pub binding: PromptRealizationBindingV2,
    pub payload: Vec<u8>,
    pub delivery_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RealizationDeliveryV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        if self.snapshot_digest.is_zero() || self.delivery_digest.is_zero() {
            return Err(PromptRegistryV2Error::EmptyDigest("delivery"));
        }
        self.binding.validate()?;
        if self.payload.is_empty() || self.payload.len() > MAX_REALIZATION_PAYLOAD_BYTES {
            return Err(PromptRegistryV2Error::PayloadUnavailable);
        }
        if Digest32::of_bytes(&self.payload) != self.binding.payload_digest {
            return Err(PromptRegistryV2Error::PayloadDigestMismatch);
        }
        if self.authority.grants_any() {
            return Err(PromptRegistryV2Error::AuthorityGranted);
        }
        if self.delivery_digest != self.compute_digest() {
            return Err(PromptRegistryV2Error::DigestMismatch("delivery"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = DELIVERY_DOMAIN.to_vec();
        bytes.extend_from_slice(self.snapshot_digest.as_array());
        bytes.extend_from_slice(self.binding.digest().as_array());
        bytes.extend_from_slice(self.binding.payload_digest.as_array());
        bytes.extend_from_slice(
            &u64::try_from(self.payload.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        Digest32::of_bytes(&bytes)
    }
}

impl PromptRegistry {
    pub(crate) fn register_realization_payload_v2(
        &mut self,
        binding: PromptRealizationBindingV2,
        payload: Vec<u8>,
        supersedes_realization_id: Option<StableId>,
    ) -> Result<RegistryReceipt, Error> {
        binding.validate().map_err(|error| match error {
            PromptRegistryV2Error::EmptyDigest(name) => Error::EmptyDigest(name),
            _ => Error::InvalidTransition,
        })?;
        if payload.is_empty() || payload.len() > MAX_REALIZATION_PAYLOAD_BYTES {
            return Err(Error::PayloadTooLarge);
        }
        if Digest32::of_bytes(&payload) != binding.payload_digest {
            return Err(Error::PayloadDigestMismatch);
        }
        let Some(factor) = self.factors.get(&binding.factor_id) else {
            return Err(Error::FactorNotFound(binding.factor_id.to_string()));
        };
        if factor.source != FactorSource::GovernedInternal
            || factor.lifecycle != Lifecycle::Admitted
        {
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
        if let (Some(existing_legacy), Some(existing_binding), Some(existing_payload)) = (
            self.realizations.get(&binding.realization_id),
            self.realization_bindings.get(&binding.realization_id),
            self.realization_payloads.get(&binding.realization_id),
        ) {
            let expected_predecessor = self
                .realization_supersessions
                .get(&binding.realization_id)
                .cloned();
            if existing_legacy == &legacy
                && existing_binding == &binding
                && existing_payload == &payload
                && expected_predecessor == supersedes_realization_id
            {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            return Err(Error::RealizationConflict(
                binding.realization_id.to_string(),
            ));
        }
        if self.realizations.contains_key(&binding.realization_id)
            || self
                .realization_bindings
                .contains_key(&binding.realization_id)
            || self
                .realization_payloads
                .contains_key(&binding.realization_id)
        {
            return Err(Error::RealizationConflict(
                binding.realization_id.to_string(),
            ));
        }

        let active_same_profile = self
            .realization_bindings
            .values()
            .filter(|existing| {
                same_profile(existing, &binding)
                    && self
                        .realizations
                        .get(&existing.realization_id)
                        .is_some_and(|realization| realization.active)
            })
            .map(|existing| existing.realization_id.clone())
            .collect::<BTreeSet<_>>();

        match supersedes_realization_id.as_ref() {
            Some(predecessor_id) => {
                if predecessor_id == &binding.realization_id
                    || active_same_profile.len() != 1
                    || !active_same_profile.contains(predecessor_id)
                {
                    return Err(Error::RealizationProfileConflict(
                        binding.factor_id.to_string(),
                    ));
                }
            }
            None if !active_same_profile.is_empty() => {
                return Err(Error::RealizationProfileConflict(
                    binding.factor_id.to_string(),
                ));
            }
            None => {}
        }

        self.ensure_capacity(/*additional*/ 1)?;
        let next_revision = self.next_revision()?;
        if let Some(predecessor_id) = supersedes_realization_id.as_ref() {
            let Some(predecessor) = self.realizations.get_mut(predecessor_id) else {
                return Err(Error::RealizationConflict(predecessor_id.to_string()));
            };
            predecessor.active = false;
        }
        self.realizations
            .insert(binding.realization_id.clone(), legacy);
        self.realization_bindings
            .insert(binding.realization_id.clone(), binding.clone());
        self.realization_payloads
            .insert(binding.realization_id.clone(), payload);
        if let Some(predecessor_id) = supersedes_realization_id {
            self.realization_supersessions
                .insert(binding.realization_id.clone(), predecessor_id);
        }
        self.commit_revision(next_revision, /*revocation*/ false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    pub fn dereference_realization_v2(
        &self,
        realization_id: &StableId,
        expected_snapshot: &PromptRegistrySnapshotV2,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
        now_unix_ms: u64,
    ) -> Result<RealizationDeliveryV2, PromptRegistryV2Error> {
        expected_snapshot.validate()?;
        let current_snapshot = self.snapshot_v2(generation_vector_digest, model_tuple)?;
        if current_snapshot != *expected_snapshot {
            return Err(PromptRegistryV2Error::SnapshotStale);
        }
        let binding = self
            .realization_bindings
            .get(realization_id)
            .ok_or(PromptRegistryV2Error::PayloadUnavailable)?;
        let factor_live = self.factors.get(&binding.factor_id).is_some_and(|factor| {
            factor.source == FactorSource::GovernedInternal
                && factor.lifecycle == Lifecycle::Admitted
        });
        let realization_live = self
            .realizations
            .get(realization_id)
            .is_some_and(|realization| realization.active);
        let compatible = binding.model_id == model_tuple.model_id
            && binding.model_version == model_tuple.model_version
            && binding.model_digest == model_tuple.model_digest
            && binding.tokenizer_digest == model_tuple.tokenizer_digest
            && binding.template_digest == model_tuple.template_digest
            && binding.tool_schema_digest == model_tuple.tool_schema_digest
            && binding.context_profile_digest == model_tuple.context_profile_digest
            && binding.locale_id == model_tuple.locale_id;
        let unexpired = binding
            .expires_unix_ms
            .is_none_or(|expires| now_unix_ms < expires);
        if !factor_live || !realization_live || !compatible || !unexpired {
            return Err(PromptRegistryV2Error::RequiredFactorUnavailable);
        }
        let payload = self
            .realization_payloads
            .get(realization_id)
            .cloned()
            .ok_or(PromptRegistryV2Error::PayloadUnavailable)?;
        if Digest32::of_bytes(&payload) != binding.payload_digest {
            return Err(PromptRegistryV2Error::PayloadDigestMismatch);
        }
        let mut delivery = RealizationDeliveryV2 {
            snapshot_digest: current_snapshot.snapshot_digest,
            binding: binding.clone(),
            payload,
            delivery_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        delivery.delivery_digest = delivery.compute_digest();
        delivery.validate()?;
        Ok(delivery)
    }

    pub fn realization_predecessor(&self, realization_id: &StableId) -> Option<&StableId> {
        self.realization_supersessions.get(realization_id)
    }
}
