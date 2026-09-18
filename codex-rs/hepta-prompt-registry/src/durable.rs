//! Durable authoritative prompt registry owner.
//!
//! The pure PromptRegistry remains the deterministic domain core. This wrapper
//! applies a mutation to a clone, fsyncs an atomic owner snapshot, and only then
//! publishes the new in-process state. Store failure therefore cannot expose an
//! uncommitted mutation.

use std::collections::BTreeMap;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::Error;
use crate::FactorSource;
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

const STORE_SCHEMA: u32 = 2;
const MAX_STATE_BYTES: u64 = 32 * 1024 * 1024;
const LEGACY_CONTEXT_PROFILE_DOMAIN: &[u8] =
    b"hepta.prompt-registry.legacy-context-profile.v1";
const MIGRATION_REASON_DOMAIN: &[u8] = b"hepta.prompt-registry.migration.v1-v2";

pub struct DurablePromptRegistry {
    registry: PromptRegistry,
    store: Store,
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
        Ok(Self { registry, store })
    }

    pub fn registry(&self) -> &PromptRegistry {
        &self.registry
    }

    pub fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| registry.register_factor(factor))
    }

    pub fn admit_factor_verified(
        &mut self,
        admission: VerifiedAdmission,
        now_unix_ms: u64,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| registry.admit_factor_verified(admission, now_unix_ms))
    }

    pub fn register_realization_payload_v2(
        &mut self,
        binding: PromptRealizationBindingV2,
        payload: Vec<u8>,
        supersedes_realization_id: Option<StableId>,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        self.commit(|registry| {
            registry.register_realization_payload_v2(
                binding,
                payload,
                supersedes_realization_id,
            )
        })
    }

    pub fn retire_factor(
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

    pub fn revoke_factor(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
        cutoff_unix_ms: u64,
    ) -> Result<RegistryReceipt, DurableRegistryError> {
        let factor_id = factor_id.clone();
        let actor_id = actor_id.clone();
        self.commit(|registry| {
            registry.revoke_factor_governed(
                &factor_id,
                &actor_id,
                reason_digest,
                cutoff_unix_ms,
            )
        })
    }

    pub fn snapshot_v2(
        &self,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
    ) -> Result<PromptRegistrySnapshotV2, DurableRegistryError> {
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
        let mut next = self.registry.clone();
        let receipt = mutation(&mut next).map_err(DurableRegistryError::Core)?;
        if receipt.disposition != crate::MutationDisposition::Unchanged {
            self.store.persist(&next)?;
            self.registry = next;
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
        lifecycle_events: registry
            .lifecycle_events
            .iter()
            .map(stored_event)
            .collect(),
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
    let mut factors = BTreeMap::new();
    let migration_actor = StableId::new("migration:v1")
        .map_err(|_| DurableRegistryError::Corrupt)?;
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

    let legacy_context_profile_digest = Digest32::of_bytes(LEGACY_CONTEXT_PROFILE_DOMAIN);
    let mut realization_bindings = BTreeMap::new();
    for stored_binding in stored.bindings {
        let binding = PromptRealizationBindingV2 {
            realization_id: parse_id(stored_binding.realization_id)?,
            factor_id: parse_id(stored_binding.factor_id)?,
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
    {
        return Err(DurableRegistryError::Corrupt);
    }
    for (realization_id, binding) in &registry.realization_bindings {
        let Some(realization) = registry.realizations.get(realization_id) else {
            return Err(DurableRegistryError::Corrupt);
        };
        if realization.factor_id != binding.factor_id
            || realization.model_digest != binding.model_digest
            || realization.tokenizer_digest != binding.tokenizer_digest
            || realization.content_digest != binding.payload_digest
        {
            return Err(DurableRegistryError::Corrupt);
        }
        if let Some(payload) = registry.realization_payloads.get(realization_id)
            && Digest32::of_bytes(payload) != binding.payload_digest
        {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    for (successor, predecessor) in &registry.realization_supersessions {
        let Some(successor_record) = registry.realizations.get(successor) else {
            return Err(DurableRegistryError::Corrupt);
        };
        let Some(predecessor_record) = registry.realizations.get(predecessor) else {
            return Err(DurableRegistryError::Corrupt);
        };
        if successor_record.factor_id != predecessor_record.factor_id || predecessor_record.active {
            return Err(DurableRegistryError::Corrupt);
        }
    }
    Ok(())
}

fn decode_factor(stored: StoredFactor) -> Result<PromptFactor, DurableRegistryError> {
    Ok(PromptFactor {
        factor_id: parse_id(stored.factor_id)?,
        proposer_id: parse_id(stored.proposer_id)?,
        semantic_version: parse_id(stored.semantic_version)?,
        content_digest: Digest32::from_array(stored.content_digest),
        source: decode_factor_source(stored.source)?,
        lifecycle: decode_lifecycle(stored.lifecycle)?,
    })
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
        admission_grant_id: stored
            .admission_grant_id
            .map(parse_id)
            .transpose()?,
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
}

impl Store {
    fn open(directory: &Path) -> Result<(Self, Option<StoredAny>), DurableRegistryError> {
        let root = prepare_directory(directory)?;
        let initialized = entry_exists(&root, "registry.lock")?;
        let lock = open_private(&root, "registry.lock", Access::Create)?;
        lock.try_lock().map_err(|_| DurableRegistryError::StateLocked)?;
        let store = Self { root, _lock: lock };
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
        let bytes =
            serde_json::to_vec(&stored_v2(registry)).map_err(|_| DurableRegistryError::Unavailable)?;
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
        self.root
            .sync_all()
            .map_err(|_| DurableRegistryError::Unavailable)
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
    Read(PromptRegistryV2Error),
    Corrupt,
    CapacityExceeded,
    Unavailable,
    UnsafeStateDirectory,
    StateLocked,
}

impl fmt::Display for DurableRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for DurableRegistryError {}

#[cfg(all(test, unix))]
mod tests {
    use std::os::unix::fs::OpenOptionsExt;

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
            realizations: Vec::new(),
            bindings: Vec::new(),
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

        let durable =
            DurablePromptRegistry::open_state_dir(&root, 64).expect("migrate registry");
        let factor = durable.registry().factor(&id("factor:1")).expect("factor");
        assert_eq!(factor.lifecycle, Lifecycle::Revoked);
        assert_eq!(durable.registry().revocation_frontier(), 4);
        assert_eq!(
            durable.registry().lifecycle_events().last().map(|event| event.kind),
            Some(LifecycleEventKind::Imported)
        );
    }

    #[test]
    fn restart_preserves_revocation_payload_and_admission_lineage() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let factor = PromptFactor {
            factor_id: id("factor:durable"),
            proposer_id: id("proposer:durable"),
            semantic_version: id("v1"),
            content_digest: digest("factor:durable"),
            source: FactorSource::GovernedInternal,
            lifecycle: Lifecycle::Draft,
        };
        let tuple = PromptModelTupleV2 {
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
                    20,
                )
                .expect("verified admission");
            durable
                .admit_factor_verified(verified, 20)
                .expect("admit factor");

            let binding = PromptRealizationBindingV2 {
                realization_id: id("realization:durable"),
                factor_id: factor.factor_id.clone(),
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

        let reopened =
            DurablePromptRegistry::open_state_dir(&root, 64).expect("reopen registry");
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
            Err(DurableRegistryError::Read(PromptRegistryV2Error::SnapshotStale))
        ));
    }

}
