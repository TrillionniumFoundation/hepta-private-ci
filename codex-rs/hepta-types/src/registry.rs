use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use crate::BoundedBytes;
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
pub const MAX_DEFINITION_BYTES_V1: usize = 16 * 1024;
pub const MAX_REGISTRY_DEFINITION_BYTES_V1: usize = 256 * 1024;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum ContractDefinitionKindV1 {
    Schema,
    Normalization,
}

impl ContractDefinitionKindV1 {
    pub const fn id(self) -> &'static str {
        match self {
            Self::Schema => "schema",
            Self::Normalization => "normalization",
        }
    }
}

/// Immutable, digest-bound definition. The body is opaque to platform.types;
/// semantic interpretation belongs to the registered consumer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractDefinitionV1 {
    kind: ContractDefinitionKindV1,
    id: StableId,
    version: u32,
    body: BoundedBytes<MAX_DEFINITION_BYTES_V1>,
    digest: Digest32,
}

impl ContractDefinitionV1 {
    pub fn new(
        kind: ContractDefinitionKindV1,
        id: StableId,
        version: u32,
        body: &[u8],
    ) -> Result<Self, ContractRegistryError> {
        if version == 0 {
            return Err(ContractRegistryError::ZeroVersion);
        }
        let body = BoundedBytes::try_from_slice(body).map_err(ContractRegistryError::Body)?;
        let type_id = validate_id(
            "platform.types:contract-definition-v1",
            IdProfileV1::Stable,
        )
        .map_err(ContractRegistryError::Identity)?;
        let fields = [
            CanonicalFieldV1::new("kind", CanonicalValueV1::Text(kind.id())),
            CanonicalFieldV1::new("id", CanonicalValueV1::Text(id.as_str())),
            CanonicalFieldV1::new("version", CanonicalValueV1::U64(u64::from(version))),
            CanonicalFieldV1::new("body", CanonicalValueV1::Bytes(body.as_slice())),
        ];
        let digest =
            canonical_digest_v1(&type_id, 1, &fields).map_err(ContractRegistryError::Canonical)?;
        Ok(Self {
            kind,
            id,
            version,
            body,
            digest,
        })
    }

    pub const fn kind(&self) -> ContractDefinitionKindV1 {
        self.kind
    }

    pub fn id(&self) -> &StableId {
        &self.id
    }

    pub const fn version(&self) -> u32 {
        self.version
    }

    pub fn body(&self) -> &[u8] {
        self.body.as_slice()
    }

    pub const fn digest(&self) -> Digest32 {
        self.digest
    }
}

/// Caller-owned immutable registry. There is deliberately no process-global
/// mutation or ambient lookup.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractRegistryV1 {
    entries: Vec<ContractDefinitionV1>,
}

impl ContractRegistryV1 {
    pub fn new(entries: Vec<ContractDefinitionV1>) -> Result<Self, ContractRegistryError> {
        if entries.len() > MAX_REGISTRY_ENTRIES_V1 {
            return Err(ContractRegistryError::TooManyEntries);
        }

        let mut identities = BTreeSet::new();
        let mut digests = BTreeSet::new();
        let mut total_bytes = 0usize;
        for definition in &entries {
            total_bytes = total_bytes
                .checked_add(definition.body().len())
                .ok_or(ContractRegistryError::TooMuchDefinitionData)?;
            if total_bytes > MAX_REGISTRY_DEFINITION_BYTES_V1 {
                return Err(ContractRegistryError::TooMuchDefinitionData);
            }
            if !identities.insert((
                definition.kind,
                definition.id.clone(),
                definition.version,
            )) {
                return Err(ContractRegistryError::DuplicateIdentity);
            }
            if !digests.insert(definition.digest) {
                return Err(ContractRegistryError::DuplicateDigest);
            }
        }
        Ok(Self { entries })
    }

    pub fn entries(&self) -> &[ContractDefinitionV1] {
        &self.entries
    }

    pub fn resolve_digest(&self, digest: Digest32) -> Option<&ContractDefinitionV1> {
        self.entries
            .iter()
            .find(|definition| definition.digest == digest)
    }

    pub fn require(
        &self,
        kind: ContractDefinitionKindV1,
        digest: Digest32,
    ) -> Result<&ContractDefinitionV1, ContractRegistryError> {
        let Some(definition) = self.resolve_digest(digest) else {
            return Err(ContractRegistryError::UnknownDigest);
        };
        if definition.kind != kind {
            return Err(ContractRegistryError::WrongKind);
        }
        Ok(definition)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContractRegistryError {
    ZeroVersion,
    Body(BoundedValueError),
    Identity(IdentityError),
    Canonical(CanonicalDigestError),
    TooManyEntries,
    TooMuchDefinitionData,
    DuplicateIdentity,
    DuplicateDigest,
    UnknownDigest,
    WrongKind,
}

impl fmt::Display for ContractRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ZeroVersion => formatter.write_str("contract definition version must be non-zero"),
            Self::Body(error) => error.fmt(formatter),
            Self::Identity(error) => error.fmt(formatter),
            Self::Canonical(error) => error.fmt(formatter),
            Self::TooManyEntries => formatter.write_str("contract registry entry limit exceeded"),
            Self::TooMuchDefinitionData => {
                formatter.write_str("contract registry definition bytes exceed 256 KiB")
            }
            Self::DuplicateIdentity => {
                formatter.write_str("duplicate contract definition identity/version")
            }
            Self::DuplicateDigest => formatter.write_str("duplicate contract definition digest"),
            Self::UnknownDigest => formatter.write_str("contract definition digest is unknown"),
            Self::WrongKind => formatter.write_str("contract definition digest has the wrong kind"),
        }
    }
}

impl Error for ContractRegistryError {}

#[cfg(test)]
#[path = "registry_tests.rs"]
mod tests;
