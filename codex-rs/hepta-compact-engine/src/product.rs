//! Product binding for compaction candidates sourced through `cognitive.read`.
//!
//! The compaction engine still owns no store, writer, authorization cache or
//! final-use capability. The durable owner supplies an exact read receipt and
//! current owner-cut digest, and this module binds them to the deterministic
//! compaction candidate.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::QualifiedCompactionCandidateV2;
use crate::QualifiedCompactionError;

pub const MAX_COGNITIVE_READ_COMPACTION_IDS: usize = 512;
const PRODUCT_BINDING_DOMAIN: &[u8] = b"hepta.compact.cognitive-read-product.v1";

/// Caller-selected policy metadata for one exact owner record identity.
///
/// No record bytes, revision, digest, authorization result or freshness claim
/// can be injected through this value. The durable owner resolves those facts.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveReadCompactionRetentionV1 {
    pub record_id: StableId,
    pub retention_priority: u32,
    pub retention_reason_digest: Digest32,
}

impl CognitiveReadCompactionRetentionV1 {
    pub fn validate(&self) -> Result<(), CognitiveReadCompactionBindingError> {
        if self.retention_reason_digest.is_zero() {
            return Err(CognitiveReadCompactionBindingError::EmptyDigest(
                "retention_reason",
            ));
        }
        Ok(())
    }
}

/// Authority-free candidate tied to one exact owner cut and exact-ID read.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveReadCompactionCandidateV1 {
    candidate: QualifiedCompactionCandidateV2,
    owner_cut_digest: Digest32,
    read_receipt_digest: Digest32,
    product_binding_digest: Digest32,
    authority: AuthorityPosture,
}

impl CognitiveReadCompactionCandidateV1 {
    pub fn new(
        candidate: QualifiedCompactionCandidateV2,
        owner_cut_digest: Digest32,
        read_receipt_digest: Digest32,
    ) -> Result<Self, CognitiveReadCompactionBindingError> {
        candidate
            .validate()
            .map_err(CognitiveReadCompactionBindingError::Candidate)?;
        for (name, digest) in [
            ("owner_cut", owner_cut_digest),
            ("read_receipt", read_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(CognitiveReadCompactionBindingError::EmptyDigest(name));
            }
        }
        let mut result = Self {
            candidate,
            owner_cut_digest,
            read_receipt_digest,
            product_binding_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        result.product_binding_digest = result.compute_binding_digest();
        result.validate()?;
        Ok(result)
    }

    #[must_use]
    pub const fn candidate(&self) -> &QualifiedCompactionCandidateV2 {
        &self.candidate
    }

    #[must_use]
    pub const fn owner_cut_digest(&self) -> Digest32 {
        self.owner_cut_digest
    }

    #[must_use]
    pub const fn read_receipt_digest(&self) -> Digest32 {
        self.read_receipt_digest
    }

    #[must_use]
    pub const fn product_binding_digest(&self) -> Digest32 {
        self.product_binding_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), CognitiveReadCompactionBindingError> {
        self.candidate
            .validate()
            .map_err(CognitiveReadCompactionBindingError::Candidate)?;
        for (name, digest) in [
            ("owner_cut", self.owner_cut_digest),
            ("read_receipt", self.read_receipt_digest),
            ("product_binding", self.product_binding_digest),
        ] {
            if digest.is_zero() {
                return Err(CognitiveReadCompactionBindingError::EmptyDigest(name));
            }
        }
        if self.authority.grants_any() {
            return Err(CognitiveReadCompactionBindingError::AuthorityGranted);
        }
        if self.product_binding_digest != self.compute_binding_digest() {
            return Err(CognitiveReadCompactionBindingError::BindingDigestMismatch);
        }
        Ok(())
    }

    fn compute_binding_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            PRODUCT_BINDING_DOMAIN,
            self.candidate.candidate_digest.as_array(),
            self.candidate.source_snapshot.vector_digest.as_array(),
            self.owner_cut_digest.as_array(),
            self.read_receipt_digest.as_array(),
        ])
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CognitiveReadCompactionBindingError {
    Candidate(QualifiedCompactionError),
    EmptyDigest(&'static str),
    BindingDigestMismatch,
    AuthorityGranted,
}

impl fmt::Display for CognitiveReadCompactionBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CognitiveReadCompactionBindingError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Candidate(error) => Some(error),
            _ => None,
        }
    }
}
