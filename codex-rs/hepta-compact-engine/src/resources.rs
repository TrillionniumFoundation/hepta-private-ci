//! Aggregate ingress limits, checked before record validation or hashing.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;

/// Maximum citations across all supplied revisions or retained payload records.
pub const MAX_COMPACTION_CITATIONS: usize = 65_536;
/// Maximum canonical V1 record-preimage bytes plus supplied omission/deletion
/// digest references. This is a payload ceiling, not a measured RSS limit.
pub const MAX_COMPACTION_ENCODED_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CompactionResourceError {
    CitationLimitExceeded,
    EncodedByteLimitExceeded,
    ArithmeticOverflow,
}

impl fmt::Display for CompactionResourceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompactionResourceError {}

/// Count the bytes encoded by MemoryRecord::record_digest without encoding,
/// sorting, cloning or hashing. That encoder has no citation-count prefix.
/// Digest references supplied separately by a candidate consume 32 bytes each.
pub(crate) fn preflight_records<'a>(
    records: impl IntoIterator<Item = &'a MemoryRecord>,
    digest_references: usize,
) -> Result<(), CompactionResourceError> {
    let mut encoded_bytes = digest_references
        .checked_mul(32)
        .ok_or(CompactionResourceError::ArithmeticOverflow)?;
    if encoded_bytes > MAX_COMPACTION_ENCODED_BYTES {
        return Err(CompactionResourceError::EncodedByteLimitExceeded);
    }
    let mut citations = 0_usize;
    for record in records {
        citations = citations
            .checked_add(record.citations.len())
            .ok_or(CompactionResourceError::ArithmeticOverflow)?;
        if citations > MAX_COMPACTION_CITATIONS {
            return Err(CompactionResourceError::CitationLimitExceeded);
        }
        // Domain, length-prefixed ID, revision, kind/state, content digest and
        // the optional-predecessor discriminator/digest are all V1 fields.
        let fixed_bytes = b"hepta.cognitive.record.v1".len() + 4 + 8 + 1 + 1 + 32 + 1;
        let record_bytes = fixed_bytes
            .checked_add(record.record_id.as_str().len())
            .and_then(|bytes| {
                bytes.checked_add(if record.predecessor_digest.is_some() {
                    32
                } else {
                    0
                })
            })
            .ok_or(CompactionResourceError::ArithmeticOverflow)?;
        add_encoded_bytes(&mut encoded_bytes, record_bytes)?;
        for citation in &record.citations {
            let citation_bytes = citation
                .source_id
                .as_str()
                .len()
                .checked_add(4 + 32)
                .ok_or(CompactionResourceError::ArithmeticOverflow)?;
            add_encoded_bytes(&mut encoded_bytes, citation_bytes)?;
        }
    }
    Ok(())
}

fn add_encoded_bytes(
    current: &mut usize,
    additional: usize,
) -> Result<(), CompactionResourceError> {
    *current = current
        .checked_add(additional)
        .ok_or(CompactionResourceError::ArithmeticOverflow)?;
    if *current > MAX_COMPACTION_ENCODED_BYTES {
        return Err(CompactionResourceError::EncodedByteLimitExceeded);
    }
    Ok(())
}
