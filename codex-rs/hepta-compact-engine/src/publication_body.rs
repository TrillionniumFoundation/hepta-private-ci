//! Complete, bounded restart preimages. Restoration always repeats admission.

#[path = "publication_body_codec.rs"]
mod codec;
#[path = "publication_body_restore.rs"]
mod restore_codec;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::IdentityError;

use crate::AuthenticatedCompactionError;
use crate::CompactionPublicationContextV1;
use crate::CompactionPublicationError;
use crate::CompactionPublicationProposalV1;
use crate::QualifiedCompactionError;

/// Exact JSON transport ceiling, including the wrapper and hexadecimal encoding.
pub const MAX_COMPACTION_PUBLICATION_BODY_BYTES_V1: usize = 65_536;
const PREFIX: &[u8] = b"{\"bodyHex\":\"";
const SUFFIX: &[u8] = b"\",\"schemaVersion\":1}";
const MAX_BINARY_BYTES: usize =
    (MAX_COMPACTION_PUBLICATION_BODY_BYTES_V1 - PREFIX.len() - SUFFIX.len()) / 2;

impl CompactionPublicationProposalV1 {
    /// Encodes full typed preimages and original signatures, never a verified token.
    /// The returned bytes are the actual JSON payload to hash for durable dedupe.
    /// Oversized proposals fail rather than relying on a process cache or reference.
    pub fn encode_restart_body_v1(&self) -> Result<Vec<u8>, CompactionPublicationBodyError> {
        let binary = codec::encode(self)?;
        let mut body = Vec::with_capacity(PREFIX.len() + 2 * binary.len() + SUFFIX.len());
        body.extend_from_slice(PREFIX);
        for byte in binary {
            body.push(b"0123456789abcdef"[usize::from(byte >> 4)]);
            body.push(b"0123456789abcdef"[usize::from(byte & 15)]);
        }
        body.extend_from_slice(SUFFIX);
        Ok(body)
    }
}

/// Restores a complete body under independently obtained current host state.
/// This reconstructs and validates a new proposal; it never deserializes admission.
/// It grants no persistence, selected-pointer, transaction or final-use authority.
pub fn restore_compaction_publication_body_v1(
    body: &[u8],
    context: &CompactionPublicationContextV1<'_>,
) -> Result<CompactionPublicationProposalV1, CompactionPublicationBodyError> {
    if body.len() > MAX_COMPACTION_PUBLICATION_BODY_BYTES_V1 {
        return Err(CompactionPublicationBodyError::BodyLimitExceeded);
    }
    let hex = body
        .strip_prefix(PREFIX)
        .and_then(|bytes| bytes.strip_suffix(SUFFIX))
        .ok_or(CompactionPublicationBodyError::NonCanonicalEnvelope)?;
    if hex.len() % 2 != 0 || hex.len() / 2 > MAX_BINARY_BYTES {
        return Err(CompactionPublicationBodyError::NonCanonicalEnvelope);
    }
    // Reject the entire alphabet before allocating or decoding any binary body.
    if !hex
        .iter()
        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
    {
        return Err(CompactionPublicationBodyError::NonCanonicalEnvelope);
    }
    let nibble = |byte: u8| {
        if byte <= b'9' {
            byte - b'0'
        } else {
            byte - b'a' + 10
        }
    };
    let binary = hex
        .chunks_exact(2)
        .map(|pair| (nibble(pair[0]) << 4) | nibble(pair[1]))
        .collect::<Vec<_>>();
    restore_codec::restore(&binary, context)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompactionPublicationBodyError {
    BodyLimitExceeded,
    NonCanonicalEnvelope,
    TruncatedBinary,
    InvalidBinary(&'static str),
    CommitmentMismatch(&'static str),
    Identity(IdentityError),
    Contract(LaneCContractError),
    Compaction(QualifiedCompactionError),
    Authentication(AuthenticatedCompactionError),
    Publication(CompactionPublicationError),
}

impl fmt::Display for CompactionPublicationBodyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompactionPublicationBodyError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Identity(error) => Some(error),
            Self::Contract(error) => Some(error),
            Self::Compaction(error) => Some(error),
            Self::Authentication(error) => Some(error),
            Self::Publication(error) => Some(error),
            Self::BodyLimitExceeded
            | Self::NonCanonicalEnvelope
            | Self::TruncatedBinary
            | Self::InvalidBinary(_)
            | Self::CommitmentMismatch(_) => None,
        }
    }
}

impl From<IdentityError> for CompactionPublicationBodyError {
    fn from(error: IdentityError) -> Self {
        Self::Identity(error)
    }
}
impl From<LaneCContractError> for CompactionPublicationBodyError {
    fn from(error: LaneCContractError) -> Self {
        Self::Contract(error)
    }
}
impl From<QualifiedCompactionError> for CompactionPublicationBodyError {
    fn from(error: QualifiedCompactionError) -> Self {
        Self::Compaction(error)
    }
}
impl From<AuthenticatedCompactionError> for CompactionPublicationBodyError {
    fn from(error: AuthenticatedCompactionError) -> Self {
        Self::Authentication(error)
    }
}
impl From<CompactionPublicationError> for CompactionPublicationBodyError {
    fn from(error: CompactionPublicationError) -> Self {
        Self::Publication(error)
    }
}

#[cfg(test)]
#[path = "publication_body_tests.rs"]
mod tests;
