//! Explicit owner-provided OAuth origins, independent of discovery metadata.

use std::collections::HashSet;

use reqwest::Url;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::de::Error as SerdeError;

use crate::address_policy::HttpAddressPolicy;

const MAX_AUTHORIZATION_ORIGINS: usize = 16;
const MAX_ORIGIN_BYTES: usize = 16 * 1024;

/// An immutable, validated list of exact origins granted by a resource owner.
///
/// This list is never constructed from metadata, a challenge, a redirect, or the
/// destination of a request. DNS names retain public-address-only resolution.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(transparent)]
pub struct OAuthAuthorizationOrigins(Vec<String>);

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum OAuthAuthorizationOriginsError {
    #[error("at most 16 OAuth authorization origins may be configured")]
    TooManyOrigins,
    #[error("OAuth authorization origin at index {index} exceeds 16384 bytes")]
    OriginTooLong { index: usize },
    #[error("OAuth authorization origin at index {index} is not an allowed canonical HTTP origin")]
    InvalidOrigin { index: usize },
    #[error("OAuth authorization origin at index {index} is duplicated")]
    DuplicateOrigin { index: usize },
}

impl OAuthAuthorizationOrigins {
    /// Validates canonical scheme, host, port, bounds, and duplicate entries.
    pub fn new(origins: Vec<String>) -> Result<Self, OAuthAuthorizationOriginsError> {
        if origins.len() > MAX_AUTHORIZATION_ORIGINS {
            return Err(OAuthAuthorizationOriginsError::TooManyOrigins);
        }
        let mut seen = HashSet::new();
        for (index, origin) in origins.iter().enumerate() {
            if origin.len() > MAX_ORIGIN_BYTES {
                return Err(OAuthAuthorizationOriginsError::OriginTooLong { index });
            }
            let url = Url::parse(origin)
                .map_err(|_| OAuthAuthorizationOriginsError::InvalidOrigin { index })?;
            if !matches!(url.scheme(), "http" | "https")
                || url.origin().ascii_serialization() != *origin
            {
                return Err(OAuthAuthorizationOriginsError::InvalidOrigin { index });
            }
            HttpAddressPolicy::from_configured_resource(origin)
                .map_err(|_| OAuthAuthorizationOriginsError::InvalidOrigin { index })?;
            if !seen.insert(origin.as_str()) {
                return Err(OAuthAuthorizationOriginsError::DuplicateOrigin { index });
            }
        }
        Ok(Self(origins))
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn as_slice(&self) -> &[String] {
        &self.0
    }
}

impl<'de> Deserialize<'de> for OAuthAuthorizationOrigins {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::new(Vec::<String>::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

#[cfg(test)]
#[path = "oauth_authorization_origins_tests.rs"]
mod tests;
