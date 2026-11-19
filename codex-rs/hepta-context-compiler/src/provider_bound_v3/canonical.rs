//! Derive fields only after the public constructor validates the sealed V2 object.

use codex_hepta_types::Digest32;

use super::CanonicalContextSourceFieldV3 as Field;
use super::CanonicalContextSourceSegmentV3 as Segment;
use super::SOURCE_FORMAT_V2;
use crate::CompiledContextV2;
use crate::ContextRoleV2;
use crate::MAX_CONTEXT_CANDIDATES_V2;
use crate::MAX_SERIALIZED_PAYLOAD_BYTES_V2;
use crate::ProviderRequestProofErrorV2 as Error;

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: u64,
    segments: Vec<Segment>,
}

impl<'a> Cursor<'a> {
    fn take(&mut self, length: u64, field: Field) -> Result<&'a [u8], Error> {
        if length == 0 {
            return Err(Error::InvalidSegment);
        }
        let end = self.offset.checked_add(length).ok_or(Error::Arithmetic)?;
        let bytes = self
            .bytes
            .get(
                usize::try_from(self.offset).map_err(|_| Error::Arithmetic)?
                    ..usize::try_from(end).map_err(|_| Error::Arithmetic)?,
            )
            .ok_or(Error::IncompleteSegmentCoverage)?;
        self.segments.push(Segment {
            field,
            offset: self.offset,
            length,
            encoded_digest: Digest32::of_bytes(bytes),
        });
        self.offset = end;
        Ok(bytes)
    }

    fn read_u64(&mut self, field: Field) -> Result<u64, Error> {
        let bytes = self.take(/*length*/ 8, field)?;
        Ok(u64::from_be_bytes(
            bytes
                .try_into()
                .map_err(|_| Error::IncompleteSegmentCoverage)?,
        ))
    }
}

pub(super) fn derive_segments(
    compiled: &CompiledContextV2,
    payload: &[u8],
) -> Result<Vec<Segment>, Error> {
    let selected = compiled.selected_candidates();
    if selected.len() > MAX_CONTEXT_CANDIDATES_V2 {
        return Err(Error::SegmentLimitExceeded);
    }
    if payload.is_empty() || payload.len() > MAX_SERIALIZED_PAYLOAD_BYTES_V2 {
        return Err(Error::InvalidSegmentMap);
    }
    // Two bundle fields and five fields per selected item; no allocation uses
    // untrusted lengths or item counts read from the payload.
    let capacity = selected
        .len()
        .checked_mul(5)
        .and_then(|count| count.checked_add(2))
        .ok_or(Error::Arithmetic)?;
    let mut cursor = Cursor {
        bytes: payload,
        offset: 0,
        segments: Vec::with_capacity(capacity),
    };
    if cursor.take(
        u64::try_from(SOURCE_FORMAT_V2.len()).map_err(|_| Error::Arithmetic)?,
        Field::Domain,
    )? != SOURCE_FORMAT_V2
    {
        return Err(Error::InvalidSegment);
    }
    if cursor.read_u64(Field::ItemCount)?
        != u64::try_from(selected.len()).map_err(|_| Error::Arithmetic)?
    {
        return Err(Error::SelectedSetMismatch);
    }
    for (index, candidate) in selected.iter().enumerate() {
        let selected_index = u64::try_from(index).map_err(|_| Error::Arithmetic)?;
        let id_length = cursor.read_u64(Field::ItemIdLength { selected_index })?;
        if cursor.take(id_length, Field::ItemId { selected_index })?
            != candidate.item_id.as_str().as_bytes()
        {
            return Err(Error::SelectedSetMismatch);
        }
        if cursor.take(
            /*length*/ 1,
            Field::Role {
                selected_index,
                role: candidate.role,
            },
        )? != [role_code(candidate.role)]
        {
            return Err(Error::InvalidSegment);
        }
        let content_length = cursor.read_u64(Field::ContentLength { selected_index })?;
        let content = cursor.take(content_length, Field::Content { selected_index })?;
        if Digest32::of_bytes(content) != candidate.content_digest {
            return Err(Error::DigestMismatch("canonical_source_content"));
        }
    }
    if cursor.offset != u64::try_from(payload.len()).map_err(|_| Error::Arithmetic)? {
        return Err(Error::IncompleteSegmentCoverage);
    }
    Ok(cursor.segments)
}

pub(super) const fn role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

#[cfg(test)]
#[path = "canonical_tests.rs"]
mod tests;
