//! Typed byte coverage over the current compiler-owned V2 canonical format.
//!
//! V3 identifies this metadata view, not a new payload format or provider proof.
//! The only constructor borrows an existing canonical object and checks it
//! against its compiled context and model profile. No request preparation,
//! transport observation, tokenizer qualification, or effect authority is added.

use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::CanonicalSerializedContextV2;
use crate::CompiledContextV2;
use crate::ContextModelProfileV2;
use crate::ContextRoleV2;
use crate::ProviderRequestProofErrorV2;

mod canonical;

const SOURCE_FORMAT_V2: &[u8] = b"hepta.context-canonical-bundle.v2";
const VIEW_DOMAIN_V3: &[u8] = b"hepta.context-canonical-source-view.v3";

/// Each field's index refers to the existing receipt's ordered selected IDs.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalContextSourceFieldV3 {
    Domain,
    ItemCount,
    ItemIdLength {
        selected_index: u64,
    },
    ItemId {
        selected_index: u64,
    },
    Role {
        selected_index: u64,
        role: ContextRoleV2,
    },
    ContentLength {
        selected_index: u64,
    },
    Content {
        selected_index: u64,
    },
}

/// An immutable range derived from the existing canonical producer.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalContextSourceSegmentV3 {
    field: CanonicalContextSourceFieldV3,
    offset: u64,
    length: u64,
    encoded_digest: Digest32,
}

impl CanonicalContextSourceSegmentV3 {
    #[must_use]
    pub const fn field(&self) -> CanonicalContextSourceFieldV3 {
        self.field
    }

    #[must_use]
    pub const fn offset(&self) -> u64 {
        self.offset
    }

    #[must_use]
    pub const fn length(&self) -> u64 {
        self.length
    }

    #[must_use]
    pub const fn encoded_digest(&self) -> Digest32 {
        self.encoded_digest
    }
}

/// A borrowed source view. Its digest is metadata identity, never dispatch proof.
///
/// All V2 bytes and receipts remain unchanged. This type has no raw-byte, map,
/// expected-hash, or callback constructor and no serialization implementation.
/// Derivation neither renews admissions nor establishes current transport state.
#[derive(Clone, Eq, PartialEq)]
pub struct CanonicalContextSourceV3<'a> {
    source: &'a CanonicalSerializedContextV2,
    segments: Vec<CanonicalContextSourceSegmentV3>,
    metadata_digest: Digest32,
}

impl<'a> CanonicalContextSourceV3<'a> {
    pub fn from_canonical_v2(
        compiled: &CompiledContextV2,
        source: &'a CanonicalSerializedContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<Self, ProviderRequestProofErrorV2> {
        source.validate_for(compiled, profile)?;
        let segments = canonical::derive_segments(compiled, source.serialized_context().payload())?;
        let mut identity = VIEW_DOMAIN_V3.to_vec();
        identity.extend_from_slice(
            &u64::try_from(SOURCE_FORMAT_V2.len())
                .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?
                .to_be_bytes(),
        );
        identity.extend_from_slice(SOURCE_FORMAT_V2);
        for digest in [
            compiled.receipt().receipt_digest(),
            profile.digest(),
            source.serialized_context().receipt().receipt_digest(),
            source.serialized_context().receipt().payload_digest(),
            source.coverage_digest(),
        ] {
            identity.extend_from_slice(digest.as_array());
        }
        identity.extend_from_slice(
            &u64::try_from(segments.len())
                .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?
                .to_be_bytes(),
        );
        for segment in &segments {
            use CanonicalContextSourceFieldV3 as Field;
            let (tag, index, role) = match segment.field {
                Field::Domain => (0, None, None),
                Field::ItemCount => (1, None, None),
                Field::ItemIdLength { selected_index } => (2, Some(selected_index), None),
                Field::ItemId { selected_index } => (3, Some(selected_index), None),
                Field::Role {
                    selected_index,
                    role,
                } => (4, Some(selected_index), Some(role)),
                Field::ContentLength { selected_index } => (5, Some(selected_index), None),
                Field::Content { selected_index } => (6, Some(selected_index), None),
            };
            identity.push(tag);
            if let Some(index) = index {
                identity.extend_from_slice(&index.to_be_bytes());
            }
            if let Some(role) = role {
                identity.push(canonical::role_code(role));
            }
            identity.extend_from_slice(&segment.offset.to_be_bytes());
            identity.extend_from_slice(&segment.length.to_be_bytes());
            identity.extend_from_slice(segment.encoded_digest.as_array());
        }
        Ok(Self {
            source,
            segments,
            metadata_digest: Digest32::of_bytes(&identity),
        })
    }

    #[must_use]
    pub const fn canonical_v2(&self) -> &'a CanonicalSerializedContextV2 {
        self.source
    }

    #[must_use]
    pub fn segments(&self) -> &[CanonicalContextSourceSegmentV3] {
        &self.segments
    }

    #[must_use]
    pub const fn metadata_digest(&self) -> Digest32 {
        self.metadata_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

impl fmt::Debug for CanonicalContextSourceV3<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CanonicalContextSourceV3")
            .field(
                "v2_receipt_digest",
                &self.source.serialized_context().receipt().receipt_digest(),
            )
            .field("segment_count", &self.segments.len())
            .field("metadata_digest", &self.metadata_digest)
            .finish()
    }
}
