use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::IdProfileV1;
use crate::StableId;
use crate::validate_id;

pub const MAX_REGISTRY_DEFINITIONS_V1: usize = 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistryKindV1 {
    Schema,
    Normalization,
}

impl RegistryKindV1 {
    const fn id_profile(self) -> IdProfileV1 {
        match self {
            Self::Schema => IdProfileV1::Schema,
            Self::Normalization => IdProfileV1::Normalization,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryDefinitionV1 {
    pub kind: RegistryKindV1,
    pub id: StableId,
    pub version: u32,
    pub definition_digest: Digest32,
}

impl RegistryDefinitionV1 {
    pub fn new(
        kind: RegistryKindV1,
        id: &str,
        version: u32,
        definition_digest: Digest32,
    ) -> Result<Self, RegistryErrorV1> {
        if version == 0 {
            return Err(RegistryErrorV1::ZeroVersion);
        }
        if definition_digest.is_zero() {
            return Err(RegistryErrorV1::ZeroDigest);
        }
        let id = validate_id(id, kind.id_profile()).map_err(|_| RegistryErrorV1::InvalidId)?;
        Ok(Self {
            kind,
            id,
            version,
            definition_digest,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DefinitionRegistryV1 {
    by_digest: BTreeMap<Digest32, RegistryDefinitionV1>,
    by_id: BTreeMap<StableId, Digest32>,
}

impl DefinitionRegistryV1 {
    pub fn new(definitions: Vec<RegistryDefinitionV1>) -> Result<Self, RegistryErrorV1> {
        if definitions.len() > MAX_REGISTRY_DEFINITIONS_V1 {
            return Err(RegistryErrorV1::TooManyDefinitions(definitions.len()));
        }
        let mut by_digest = BTreeMap::new();
        let mut by_id = BTreeMap::new();
        for definition in definitions {
            let id = definition.id.clone();
            let digest = definition.definition_digest;
            if by_digest.insert(digest, definition).is_some() {
                return Err(RegistryErrorV1::DuplicateDigest);
            }
            if by_id.insert(id, digest).is_some() {
                return Err(RegistryErrorV1::DuplicateId);
            }
        }
        Ok(Self { by_digest, by_id })
    }

    pub fn resolve(&self, digest: Digest32) -> Option<&RegistryDefinitionV1> {
        self.by_digest.get(&digest)
    }

    pub fn digest_for_id(&self, id: &StableId) -> Option<Digest32> {
        self.by_id.get(id).copied()
    }

    pub fn len(&self) -> usize {
        self.by_digest.len()
    }

    pub fn is_empty(&self) -> bool {
        self.by_digest.is_empty()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistryErrorV1 {
    InvalidId,
    ZeroVersion,
    ZeroDigest,
    DuplicateId,
    DuplicateDigest,
    TooManyDefinitions(usize),
}

impl fmt::Display for RegistryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidId => formatter.write_str("registry definition id does not match its namespace"),
            Self::ZeroVersion => formatter.write_str("registry definition version must be non-zero"),
            Self::ZeroDigest => formatter.write_str("registry definition digest must be non-zero"),
            Self::DuplicateId => formatter.write_str("registry definition id is duplicated"),
            Self::DuplicateDigest => formatter.write_str("registry definition digest is duplicated"),
            Self::TooManyDefinitions(count) => write!(formatter, "registry definition count exceeds limit: {count}"),
        }
    }
}

impl Error for RegistryErrorV1 {}

#[cfg(test)]
#[path = "registry_tests.rs"]
mod tests;
