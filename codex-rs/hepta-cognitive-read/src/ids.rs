//! Exact-ID, field-projected cognitive reads over an already acquired snapshot.
//!
//! This is the typed local ModulePort shape used by owner-local consumers. It
//! deliberately does not become a durable or cross-process wire protocol.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::Error;
use crate::MAX_ENCODED_READ_RESULT_BYTES_V2;
use crate::current_records;

pub const MAX_READ_IDS_V1: usize = 512;
const READ_IDS_RECEIPT_DOMAIN: &[u8] = b"hepta.cognitive.read.ids.v1";
const READ_IDS_REQUEST_DOMAIN: &[u8] = b"hepta.cognitive.read.ids.request.v1";
const RECEIPT_DIGEST_BYTES: usize = 32;
const U32_BYTES: usize = 4;
const U64_BYTES: usize = 8;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ReadFieldV1 {
    ContentDigest,
    PredecessorDigest,
    Citations,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadIdsRequestV1 {
    pub snapshot_digest: Digest32,
    pub record_ids: Vec<StableId>,
    pub fields: Vec<ReadFieldV1>,
    pub maximum_encoded_bytes: usize,
}

impl ReadIdsRequestV1 {
    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        let mut ids = self.record_ids.clone();
        ids.sort();
        let mut fields = self.fields.clone();
        fields.sort();
        let mut bytes = READ_IDS_REQUEST_DOMAIN.to_vec();
        bytes.extend_from_slice(self.snapshot_digest.as_array());
        bytes.extend_from_slice(&u32::try_from(ids.len()).unwrap_or(u32::MAX).to_be_bytes());
        for id in ids {
            push_id(&mut bytes, &id);
        }
        bytes.extend_from_slice(
            &u32::try_from(fields.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for field in fields {
            bytes.push(field_code(field));
        }
        bytes.extend_from_slice(
            &u64::try_from(self.maximum_encoded_bytes)
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadProjectionRecordV1 {
    pub record_id: StableId,
    pub revision: Revision,
    pub kind: MemoryKind,
    pub state: RecordState,
    pub content_digest: Option<Digest32>,
    pub predecessor_digest: Option<Digest32>,
    pub citations: Vec<Citation>,
}

impl ReadProjectionRecordV1 {
    #[must_use]
    pub const fn is_live(&self) -> bool {
        matches!(self.state, RecordState::Live)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadIdsResultV1 {
    snapshot_digest: Digest32,
    request_binding_digest: Digest32,
    included_fields: Vec<ReadFieldV1>,
    records: Vec<ReadProjectionRecordV1>,
    missing_ids: Vec<StableId>,
    payload_encoded_bytes: usize,
    total_encoded_bytes: usize,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
    canonical_bytes: Vec<u8>,
}

impl ReadIdsResultV1 {
    #[must_use]
    pub const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub const fn request_binding_digest(&self) -> Digest32 {
        self.request_binding_digest
    }

    #[must_use]
    pub fn included_fields(&self) -> &[ReadFieldV1] {
        &self.included_fields
    }

    #[must_use]
    pub fn records(&self) -> &[ReadProjectionRecordV1] {
        &self.records
    }

    #[must_use]
    pub fn missing_ids(&self) -> &[StableId] {
        &self.missing_ids
    }

    /// Canonical bytes covered by [`Self::receipt_digest`].
    ///
    /// This excludes the trailing receipt digest itself.
    #[must_use]
    pub const fn payload_encoded_bytes(&self) -> usize {
        self.payload_encoded_bytes
    }

    /// Complete module-local canonical representation, including the trailing
    /// receipt digest.
    #[must_use]
    pub const fn total_encoded_bytes(&self) -> usize {
        self.total_encoded_bytes
    }

    /// Compatibility alias for callers that previously treated the canonical
    /// representation as one opaque byte budget.
    #[must_use]
    pub const fn encoded_bytes(&self) -> usize {
        self.total_encoded_bytes
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReadIdsError {
    Read(Error),
    TooManyRecordIds { requested: usize, maximum: usize },
    DuplicateRecordId,
    DuplicateField,
    InvalidMaximumEncodedBytes { requested: usize, maximum: usize },
    EncodedResultTooLarge { actual: usize, maximum: usize },
    InvalidCanonicalEncoding,
}

impl fmt::Display for ReadIdsError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ReadIdsError {}

impl From<Error> for ReadIdsError {
    fn from(error: Error) -> Self {
        Self::Read(error)
    }
}

/// Return the current head for each requested ID from one already validated
/// snapshot. Missing IDs are explicit. The result is all-or-error under the
/// caller-selected byte ceiling; exact-ID reads never silently prefix-truncate.
///
/// The full canonical length is calculated before citation or projection
/// cloning. This makes the byte ceiling a construction budget rather than a
/// check performed after potentially expensive output allocation.
pub fn read_ids_v1(
    snapshot: &CognitiveSnapshot,
    request: ReadIdsRequestV1,
) -> Result<ReadIdsResultV1, ReadIdsError> {
    if request.record_ids.len() > MAX_READ_IDS_V1 {
        return Err(ReadIdsError::TooManyRecordIds {
            requested: request.record_ids.len(),
            maximum: MAX_READ_IDS_V1,
        });
    }
    if request.maximum_encoded_bytes == 0
        || request.maximum_encoded_bytes > MAX_ENCODED_READ_RESULT_BYTES_V2
    {
        return Err(ReadIdsError::InvalidMaximumEncodedBytes {
            requested: request.maximum_encoded_bytes,
            maximum: MAX_ENCODED_READ_RESULT_BYTES_V2,
        });
    }

    let mut ids = BTreeSet::new();
    for id in &request.record_ids {
        if !ids.insert(id.clone()) {
            return Err(ReadIdsError::DuplicateRecordId);
        }
    }
    let mut fields = BTreeSet::new();
    for field in &request.fields {
        if !fields.insert(*field) {
            return Err(ReadIdsError::DuplicateField);
        }
    }

    let current = current_records(snapshot, request.snapshot_digest)?;
    let request_binding_digest = request.binding_digest();
    let included_fields = fields.into_iter().collect::<Vec<_>>();
    let include_content = included_fields.contains(&ReadFieldV1::ContentDigest);
    let include_predecessor = included_fields.contains(&ReadFieldV1::PredecessorDigest);
    let include_citations = included_fields.contains(&ReadFieldV1::Citations);

    let mut selected = Vec::with_capacity(ids.len());
    let mut missing_ids = Vec::new();
    for id in ids {
        match current.get(&id) {
            Some(record) => selected.push(*record),
            None => missing_ids.push(id),
        }
    }

    let payload_encoded_bytes = encoded_payload_len(
        &included_fields,
        &selected,
        &missing_ids,
        include_content,
        include_predecessor,
        include_citations,
    )?;
    let total_encoded_bytes = payload_encoded_bytes
        .checked_add(RECEIPT_DIGEST_BYTES)
        .ok_or(ReadIdsError::InvalidCanonicalEncoding)?;
    if total_encoded_bytes > request.maximum_encoded_bytes {
        return Err(ReadIdsError::EncodedResultTooLarge {
            actual: total_encoded_bytes,
            maximum: request.maximum_encoded_bytes,
        });
    }

    let mut records = Vec::with_capacity(selected.len());
    for record in selected {
        let mut citations = if include_citations {
            record.citations.clone()
        } else {
            Vec::new()
        };
        citations.sort();
        records.push(ReadProjectionRecordV1 {
            record_id: record.record_id.clone(),
            revision: record.revision,
            kind: record.kind,
            state: record.state,
            content_digest: include_content.then_some(record.content_digest),
            predecessor_digest: if include_predecessor {
                record.predecessor_digest
            } else {
                None
            },
            citations,
        });
    }

    let mut bytes = Vec::with_capacity(total_encoded_bytes);
    bytes.extend_from_slice(READ_IDS_RECEIPT_DOMAIN);
    bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
    bytes.extend_from_slice(request_binding_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(included_fields.len())
            .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?
            .to_be_bytes(),
    );
    for field in &included_fields {
        bytes.push(field_code(*field));
    }
    bytes.extend_from_slice(
        &u32::try_from(records.len())
            .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?
            .to_be_bytes(),
    );
    for record in &records {
        encode_record(&mut bytes, record)?;
    }
    bytes.extend_from_slice(
        &u32::try_from(missing_ids.len())
            .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?
            .to_be_bytes(),
    );
    for id in &missing_ids {
        push_id(&mut bytes, id);
    }
    bytes.push(0); // DENY_ALL
    if bytes.len() != payload_encoded_bytes {
        return Err(ReadIdsError::InvalidCanonicalEncoding);
    }

    let receipt_digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(receipt_digest.as_array());
    if bytes.len() != total_encoded_bytes {
        return Err(ReadIdsError::InvalidCanonicalEncoding);
    }

    Ok(ReadIdsResultV1 {
        snapshot_digest: snapshot.snapshot_digest,
        request_binding_digest,
        included_fields,
        records,
        missing_ids,
        payload_encoded_bytes,
        total_encoded_bytes,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
        canonical_bytes: bytes,
    })
}

fn encoded_payload_len(
    included_fields: &[ReadFieldV1],
    records: &[&MemoryRecord],
    missing_ids: &[StableId],
    include_content: bool,
    include_predecessor: bool,
    include_citations: bool,
) -> Result<usize, ReadIdsError> {
    u32::try_from(included_fields.len()).map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;
    u32::try_from(records.len()).map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;
    u32::try_from(missing_ids.len()).map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;

    let mut len = READ_IDS_RECEIPT_DOMAIN.len();
    add_len(&mut len, 32)?;
    add_len(&mut len, 32)?;
    add_len(&mut len, U32_BYTES)?;
    add_len(&mut len, included_fields.len())?;
    add_len(&mut len, U32_BYTES)?;
    for record in records {
        add_len(
            &mut len,
            encoded_record_len(
                record,
                include_content,
                include_predecessor,
                include_citations,
            )?,
        )?;
    }
    add_len(&mut len, U32_BYTES)?;
    for id in missing_ids {
        add_len(&mut len, encoded_id_len(id)?)?;
    }
    add_len(&mut len, 1)?;
    Ok(len)
}

fn encoded_record_len(
    record: &MemoryRecord,
    include_content: bool,
    include_predecessor: bool,
    include_citations: bool,
) -> Result<usize, ReadIdsError> {
    let mut len = encoded_id_len(&record.record_id)?;
    add_len(&mut len, U64_BYTES)?;
    add_len(&mut len, 1)?;
    add_len(&mut len, 1)?;
    add_len(&mut len, 1)?;
    if include_content {
        add_len(&mut len, 32)?;
    }
    add_len(&mut len, 1)?;
    if include_predecessor && record.predecessor_digest.is_some() {
        add_len(&mut len, 32)?;
    }
    add_len(&mut len, U32_BYTES)?;
    if include_citations {
        u32::try_from(record.citations.len())
            .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;
        for citation in &record.citations {
            add_len(&mut len, encoded_id_len(&citation.source_id)?)?;
            add_len(&mut len, 32)?;
        }
    }
    Ok(len)
}

fn encoded_id_len(value: &StableId) -> Result<usize, ReadIdsError> {
    let raw_len = value.as_str().as_bytes().len();
    u32::try_from(raw_len).map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;
    U32_BYTES
        .checked_add(raw_len)
        .ok_or(ReadIdsError::InvalidCanonicalEncoding)
}

fn add_len(total: &mut usize, additional: usize) -> Result<(), ReadIdsError> {
    *total = total
        .checked_add(additional)
        .ok_or(ReadIdsError::InvalidCanonicalEncoding)?;
    Ok(())
}

fn encode_record(bytes: &mut Vec<u8>, record: &ReadProjectionRecordV1) -> Result<(), ReadIdsError> {
    push_id(bytes, &record.record_id);
    bytes.extend_from_slice(&record.revision.get().to_be_bytes());
    bytes.push(kind_code(record.kind));
    bytes.push(state_code(record.state));

    match record.content_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    match record.predecessor_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(
        &u32::try_from(record.citations.len())
            .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?
            .to_be_bytes(),
    );
    for citation in &record.citations {
        push_id(bytes, &citation.source_id);
        bytes.extend_from_slice(citation.source_digest.as_array());
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

const fn field_code(field: ReadFieldV1) -> u8 {
    match field {
        ReadFieldV1::ContentDigest => 1,
        ReadFieldV1::PredecessorDigest => 2,
        ReadFieldV1::Citations => 3,
    }
}

const fn kind_code(kind: MemoryKind) -> u8 {
    match kind {
        MemoryKind::Episode => 0,
        MemoryKind::Fact => 1,
        MemoryKind::Preference => 2,
        MemoryKind::Procedure => 3,
    }
}

const fn state_code(state: RecordState) -> u8 {
    match state {
        RecordState::Live => 0,
        RecordState::Tombstone => 1,
    }
}
