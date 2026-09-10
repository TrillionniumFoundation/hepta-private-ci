//! Model-profile-bound prompt realization registry views.
//!
//! Semantic prompt factors and concrete model realizations remain separate
//! identities. V2 bindings add template, tool-schema, locale, role, token cost
//! and expiry without changing the legacy V1 record. Reads freeze one exact
//! registry snapshot and fail closed on any lifecycle, revocation or model tuple
//! drift.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::Error;
use crate::FactorSource;
use crate::Lifecycle;
use crate::MutationDisposition;
use crate::PromptRealization;
use crate::PromptRegistry;
use crate::RegistryReceipt;

pub const MAX_COMPATIBLE_REALIZATIONS_V2: usize = 128;
const BINDING_DOMAIN: &[u8] = b"hepta.prompt-realization-binding.v2";
const SNAPSHOT_DOMAIN: &[u8] = b"hepta.prompt-registry-snapshot.v2";
const COMPATIBLE_SET_DOMAIN: &[u8] = b"hepta.prompt-compatible-realization-set.v2";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum PromptRoleV2 {
    SystemInstruction,
    DeveloperInstruction,
    UserTemplate,
    ToolSchemaFragment,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRealizationBindingV2 {
    pub realization_id: StableId,
    pub factor_id: StableId,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub locale_id: StableId,
    pub role: PromptRoleV2,
    pub payload_digest: Digest32,
    pub token_cost: u32,
    pub expires_unix_ms: Option<u64>,
}

impl PromptRealizationBindingV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
            ("payload", self.payload_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.token_cost == 0 {
            return Err(PromptRegistryV2Error::ZeroTokenCost);
        }
        if self.expires_unix_ms == Some(0) {
            return Err(PromptRegistryV2Error::InvalidExpiry);
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(BINDING_DOMAIN);
        push_id(&mut bytes, &self.realization_id);
        push_id(&mut bytes, &self.factor_id);
        for digest in [
            self.model_digest,
            self.tokenizer_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_id(&mut bytes, &self.locale_id);
        bytes.push(role_code(self.role));
        push_digest(&mut bytes, self.payload_digest);
        push_u64(&mut bytes, u64::from(self.token_cost));
        match self.expires_unix_ms {
            Some(value) => {
                bytes.push(1);
                push_u64(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptModelTupleV2 {
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub locale_id: StableId,
}

impl PromptModelTupleV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-model-tuple.v2".to_vec();
        for digest in [
            self.model_digest,
            self.tokenizer_digest,
            self.template_digest,
            self.tool_schema_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_id(&mut bytes, &self.locale_id);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptRegistrySnapshotV2 {
    pub revision: Revision,
    pub registry_digest: Digest32,
    pub lifecycle_frontier: u64,
    pub revocation_frontier: u64,
    pub generation_vector_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptRegistrySnapshotV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        for (name, digest) in [
            ("registry", self.registry_digest),
            ("generation_vector", self.generation_vector_digest),
            ("model_tuple", self.model_tuple_digest),
            ("snapshot", self.snapshot_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.revocation_frontier > self.lifecycle_frontier
            || self.lifecycle_frontier > self.revision.get()
        {
            return Err(PromptRegistryV2Error::InvalidFrontier);
        }
        if self.authority.grants_any() {
            return Err(PromptRegistryV2Error::AuthorityGranted);
        }
        if self.snapshot_digest != self.compute_snapshot_digest() {
            return Err(PromptRegistryV2Error::DigestMismatch("snapshot"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_snapshot_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(SNAPSHOT_DOMAIN);
        push_u64(&mut bytes, self.revision.get());
        push_digest(&mut bytes, self.registry_digest);
        push_u64(&mut bytes, self.lifecycle_frontier);
        push_u64(&mut bytes, self.revocation_frontier);
        push_digest(&mut bytes, self.generation_vector_digest);
        push_digest(&mut bytes, self.model_tuple_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompatibleRealizationSetV2 {
    pub snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub required_factor_ids: Vec<StableId>,
    pub bindings: Vec<PromptRealizationBindingV2>,
    pub omitted_count: u32,
    pub set_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompatibleRealizationSetV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        for (name, digest) in [
            ("snapshot", self.snapshot_digest),
            ("model_tuple", self.model_tuple_digest),
            ("compatible_set", self.set_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.bindings.len() > MAX_COMPATIBLE_REALIZATIONS_V2 {
            return Err(PromptRegistryV2Error::ReadLimitExceeded);
        }
        if self.authority.grants_any() {
            return Err(PromptRegistryV2Error::AuthorityGranted);
        }
        if self.set_digest != self.compute_set_digest() {
            return Err(PromptRegistryV2Error::DigestMismatch("compatible_set"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_set_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(COMPATIBLE_SET_DOMAIN);
        push_digest(&mut bytes, self.snapshot_digest);
        push_digest(&mut bytes, self.model_tuple_digest);
        push_len(&mut bytes, self.required_factor_ids.len());
        for factor_id in &self.required_factor_ids {
            push_id(&mut bytes, factor_id);
        }
        push_len(&mut bytes, self.bindings.len());
        for binding in &self.bindings {
            push_digest(&mut bytes, binding.digest());
        }
        push_u64(&mut bytes, u64::from(self.omitted_count));
        Digest32::of_bytes(&bytes)
    }
}

impl PromptRegistry {
    pub fn register_realization_v2(
        &mut self,
        binding: PromptRealizationBindingV2,
    ) -> Result<RegistryReceipt, Error> {
        binding.validate().map_err(|error| match error {
            PromptRegistryV2Error::EmptyDigest(name) => Error::EmptyDigest(name),
            _ => Error::InvalidTransition,
        })?;
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
        let existing_legacy = self.realizations.get(&binding.realization_id);
        let existing_binding = self.realization_bindings.get(&binding.realization_id);
        match (existing_legacy, existing_binding) {
            (Some(existing_legacy), Some(existing_binding))
                if existing_legacy == &legacy && existing_binding == &binding =>
            {
                return Ok(self.receipt(MutationDisposition::Unchanged));
            }
            (None, None) => {}
            _ => {
                return Err(Error::RealizationConflict(
                    binding.realization_id.to_string(),
                ));
            }
        }
        self.ensure_capacity(1)?;
        let next_revision = self.next_revision()?;
        self.realizations
            .insert(binding.realization_id.clone(), legacy);
        self.realization_bindings
            .insert(binding.realization_id.clone(), binding);
        self.commit_revision(next_revision, false);
        Ok(self.receipt(MutationDisposition::Inserted))
    }

    pub fn snapshot_v2(
        &self,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
    ) -> Result<PromptRegistrySnapshotV2, PromptRegistryV2Error> {
        ensure_digest("generation_vector", generation_vector_digest)?;
        model_tuple.validate()?;
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
        required_factor_ids: Vec<StableId>,
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
        let mut factor_filter = BTreeSet::new();
        for factor_id in &required_factor_ids {
            if !factor_filter.insert(factor_id.clone()) {
                return Err(PromptRegistryV2Error::DuplicateFactorFilter(
                    factor_id.to_string(),
                ));
            }
        }
        let mut bindings = self
            .realization_bindings
            .values()
            .filter(|binding| {
                let factor_valid = self
                    .factors
                    .get(&binding.factor_id)
                    .is_some_and(|factor| factor.lifecycle == Lifecycle::Admitted);
                let realization_active = self
                    .realizations
                    .get(&binding.realization_id)
                    .is_some_and(|realization| realization.active);
                let selected_factor =
                    factor_filter.is_empty() || factor_filter.contains(&binding.factor_id);
                let compatible = binding.model_digest == model_tuple.model_digest
                    && binding.tokenizer_digest == model_tuple.tokenizer_digest
                    && binding.template_digest == model_tuple.template_digest
                    && binding.tool_schema_digest == model_tuple.tool_schema_digest
                    && binding.locale_id == model_tuple.locale_id;
                let live = binding
                    .expires_unix_ms
                    .is_none_or(|expires| now_unix_ms < expires);
                factor_valid && realization_active && selected_factor && compatible && live
            })
            .cloned()
            .collect::<Vec<_>>();
        bindings.sort_by(|left, right| {
            left.factor_id
                .cmp(&right.factor_id)
                .then_with(|| left.realization_id.cmp(&right.realization_id))
        });
        let omitted_count = bindings.len().saturating_sub(maximum_results);
        bindings.truncate(maximum_results);
        if !factor_filter.is_empty() {
            let returned = bindings
                .iter()
                .map(|binding| binding.factor_id.clone())
                .collect::<BTreeSet<_>>();
            if factor_filter
                .iter()
                .any(|factor_id| !returned.contains(factor_id))
            {
                return Err(PromptRegistryV2Error::RequiredFactorUnavailable);
            }
        }
        let mut result = CompatibleRealizationSetV2 {
            snapshot_digest: current_snapshot.snapshot_digest,
            model_tuple_digest: model_tuple.digest(),
            required_factor_ids,
            bindings,
            omitted_count: u32::try_from(omitted_count).unwrap_or(u32::MAX),
            set_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        result.set_digest = result.compute_set_digest();
        result.validate()?;
        Ok(result)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptRegistryV2Error {
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    ZeroTokenCost,
    InvalidExpiry,
    InvalidFrontier,
    ReadLimitExceeded,
    DuplicateFactorFilter(String),
    RequiredFactorUnavailable,
    SnapshotStale,
    AuthorityGranted,
}

impl fmt::Display for PromptRegistryV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptRegistryV2Error {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), PromptRegistryV2Error> {
    if digest.is_zero() {
        return Err(PromptRegistryV2Error::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn role_code(role: PromptRoleV2) -> u8 {
    match role {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
