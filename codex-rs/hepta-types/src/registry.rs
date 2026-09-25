use std::error::Error;
use std::fmt;

use crate::BoundedText;
use crate::BoundedValueError;
use crate::CanonicalDigestError;
use crate::CanonicalFieldV1;
use crate::CanonicalValueV1;
use crate::Digest32;
use crate::IdProfileV1;
use crate::IdentityError;
use crate::NumericProfileDefinitionV1;
use crate::NumericProfileV1;
use crate::StableId;
use crate::canonical_digest_v1;
use crate::validate_id;

pub const MAX_REGISTRY_ENTRIES_V1: usize = 256;
pub const MAX_REGISTRY_DEFINITION_BYTES_V1: usize = 4_096;
pub const MAX_REGISTRY_AGGREGATE_DEFINITION_BYTES_V1: usize = 256 * 1024;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum RegistryKindV1 {
    Schema,
    Normalization,
}

impl RegistryKindV1 {
    pub const fn id(self) -> &'static str {
        match self {
            Self::Schema => "schema",
            Self::Normalization => "normalization",
        }
    }

    const fn id_profile(self) -> IdProfileV1 {
        match self {
            Self::Schema => IdProfileV1::Schema,
            Self::Normalization => IdProfileV1::Normalization,
        }
    }
}

/// Immutable canonical definition addressable by its digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegistryDefinitionV1 {
    kind: RegistryKindV1,
    id: StableId,
    version: u32,
    definition: BoundedText<MAX_REGISTRY_DEFINITION_BYTES_V1>,
    digest: Digest32,
}

impl RegistryDefinitionV1 {
    pub fn new(
        kind: RegistryKindV1,
        id: StableId,
        version: u32,
        definition: &str,
    ) -> Result<Self, RegistryError> {
        if version == 0 {
            return Err(RegistryError::InvalidVersion);
        }
        validate_id(id.as_str(), kind.id_profile()).map_err(RegistryError::Identity)?;
        let definition = BoundedText::try_from_str(definition).map_err(RegistryError::Bounded)?;
        let type_id = StableId::new("platform.types:registry-definition-v1")
            .map_err(RegistryError::Identity)?;
        let fields = [
            CanonicalFieldV1 {
                name: "definition",
                value: CanonicalValueV1::Text(definition.as_str()),
            },
            CanonicalFieldV1 {
                name: "id",
                value: CanonicalValueV1::StableId(&id),
            },
            CanonicalFieldV1 {
                name: "kind",
                value: CanonicalValueV1::Text(kind.id()),
            },
            CanonicalFieldV1 {
                name: "version",
                value: CanonicalValueV1::U64(u64::from(version)),
            },
        ];
        let digest = canonical_digest_v1(&type_id, 1, &fields).map_err(RegistryError::Canonical)?;
        Ok(Self {
            kind,
            id,
            version,
            definition,
            digest,
        })
    }

    pub const fn kind(&self) -> RegistryKindV1 {
        self.kind
    }

    pub fn id(&self) -> &StableId {
        &self.id
    }

    pub const fn version(&self) -> u32 {
        self.version
    }

    pub fn definition(&self) -> &str {
        self.definition.as_str()
    }

    pub const fn digest(&self) -> Digest32 {
        self.digest
    }
}

/// Bounded immutable in-process registry. There is no global singleton or
/// mutation API; callers construct one generation and pass it explicitly.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractRegistryV1 {
    entries: Vec<RegistryDefinitionV1>,
    numeric_profiles: Vec<NumericProfileDefinitionV1>,
}

impl ContractRegistryV1 {
    pub fn new(entries: Vec<RegistryDefinitionV1>) -> Result<Self, RegistryError> {
        Self::new_with_numeric_profiles(entries, Vec::new())
    }

    pub fn new_with_numeric_profiles(
        mut entries: Vec<RegistryDefinitionV1>,
        mut numeric_profiles: Vec<NumericProfileDefinitionV1>,
    ) -> Result<Self, RegistryError> {
        if entries.len().saturating_add(numeric_profiles.len()) > MAX_REGISTRY_ENTRIES_V1 {
            return Err(RegistryError::TooManyEntries);
        }
        let total_definition_bytes = entries.iter().try_fold(0usize, |total, entry| {
            total
                .checked_add(entry.definition().len())
                .ok_or(RegistryError::TooMuchDefinitionData)
        })?;
        if total_definition_bytes > MAX_REGISTRY_AGGREGATE_DEFINITION_BYTES_V1 {
            return Err(RegistryError::TooMuchDefinitionData);
        }
        entries.sort_unstable_by(|left, right| {
            (left.kind, left.id.as_str(), left.version).cmp(&(
                right.kind,
                right.id.as_str(),
                right.version,
            ))
        });
        for pair in entries.windows(2) {
            if pair[0].kind == pair[1].kind
                && pair[0].id == pair[1].id
                && pair[0].version == pair[1].version
            {
                return Err(RegistryError::DuplicateDefinition);
            }
        }
        numeric_profiles
            .sort_unstable_by_key(super::numeric_profile::NumericProfileDefinitionV1::profile);
        for pair in numeric_profiles.windows(2) {
            if pair[0].profile() == pair[1].profile() {
                return Err(RegistryError::DuplicateNumericProfile);
            }
        }
        Ok(Self {
            entries,
            numeric_profiles,
        })
    }

    pub fn entries(&self) -> &[RegistryDefinitionV1] {
        &self.entries
    }

    pub fn numeric_profiles(&self) -> &[NumericProfileDefinitionV1] {
        &self.numeric_profiles
    }

    pub fn resolve(
        &self,
        kind: RegistryKindV1,
        id: &StableId,
        version: u32,
    ) -> Option<&RegistryDefinitionV1> {
        self.entries
            .iter()
            .find(|entry| entry.kind == kind && entry.id == *id && entry.version == version)
    }

    pub fn resolve_digest(
        &self,
        kind: RegistryKindV1,
        digest: Digest32,
    ) -> Option<&RegistryDefinitionV1> {
        self.entries
            .iter()
            .find(|entry| entry.kind == kind && entry.digest == digest)
    }

    pub fn normalization_definition(&self, digest: Digest32) -> Option<&RegistryDefinitionV1> {
        self.resolve_digest(RegistryKindV1::Normalization, digest)
    }

    pub fn require_normalization(
        &self,
        digest: Digest32,
    ) -> Result<&RegistryDefinitionV1, RegistryError> {
        self.normalization_definition(digest)
            .ok_or(RegistryError::UnknownDefinition)
    }

    pub fn require_numeric_profile(
        &self,
        profile: NumericProfileV1,
    ) -> Result<&NumericProfileDefinitionV1, RegistryError> {
        self.numeric_profiles
            .iter()
            .find(|definition| definition.profile() == profile)
            .ok_or(RegistryError::UnknownNumericProfile)
    }

    pub fn registry_digest(&self) -> Result<Digest32, RegistryError> {
        let type_id = StableId::new("platform.types:contract-registry-v1")
            .map_err(RegistryError::Identity)?;
        let definition_values: Vec<CanonicalValueV1<'_>> = self
            .entries
            .iter()
            .map(|entry| CanonicalValueV1::Digest(entry.digest))
            .collect();
        let profile_values: Vec<CanonicalValueV1<'_>> = self
            .numeric_profiles
            .iter()
            .map(|profile| CanonicalValueV1::Digest(profile.digest()))
            .collect();
        let fields = [
            CanonicalFieldV1 {
                name: "definitions",
                value: CanonicalValueV1::Array(&definition_values),
            },
            CanonicalFieldV1 {
                name: "numeric_profiles",
                value: CanonicalValueV1::Array(&profile_values),
            },
        ];
        canonical_digest_v1(&type_id, 1, &fields).map_err(RegistryError::Canonical)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RegistryError {
    Bounded(BoundedValueError),
    Identity(IdentityError),
    Canonical(CanonicalDigestError),
    InvalidVersion,
    TooManyEntries,
    TooMuchDefinitionData,
    DuplicateDefinition,
    DuplicateNumericProfile,
    UnknownDefinition,
    UnknownNumericProfile,
}

impl fmt::Display for RegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Bounded(error) => error.fmt(formatter),
            Self::Identity(error) => error.fmt(formatter),
            Self::Canonical(error) => error.fmt(formatter),
            Self::InvalidVersion => {
                formatter.write_str("registry definition version must be non-zero")
            }
            Self::TooManyEntries => formatter.write_str("registry entry limit exceeded"),
            Self::TooMuchDefinitionData => {
                formatter.write_str("registry definition bytes exceed aggregate limit")
            }
            Self::DuplicateDefinition => {
                formatter.write_str("duplicate registry definition identity")
            }
            Self::DuplicateNumericProfile => {
                formatter.write_str("duplicate numeric profile definition")
            }
            Self::UnknownDefinition => formatter.write_str("registry definition digest is unknown"),
            Self::UnknownNumericProfile => {
                formatter.write_str("numeric profile is not admitted by this registry generation")
            }
        }
    }
}

impl Error for RegistryError {}

#[cfg(test)]
#[path = "registry_tests.rs"]
mod tests;
