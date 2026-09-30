use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::NduDurableProjectionArtifactV2;
use crate::NduHardeningError;
use crate::NduProjectionArtifactKindV2;

const MAX_LOCATOR_BYTES: usize = 512;
const MAX_VERSION_BYTES: usize = 256;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NduImmutableLocatorSchemeV2 {
    S3Versioned,
    GcsGeneration,
    AzureVersioned,
    OciDigest,
    FileContentAddressed,
}

impl NduImmutableLocatorSchemeV2 {
    const fn tag(self) -> u8 {
        match self {
            Self::S3Versioned => 1,
            Self::GcsGeneration => 2,
            Self::AzureVersioned => 3,
            Self::OciDigest => 4,
            Self::FileContentAddressed => 5,
        }
    }

    const fn prefix(self) -> &'static str {
        match self {
            Self::S3Versioned => "s3://",
            Self::GcsGeneration => "gs://",
            Self::AzureVersioned => "azure://",
            Self::OciDigest => "oci://",
            Self::FileContentAddressed => "file+sha256://",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduArtifactLocatorErrorV2 {
    EmptyDigest(&'static str),
    InvalidLocator,
    InvalidImmutableVersion,
    VersionBindingMismatch,
    Legacy(NduHardeningError),
}

impl fmt::Display for NduArtifactLocatorErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduArtifactLocatorErrorV2 {}

impl From<NduHardeningError> for NduArtifactLocatorErrorV2 {
    fn from(error: NduHardeningError) -> Self {
        Self::Legacy(error)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduImmutableArtifactLocatorV2 {
    scheme: NduImmutableLocatorSchemeV2,
    locator: String,
    content_digest: Digest32,
    immutable_version: String,
    binding_digest: Digest32,
}

impl NduImmutableArtifactLocatorV2 {
    pub fn new(
        scheme: NduImmutableLocatorSchemeV2,
        locator: String,
        content_digest: Digest32,
        immutable_version: String,
    ) -> Result<Self, NduArtifactLocatorErrorV2> {
        require_digest(content_digest, "content")?;
        validate_locator(scheme, &locator)?;
        validate_version(scheme, &locator, content_digest, &immutable_version)?;
        let binding_digest =
            digest_locator(scheme, &locator, content_digest, &immutable_version);
        Ok(Self {
            scheme,
            locator,
            content_digest,
            immutable_version,
            binding_digest,
        })
    }

    #[must_use]
    pub const fn scheme(&self) -> NduImmutableLocatorSchemeV2 {
        self.scheme
    }

    #[must_use]
    pub fn locator(&self) -> &str {
        &self.locator
    }

    #[must_use]
    pub const fn content_digest(&self) -> Digest32 {
        self.content_digest
    }

    #[must_use]
    pub fn immutable_version(&self) -> &str {
        &self.immutable_version
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn validate(&self) -> Result<(), NduArtifactLocatorErrorV2> {
        let rebuilt = Self::new(
            self.scheme,
            self.locator.clone(),
            self.content_digest,
            self.immutable_version.clone(),
        )?;
        if rebuilt.binding_digest != self.binding_digest {
            return Err(NduArtifactLocatorErrorV2::VersionBindingMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduDurableProjectionArtifactV3 {
    projection_kind: NduProjectionArtifactKindV2,
    projection_digest: Digest32,
    locator: NduImmutableArtifactLocatorV2,
    size_bytes: u64,
    schema_revision: u32,
    policy_digest: Digest32,
    provenance_digest: Digest32,
    retention_epoch: u64,
    binding_digest: Digest32,
}

impl NduDurableProjectionArtifactV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        projection_kind: NduProjectionArtifactKindV2,
        projection_digest: Digest32,
        locator: NduImmutableArtifactLocatorV2,
        size_bytes: u64,
        schema_revision: u32,
        policy_digest: Digest32,
        provenance_digest: Digest32,
        retention_epoch: u64,
    ) -> Result<Self, NduArtifactLocatorErrorV2> {
        for (field, digest) in [
            ("projection", projection_digest),
            ("policy", policy_digest),
            ("provenance", provenance_digest),
        ] {
            require_digest(digest, field)?;
        }
        locator.validate()?;
        if locator.content_digest != projection_digest {
            return Err(NduArtifactLocatorErrorV2::VersionBindingMismatch);
        }
        if size_bytes == 0 || schema_revision == 0 || retention_epoch == 0 {
            return Err(NduArtifactLocatorErrorV2::InvalidImmutableVersion);
        }
        let binding_digest = digest_artifact(
            projection_kind,
            projection_digest,
            &locator,
            size_bytes,
            schema_revision,
            policy_digest,
            provenance_digest,
            retention_epoch,
        );
        Ok(Self {
            projection_kind,
            projection_digest,
            locator,
            size_bytes,
            schema_revision,
            policy_digest,
            provenance_digest,
            retention_epoch,
            binding_digest,
        })
    }

    #[must_use]
    pub const fn projection_kind(&self) -> NduProjectionArtifactKindV2 {
        self.projection_kind
    }

    #[must_use]
    pub const fn projection_digest(&self) -> Digest32 {
        self.projection_digest
    }

    #[must_use]
    pub fn locator(&self) -> &NduImmutableArtifactLocatorV2 {
        &self.locator
    }

    #[must_use]
    pub const fn size_bytes(&self) -> u64 {
        self.size_bytes
    }

    #[must_use]
    pub const fn schema_revision(&self) -> u32 {
        self.schema_revision
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub const fn provenance_digest(&self) -> Digest32 {
        self.provenance_digest
    }

    #[must_use]
    pub const fn retention_epoch(&self) -> u64 {
        self.retention_epoch
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn validate(&self) -> Result<(), NduArtifactLocatorErrorV2> {
        let rebuilt = Self::new(
            self.projection_kind,
            self.projection_digest,
            self.locator.clone(),
            self.size_bytes,
            self.schema_revision,
            self.policy_digest,
            self.provenance_digest,
            self.retention_epoch,
        )?;
        if rebuilt.binding_digest != self.binding_digest {
            return Err(NduArtifactLocatorErrorV2::VersionBindingMismatch);
        }
        Ok(())
    }
}

pub trait NduArtifactLocatorResolverV2 {
    fn resolve(
        &self,
        legacy: &NduDurableProjectionArtifactV2,
    ) -> Result<NduImmutableArtifactLocatorV2, NduArtifactLocatorErrorV2>;
}

pub fn migrate_projection_artifact_v2_to_v3(
    legacy: &NduDurableProjectionArtifactV2,
    resolver: &dyn NduArtifactLocatorResolverV2,
) -> Result<NduDurableProjectionArtifactV3, NduArtifactLocatorErrorV2> {
    legacy.validate()?;
    let locator = resolver.resolve(legacy)?;
    if locator.locator() != legacy.immutable_locator()
        || locator.content_digest() != legacy.projection_digest()
    {
        return Err(NduArtifactLocatorErrorV2::VersionBindingMismatch);
    }
    NduDurableProjectionArtifactV3::new(
        legacy.projection_kind(),
        legacy.projection_digest(),
        locator,
        legacy.size_bytes(),
        legacy.schema_revision(),
        legacy.policy_digest(),
        legacy.provenance_digest(),
        legacy.retention_epoch(),
    )
}

fn validate_locator(
    scheme: NduImmutableLocatorSchemeV2,
    locator: &str,
) -> Result<(), NduArtifactLocatorErrorV2> {
    if locator.is_empty()
        || locator.len() > MAX_LOCATOR_BYTES
        || !locator.starts_with(scheme.prefix())
        || locator.len() == scheme.prefix().len()
        || !locator.bytes().all(|byte| byte.is_ascii_graphic())
        || locator.contains('\\')
        || locator.contains("/../")
        || locator.ends_with("/..")
        || locator.contains('?')
        || locator.contains('#')
    {
        return Err(NduArtifactLocatorErrorV2::InvalidLocator);
    }
    Ok(())
}

fn validate_version(
    scheme: NduImmutableLocatorSchemeV2,
    locator: &str,
    content_digest: Digest32,
    immutable_version: &str,
) -> Result<(), NduArtifactLocatorErrorV2> {
    if immutable_version.is_empty()
        || immutable_version.len() > MAX_VERSION_BYTES
        || !immutable_version
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
    {
        return Err(NduArtifactLocatorErrorV2::InvalidImmutableVersion);
    }
    match scheme {
        NduImmutableLocatorSchemeV2::OciDigest => {
            let expected = format!("sha256:{}", content_digest);
            if immutable_version != expected || !locator.ends_with(immutable_version) {
                return Err(NduArtifactLocatorErrorV2::VersionBindingMismatch);
            }
        }
        NduImmutableLocatorSchemeV2::FileContentAddressed => {
            if immutable_version != content_digest.to_string() {
                return Err(NduArtifactLocatorErrorV2::VersionBindingMismatch);
            }
        }
        NduImmutableLocatorSchemeV2::S3Versioned
        | NduImmutableLocatorSchemeV2::GcsGeneration
        | NduImmutableLocatorSchemeV2::AzureVersioned => {}
    }
    Ok(())
}

fn digest_locator(
    scheme: NduImmutableLocatorSchemeV2,
    locator: &str,
    content_digest: Digest32,
    immutable_version: &str,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.immutable-artifact-locator.v2\0".to_vec();
    bytes.push(scheme.tag());
    push_str(&mut bytes, locator);
    bytes.extend_from_slice(content_digest.as_array());
    push_str(&mut bytes, immutable_version);
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn digest_artifact(
    projection_kind: NduProjectionArtifactKindV2,
    projection_digest: Digest32,
    locator: &NduImmutableArtifactLocatorV2,
    size_bytes: u64,
    schema_revision: u32,
    policy_digest: Digest32,
    provenance_digest: Digest32,
    retention_epoch: u64,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.durable-projection-artifact.v3\0".to_vec();
    bytes.push(match projection_kind {
        NduProjectionArtifactKindV2::Preference => 1,
        NduProjectionArtifactKindV2::Utility => 2,
        NduProjectionArtifactKindV2::Coefficient => 3,
    });
    bytes.extend_from_slice(projection_digest.as_array());
    bytes.extend_from_slice(locator.binding_digest.as_array());
    bytes.extend_from_slice(&size_bytes.to_be_bytes());
    bytes.extend_from_slice(&schema_revision.to_be_bytes());
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(provenance_digest.as_array());
    bytes.extend_from_slice(&retention_epoch.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), NduArtifactLocatorErrorV2> {
    if value.is_zero() {
        return Err(NduArtifactLocatorErrorV2::EmptyDigest(field));
    }
    Ok(())
}

fn push_str(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    #![allow(clippy::expect_used)]
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[test]
    fn rejects_mutable_or_unversioned_locations() {
        assert_eq!(
            NduImmutableArtifactLocatorV2::new(
                NduImmutableLocatorSchemeV2::S3Versioned,
                "https://bucket/key".to_string(),
                digest(b"content"),
                "version-1".to_string(),
            ),
            Err(NduArtifactLocatorErrorV2::InvalidLocator)
        );
        assert_eq!(
            NduImmutableArtifactLocatorV2::new(
                NduImmutableLocatorSchemeV2::S3Versioned,
                "s3://bucket/key?versionId=1".to_string(),
                digest(b"content"),
                "version-1".to_string(),
            ),
            Err(NduArtifactLocatorErrorV2::InvalidLocator)
        );
    }

    #[test]
    fn binds_content_and_immutable_version() {
        let content = digest(b"content");
        let locator = NduImmutableArtifactLocatorV2::new(
            NduImmutableLocatorSchemeV2::S3Versioned,
            "s3://bucket/key".to_string(),
            content,
            "version-1".to_string(),
        )
        .expect("locator");
        let artifact = NduDurableProjectionArtifactV3::new(
            NduProjectionArtifactKindV2::Coefficient,
            content,
            locator,
            64,
            3,
            digest(b"policy"),
            digest(b"provenance"),
            9,
        )
        .expect("artifact");
        artifact.validate().expect("valid artifact");
    }
}
