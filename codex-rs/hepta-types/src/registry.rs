use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use crate::BoundedBytes;
use crate::BoundedText;
use crate::BoundedValueError;
use crate::CanonicalDigestError;
use crate::CanonicalFieldV1;
use crate::CanonicalValueV1;
use crate::Digest32;
use crate::IdProfileV1;
use crate::IdentityError;
use crate::StableId;
use crate::canonical_digest_v1;
use crate::validate_id;

pub const MAX_REGISTRY_ENTRIES_V1: usize = 256;
pub const MAX_REGISTRY_DEFINITION_BYTES_V1: usize = 64 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistryKindV1 {
    Schema,
    Normalization,
}

impl RegistryKindV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Schema => "schema",
            Self::Normalization => "normalization",
        }
    }

    const fn id_profile(self) -> IdProfileV1 {
        match self {
            Self::Schema => IdProfileV1::SCHEMA,
            Self::Normalization => IdProfileV1::NORMALIZATION,
        }
    }
}

/// Immutable, content-addressed registry definition. The body is an externally
/// versioned canonical representation identified by media_type and schema_version.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryDefinitionV1 {
    kind: RegistryKindV1,
    id: StableId,
    media_type: BoundedText<128>,
    schema_version: u64,
    canonical_body: BoundedBytes<MAX_REGISTRY_DEFINITION_BYTES_V1>,
}

impl RegistryDefinitionV1 {
    pub fn new(
        kind: RegistryKindV1,
        id: &str,
        media_type: &str,
        schema_version: u64,
        canonical_body: &[u8],
    ) -> Result<Self, RegistryError> {
        if schema_version == 0 {
            return Err(RegistryError::ZeroSchemaVersion);
        }
        let id = validate_id(id, kind.id_profile()).map_err(RegistryError::Identity)?;
        let media_type =
            BoundedText::copy_from_str(media_type).map_err(RegistryError::Bounded)?;
        let canonical_body =
            BoundedBytes::copy_from_slice(canonical_body).map_err(RegistryError::Bounded)?;
        Ok(Self {
            kind,
            id,
            media_type,
            schema_version,
            canonical_body,
        })
    }

    pub const fn kind(&self) -> RegistryKindV1 {
        self.kind
    }

    pub fn id(&self) -> &StableId {
        &self.id
    }

    pub fn media_type(&self) -> &str {
        self.media_type.as_str()
    }

    pub const fn schema_version(&self) -> u64 {
        self.schema_version
    }

    pub fn canonical_body(&self) -> &[u8] {
        self.canonical_body.as_slice()
    }

    pub fn digest(&self) -> Result<Digest32, RegistryError> {
        let fields = [
            CanonicalFieldV1 {
                name: "body",
                value: CanonicalValueV1::Bytes(self.canonical_body.as_slice()),
            },
            CanonicalFieldV1 {
                name: "id",
                value: CanonicalValueV1::StableId(&self.id),
            },
            CanonicalFieldV1 {
                name: "kind",
                value: CanonicalValueV1::Text(self.kind.as_str()),
            },
            CanonicalFieldV1 {
                name: "media_type",
                value: CanonicalValueV1::Text(self.media_type.as_str()),
            },
            CanonicalFieldV1 {
                name: "schema_version",
                value: CanonicalValueV1::U64(self.schema_version),
            },
        ];
        canonical_digest_v1("platform.types.registry-definition", &fields)
            .map_err(RegistryError::Canonical)
    }
}

/// Bounded in-memory V1 contract registry. It owns no process-global state or
/// durability; hosts may persist definitions separately but must preserve the
/// digest-to-definition bytes exactly.
#[derive(Clone, Debug, Default)]
pub struct SchemaNormalizationRegistryV1 {
    entries: BTreeMap<Digest32, RegistryDefinitionV1>,
}

impl SchemaNormalizationRegistryV1 {
    pub const fn new() -> Self {
        Self {
            entries: BTreeMap::new(),
        }
    }

    pub fn register(&mut self, definition: RegistryDefinitionV1) -> Result<Digest32, RegistryError> {
        let digest = definition.digest()?;
        if let Some(existing) = self.entries.get(&digest) {
            return if existing == &definition {
                Ok(digest)
            } else {
                Err(RegistryError::DigestCollision)
            };
        }
        if self.entries.len() >= MAX_REGISTRY_ENTRIES_V1 {
            return Err(RegistryError::Capacity);
        }
        self.entries.insert(digest, definition);
        Ok(digest)
    }

    pub fn resolve(
        &self,
        kind: RegistryKindV1,
        digest: Digest32,
    ) -> Result<&RegistryDefinitionV1, RegistryError> {
        let definition = self
            .entries
            .get(&digest)
            .ok_or(RegistryError::UnknownDigest)?;
        if definition.kind != kind {
            return Err(RegistryError::KindMismatch);
        }
        Ok(definition)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistryError {
    Identity(IdentityError),
    Bounded(BoundedValueError),
    Canonical(CanonicalDigestError),
    ZeroSchemaVersion,
    UnknownDigest,
    KindMismatch,
    DigestCollision,
    Capacity,
}

impl fmt::Display for RegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for RegistryError {}

#[cfg(test)]
#[path = "registry_tests.rs"]
mod tests;
