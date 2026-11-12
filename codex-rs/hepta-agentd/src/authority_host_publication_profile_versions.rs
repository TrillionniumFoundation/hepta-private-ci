//! Explicit publication versions. V1 retains exact incarnation equality.
//! V2 preserves the original persisted profile as provenance while a fresh
//! Root writer admits only a new live identity over the identical durable cut.

use super::*;

const PURPOSE_V2: &str = "runtime.learning.cell-generation.publication.v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PublicationVersion {
    LegacyV1,
    DurableV2,
}

impl PublicationVersion {
    pub(crate) fn from_purpose(purpose: &str) -> io::Result<Self> {
        match purpose {
            PURPOSE => Ok(Self::LegacyV1),
            PURPOSE_V2 => Ok(Self::DurableV2),
            _ => Err(io::Error::other("unknown original publication version")),
        }
    }

    pub(crate) fn purpose(self) -> &'static str {
        match self {
            Self::LegacyV1 => PURPOSE,
            Self::DurableV2 => PURPOSE_V2,
        }
    }

    pub(crate) fn schema(self) -> u8 {
        match self {
            Self::LegacyV1 => 1,
            Self::DurableV2 => 2,
        }
    }

    pub(crate) fn socket(self) -> &'static str {
        match self {
            Self::LegacyV1 => SOCKET,
            Self::DurableV2 => "cell-generation-publication-v2.sock",
        }
    }

    pub(crate) fn owner_prefix(self) -> &'static str {
        match self {
            Self::LegacyV1 => "generation-publication",
            Self::DurableV2 => "generation-publication-v2",
        }
    }

    pub(crate) fn binding_domain(self) -> &'static [u8] {
        match self {
            Self::LegacyV1 => b"hepta.root.generation-publication.profile.v1\0",
            Self::DurableV2 => b"hepta.root.generation-publication.profile.v2\0",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct DurablePublicationProfileV2 {
    schema_version: u8,
    original: PublicationProfile,
}

/// The V1 JSON object is unchanged. An explicit V2 object cannot deserialize
/// as V1, and recovery never rewrites either stored object or its origin.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub(crate) enum ReservedPublicationProfile {
    LegacyV1(PublicationProfile),
    DurableV2(DurablePublicationProfileV2),
}

impl ReservedPublicationProfile {
    pub(crate) fn retain_original(profile: PublicationProfile) -> io::Result<Self> {
        if profile.digest()? != profile.binding {
            return Err(io::Error::other(
                "original publication profile binding differs",
            ));
        }
        Ok(match PublicationVersion::from_purpose(&profile.purpose)? {
            PublicationVersion::LegacyV1 => Self::LegacyV1(profile),
            PublicationVersion::DurableV2 => Self::DurableV2(DurablePublicationProfileV2 {
                schema_version: 2,
                original: profile,
            }),
        })
    }

    pub(crate) fn original_for_version(
        &self,
        version: PublicationVersion,
    ) -> io::Result<&PublicationProfile> {
        let original = match (self, version) {
            (Self::LegacyV1(original), PublicationVersion::LegacyV1) => original,
            (Self::DurableV2(durable), PublicationVersion::DurableV2)
                if durable.schema_version == 2 =>
            {
                &durable.original
            }
            _ => {
                return Err(io::Error::other(
                    "original publication reservation version differs",
                ));
            }
        };
        if original.purpose != version.purpose() || original.digest()? != original.binding {
            return Err(io::Error::other(
                "original publication reservation is invalid",
            ));
        }
        Ok(original)
    }

    /// Called only after actual with_learning_profile has bound the current
    /// identity and writer. The persisted original profile is never mutated.
    pub(crate) fn require_live_profile(&self, live: &PublicationProfile) -> io::Result<()> {
        let version = PublicationVersion::from_purpose(&live.purpose)?;
        let original = self.original_for_version(version)?;
        if live.digest()? != live.binding {
            return Err(io::Error::other("actual live publication binding differs"));
        }
        let mut expected = original.clone();
        match version {
            PublicationVersion::LegacyV1 => {}
            PublicationVersion::DurableV2 => {
                for text in [&live.writer, &live.identity] {
                    let digest: Digest32 = text.parse().map_err(io::Error::other)?;
                    if digest.is_zero() || digest.to_string() != *text {
                        return Err(io::Error::other(
                            "actual live publication admission required",
                        ));
                    }
                }
                expected.writer = live.writer.clone();
                expected.identity = live.identity.clone();
                expected.binding = expected.digest()?;
            }
        }
        // Includes the operation, initial, scope, decision, both original file
        // bindings, complete Artifact/Selector trust and selection pins,
        // consumer custody/trust, and every byte of the one CURRENT intent.
        if expected != *live {
            return Err(io::Error::other(
                "original complete publication reservation differs",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "authority_host_publication_profile_versions_tests.rs"]
mod tests;
