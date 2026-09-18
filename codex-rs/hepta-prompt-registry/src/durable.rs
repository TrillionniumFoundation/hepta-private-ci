//! Durable authoritative prompt registry owner.
//!
//! The pure PromptRegistry remains the deterministic domain core. This wrapper
//! applies a mutation to a clone, fsyncs an atomic owner snapshot, and only then
//! publishes the new in-process state. Store failure therefore cannot expose an
//! uncommitted mutation.

#[cfg(test)]
use std::cell::Cell;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AdmissionError;
use crate::Error;
use crate::FactorSource;
use crate::FinalUseAdmissionAuthority;
use crate::Lifecycle;
use crate::LifecycleEvent;
use crate::LifecycleEventKind;
use crate::PromptFactor;
use crate::PromptModelTupleV2;
use crate::PromptRealization;
use crate::PromptRealizationBindingV2;
use crate::PromptRegistry;
use crate::PromptRegistrySnapshotV2;
use crate::PromptRegistryV2Error;
use crate::PromptRoleV2;
use crate::RealizationDeliveryV2;
use crate::RegistryReceipt;
use crate::VerifiedAdmission;
use crate::admission::map_final_use_error;
use crate::protocol::LEGACY_UNRESOLVED_FACTOR_PURPOSE;
use crate::protocol::LEGACY_UNRESOLVED_MODEL_ID;
use crate::protocol::LEGACY_UNRESOLVED_MODEL_VERSION;
use crate::final_use_realization_binding;
use crate::final_use_retire_binding;
use crate::final_use_revoke_binding;

const STORE_SCHEMA: u32 = 2;
const MAX_STATE_BYTES: u64 = 32 * 1024 * 1024;
const LEGACY_CONTEXT_PROFILE_DOMAIN: &[u8] = b"hepta.prompt-registry.legacy-context-profile.v1";
const MIGRATION_REASON_DOMAIN: &[u8] = b"hepta.prompt-registry.migration.v1-v2";

pub struct DurablePromptRegistry {
    registry: PromptRegistry,
    store: Store,
    poisoned: bool,
}

impl fmt::Debug for DurablePromptRegistry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DurablePromptRegistry")
            .field("revision", &self.registry.revision())
            .field("registry_digest", &self.registry.snapshot_digest())
            .finish_non_exhaustive()
    }
}

impl DurablePromptRegistry {
    pub fn open_state_dir(
        directory: &Path,
        maximum_records: usize,
    ) -> Result<Self, DurableRegistryError> {
        let (store, stored) = Store::open(directory)?;
        let registry = match stored {
            Some(StoredAny::V2(stored)) => restore_v2(stored, maximum_records)?,
            Some(StoredAny::V1(stored)) => migrate_v1(stored, maximum_records)?,
            None => PromptRegistry::new(maximum_records).map_err(DurableRegistryError::Core)?,
        };
        store.persist(&registry)?;
        Ok(Self {
            registry,
            store,
            poisoned: false,
        })
    }

    /// Returns the last in-process image. After an indeterminate durable commit
    /// this image is diagnostic only; authoritative reads reject until reopen.
    pub fn registry(&self) -> &PromptRegistry {
        &self.registry
    }

    #[must_use]
    pub const fn requires_reopen(&self) -> bool {
        self.poisoned
    }

    #[cfg(test)]
    fn fail_directory_sync_after_rename_once(&self) {
        self.store.fail_directory_sync_after_rename_once.set(true);
    }

    pub fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| registry.register_factor(factor))
    }

    #[cfg(test)]
    pub(crate) fn admit_factor_verified(
        &mut self,
        admission: VerifiedAdmission,
        now_unix_ms: u64,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| registry.admit_factor_verified(admission, now_unix_ms))
    }

    pub fn admit_factor_final_use(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        factor_id: &StableId,
        reviewed_scope_digest: Digest32,
        evidence_digest: Digest32,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        let factor = self.registry.factor(factor_id).cloned().ok_or_else(|| {
            DurableRegistryError::Core(Error::FactorNotFound(factor_id.to_string()))
        })?;
        FinalUseAdmissionAuthority::new(authority)
            .with_verified_admission(
                signed,
                &factor,
                reviewed_scope_digest,
                evidence_digest,
                |admission| {
                    let verified_at_unix_ms = admission.verified_at_unix_ms();
                    self.commit(|registry| {
                        registry.admit_factor_verified(admission, verified_at_unix_ms)
                    })
                },
            )
            .map_err(DurableRegistryError::Admission)?
    }

    #[cfg(test)]
    pub(crate) fn register_realization_payload_v2(
        &mut self,
        binding: PromptRealizationBindingV2,
        payload: Vec<u8>,
        supersedes_realization_id: Option<StableId>,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| {
            registry.register_realization_payload_v2(binding, payload, supersedes_realization_id)
        })
    }

    pub fn register_realization_payload_final_use_v2(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        actor_id: &StableId,
        scope_digest: Digest32,
        binding: PromptRealizationBindingV2,
        payload: Vec<u8>,
        supersedes_realization_id: Option<StableId>,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        let factor = self
            .registry
            .factor(&binding.factor_id)
            .cloned()
            .ok_or_else(|| {
                DurableRegistryError::Core(Error::FactorNotFound(binding.factor_id.to_string()))
            })?;
        let expected = final_use_realization_binding(
            &factor,
            actor_id,
            scope_digest,
            &binding,
            supersedes_realization_id.as_ref(),
        )
        .map_err(DurableRegistryError::Admission)?;
        if Digest32::of_bytes(&payload) != binding.payload_digest {
            return Err(DurableRegistryError::Core(Error::PayloadDigestMismatch));
        }
        let token = authority
            .claim(signed, &expected)
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?;
        authority
            .with_verified_use(token, &expected, || {
                self.commit(|registry| {
                    registry.register_realization_payload_v2(
                        binding,
                        payload,
                        supersedes_realization_id,
                    )
                })
            })
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?
    }

    #[cfg(test)]
    pub(crate) fn retire_factor(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        let factor_id = factor_id.clone();
        let actor_id = actor_id.clone();
        self.commit(|registry| {
            registry.retire_factor_governed(&factor_id, &actor_id, reason_digest)
        })
    }

    #[cfg(test)]
    pub(crate) fn revoke_factor(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
        cutoff_unix_ms: u64,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        let factor_id = factor_id.clone();
        let actor_id = actor_id.clone();
        self.commit(|registry| {
            registry.revoke_factor_governed(&factor_id, &actor_id, reason_digest, cutoff_unix_ms)
        })
    }

    pub fn retire_factor_final_use(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        factor_id: &StableId,
        actor_id: &StableId,
        scope_digest: Digest32,
        reason_digest: Digest32,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        let factor = self.registry.factor(factor_id).cloned().ok_or_else(|| {
            DurableRegistryError::Core(Error::FactorNotFound(factor_id.to_string()))
        })?;
        let expected = final_use_retire_binding(&factor, actor_id, scope_digest, reason_digest)
            .map_err(DurableRegistryError::Admission)?;
        let token = authority
            .claim(signed, &expected)
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?;
        let factor_id = factor_id.clone();
        let actor_id = actor_id.clone();
        authority
            .with_verified_use(token, &expected, || {
                self.commit(|registry| {
                    registry.retire_factor_governed(&factor_id, &actor_id, reason_digest)
                })
            })
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?
    }

    pub fn revoke_factor_final_use(
        &mut self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        factor_id: &StableId,
        actor_id: &StableId,
        scope_digest: Digest32,
        reason_digest: Digest32,
        cutoff_unix_ms: u64,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        let factor = self.registry.factor(factor_id).cloned().ok_or_else(|| {
            DurableRegistryError::Core(Error::FactorNotFound(factor_id.to_string()))
        })?;
        let expected = final_use_revoke_binding(
            &factor,
            actor_id,
            scope_digest,
            reason_digest,
            cutoff_unix_ms,
        )
        .map_err(DurableRegistryError::Admission)?;
        let token = authority
            .claim(signed, &expected)
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?;
        let factor_id = factor_id.clone();
        let actor_id = actor_id.clone();
        authority
            .with_verified_use(token, &expected, || {
                self.commit(|registry| {
                    registry.revoke_factor_governed(
                        &factor_id,
                        &actor_id,
                        reason_digest,
                        cutoff_unix_ms,
                    )
                })
            })
            .map_err(map_final_use_error)
            .map_err(DurableRegistryError::Admission)?
    }

    pub fn snapshot_v2(
        &self,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
    ) -> Result<PromptRegistrySnapshotV2, DurableRegistryError> {
        if self.poisoned {
            return Err(DurableRegistryError::ReopenRequired);
        }
        self.registry
            .snapshot_v2(generation_vector_digest, model_tuple)
            .map_err(DurableRegistryError::Read)
    }

    pub fn read_compatible_v2(
        &self,
        expected_snapshot: &PromptRegistrySnapshotV2,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
        now_unix_ms: u64,
        required_factor_ids: Vec<StableId>,
        maximum_results: u32,
    ) -> Result<crate::CompatibleRealizationSetV2, DurableRegistryError> {
        if self.poisoned {
            return Err(DurableRegistryError::ReopenRequired);
        }
        self.registry
            .read_compatible_v2(
                expected_snapshot,
                generation_vector_digest,
                model_tuple,
                now_unix_ms,
                required_factor_ids,
                maximum_results,
            )
            .map_err(DurableRegistryError::Read)
    }

    pub fn dereference_realization_v2(
        &self,
        realization_id: &StableId,
        expected_snapshot: &PromptRegistrySnapshotV2,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
        now_unix_ms: u64,
    ) -> Result<RealizationDeliveryV2, DurableRegistryError> {
        if self.poisoned {
            return Err(DurableRegistryError::ReopenRequired);
        }
        self.registry
            .dereference_realization_v2(
                realization_id,
                expected_snapshot,
                generation_vector_digest,
                model_tuple,
                now_unix_ms,
            )
            .map_err(DurableRegistryError::Read)
    }

    fn commit(
        &mut self,
        mutation: impl FnOnce(&mut PromptRegistry) -> Result<RegistryReceipt, Error>,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        if self.poisoned {
            return Err(DurableRegistryError::ReopenRequired);
        }
        let mut next = self.registry.clone();
        let receipt = mutation(&mut next).map_err(DurableRegistryError::Core)?;
        if receipt.disposition != crate::MutationDisposition::Unchanged {
            match self.store.persist(&next) {
                Ok(()) => self.registry = next,
                Err(DurableRegistryError::IndeterminateDurability) => {
                    self.poisoned = true;
                    return Err(DurableRegistryError::IndeterminateDurability);
                }
                Err(error) => return Err(error),
            }
        }
        Ok(receipt)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredV2 {
    schema: u32,
    registry_digest: [u8; 32],
    revision: u64,
    lifecycle_frontier: u64,
    revocation_frontier: u64,
    maximum_records: usize,
    factors: Vec<StoredFactor>,
    realizations: Vec<StoredRealization>,
    bindings: Vec<StoredBindingV2>,
    payloads: Vec<StoredPayload>,
    supersessions: Vec<StoredSupersession>,
    lifecycle_events: Vec<StoredLifecycleEvent>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredV1 {
    schema: u32,
    revision: u64,
    lifecycle_frontier: u64,
    revocation_frontier: u64,
    maximum_records: usize,
    factors: Vec<StoredFactor>,
    realizations: Vec<StoredRealization>,
    bindings: Vec<StoredBindingV1>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredFactor {
    factor_id: String,
    proposer_id: String,
    semantic_version: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    semantic_purpose: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    authority_class: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    eligible_objective_dimensions: Vec<String>,
    content_digest: [u8; 32],
    source: u8,
    lifecycle: u8,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredRealization {
    realization_id: String,
    factor_id: String,
    model_digest: [u8; 32],
    tokenizer_digest: [u8; 32],
    content_digest: [u8; 32],
    active: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredBindingV2 {
    realization_id: String,
    factor_id: String,
    model_id: String,
    model_version: String,
    model_digest: [u8; 32],
    tokenizer_digest: [u8; 32],
    template_digest: [u8; 32],
    tool_schema_digest: [u8; 32],
    context_profile_digest: [u8; 32],
    locale_id: String,
    role: u8,
    payload_digest: [u8; 32],
    token_cost: u32,
    expires_unix_ms: Option<u64>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredBindingV1 {
    realization_id: String,
    factor_id: String,
    model_digest: [u8; 32],
    tokenizer_digest: [u8; 32],
    template_digest: [u8; 32],
    tool_schema_digest: [u8; 32],
    locale_id: String,
    role: u8,
    payload_digest: [u8; 32],
    token_cost: u32,
    expires_unix_ms: Option<u64>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredPayload {
    realization_id: String,
    payload: Vec<u8>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredSupersession {
    successor_id: String,
    predecessor_id: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredLifecycleEvent {
    revision: u64,
    factor_id: String,
    kind: u8,
    from: Option<u8>,
    to: u8,
    actor_id: String,
    admission_grant_id: Option<String>,
    evidence_digest: [u8; 32],
    scope_digest: Option<[u8; 32]>,
    reason_digest: Option<[u8; 32]>,
    cutoff_unix_ms: Option<u64>,
    event_digest: [u8; 32],
}

fn stored_v2(registry: &PromptRegistry) -> StoredV2 {
    StoredV2 {
        schema: STORE_SCHEMA,
        registry_digest: registry.snapshot_digest().into_array(),
        revision: registry.revision.get(),
        lifecycle_frontier: registry.lifecycle_frontier,
        revocation_frontier: registry.revocation_frontier,
        maximum_records: registry.maximum_records,
        factors: registry
            .factors
            .values()
            .map(|factor| StoredFactor {
                factor_id: factor.factor_id.to_string(),
                proposer_id: factor.proposer_id.to_string(),
                semantic_version: factor.semantic_version.to_string(),
                semantic_purpose: factor.semantic_purpose.clone(),
                authority_class: factor.authority_class.clone(),
                eligible_objective_dimensions: factor
                    .eligible_objective_dimensions
                    .iter()
                    .map(ToString::to_string)
                    .collect(),
                content_digest: factor.content_digest.into_array(),
                source: factor_source_code(factor.source),
                lifecycle: lifecycle_code(factor.lifecycle),
            })
            .collect(),
        realizations: registry
            .realizations
            .values()
            .map(|realization| StoredRealization {
                realization_id: realization.realization_id.to_string(),
                factor_id: realization.factor_id.to_string(),
                model_digest: realization.model_digest.into_array(),
                tokenizer_digest: realization.tokenizer_digest.into_array(),
                content_digest: realization.content_digest.into_array(),
                active: realization.active,
            })
            .collect(),
        bindings: registry
            .realization_bindings
            .values()
            .map(|binding| StoredBindingV2 {
                realization_id: binding.realization_id.to_string(),
                factor_id: binding.factor_id.to_string(),
                model_id: binding.model_id.to_string(),
                model_version: binding.model_version.clone(),
                model_digest: binding.model_digest.into_array(),
                tokenizer_digest: binding.tokenizer_digest.into_array(),
                template_digest: binding.template_digest.into_array(),
                tool_schema_digest: binding.tool_schema_digest.into_array(),
                context_profile_digest: binding.context_profile_digest.into_array(),
                locale_id: binding.locale_id.to_string(),
                role: role_code(binding.role),
                payload_digest: binding.payload_digest.into_array(),
                token_cost: binding.token_cost,
                expires_unix_ms: binding.expires_unix_ms,
            })
            .collect(),
        payloads: registry
            .realization_payloads
            .iter()
            .map(|(realization_id, payload)| StoredPayload {
                realization_id: realization_id.to_string(),
                payload: payload.clone(),
            })
            .collect(),
        supersessions: registry
            .realization_supersessions
            .iter()
            .map(|(successor_id, predecessor_id)| StoredSupersession {
                successor_id: successor_id.to_string(),
                predecessor_id: predecessor_id.to_string(),
            })
            .collect(),
        lifecycle_events: registry.lifecycle_events.iter().map(stored_event).collect(),
    }
}

fn stored_event(event: &LifecycleEvent) -> StoredLifecycleEvent {
    StoredLifecycleEvent {
        revision: event.revision.get(),
        factor_id: event.factor_id.to_string(),
        kind: event_kind_code(event.kind),
        from: event.from.map(lifecycle_code),
        to: lifecycle_code(event.to),
        actor_id: event.actor_id.to_string(),
        admission_grant_id: event.admission_grant_id.as_ref().map(ToString::to_string),
        evidence_digest: event.evidence_digest.into_array(),
        scope_digest: event.scope_digest.map(Digest32::into_array),
        reason_digest: event.reason_digest.map(Digest32::into_array),
        cutoff_unix_ms: event.cutoff_unix_ms,
        event_digest: event.event_digest.into_array(),
    }
}

fn restore_v2(
    stored: StoredV2,
    maximum_records: usize,
) -> Result<PromptRegistry, DurableRegistryError> {
    if stored.schema != STORE_SCHEMA || stored.maximum_records == 0 || maximum_records == 0 {
        return Err(DurableRegistryError::Corrupt);
    }
    let revision = Revision::new(stored.revision).map_err(|_| DurableRegistryError::Corrupt)?;
    let configured_maximum = maximum_records.min(crate::MAX_RECORDS);
    if stored.maximum_records != configured_maximum {
        return Err(DurableRegistryError::ConfigurationMismatch);
    }
    let mut factors = BTreeMap::new();
    for stored_factor in stored.factors {
        let factor = decode_factor(stored_factor)?;
        if factors.insert(factor.factor_id.clone(), factor).is_some() {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    let mut realizations = BTreeMap::new();
    for stored_realization in stored.realizations {
        let realization = decode_realization(stored_realization)?;
        if realizations
            .insert(realization.realization_id.clone(), realization)
            .is_some()
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    if factors.len().saturating_add(realizations.len()) > configured_maximum {
        return Err(DurableRegistryError::CapacityExceeded);
    }

    let mut realization_bindings = BTreeMap::new();
    for stored_binding in stored.bindings {
        let binding = decode_binding_v2(stored_binding)?;
        binding
            .validate()
            .map_err(|_| DurableRegistryError::Corrupt)?;
        if realization_bindings
            .insert(binding.realization_id.clone(), binding)
            .is_some()
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }

    let mut realization_payloads = BTreeMap::new();
    for stored_payload in stored.payloads {
        let realization_id = parse_id(stored_payload.realization_id)?;
        if stored_payload.payload.is_empty()
            || stored_payload.payload.len() > crate::MAX_REALIZATION_PAYLOAD_BYTES
            || realization_payloads
                .insert(realization_id, stored_payload.payload)
                .is_some()
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }

    let mut realization_supersessions = BTreeMap::new();
    for stored_supersession in stored.supersessions {
        let successor_id = parse_id(stored_supersession.successor_id)?;
        let predecessor_id = parse_id(stored_supersession.predecessor_id)?;
        if successor_id == predecessor_id
            || realization_supersessions
                .insert(successor_id, predecessor_id)
                .is_some()
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }

    let mut lifecycle_events = Vec::new();
    for stored_event in stored.lifecycle_events {
        let event = decode_event(stored_event)?;
        if event.event_digest != event.compute_digest() {
            return Err(DurableRegistryError::Corrupt);
        }
        lifecycle_events.push(event);
    }

    let registry = PromptRegistry {
        factors,
        realizations,
        realization_bindings,
        realization_payloads,
        realization_supersessions,
        lifecycle_events,
        revision,
        lifecycle_frontier: stored.lifecycle_frontier,
        revocation_frontier: stored.revocation_frontier,
        maximum_records: configured_maximum,
    };
    validate_restored(&registry)?;
    if registry.snapshot_digest() != Digest32::from_array(stored.registry_digest) {
        return Err(DurableRegistryError::Corrupt);
    }
    Ok(registry)
}

fn migrate_v1(
    stored: StoredV1,
    maximum_records: usize,
) -> Result<PromptRegistry, DurableRegistryError> {
    if stored.schema != 1 || stored.maximum_records == 0 || maximum_records == 0 {
        return Err(DurableRegistryError::Corrupt);
    }
    let revision = Revision::new(stored.revision).map_err(|_| DurableRegistryError::Corrupt)?;
    let configured_maximum = maximum_records.min(crate::MAX_RECORDS);
    if stored.maximum_records != configured_maximum {
        return Err(DurableRegistryError::ConfigurationMismatch);
    }
    let mut factors = BTreeMap::new();
    let migration_actor =
        StableId::new("migration:v1").map_err(|_| DurableRegistryError::Corrupt)?;
    let migration_reason = Digest32::of_bytes(MIGRATION_REASON_DOMAIN);
    let mut lifecycle_events = Vec::new();
    for stored_factor in stored.factors {
        let factor = decode_factor(stored_factor)?;
        let mut event = LifecycleEvent {
            revision,
            factor_id: factor.factor_id.clone(),
            kind: LifecycleEventKind::Imported,
            from: None,
            to: factor.lifecycle,
            actor_id: migration_actor.clone(),
            admission_grant_id: None,
            evidence_digest: factor.content_digest,
            scope_digest: None,
            reason_digest: Some(migration_reason),
            cutoff_unix_ms: None,
            event_digest: Digest32::ZERO,
        };
        event.event_digest = event.compute_digest();
        lifecycle_events.push(event);
        if factors.insert(factor.factor_id.clone(), factor).is_some() {
            return Err(DurableRegistryError::Corrupt);
        }
    }

    let mut realizations = BTreeMap::new();
    for stored_realization in stored.realizations {
        let mut realization = decode_realization(stored_realization)?;
        // V1 persisted only a payload digest and never persisted the payload
        // bytes. Migration must therefore preserve the historical identity but
        // fail closed by deactivating the realization until bytes are
        // re-registered through the V2 payload path.
        realization.active = false;
        if realizations
            .insert(realization.realization_id.clone(), realization)
            .is_some()
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    if factors.len().saturating_add(realizations.len()) > configured_maximum {
        return Err(DurableRegistryError::CapacityExceeded);
    }

    let legacy_context_profile_digest = Digest32::of_bytes(LEGACY_CONTEXT_PROFILE_DOMAIN);
    let mut realization_bindings = BTreeMap::new();
    for stored_binding in stored.bindings {
        let binding = PromptRealizationBindingV2 {
            realization_id: parse_id(stored_binding.realization_id)?,
            factor_id: parse_id(stored_binding.factor_id)?,
            model_id: StableId::new(LEGACY_UNRESOLVED_MODEL_ID)
                .map_err(|_| DurableRegistryError::Corrupt)?,
            model_version: LEGACY_UNRESOLVED_MODEL_VERSION.to_owned(),
            model_digest: Digest32::from_array(stored_binding.model_digest),
            tokenizer_digest: Digest32::from_array(stored_binding.tokenizer_digest),
            template_digest: Digest32::from_array(stored_binding.template_digest),
            tool_schema_digest: Digest32::from_array(stored_binding.tool_schema_digest),
            context_profile_digest: legacy_context_profile_digest,
            locale_id: parse_id(stored_binding.locale_id)?,
            role: decode_role(stored_binding.role)?,
            payload_digest: Digest32::from_array(stored_binding.payload_digest),
            token_cost: stored_binding.token_cost,
            expires_unix_ms: stored_binding.expires_unix_ms,
        };
        binding
            .validate()
            .map_err(|_| DurableRegistryError::Corrupt)?;
        if realization_bindings
            .insert(binding.realization_id.clone(), binding)
            .is_some()
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }

    let registry = PromptRegistry {
        factors,
        realizations,
        realization_bindings,
        realization_payloads: BTreeMap::new(),
        realization_supersessions: BTreeMap::new(),
        lifecycle_events,
        revision,
        lifecycle_frontier: stored.lifecycle_frontier,
        revocation_frontier: stored.revocation_frontier,
        maximum_records: configured_maximum,
    };
    validate_restored(&registry)?;
    Ok(registry)
}

fn validate_restored(registry: &PromptRegistry) -> Result<(), DurableRegistryError> {
    if registry.revocation_frontier > registry.lifecycle_frontier
        || registry.lifecycle_frontier > registry.revision.get()
        || registry
            .factors
            .len()
            .saturating_add(registry.realizations.len())
            > registry.maximum_records
    {
        return Err(DurableRegistryError::Corrupt);
    }
    if registry.revision.get() > 1 && registry.lifecycle_frontier != registry.revision.get() {
        return Err(DurableRegistryError::Corrupt);
    }

    // Replay factor lifecycle lineage instead of trusting the materialized
    // lifecycle byte. Imported migration events may share one revision; native
    // lifecycle mutations are strictly revision ordered.
    let mut replayed = BTreeMap::<StableId, Lifecycle>::new();
    let mut last_event_revision = 0_u64;
    let mut last_native_revision = 0_u64;
    let mut latest_revocation_revision = 0_u64;
    for event in &registry.lifecycle_events {
        let event_revision = event.revision.get();
        if event_revision > registry.revision.get()
            || event_revision < last_event_revision
            || event.event_digest != event.compute_digest()
            || !registry.factors.contains_key(&event.factor_id)
        {
            return Err(DurableRegistryError::Corrupt);
        }
        last_event_revision = event_revision;
        if event.kind != LifecycleEventKind::Imported {
            if event_revision <= last_native_revision {
                return Err(DurableRegistryError::Corrupt);
            }
            last_native_revision = event_revision;
        }

        let prior = replayed.get(&event.factor_id).copied();
        let next = match event.kind {
            LifecycleEventKind::Registered => {
                if prior.is_some() || event.from.is_some() || event.to != Lifecycle::Draft {
                    return Err(DurableRegistryError::Corrupt);
                }
                Lifecycle::Draft
            }
            LifecycleEventKind::Imported => {
                if prior.is_some() || event.from.is_some() {
                    return Err(DurableRegistryError::Corrupt);
                }
                if event.to == Lifecycle::Revoked {
                    latest_revocation_revision = latest_revocation_revision.max(event_revision);
                }
                event.to
            }
            LifecycleEventKind::Admitted => {
                if prior != Some(Lifecycle::Draft)
                    || event.from != Some(Lifecycle::Draft)
                    || event.to != Lifecycle::Admitted
                    || event.evidence_digest.is_zero()
                {
                    return Err(DurableRegistryError::Corrupt);
                }
                Lifecycle::Admitted
            }
            LifecycleEventKind::Retired => {
                if prior != Some(Lifecycle::Admitted)
                    || event.from != Some(Lifecycle::Admitted)
                    || event.to != Lifecycle::Retired
                    || event.reason_digest.is_some_and(|digest| digest.is_zero())
                {
                    return Err(DurableRegistryError::Corrupt);
                }
                Lifecycle::Retired
            }
            LifecycleEventKind::Revoked => {
                let Some(prior) = prior else {
                    return Err(DurableRegistryError::Corrupt);
                };
                if prior == Lifecycle::Revoked
                    || event.from != Some(prior)
                    || event.to != Lifecycle::Revoked
                    || event.reason_digest.is_some_and(Digest32::is_zero)
                    || event.cutoff_unix_ms == Some(0)
                {
                    return Err(DurableRegistryError::Corrupt);
                }
                latest_revocation_revision = latest_revocation_revision.max(event_revision);
                Lifecycle::Revoked
            }
        };
        replayed.insert(event.factor_id.clone(), next);
    }
    if replayed.len() != registry.factors.len()
        || latest_revocation_revision != registry.revocation_frontier
    {
        return Err(DurableRegistryError::Corrupt);
    }
    for (factor_id, factor) in &registry.factors {
        if replayed.get(factor_id) != Some(&factor.lifecycle)
            || (factor.source == FactorSource::ExternalUntrusted
                && factor.lifecycle == Lifecycle::Admitted)
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }

    if registry.realizations.len() != registry.realization_bindings.len() {
        return Err(DurableRegistryError::Corrupt);
    }
    let mut active_profiles = BTreeSet::new();
    for (realization_id, realization) in &registry.realizations {
        let Some(binding) = registry.realization_bindings.get(realization_id) else {
            return Err(DurableRegistryError::Corrupt);
        };
        let Some(factor) = registry.factors.get(&binding.factor_id) else {
            return Err(DurableRegistryError::Corrupt);
        };
        if realization.factor_id != binding.factor_id
            || realization.model_digest != binding.model_digest
            || realization.tokenizer_digest != binding.tokenizer_digest
            || realization.content_digest != binding.payload_digest
        {
            return Err(DurableRegistryError::Corrupt);
        }
        match registry.realization_payloads.get(realization_id) {
            Some(payload) if Digest32::of_bytes(payload) == binding.payload_digest => {}
            Some(_) => return Err(DurableRegistryError::Corrupt),
            None if realization.active => return Err(DurableRegistryError::Corrupt),
            None => {}
        }
        if realization.active {
            if factor.source != FactorSource::GovernedInternal
                || factor.lifecycle != Lifecycle::Admitted
                || !active_profiles.insert((
                    binding.factor_id.clone(),
                    binding.model_digest,
                    binding.tokenizer_digest,
                    binding.template_digest,
                    binding.tool_schema_digest,
                    binding.context_profile_digest,
                    binding.locale_id.clone(),
                    binding.role,
                ))
            {
                return Err(DurableRegistryError::Corrupt);
            }
        }
    }
    for realization_id in registry.realization_payloads.keys() {
        if !registry.realizations.contains_key(realization_id)
            || !registry.realization_bindings.contains_key(realization_id)
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }

    let mut seen_predecessors = BTreeSet::new();
    for (successor, predecessor) in &registry.realization_supersessions {
        let Some(successor_record) = registry.realizations.get(successor) else {
            return Err(DurableRegistryError::Corrupt);
        };
        let Some(predecessor_record) = registry.realizations.get(predecessor) else {
            return Err(DurableRegistryError::Corrupt);
        };
        let Some(successor_binding) = registry.realization_bindings.get(successor) else {
            return Err(DurableRegistryError::Corrupt);
        };
        let Some(predecessor_binding) = registry.realization_bindings.get(predecessor) else {
            return Err(DurableRegistryError::Corrupt);
        };
        if successor == predecessor
            || successor_record.factor_id != predecessor_record.factor_id
            || predecessor_record.active
            || !crate::v2::same_profile(successor_binding, predecessor_binding)
            || !seen_predecessors.insert(predecessor.clone())
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    for start in registry.realization_supersessions.keys() {
        let mut visited = BTreeSet::new();
        let mut current = start;
        while let Some(predecessor) = registry.realization_supersessions.get(current) {
            if !visited.insert(current.clone()) {
                return Err(DurableRegistryError::Corrupt);
            }
            current = predecessor;
        }
    }
    Ok(())
}

fn decode_factor(mut stored: StoredFactor) -> Result<PromptFactor, DurableRegistryError> {
    if stored.semantic_purpose.is_empty() {
        stored.semantic_purpose = LEGACY_UNRESOLVED_FACTOR_PURPOSE.to_owned();
    }
    if stored.authority_class.is_empty() {
        stored.authority_class = "registered_prompt_factor".to_owned();
    }
    let factor = PromptFactor {
        factor_id: parse_id(stored.factor_id)?,
        proposer_id: parse_id(stored.proposer_id)?,
        semantic_version: parse_id(stored.semantic_version)?,
        semantic_purpose: stored.semantic_purpose,
        authority_class: stored.authority_class,
        eligible_objective_dimensions: stored
            .eligible_objective_dimensions
            .into_iter()
            .map(parse_id)
            .collect::<Result<Vec<_>, _>>()?,
        content_digest: Digest32::from_array(stored.content_digest),
        source: decode_factor_source(stored.source)?,
        lifecycle: decode_lifecycle(stored.lifecycle)?,
    };
    crate::protocol::validate_factor_semantics(&factor)
        .map_err(|_| DurableRegistryError::Corrupt)?;
    Ok(factor)
}

fn decode_realization(
    stored: StoredRealization,
) -> Result<PromptRealization, DurableRegistryError> {
    Ok(PromptRealization {
        realization_id: parse_id(stored.realization_id)?,
        factor_id: parse_id(stored.factor_id)?,
        model_digest: Digest32::from_array(stored.model_digest),
        tokenizer_digest: Digest32::from_array(stored.tokenizer_digest),
        content_digest: Digest32::from_array(stored.content_digest),
        active: stored.active,
    })
}

fn decode_binding_v2(
    stored: StoredBindingV2,
) -> Result<PromptRealizationBindingV2, DurableRegistryError> {
    Ok(PromptRealizationBindingV2 {
        realization_id: parse_id(stored.realization_id)?,
        factor_id: parse_id(stored.factor_id)?,
        model_id: parse_id(stored.model_id)?,
        model_version: stored.model_version,
        model_digest: Digest32::from_array(stored.model_digest),
        tokenizer_digest: Digest32::from_array(stored.tokenizer_digest),
        template_digest: Digest32::from_array(stored.template_digest),
        tool_schema_digest: Digest32::from_array(stored.tool_schema_digest),
        context_profile_digest: Digest32::from_array(stored.context_profile_digest),
        locale_id: parse_id(stored.locale_id)?,
        role: decode_role(stored.role)?,
        payload_digest: Digest32::from_array(stored.payload_digest),
        token_cost: stored.token_cost,
        expires_unix_ms: stored.expires_unix_ms,
    })
}

fn decode_event(stored: StoredLifecycleEvent) -> Result<LifecycleEvent, DurableRegistryError> {
    Ok(LifecycleEvent {
        revision: Revision::new(stored.revision).map_err(|_| DurableRegistryError::Corrupt)?,
        factor_id: parse_id(stored.factor_id)?,
        kind: decode_event_kind(stored.kind)?,
        from: stored.from.map(decode_lifecycle).transpose()?,
        to: decode_lifecycle(stored.to)?,
        actor_id: parse_id(stored.actor_id)?,
        admission_grant_id: stored.admission_grant_id.map(parse_id).transpose()?,
        evidence_digest: Digest32::from_array(stored.evidence_digest),
        scope_digest: stored.scope_digest.map(Digest32::from_array),
        reason_digest: stored.reason_digest.map(Digest32::from_array),
        cutoff_unix_ms: stored.cutoff_unix_ms,
        event_digest: Digest32::from_array(stored.event_digest),
    })
}

fn parse_id(value: String) -> Result<StableId, DurableRegistryError> {
    StableId::new(value).map_err(|_| DurableRegistryError::Corrupt)
}

const fn factor_source_code(value: FactorSource) -> u8 {
    match value {
        FactorSource::GovernedInternal => 0,
        FactorSource::ExternalUntrusted => 1,
    }
}

fn decode_factor_source(value: u8) -> Result<FactorSource, DurableRegistryError> {
    match value {
        0 => Ok(FactorSource::GovernedInternal),
        1 => Ok(FactorSource::ExternalUntrusted),
        _ => Err(DurableRegistryError::Corrupt),
    }
}

const fn lifecycle_code(value: Lifecycle) -> u8 {
    match value {
        Lifecycle::Draft => 0,
        Lifecycle::Admitted => 1,
        Lifecycle::Retired => 2,
        Lifecycle::Revoked => 3,
    }
}

fn decode_lifecycle(value: u8) -> Result<Lifecycle, DurableRegistryError> {
    match value {
        0 => Ok(Lifecycle::Draft),
        1 => Ok(Lifecycle::Admitted),
        2 => Ok(Lifecycle::Retired),
        3 => Ok(Lifecycle::Revoked),
        _ => Err(DurableRegistryError::Corrupt),
    }
}

const fn event_kind_code(value: LifecycleEventKind) -> u8 {
    match value {
        LifecycleEventKind::Registered => 0,
        LifecycleEventKind::Admitted => 1,
        LifecycleEventKind::Retired => 2,
        LifecycleEventKind::Revoked => 3,
        LifecycleEventKind::Imported => 4,
    }
}

fn decode_event_kind(value: u8) -> Result<LifecycleEventKind, DurableRegistryError> {
    match value {
        0 => Ok(LifecycleEventKind::Registered),
        1 => Ok(LifecycleEventKind::Admitted),
        2 => Ok(LifecycleEventKind::Retired),
        3 => Ok(LifecycleEventKind::Revoked),
        4 => Ok(LifecycleEventKind::Imported),
        _ => Err(DurableRegistryError::Corrupt),
    }
}

const fn role_code(value: PromptRoleV2) -> u8 {
    match value {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}

fn decode_role(value: u8) -> Result<PromptRoleV2, DurableRegistryError> {
    match value {
        0 => Ok(PromptRoleV2::SystemInstruction),
        1 => Ok(PromptRoleV2::DeveloperInstruction),
        2 => Ok(PromptRoleV2::UserTemplate),
        3 => Ok(PromptRoleV2::ToolSchemaFragment),
        _ => Err(DurableRegistryError::Corrupt),
    }
}

enum StoredAny {
    V1(StoredV1),
    V2(StoredV2),
}

struct Store {
    root: File,
    _lock: File,
    #[cfg(test)]
    fail_directory_sync_after_rename_once: Cell<bool>,
}

impl Store {
    fn open(directory: &Path) -> Result<(Self, Option<StoredAny>), DurableRegistryError> {
        let root = prepare_directory(directory)?;
        let initialized = entry_exists(&root, "registry.lock")?;
        let lock = open_private(&root, "registry.lock", Access::Create)?;
        lock.try_lock()
            .map_err(|_| DurableRegistryError::StateLocked)?;
        let store = Self {
            root,
            _lock: lock,
            #[cfg(test)]
            fail_directory_sync_after_rename_once: Cell::new(false),
        };
        let has_state = entry_exists(&store.root, "registry.json")?;
        if !has_state {
            if initialized {
                return Err(DurableRegistryError::Corrupt);
            }
            return Ok((store, None));
        }
        let mut bytes = Vec::new();
        open_private(&store.root, "registry.json", Access::Read)?
            .take(MAX_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| DurableRegistryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
            return Err(DurableRegistryError::Corrupt);
        }
        let value: serde_json::Value =
            serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?;
        let schema = value
            .get("schema")
            .and_then(serde_json::Value::as_u64)
            .ok_or(DurableRegistryError::Corrupt)?;
        let stored = match schema {
            1 => StoredAny::V1(
                serde_json::from_value(value).map_err(|_| DurableRegistryError::Corrupt)?,
            ),
            2 => StoredAny::V2(
                serde_json::from_value(value).map_err(|_| DurableRegistryError::Corrupt)?,
            ),
            _ => return Err(DurableRegistryError::Corrupt),
        };
        Ok((store, Some(stored)))
    }

    fn persist(&self, registry: &PromptRegistry) -> Result<(), DurableRegistryError> {
        let bytes = serde_json::to_vec(&stored_v2(registry))
            .map_err(|_| DurableRegistryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
            return Err(DurableRegistryError::CapacityExceeded);
        }
        let mut file = open_private(&self.root, "registry.next", Access::Create)?;
        file.set_len(0)
            .map_err(|_| DurableRegistryError::Unavailable)?;
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| DurableRegistryError::Unavailable)?;
        replace_state(&self.root)?;
        // After rename succeeds the durable outcome is unknown if directory
        // fsync fails. The caller must poison this writer and reopen/reconcile;
        // treating this as an ordinary pre-commit failure could overwrite a
        // state that actually reached the filesystem.
        #[cfg(test)]
        if self.fail_directory_sync_after_rename_once.replace(false) {
            return Err(DurableRegistryError::IndeterminateDurability);
        }
        self.root
            .sync_all()
            .map_err(|_| DurableRegistryError::IndeterminateDurability)
    }
}

enum Access {
    Read,
    Create,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, DurableRegistryError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(DurableRegistryError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| DurableRegistryError::UnsafeStateDirectory)?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| DurableRegistryError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(DurableRegistryError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(unix)]
fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, DurableRegistryError> {
    use std::os::unix::fs::MetadataExt;

    let flags = match access {
        Access::Read => rustix::fs::OFlags::RDONLY,
        Access::Create => rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE,
    } | rustix::fs::OFlags::NOFOLLOW
        | rustix::fs::OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(
        directory,
        name,
        flags,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
    )
    .map_err(|_| DurableRegistryError::Unavailable)?
    .into();
    let metadata = file
        .metadata()
        .map_err(|_| DurableRegistryError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(DurableRegistryError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn open_private(
    _directory: &File,
    _name: &str,
    _access: Access,
) -> Result<File, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, DurableRegistryError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(DurableRegistryError::Unavailable),
    }
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}

#[cfg(unix)]
fn replace_state(directory: &File) -> Result<(), DurableRegistryError> {
    rustix::fs::renameat(directory, "registry.next", directory, "registry.json")
        .map_err(|_| DurableRegistryError::Unavailable)
}

#[cfg(not(unix))]
fn replace_state(_directory: &File) -> Result<(), DurableRegistryError> {
    Err(DurableRegistryError::UnsafeStateDirectory)
}

#[derive(Debug)]
pub enum DurableRegistryError {
    Core(Error),
    Admission(AdmissionError),
    Read(PromptRegistryV2Error),
    Corrupt,
    CapacityExceeded,
    ConfigurationMismatch,
    Unavailable,
    UnsafeStateDirectory,
    StateLocked,
    /// Rename may have succeeded but directory fsync failed; disk state is
    /// unknown and the current writer is poisoned until reopened.
    IndeterminateDurability,
    /// This in-process image may be stale relative to disk after an
    /// indeterminate commit and must not serve authoritative reads or writes.
    ReopenRequired,
}

impl fmt::Display for DurableRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for DurableRegistryError {}

#[cfg(all(test, unix))]
mod tests {
    use std::collections::BTreeSet;
    use std::os::unix::fs::OpenOptionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::AdmissionAuthority;
    use crate::AdmissionBindingV1;
    use crate::AdmissionGrantV1;
    use crate::SignedAdmissionGrantV1;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn schema_v1_migrates_without_resurrecting_state() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&root)
            .expect("state dir");
        let factor = StoredFactor {
            factor_id: "factor:1".to_owned(),
            proposer_id: "proposer:1".to_owned(),
            semantic_version: "v1".to_owned(),
            semantic_purpose: String::new(),
            authority_class: String::new(),
            eligible_objective_dimensions: Vec::new(),
            content_digest: digest("factor").into_array(),
            source: 0,
            lifecycle: 3,
        };
        let stored = StoredV1 {
            schema: 1,
            revision: 4,
            lifecycle_frontier: 4,
            revocation_frontier: 4,
            maximum_records: 64,
            factors: vec![factor],
            realizations: vec![StoredRealization {
                realization_id: "realization:legacy".to_owned(),
                factor_id: "factor:1".to_owned(),
                model_digest: digest("model").into_array(),
                tokenizer_digest: digest("tokenizer").into_array(),
                content_digest: digest("legacy-payload").into_array(),
                active: true,
            }],
            bindings: vec![StoredBindingV1 {
                realization_id: "realization:legacy".to_owned(),
                factor_id: "factor:1".to_owned(),
                model_digest: digest("model").into_array(),
                tokenizer_digest: digest("tokenizer").into_array(),
                template_digest: digest("template").into_array(),
                tool_schema_digest: digest("tool-schema").into_array(),
                locale_id: "locale:en-US".to_owned(),
                role: 1,
                payload_digest: digest("legacy-payload").into_array(),
                token_cost: 8,
                expires_unix_ms: None,
            }],
        };
        let bytes = serde_json::to_vec(&stored).expect("serialize legacy state");
        let path = root.join("registry.json");
        let mut file = std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(path)
            .expect("legacy state");
        file.write_all(&bytes).expect("legacy bytes");
        file.sync_all().expect("legacy fsync");
        drop(file);

        let durable = DurablePromptRegistry::open_state_dir(&root, 64).expect("migrate registry");
        let factor = durable.registry().factor(&id("factor:1")).expect("factor");
        assert_eq!(factor.lifecycle, Lifecycle::Revoked);
        assert_eq!(durable.registry().revocation_frontier(), 4);
        assert_eq!(
            durable
                .registry()
                .realization(&id("realization:legacy"))
                .map(|record| record.active),
            Some(false)
        );
        assert_eq!(
            durable
                .registry()
                .lifecycle_events()
                .last()
                .map(|event| event.kind),
            Some(LifecycleEventKind::Imported)
        );
        assert_eq!(
            durable.registry().factor_protocol_v1(&id("factor:1")),
            Err(crate::ProtocolCodecError::MissingAuthoritativeLineage)
        );
        assert_eq!(
            durable
                .registry()
                .realization_protocol_v1(&id("realization:legacy")),
            Err(crate::ProtocolCodecError::MissingAuthoritativeLineage)
        );
        drop(durable);
        let reopened =
            DurablePromptRegistry::open_state_dir(&root, 64).expect("reopen migrated registry");
        assert_eq!(
            reopened
                .registry()
                .realization(&id("realization:legacy"))
                .map(|record| record.active),
            Some(false)
        );
    }

    #[test]
    fn restart_preserves_active_payload_backed_realization() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let factor = PromptFactor {
            factor_id: id("factor:active-reopen"),
            proposer_id: id("proposer:active-reopen"),
            semantic_version: id("v1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest("factor:active-reopen"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        let tuple = PromptModelTupleV2 {
            model_id: id("model:hepta-test"),
            model_version: "2026-09-18".to_owned(),
            model_digest: digest("model:active-reopen"),
            tokenizer_digest: digest("tokenizer:active-reopen"),
            template_digest: digest("template:active-reopen"),
            tool_schema_digest: digest("tool-schema:active-reopen"),
            context_profile_digest: digest("context-profile:active-reopen"),
            locale_id: id("locale:en-US"),
        };
        let payload = b"persist this active realization".to_vec();
        {
            let mut durable =
                DurablePromptRegistry::open_state_dir(&root, 64).expect("open registry");
            durable
                .register_factor(factor.clone())
                .expect("register factor");
            durable
                .registry
                .admit_factor(
                    &factor.factor_id,
                    &id("reviewer:active-reopen"),
                    digest("evidence"),
                )
                .expect("legacy test admission");
            let binding = PromptRealizationBindingV2 {
                realization_id: id("realization:active-reopen"),
                factor_id: factor.factor_id.clone(),
                model_id: id("model:hepta-test"),
                model_version: "2026-09-18".to_owned(),
                model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                context_profile_digest: tuple.context_profile_digest,
                locale_id: tuple.locale_id.clone(),
                role: PromptRoleV2::DeveloperInstruction,
                payload_digest: Digest32::of_bytes(&payload),
                token_cost: 6,
                expires_unix_ms: None,
            };
            durable
                .register_realization_payload_v2(binding, payload.clone(), None)
                .expect("register payload");
            durable
                .store
                .persist(&durable.registry)
                .expect("persist admission");
        }

        let reopened =
            DurablePromptRegistry::open_state_dir(&root, 64).expect("reopen active registry");
        assert_eq!(
            reopened
                .registry()
                .realization(&id("realization:active-reopen"))
                .map(|record| record.active),
            Some(true)
        );
        let snapshot = reopened
            .snapshot_v2(digest("generation-vector:active-reopen"), &tuple)
            .expect("snapshot");
        let compatible = reopened
            .read_compatible_v2(
                &snapshot,
                digest("generation-vector:active-reopen"),
                &tuple,
                10,
                vec![factor.factor_id],
                8,
            )
            .expect("active realization remains readable after reopen");
        assert_eq!(compatible.bindings.len(), 1);
        let delivery = reopened
            .dereference_realization_v2(
                &id("realization:active-reopen"),
                &snapshot,
                digest("generation-vector:active-reopen"),
                &tuple,
                10,
            )
            .expect("payload remains dereferenceable after reopen");
        assert_eq!(delivery.payload, payload);
    }

    #[test]
    fn restart_preserves_revocation_payload_and_admission_lineage() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let factor = PromptFactor {
            factor_id: id("factor:durable"),
            proposer_id: id("proposer:durable"),
            semantic_version: id("v1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest("factor:durable"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        let tuple = PromptModelTupleV2 {
            model_id: id("model:hepta-test"),
            model_version: "2026-09-18".to_owned(),
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tool-schema"),
            context_profile_digest: digest("context-profile"),
            locale_id: id("locale:en-US"),
        };
        let payload = b"durable developer instruction".to_vec();
        let old_snapshot = {
            let mut durable =
                DurablePromptRegistry::open_state_dir(&root, 64).expect("open registry");
            durable
                .register_factor(factor.clone())
                .expect("register factor");

            let signing_key = SigningKey::from_bytes(&[31; 32]);
            let authority = AdmissionAuthority::new(
                id("review-authority:durable"),
                signing_key.verifying_key().to_bytes(),
            )
            .expect("authority");
            let grant = AdmissionGrantV1 {
                schema_version: 1,
                signer_id: "review-authority:durable".to_owned(),
                grant_id: "admission:durable".to_owned(),
                binding: AdmissionBindingV1 {
                    factor_id: factor.factor_id.to_string(),
                    factor_content_sha256: factor.content_digest.into_array(),
                    reviewer_id: "reviewer:durable".to_owned(),
                    reviewed_scope_sha256: digest("scope:durable").into_array(),
                    evidence_sha256: digest("evidence:durable").into_array(),
                },
                not_before_unix_ms: 10,
                expires_at_unix_ms: 1000,
            };
            let signature = signing_key
                .sign(&grant.signing_bytes().expect("signing bytes"))
                .to_bytes()
                .to_vec();
            let verified = authority
                .verify(
                    &SignedAdmissionGrantV1 { grant, signature },
                    &factor,
                    digest("scope:durable"),
                    20,
                )
                .expect("verified admission");
            durable
                .admit_factor_verified(verified, 20)
                .expect("admit factor");

            let binding = PromptRealizationBindingV2 {
                realization_id: id("realization:durable"),
                factor_id: factor.factor_id.clone(),
                model_id: id("model:hepta-test"),
                model_version: "2026-09-18".to_owned(),
                model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                context_profile_digest: tuple.context_profile_digest,
                locale_id: tuple.locale_id.clone(),
                role: PromptRoleV2::DeveloperInstruction,
                payload_digest: Digest32::of_bytes(&payload),
                token_cost: 8,
                expires_unix_ms: None,
            };
            durable
                .register_realization_payload_v2(binding, payload.clone(), None)
                .expect("register payload");
            let snapshot = durable
                .snapshot_v2(digest("generation-vector"), &tuple)
                .expect("old snapshot");
            durable
                .revoke_factor(
                    &factor.factor_id,
                    &id("revoker:durable"),
                    digest("reason:revoked"),
                    50,
                )
                .expect("revoke factor");
            snapshot
        };

        let reopened = DurablePromptRegistry::open_state_dir(&root, 64).expect("reopen registry");
        assert_eq!(
            reopened
                .registry()
                .factor(&factor.factor_id)
                .map(|record| record.lifecycle),
            Some(Lifecycle::Revoked)
        );
        assert!(reopened.registry().revocation_frontier() > old_snapshot.revocation_frontier);
        assert!(
            reopened
                .registry()
                .lifecycle_events()
                .iter()
                .any(|event| event.kind == LifecycleEventKind::Admitted
                    && event.admission_grant_id == Some(id("admission:durable"))
                    && event.evidence_digest == digest("evidence:durable"))
        );
        assert_eq!(
            reopened
                .registry()
                .realization(&id("realization:durable"))
                .map(|record| record.active),
            Some(false)
        );
        assert_eq!(
            reopened
                .registry()
                .realization_payloads
                .get(&id("realization:durable")),
            Some(&payload)
        );
        assert!(matches!(
            reopened.read_compatible_v2(
                &old_snapshot,
                digest("generation-vector"),
                &tuple,
                60,
                vec![factor.factor_id],
                8,
            ),
            Err(DurableRegistryError::Read(
                PromptRegistryV2Error::SnapshotStale
            ))
        ));
    }

    #[test]
    fn final_use_admission_is_scope_bound_single_use_and_revocation_aware() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let registry_root = temporary.path().join("registry");
        let authority_root = temporary.path().join("authority");
        let signing_key = SigningKey::from_bytes(&[43; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &authority_root,
            "security-owner".to_owned(),
            signing_key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("final-use authority");

        let mut durable =
            DurablePromptRegistry::open_state_dir(&registry_root, 64).expect("registry");
        let factor = PromptFactor {
            factor_id: id("factor:final-use"),
            proposer_id: id("proposer:final-use"),
            semantic_version: id("v1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest("factor:final-use"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        durable
            .register_factor(factor.clone())
            .expect("register factor");

        let reviewer = id("reviewer:final-use");
        let scope = digest("scope:final-use");
        let evidence = digest("evidence:final-use");
        let binding = crate::final_use_admission_binding(&factor, &reviewer, scope, evidence)
            .expect("binding");
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis() as u64;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".to_owned(),
            authority_epoch: 7,
            grant_id: "admission-final-use-1".to_owned(),
            nonce: [17; 32],
            binding,
            not_before_unix_ms: now.saturating_sub(1000),
            expires_at_unix_ms: now + 30_000,
        };
        let signed = SignedFinalUseGrant {
            signature: signing_key
                .sign(&grant.signing_bytes().expect("signing bytes"))
                .to_bytes()
                .to_vec(),
            grant,
        };

        durable
            .admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence)
            .expect("final-use admission");
        let event = durable
            .registry()
            .lifecycle_events()
            .last()
            .expect("admission event");
        assert_eq!(event.kind, LifecycleEventKind::Admitted);
        assert_eq!(event.actor_id, reviewer);
        assert_eq!(event.scope_digest, Some(scope));
        assert_eq!(event.evidence_digest, evidence);
        assert_eq!(event.admission_grant_id, Some(id("admission-final-use-1")));

        assert!(matches!(
            durable
                .admit_factor_final_use(&authority, &signed, &factor.factor_id, scope, evidence,),
            Err(DurableRegistryError::Admission(AdmissionError::AlreadyUsed))
        ));

        let second_factor = PromptFactor {
            factor_id: id("factor:revoked-grant"),
            proposer_id: id("proposer:revoked-grant"),
            semantic_version: id("v1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest("factor:revoked-grant"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        durable
            .register_factor(second_factor.clone())
            .expect("register second factor");
        let second_binding = crate::final_use_admission_binding(
            &second_factor,
            &id("reviewer:revoked-grant"),
            scope,
            evidence,
        )
        .expect("second binding");
        let second_grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".to_owned(),
            authority_epoch: 7,
            grant_id: "admission-final-use-revoked".to_owned(),
            nonce: [18; 32],
            binding: second_binding,
            not_before_unix_ms: now.saturating_sub(1000),
            expires_at_unix_ms: now + 30_000,
        };
        let second_signed = SignedFinalUseGrant {
            signature: signing_key
                .sign(&second_grant.signing_bytes().expect("second signing bytes"))
                .to_bytes()
                .to_vec(),
            grant: second_grant,
        };
        authority
            .update_revocations(FinalUseRevocations {
                authority_epoch: 7,
                revision: 2,
                revoked_grant_ids: BTreeSet::from(["admission-final-use-revoked".to_owned()]),
            })
            .expect("revoke grant");
        assert!(matches!(
            durable.admit_factor_final_use(
                &authority,
                &second_signed,
                &second_factor.factor_id,
                scope,
                evidence,
            ),
            Err(DurableRegistryError::Admission(AdmissionError::Revoked))
        ));
        assert_eq!(
            durable
                .registry()
                .factor(&second_factor.factor_id)
                .map(|factor| factor.lifecycle),
            Some(Lifecycle::Draft)
        );
    }

    #[test]
    fn final_use_revocation_binds_actor_reason_cutoff_and_persists_lineage() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let registry_root = temporary.path().join("registry-lifecycle");
        let authority_root = temporary.path().join("authority-lifecycle");
        let signing_key = SigningKey::from_bytes(&[51; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &authority_root,
            "security-owner:lifecycle".to_owned(),
            signing_key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 9,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("final-use authority");

        let mut durable =
            DurablePromptRegistry::open_state_dir(&registry_root, 64).expect("registry");
        let factor = PromptFactor {
            factor_id: id("factor:lifecycle-final-use"),
            proposer_id: id("proposer:lifecycle-final-use"),
            semantic_version: id("v1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest("factor:lifecycle-final-use"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        durable
            .register_factor(factor.clone())
            .expect("register factor");

        let reviewer = id("reviewer:lifecycle-final-use");
        let admission_scope = digest("scope:admission:lifecycle");
        let evidence = digest("evidence:admission:lifecycle");
        let admission_binding =
            crate::final_use_admission_binding(&factor, &reviewer, admission_scope, evidence)
                .expect("admission binding");
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis() as u64;
        let admission_grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner:lifecycle".to_owned(),
            authority_epoch: 9,
            grant_id: "grant:lifecycle-admit".to_owned(),
            nonce: [51; 32],
            binding: admission_binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let admission_signed = SignedFinalUseGrant {
            signature: signing_key
                .sign(
                    &admission_grant
                        .signing_bytes()
                        .expect("admission signing bytes"),
                )
                .to_bytes()
                .to_vec(),
            grant: admission_grant,
        };
        durable
            .admit_factor_final_use(
                &authority,
                &admission_signed,
                &factor.factor_id,
                admission_scope,
                evidence,
            )
            .expect("admit factor");

        let actor = id("revoker:lifecycle-final-use");
        let revoke_scope = digest("scope:revoke:lifecycle");
        let reason = digest("reason:revoke:lifecycle");
        let cutoff = now + 5_000;
        let admitted_factor = durable
            .registry()
            .factor(&factor.factor_id)
            .cloned()
            .expect("admitted factor");
        let revoke_binding =
            crate::final_use_revoke_binding(&admitted_factor, &actor, revoke_scope, reason, cutoff)
                .expect("revoke binding");
        let revoke_grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner:lifecycle".to_owned(),
            authority_epoch: 9,
            grant_id: "grant:lifecycle-revoke".to_owned(),
            nonce: [52; 32],
            binding: revoke_binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let revoke_signed = SignedFinalUseGrant {
            signature: signing_key
                .sign(&revoke_grant.signing_bytes().expect("revoke signing bytes"))
                .to_bytes()
                .to_vec(),
            grant: revoke_grant,
        };
        durable
            .revoke_factor_final_use(
                &authority,
                &revoke_signed,
                &factor.factor_id,
                &actor,
                revoke_scope,
                reason,
                cutoff,
            )
            .expect("revoke factor through final-use authority");

        let event = durable
            .registry()
            .lifecycle_events()
            .last()
            .expect("revocation event");
        assert_eq!(event.kind, LifecycleEventKind::Revoked);
        assert_eq!(event.actor_id, actor);
        assert_eq!(event.reason_digest, Some(reason));
        assert_eq!(event.cutoff_unix_ms, Some(cutoff));
        drop(durable);

        let reopened =
            DurablePromptRegistry::open_state_dir(&registry_root, 64).expect("reopen registry");
        assert_eq!(
            reopened
                .registry()
                .factor(&factor.factor_id)
                .map(|record| record.lifecycle),
            Some(Lifecycle::Revoked)
        );
        let persisted = reopened
            .registry()
            .lifecycle_events()
            .last()
            .expect("persisted revocation event");
        assert_eq!(persisted.actor_id, actor);
        assert_eq!(persisted.reason_digest, Some(reason));
        assert_eq!(persisted.cutoff_unix_ms, Some(cutoff));
    }

    #[test]
    fn post_rename_sync_failure_poison_writer_until_reopen() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry-indeterminate");
        let mut durable =
            DurablePromptRegistry::open_state_dir(&root, 64).expect("initialize registry");
        let factor = PromptFactor {
            factor_id: id("factor:indeterminate"),
            proposer_id: id("proposer:indeterminate"),
            semantic_version: id("v1"),
            semantic_purpose: "verify before mutating".to_owned(),
            authority_class: "registered_prompt_factor".to_owned(),
            eligible_objective_dimensions: vec![id("dimension:truth")],
            content_digest: digest("factor:indeterminate"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };

        durable.fail_directory_sync_after_rename_once();
        assert!(matches!(
            durable.register_factor(factor.clone()),
            Err(DurableRegistryError::IndeterminateDurability)
        ));
        assert!(durable.requires_reopen());
        assert!(durable.registry().factor(&factor.factor_id).is_none());
        assert!(matches!(
            durable.register_factor(PromptFactor {
                factor_id: id("factor:must-not-write"),
                proposer_id: id("proposer:must-not-write"),
                semantic_version: id("v1"),
                semantic_purpose: "verify before mutating".to_owned(),
                authority_class: "registered_prompt_factor".to_owned(),
                eligible_objective_dimensions: vec![id("dimension:truth")],
                content_digest: digest("factor:must-not-write"),
                source: FactorSource::GovernedInternal,
                lifecycle: Lifecycle::Draft,
            }),
            Err(DurableRegistryError::ReopenRequired)
        ));
        assert!(matches!(
            durable.snapshot_v2(
                digest("generation-vector:poisoned"),
                &PromptModelTupleV2 {
                    model_id: id("model:hepta-test"),
                    model_version: "2026-09-18".to_owned(),
                    model_digest: digest("model:poisoned"),
                    tokenizer_digest: digest("tokenizer:poisoned"),
                    template_digest: digest("template:poisoned"),
                    tool_schema_digest: digest("tool-schema:poisoned"),
                    context_profile_digest: digest("context-profile:poisoned"),
                    locale_id: id("locale:en-US"),
                },
            ),
            Err(DurableRegistryError::ReopenRequired)
        ));

        drop(durable);
        let reopened =
            DurablePromptRegistry::open_state_dir(&root, 64).expect("reconcile by reopen");
        assert!(!reopened.requires_reopen());
        assert_eq!(reopened.registry().factor(&factor.factor_id), Some(&factor));
    }

    #[test]
    fn reopen_rejects_resource_policy_drift() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        drop(DurablePromptRegistry::open_state_dir(&root, 64).expect("initialize registry"));
        assert!(matches!(
            DurablePromptRegistry::open_state_dir(&root, 65),
            Err(DurableRegistryError::ConfigurationMismatch)
        ));
    }
}
