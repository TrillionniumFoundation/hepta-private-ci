use codex_hepta_types::Digest32;

use super::{
    digest_hex, push_string, require_digest, NduAuthenticityError, MAX_AUTH_LOCATOR_BYTES,
    MAX_AUTH_VERSION_BYTES,
};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NduImmutableLocatorKindV2 {
    ContentAddressedArtifact,
    VersionedS3Object,
    ContentAddressedHttps,
    ContentAddressedFile,
}

impl NduImmutableLocatorKindV2 {
    const fn tag(self) -> u8 {
        match self {
            Self::ContentAddressedArtifact => 0,
            Self::VersionedS3Object => 1,
            Self::ContentAddressedHttps => 2,
            Self::ContentAddressedFile => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduImmutableLocatorV2 {
    kind: NduImmutableLocatorKindV2,
    locator: String,
    content_digest: Digest32,
    object_version: Option<String>,
    binding_digest: Digest32,
}

impl NduImmutableLocatorV2 {
    pub fn new(
        locator: String,
        content_digest: Digest32,
        object_version: Option<String>,
    ) -> Result<Self, NduAuthenticityError> {
        require_digest(content_digest, "locator content")?;
        if locator.is_empty()
            || locator.len() > MAX_AUTH_LOCATOR_BYTES
            || !locator.bytes().all(|byte| byte.is_ascii_graphic())
        {
            return Err(NduAuthenticityError::InvalidLocator);
        }
        if object_version.as_ref().is_some_and(|version| {
            version.is_empty()
                || version.len() > MAX_AUTH_VERSION_BYTES
                || !version.bytes().all(valid_version_byte)
        }) {
            return Err(NduAuthenticityError::InvalidObjectVersion);
        }

        let expected_hex = digest_hex(content_digest);
        let kind = if let Some(suffix) = locator.strip_prefix("artifact://sha256/") {
            if suffix != expected_hex || object_version.is_some() {
                return Err(NduAuthenticityError::InvalidLocator);
            }
            NduImmutableLocatorKindV2::ContentAddressedArtifact
        } else if let Some(rest) = locator.strip_prefix("s3+version://") {
            let (address_and_version, digest_fragment) = rest
                .split_once("#sha256=")
                .ok_or(NduAuthenticityError::InvalidLocator)?;
            if digest_fragment != expected_hex {
                return Err(NduAuthenticityError::InvalidLocator);
            }
            let (address, encoded_version) = address_and_version
                .split_once("?versionId=")
                .ok_or(NduAuthenticityError::InvalidLocator)?;
            if address.is_empty()
                || !address.contains('/')
                || encoded_version.is_empty()
                || encoded_version
                    .bytes()
                    .any(|byte| matches!(byte, b'&' | b'?' | b'#'))
                || object_version.as_deref() != Some(encoded_version)
            {
                return Err(NduAuthenticityError::InvalidObjectVersion);
            }
            NduImmutableLocatorKindV2::VersionedS3Object
        } else if let Some(rest) = locator.strip_prefix("https+sha256://") {
            let (address, digest_fragment) = rest
                .split_once("#sha256=")
                .ok_or(NduAuthenticityError::InvalidLocator)?;
            if address.is_empty()
                || !address.contains('/')
                || digest_fragment != expected_hex
                || object_version.is_some()
            {
                return Err(NduAuthenticityError::InvalidLocator);
            }
            NduImmutableLocatorKindV2::ContentAddressedHttps
        } else if let Some(rest) = locator.strip_prefix("file+sha256://") {
            let (path, digest_fragment) = rest
                .split_once("#sha256=")
                .ok_or(NduAuthenticityError::InvalidLocator)?;
            if !path.starts_with('/')
                || path.split('/').any(|segment| segment == "..")
                || digest_fragment != expected_hex
                || object_version.is_some()
            {
                return Err(NduAuthenticityError::InvalidLocator);
            }
            NduImmutableLocatorKindV2::ContentAddressedFile
        } else {
            return Err(NduAuthenticityError::InvalidLocator);
        };

        let binding_digest =
            digest_binding(kind, &locator, content_digest, object_version.as_deref());
        Ok(Self {
            kind,
            locator,
            content_digest,
            object_version,
            binding_digest,
        })
    }

    #[must_use]
    pub const fn kind(&self) -> NduImmutableLocatorKindV2 {
        self.kind
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
    pub fn object_version(&self) -> Option<&str> {
        self.object_version.as_deref()
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    pub fn validate(&self) -> Result<(), NduAuthenticityError> {
        let rebuilt = Self::new(
            self.locator.clone(),
            self.content_digest,
            self.object_version.clone(),
        )?;
        if rebuilt.binding_digest != self.binding_digest || rebuilt.kind != self.kind {
            return Err(NduAuthenticityError::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

fn valid_version_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~' | b'=' | b'%')
}

fn digest_binding(
    kind: NduImmutableLocatorKindV2,
    locator: &str,
    content_digest: Digest32,
    object_version: Option<&str>,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.immutable-locator.v2\0".to_vec();
    bytes.push(kind.tag());
    push_string(&mut bytes, locator);
    bytes.extend_from_slice(content_digest.as_array());
    match object_version {
        Some(version) => {
            bytes.push(1);
            push_string(&mut bytes, version);
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn content_addressed_and_versioned_locators_are_canonical() {
        let content = digest("artifact");
        let hex = digest_hex(content);
        let artifact = NduImmutableLocatorV2::new(
            format!("artifact://sha256/{hex}"),
            content,
            None,
        )
        .expect("content-addressed locator");
        artifact.validate().expect("valid binding");

        let s3 = NduImmutableLocatorV2::new(
            format!("s3+version://bucket/key?versionId=v-17#sha256={hex}"),
            content,
            Some("v-17".to_string()),
        )
        .expect("versioned s3 locator");
        assert_eq!(s3.object_version(), Some("v-17"));
    }

    #[test]
    fn mutable_or_digest_drifting_locators_fail_closed() {
        let content = digest("artifact");
        assert_eq!(
            NduImmutableLocatorV2::new(
                "https://example.invalid/object".to_string(),
                content,
                None,
            ),
            Err(NduAuthenticityError::InvalidLocator)
        );
        assert_eq!(
            NduImmutableLocatorV2::new(
                "s3+version://bucket/key?versionId=v-1#sha256=00".to_string(),
                content,
                Some("v-1".to_string()),
            ),
            Err(NduAuthenticityError::InvalidLocator)
        );
    }
}
