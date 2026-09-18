//! V2 prompt-realization contract types and canonical digest semantics.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::model::push_id;

pub const MAX_COMPATIBLE_REALIZATIONS_V2: usize = 128;
pub const MAX_REALIZATION_PAYLOAD_BYTES: usize = 64 * 1024;
pub const MAX_TOTAL_REALIZATION_PAYLOAD_BYTES: usize = 32 * 1024 * 1024;
const BINDING_DOMAIN: &[u8] = b"hepta.prompt-realization-binding.v2";
const SNAPSHOT_DOMAIN: &[u8] = b"hepta.prompt-registry-snapshot.v2";
const COMPATIBLE_SET_DOMAIN: &[u8] = b"hepta.prompt-compatible-realization-set.v2";
const PAYLOAD_RESOLUTION_DOMAIN: &[u8] = b"hepta.prompt-payload-resolution.v2";

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
    pub context_profile_digest: Digest32,
    pub locale_id: StableId,
    pub role: PromptRoleV2,
    pub payload_digest: Digest32,
    pub token_cost: u32,
    pub expires_unix_ms: Option<u64>,
    pub predecessor_realization_id: Option<StableId>,
}

impl PromptRealizationBindingV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
            ("context_profile", self.context_profile_digest),
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
        if self
            .predecessor_realization_id
            .as_ref()
            .is_some_and(|value| value == &self.realization_id)
        {
            return Err(PromptRegistryV2Error::InvalidSupersession(
                self.realization_id.to_string(),
            ));
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
            self.context_profile_digest,
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
        match &self.predecessor_realization_id {
            Some(value) => {
                bytes.push(1);
                push_id(&mut bytes, value);
            }
            None => bytes.push(0),
        }
        Digest32::of_bytes(&bytes)
    }

    pub(crate) fn same_active_key(&self, other: &Self) -> bool {
        self.factor_id == other.factor_id
            && self.model_digest == other.model_digest
            && self.tokenizer_digest == other.tokenizer_digest
            && self.template_digest == other.template_digest
            && self.tool_schema_digest == other.tool_schema_digest
            && self.context_profile_digest == other.context_profile_digest
            && self.locale_id == other.locale_id
    }

    pub(crate) fn compatible_with(&self, model_tuple: &PromptModelTupleV2) -> bool {
        self.model_digest == model_tuple.model_digest
            && self.tokenizer_digest == model_tuple.tokenizer_digest
            && self.template_digest == model_tuple.template_digest
            && self.tool_schema_digest == model_tuple.tool_schema_digest
            && self.context_profile_digest == model_tuple.context_profile_digest
            && self.locale_id == model_tuple.locale_id
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptModelTupleV2 {
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub tool_schema_digest: Digest32,
    pub context_profile_digest: Digest32,
    pub locale_id: StableId,
}

impl PromptModelTupleV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        for (name, digest) in [
            ("model", self.model_digest),
            ("tokenizer", self.tokenizer_digest),
            ("template", self.template_digest),
            ("tool_schema", self.tool_schema_digest),
            ("context_profile", self.context_profile_digest),
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
            self.context_profile_digest,
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
        if !is_strictly_sorted(&self.required_factor_ids) {
            return Err(PromptRegistryV2Error::NonCanonicalFactorFilter);
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPayloadResolutionV2 {
    pub realization_id: StableId,
    pub factor_id: StableId,
    pub payload: Vec<u8>,
    pub payload_digest: Digest32,
    pub binding_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub resolution_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptPayloadResolutionV2 {
    pub fn validate(&self) -> Result<(), PromptRegistryV2Error> {
        if self.payload.is_empty() || self.payload.len() > MAX_REALIZATION_PAYLOAD_BYTES {
            return Err(PromptRegistryV2Error::InvalidPayloadSize);
        }
        for (name, digest) in [
            ("payload", self.payload_digest),
            ("binding", self.binding_digest),
            ("snapshot", self.snapshot_digest),
            ("model_tuple", self.model_tuple_digest),
            ("resolution", self.resolution_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if Digest32::of_bytes(&self.payload) != self.payload_digest {
            return Err(PromptRegistryV2Error::DigestMismatch("payload"));
        }
        if self.authority.grants_any() {
            return Err(PromptRegistryV2Error::AuthorityGranted);
        }
        if self.resolution_digest != self.compute_resolution_digest() {
            return Err(PromptRegistryV2Error::DigestMismatch("payload_resolution"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_resolution_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(PAYLOAD_RESOLUTION_DOMAIN);
        push_id(&mut bytes, &self.realization_id);
        push_id(&mut bytes, &self.factor_id);
        push_digest(&mut bytes, self.payload_digest);
        push_digest(&mut bytes, self.binding_digest);
        push_digest(&mut bytes, self.snapshot_digest);
        push_digest(&mut bytes, self.model_tuple_digest);
        Digest32::of_bytes(&bytes)
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
    RequiredFactorLimitExceeded,
    DuplicateFactorFilter(String),
    NonCanonicalFactorFilter,
    RequiredFactorUnavailable,
    RealizationUnavailable(String),
    PayloadUnavailable(String),
    InvalidPayloadSize,
    InvalidSupersession(String),
    SnapshotStale,
    RegistryIntegrity,
    AuthorityGranted,
}

impl fmt::Display for PromptRegistryV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptRegistryV2Error {}

pub(crate) fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), PromptRegistryV2Error> {
    if digest.is_zero() {
        return Err(PromptRegistryV2Error::EmptyDigest(name));
    }
    Ok(())
}

fn is_strictly_sorted(values: &[StableId]) -> bool {
    values.windows(2).all(|pair| pair[0] < pair[1])
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

pub(crate) fn role_code(role: PromptRoleV2) -> u8 {
    match role {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}
