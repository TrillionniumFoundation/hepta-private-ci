use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DecodedEnvelope;
use crate::NegotiatedWire;
use crate::SchemaAdmissionError;
use crate::SchemaDescriptor;
use crate::SchemaRegistry;
use crate::WireCapabilities;
use crate::WireVersion;

pub const MAX_FROZEN_SCHEMA_ENTRIES: usize = 256;
pub const MAX_POLICY_SUBJECTS: usize = 64;
const REGISTRY_DIGEST_DOMAIN: &[u8] = b"HPTA-SCHEMA-REGISTRY-V2\0";
const DEFAULT_SCHEMA_REVISION_DOMAIN: &[u8] = b"HPTA-SCHEMA-REVISION-V1\0";

/// Generation admission owned by a frozen schema policy.
///
/// Replay ordering remains a session/record-layer concern. This policy only
/// rejects a frame generation that predates the schema's admitted floor.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GenerationPolicy {
    NonZero,
    AtLeast(u64),
}

impl GenerationPolicy {
    pub const fn minimum(self) -> u64 {
        match self {
            Self::NonZero => 1,
            Self::AtLeast(minimum) => minimum,
        }
    }

    const fn admits(self, generation: Generation) -> bool {
        generation.get() >= self.minimum()
    }
}

/// Canonicalization contract delegated to the registered typed codec.
///
/// This marker is bound into the immutable registry snapshot and therefore the
/// authenticated negotiation transcript. It never canonicalizes untyped bytes
/// by itself; the matching codec must enforce the selected profile.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalizationProfile {
    CodecOwnedStrictV1,
    CanonicalJsonV1,
    OpaqueBytesV1,
}

impl CanonicalizationProfile {
    pub const fn id(self) -> &'static str {
        match self {
            Self::CodecOwnedStrictV1 => "codec-owned-strict-v1",
            Self::CanonicalJsonV1 => "canonical-json-v1",
            Self::OpaqueBytesV1 => "opaque-bytes-v1",
        }
    }
}

/// Immutable admission policy for one schema.
///
/// Production callers must enumerate producer identities and runtime roles and
/// bind a semantic schema revision, generation floor and canonicalization
/// profile. This prevents a newly introduced caller from treating basic schema
/// admission as producer authorization or silently changing payload semantics.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchemaPolicy {
    descriptor: SchemaDescriptor,
    schema_revision: Digest32,
    generation_policy: GenerationPolicy,
    canonicalization_profile: CanonicalizationProfile,
    allowed_producers: Vec<StableId>,
    allowed_roles: Vec<StableId>,
    required_capabilities: WireCapabilities,
}

impl SchemaPolicy {
    /// Backward-compatible strict constructor.
    ///
    /// The derived revision is deterministic for the descriptor, generations
    /// remain non-zero, and canonicalization remains codec-owned. Production
    /// domains that need an externally frozen semantic revision or a later
    /// generation floor should use `new_bound`.
    pub fn new(
        descriptor: SchemaDescriptor,
        allowed_producers: Vec<StableId>,
        allowed_roles: Vec<StableId>,
        required_capabilities: WireCapabilities,
    ) -> Result<Self, RegistryBuildError> {
        let schema_revision = default_schema_revision(&descriptor);
        Self::new_bound(
            descriptor,
            schema_revision,
            GenerationPolicy::NonZero,
            CanonicalizationProfile::CodecOwnedStrictV1,
            allowed_producers,
            allowed_roles,
            required_capabilities,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn new_bound(
        descriptor: SchemaDescriptor,
        schema_revision: Digest32,
        generation_policy: GenerationPolicy,
        canonicalization_profile: CanonicalizationProfile,
        mut allowed_producers: Vec<StableId>,
        mut allowed_roles: Vec<StableId>,
        required_capabilities: WireCapabilities,
    ) -> Result<Self, RegistryBuildError> {
        if schema_revision.is_zero() {
            return Err(RegistryBuildError::ZeroSchemaRevision(
                descriptor.schema().clone(),
            ));
        }
        if generation_policy.minimum() == 0 {
            return Err(RegistryBuildError::InvalidGenerationFloor {
                schema: descriptor.schema().clone(),
                minimum: 0,
            });
        }
        allowed_producers.sort();
        allowed_producers.dedup();
        allowed_roles.sort();
        allowed_roles.dedup();
        if allowed_producers.is_empty() {
            return Err(RegistryBuildError::EmptyProducerPolicy(
                descriptor.schema().clone(),
            ));
        }
        if allowed_roles.is_empty() {
            return Err(RegistryBuildError::EmptyRolePolicy(
                descriptor.schema().clone(),
            ));
        }
        if allowed_producers.len() > MAX_POLICY_SUBJECTS {
            return Err(RegistryBuildError::TooManyProducers {
                schema: descriptor.schema().clone(),
                actual: allowed_producers.len(),
                maximum: MAX_POLICY_SUBJECTS,
            });
        }
        if allowed_roles.len() > MAX_POLICY_SUBJECTS {
            return Err(RegistryBuildError::TooManyRoles {
                schema: descriptor.schema().clone(),
                actual: allowed_roles.len(),
                maximum: MAX_POLICY_SUBJECTS,
            });
        }
        Ok(Self {
            descriptor,
            schema_revision,
            generation_policy,
            canonicalization_profile,
            allowed_producers,
            allowed_roles,
            required_capabilities,
        })
    }

    pub fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    pub const fn schema_revision(&self) -> Digest32 {
        self.schema_revision
    }

    pub const fn generation_policy(&self) -> GenerationPolicy {
        self.generation_policy
    }

    pub const fn canonicalization_profile(&self) -> CanonicalizationProfile {
        self.canonicalization_profile
    }

    pub fn allowed_producers(&self) -> &[StableId] {
        &self.allowed_producers
    }

    pub fn allowed_roles(&self) -> &[StableId] {
        &self.allowed_roles
    }

    pub const fn required_capabilities(&self) -> WireCapabilities {
        self.required_capabilities
    }
}

fn default_schema_revision(descriptor: &SchemaDescriptor) -> Digest32 {
    let mut encoded = Vec::new();
    encoded.extend_from_slice(DEFAULT_SCHEMA_REVISION_DOMAIN);
    put_id(&mut encoded, descriptor.schema());
    encoded.extend_from_slice(&descriptor.min_version().as_u16().to_be_bytes());
    encoded.extend_from_slice(&descriptor.max_version().as_u16().to_be_bytes());
    encoded.extend_from_slice(&(descriptor.max_payload_bytes() as u64).to_be_bytes());
    Digest32::of_bytes(&encoded)
}

#[derive(Clone, Debug)]
pub struct FrozenSchemaRegistryBuilder {
    maximum_entries: usize,
    policies: BTreeMap<StableId, SchemaPolicy>,
}

impl Default for FrozenSchemaRegistryBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl FrozenSchemaRegistryBuilder {
    pub fn new() -> Self {
        Self {
            maximum_entries: MAX_FROZEN_SCHEMA_ENTRIES,
            policies: BTreeMap::new(),
        }
    }

    pub fn with_maximum_entries(maximum_entries: usize) -> Result<Self, RegistryBuildError> {
        if !(1..=MAX_FROZEN_SCHEMA_ENTRIES).contains(&maximum_entries) {
            return Err(RegistryBuildError::InvalidEntryLimit {
                actual: maximum_entries,
                maximum: MAX_FROZEN_SCHEMA_ENTRIES,
            });
        }
        Ok(Self {
            maximum_entries,
            policies: BTreeMap::new(),
        })
    }

    pub fn register(&mut self, policy: SchemaPolicy) -> Result<(), RegistryBuildError> {
        let schema = policy.descriptor().schema().clone();
        if let Some(existing) = self.policies.get(&schema) {
            if existing == &policy {
                return Ok(());
            }
            return Err(RegistryBuildError::ConflictingPolicy(schema));
        }
        let attempted = self.policies.len().saturating_add(1);
        if attempted > self.maximum_entries {
            return Err(RegistryBuildError::EntryLimit {
                attempted,
                maximum: self.maximum_entries,
            });
        }
        self.policies.insert(schema, policy);
        Ok(())
    }

    pub fn freeze(self) -> Result<FrozenSchemaRegistry, RegistryBuildError> {
        let mut registry = SchemaRegistry::new();
        for policy in self.policies.values() {
            registry
                .register(policy.descriptor().clone())
                .map_err(RegistryBuildError::Schema)?;
        }
        let snapshot_digest = snapshot_digest(&self.policies);
        Ok(FrozenSchemaRegistry {
            registry,
            policies: self.policies,
            snapshot_digest,
        })
    }
}

/// Read-only schema and identity policy snapshot bound into a wire session.
#[derive(Clone, Debug)]
pub struct FrozenSchemaRegistry {
    registry: SchemaRegistry,
    policies: BTreeMap<StableId, SchemaPolicy>,
    snapshot_digest: Digest32,
}

impl FrozenSchemaRegistry {
    pub fn len(&self) -> usize {
        self.policies.len()
    }

    pub fn is_empty(&self) -> bool {
        self.policies.is_empty()
    }

    pub const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    pub fn policy(&self, schema: &StableId) -> Option<&SchemaPolicy> {
        self.policies.get(schema)
    }

    pub fn admit_envelope(
        &self,
        negotiated: NegotiatedWire,
        role: &StableId,
        envelope: &DecodedEnvelope,
    ) -> Result<&SchemaPolicy, FrozenAdmissionError> {
        self.registry
            .admit(envelope.version(), envelope.schema(), envelope.payload())
            .map_err(FrozenAdmissionError::Schema)?;
        self.admit_metadata(
            negotiated,
            role,
            envelope.version(),
            envelope.schema(),
            envelope.producer(),
            envelope.generation(),
        )
    }

    /// Validate all policy fields available before payload serialization.
    /// The completed envelope still undergoes payload-bound admission.
    pub(crate) fn admit_metadata(
        &self,
        negotiated: NegotiatedWire,
        role: &StableId,
        version: WireVersion,
        schema: &StableId,
        producer: &StableId,
        generation: Generation,
    ) -> Result<&SchemaPolicy, FrozenAdmissionError> {
        self.registry
            .admit_schema(version, schema)
            .map_err(FrozenAdmissionError::Schema)?;
        let policy = self.policies.get(schema).ok_or_else(|| {
            FrozenAdmissionError::Schema(SchemaAdmissionError::UnknownSchema(schema.clone()))
        })?;
        if version != negotiated.version() {
            return Err(FrozenAdmissionError::VersionMismatch {
                expected: negotiated.version().as_u16(),
                actual: version.as_u16(),
                byte_offset: 4,
            });
        }
        let effective = negotiated.capabilities();
        let required = policy.required_capabilities();
        if !effective.contains(required) {
            return Err(FrozenAdmissionError::CapabilityDenied {
                schema: schema.clone(),
                required: required.bits(),
                actual: effective.bits(),
            });
        }
        if policy.allowed_producers().binary_search(producer).is_err() {
            return Err(FrozenAdmissionError::ProducerDenied {
                schema: schema.clone(),
                producer: producer.clone(),
            });
        }
        if policy.allowed_roles().binary_search(role).is_err() {
            return Err(FrozenAdmissionError::RoleDenied {
                schema: schema.clone(),
                role: role.clone(),
            });
        }
        if !policy.generation_policy().admits(generation) {
            return Err(FrozenAdmissionError::GenerationDenied {
                schema: schema.clone(),
                minimum: policy.generation_policy().minimum(),
                actual: generation.get(),
            });
        }
        Ok(policy)
    }

    pub(crate) const fn inner(&self) -> &SchemaRegistry {
        &self.registry
    }
}

fn snapshot_digest(policies: &BTreeMap<StableId, SchemaPolicy>) -> Digest32 {
    let mut encoded = Vec::new();
    encoded.extend_from_slice(REGISTRY_DIGEST_DOMAIN);
    encoded.extend_from_slice(&(policies.len() as u32).to_be_bytes());
    for policy in policies.values() {
        let descriptor = policy.descriptor();
        put_id(&mut encoded, descriptor.schema());
        encoded.extend_from_slice(&descriptor.min_version().as_u16().to_be_bytes());
        encoded.extend_from_slice(&descriptor.max_version().as_u16().to_be_bytes());
        encoded.extend_from_slice(&(descriptor.max_payload_bytes() as u64).to_be_bytes());
        encoded.extend_from_slice(policy.schema_revision().as_array());
        encoded.extend_from_slice(&policy.generation_policy().minimum().to_be_bytes());
        put_raw(
            &mut encoded,
            policy.canonicalization_profile().id().as_bytes(),
        );
        encoded.extend_from_slice(&policy.required_capabilities().bits().to_be_bytes());
        encoded.extend_from_slice(&(policy.allowed_producers().len() as u16).to_be_bytes());
        for producer in policy.allowed_producers() {
            put_id(&mut encoded, producer);
        }
        encoded.extend_from_slice(&(policy.allowed_roles().len() as u16).to_be_bytes());
        for role in policy.allowed_roles() {
            put_id(&mut encoded, role);
        }
    }
    Digest32::of_bytes(&encoded)
}

fn put_id(encoded: &mut Vec<u8>, value: &StableId) {
    put_raw(encoded, value.as_str().as_bytes());
}

fn put_raw(encoded: &mut Vec<u8>, bytes: &[u8]) {
    encoded.extend_from_slice(&(bytes.len() as u16).to_be_bytes());
    encoded.extend_from_slice(bytes);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegistryBuildError {
    InvalidEntryLimit {
        actual: usize,
        maximum: usize,
    },
    EntryLimit {
        attempted: usize,
        maximum: usize,
    },
    ZeroSchemaRevision(StableId),
    InvalidGenerationFloor {
        schema: StableId,
        minimum: u64,
    },
    EmptyProducerPolicy(StableId),
    EmptyRolePolicy(StableId),
    TooManyProducers {
        schema: StableId,
        actual: usize,
        maximum: usize,
    },
    TooManyRoles {
        schema: StableId,
        actual: usize,
        maximum: usize,
    },
    ConflictingPolicy(StableId),
    Schema(SchemaAdmissionError),
}

impl fmt::Display for RegistryBuildError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidEntryLimit { actual, maximum } => write!(
                formatter,
                "frozen schema entry limit {actual} is outside 1..={maximum}"
            ),
            Self::EntryLimit { attempted, maximum } => write!(
                formatter,
                "frozen schema registry would contain {attempted} entries, maximum is {maximum}"
            ),
            Self::ZeroSchemaRevision(schema) => {
                write!(
                    formatter,
                    "schema {schema} has a zero semantic revision digest"
                )
            }
            Self::InvalidGenerationFloor { schema, minimum } => write!(
                formatter,
                "schema {schema} has invalid generation floor {minimum}; minimum is one"
            ),
            Self::EmptyProducerPolicy(schema) => {
                write!(formatter, "schema {schema} has no admitted producers")
            }
            Self::EmptyRolePolicy(schema) => {
                write!(formatter, "schema {schema} has no admitted runtime roles")
            }
            Self::TooManyProducers {
                schema,
                actual,
                maximum,
            } => write!(
                formatter,
                "schema {schema} has {actual} producer subjects, maximum is {maximum}"
            ),
            Self::TooManyRoles {
                schema,
                actual,
                maximum,
            } => write!(
                formatter,
                "schema {schema} has {actual} role subjects, maximum is {maximum}"
            ),
            Self::ConflictingPolicy(schema) => {
                write!(formatter, "conflicting frozen policy for schema {schema}")
            }
            Self::Schema(error) => error.fmt(formatter),
        }
    }
}

impl Error for RegistryBuildError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Schema(error) => Some(error),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FrozenAdmissionError {
    Schema(SchemaAdmissionError),
    VersionMismatch {
        expected: u16,
        actual: u16,
        byte_offset: usize,
    },
    CapabilityDenied {
        schema: StableId,
        required: u64,
        actual: u64,
    },
    ProducerDenied {
        schema: StableId,
        producer: StableId,
    },
    RoleDenied {
        schema: StableId,
        role: StableId,
    },
    GenerationDenied {
        schema: StableId,
        minimum: u64,
        actual: u64,
    },
}

impl fmt::Display for FrozenAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Schema(error) => error.fmt(formatter),
            Self::VersionMismatch {
                expected,
                actual,
                byte_offset,
            } => write!(
                formatter,
                "wire version at byte {byte_offset} is {actual}, expected {expected} for this session"
            ),
            Self::CapabilityDenied {
                schema,
                required,
                actual,
            } => write!(
                formatter,
                "schema {schema} requires capabilities 0x{required:016x}, session has 0x{actual:016x}"
            ),
            Self::ProducerDenied { schema, producer } => {
                write!(
                    formatter,
                    "producer {producer} is not admitted for schema {schema}"
                )
            }
            Self::RoleDenied { schema, role } => {
                write!(
                    formatter,
                    "runtime role {role} is not admitted for schema {schema}"
                )
            }
            Self::GenerationDenied {
                schema,
                minimum,
                actual,
            } => write!(
                formatter,
                "schema {schema} generation {actual} predates admitted floor {minimum}"
            ),
        }
    }
}

impl Error for FrozenAdmissionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Schema(error) => Some(error),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use super::*;
    use crate::NegotiationOffer;
    use crate::WireEnvelopeV2;
    use crate::WireVersion;
    use crate::negotiate;

    fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
        Ok(StableId::new(value)?)
    }

    fn descriptor(schema: &str) -> Result<SchemaDescriptor, Box<dyn Error>> {
        Ok(SchemaDescriptor::new(
            id(schema)?,
            WireVersion::V2,
            WireVersion::V2,
            256,
        )?)
    }

    fn policy(schema: &str) -> Result<SchemaPolicy, Box<dyn Error>> {
        Ok(SchemaPolicy::new(
            descriptor(schema)?,
            vec![id("producer.test")?],
            vec![id("role.test")?],
            WireCapabilities::METADATA_BOUND_DIGEST,
        )?)
    }

    fn bound_policy(
        schema: &str,
        revision: &[u8],
        generation_policy: GenerationPolicy,
        canonicalization_profile: CanonicalizationProfile,
    ) -> Result<SchemaPolicy, Box<dyn Error>> {
        Ok(SchemaPolicy::new_bound(
            descriptor(schema)?,
            Digest32::of_bytes(revision),
            generation_policy,
            canonicalization_profile,
            vec![id("producer.test")?],
            vec![id("role.test")?],
            WireCapabilities::METADATA_BOUND_DIGEST,
        )?)
    }

    #[test]
    fn snapshot_is_independent_of_registration_order() -> Result<(), Box<dyn Error>> {
        let mut left = FrozenSchemaRegistryBuilder::new();
        left.register(policy("schema.b")?)?;
        left.register(policy("schema.a")?)?;
        let mut right = FrozenSchemaRegistryBuilder::new();
        right.register(policy("schema.a")?)?;
        right.register(policy("schema.b")?)?;
        assert_eq!(
            left.freeze()?.snapshot_digest(),
            right.freeze()?.snapshot_digest()
        );
        Ok(())
    }

    #[test]
    fn semantic_policy_fields_change_snapshot_digest() -> Result<(), Box<dyn Error>> {
        let mut baseline = FrozenSchemaRegistryBuilder::new();
        baseline.register(bound_policy(
            "schema.a",
            b"revision-a",
            GenerationPolicy::AtLeast(7),
            CanonicalizationProfile::CanonicalJsonV1,
        )?)?;
        let baseline = baseline.freeze()?.snapshot_digest();

        for policy in [
            bound_policy(
                "schema.a",
                b"revision-b",
                GenerationPolicy::AtLeast(7),
                CanonicalizationProfile::CanonicalJsonV1,
            )?,
            bound_policy(
                "schema.a",
                b"revision-a",
                GenerationPolicy::AtLeast(8),
                CanonicalizationProfile::CanonicalJsonV1,
            )?,
            bound_policy(
                "schema.a",
                b"revision-a",
                GenerationPolicy::AtLeast(7),
                CanonicalizationProfile::OpaqueBytesV1,
            )?,
        ] {
            let mut changed = FrozenSchemaRegistryBuilder::new();
            changed.register(policy)?;
            assert_ne!(baseline, changed.freeze()?.snapshot_digest());
        }
        Ok(())
    }

    #[test]
    fn builder_enforces_entry_limit() -> Result<(), Box<dyn Error>> {
        let mut builder = FrozenSchemaRegistryBuilder::with_maximum_entries(1)?;
        builder.register(policy("schema.a")?)?;
        assert!(matches!(
            builder.register(policy("schema.b")?),
            Err(RegistryBuildError::EntryLimit {
                attempted: 2,
                maximum: 1
            })
        ));
        Ok(())
    }

    #[test]
    fn frozen_registry_enforces_version_producer_role_capabilities_and_generation()
    -> Result<(), Box<dyn Error>> {
        let schema = id("schema.a")?;
        let producer = id("producer.test")?;
        let role = id("role.test")?;
        let mut builder = FrozenSchemaRegistryBuilder::new();
        builder.register(bound_policy(
            schema.as_str(),
            b"revision-a",
            GenerationPolicy::AtLeast(7),
            CanonicalizationProfile::CodecOwnedStrictV1,
        )?)?;
        let registry = builder.freeze()?;
        let offer = NegotiationOffer::current();
        let negotiated = negotiate(&offer, &offer, WireCapabilities::METADATA_BOUND_DIGEST)?;
        let admitted = DecodedEnvelope::V2(WireEnvelopeV2::new(
            schema.clone(),
            producer.clone(),
            Generation::new(7)?,
            b"payload".to_vec(),
        )?);
        registry.admit_envelope(negotiated, &role, &admitted)?;
        assert!(matches!(
            registry.admit_envelope(negotiated, &id("role.denied")?, &admitted),
            Err(FrozenAdmissionError::RoleDenied { .. })
        ));

        let stale = DecodedEnvelope::V2(WireEnvelopeV2::new(
            schema,
            producer,
            Generation::new(6)?,
            b"payload".to_vec(),
        )?);
        assert!(matches!(
            registry.admit_envelope(negotiated, &role, &stale),
            Err(FrozenAdmissionError::GenerationDenied {
                minimum: 7,
                actual: 6,
                ..
            })
        ));
        Ok(())
    }
}
