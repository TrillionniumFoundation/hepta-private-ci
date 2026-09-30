mod locator;
mod signature;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{Digest32, StableId};

pub use locator::{NduImmutableLocatorKindV2, NduImmutableLocatorV2};
pub use signature::{
    NduAuthenticatedProjectionArtifactV3, NduAuthorityTrustBindingV2,
    NduSignedHierarchyProofV2, NduVerifiedHierarchyProofV2,
    NduVerifiedProjectionArtifactV3,
};

pub(crate) const MAX_AUTH_LOCATOR_BYTES: usize = 1_024;
pub(crate) const MAX_AUTH_VERSION_BYTES: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduAuthenticityError {
    EmptyDigest(&'static str),
    InvalidLocator,
    InvalidObjectVersion,
    InvalidKey,
    InvalidValidityWindow,
    InvalidTrustRevision,
    InvalidSignature,
    SignerMismatch,
    PolicyMismatch,
    NotYetValid,
    Expired,
    RevocationEpochMismatch,
    RevocationFrontierMismatch,
    HierarchyProofInvalid,
    ArtifactBindingMismatch,
    ReceiptDigestMismatch,
}

impl fmt::Display for NduAuthenticityError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduAuthenticityError {}

pub(crate) fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduAuthenticityError> {
    if digest.is_zero() {
        Err(NduAuthenticityError::EmptyDigest(field))
    } else {
        Ok(())
    }
}

pub(crate) fn validate_window(
    issued_at_ms: u64,
    expires_at_ms: u64,
) -> Result<(), NduAuthenticityError> {
    if issued_at_ms == 0 || expires_at_ms <= issued_at_ms {
        Err(NduAuthenticityError::InvalidValidityWindow)
    } else {
        Ok(())
    }
}

pub(crate) fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u32::try_from(value.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}

pub(crate) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_string(bytes, value.as_str());
}

pub(crate) fn digest_hex(digest: Digest32) -> String {
    let mut encoded = String::with_capacity(64);
    for byte in digest.as_array() {
        use std::fmt::Write as _;
        let _ = write!(&mut encoded, "{byte:02x}");
    }
    encoded
}
