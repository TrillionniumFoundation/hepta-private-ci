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
        bytes.extend_from_slice(
            &u32::try_from(ids.len()).unwrap_or(u32::MAX).to_be_bytes(),
        );
        for id in ids {
            push_id(&mut bytes, &id);
        }
        bytes.extend_from_slice(
            &u32::try_from(fields.len()).unwrap_or(u32::MAX).to_be_bytes(),
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
    let mut records = Vec::new();
    let mut missing_ids = Vec::new();
    for id in ids {
        let Some(record) = current.get(&id) else {
            missing_ids.push(id);
            continue;
        };
        let mut citations = if included_fields.contains(&ReadFieldV1::Citations) {
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
            content_digest: included_fields
                .contains(&ReadFieldV1::ContentDigest)
                .then_some(record.content_digest),
            predecessor_digest: if included_fields.contains(&ReadFieldV1::PredecessorDigest) {
                record.predecessor_digest
            } else {
                None
            },
            citations,
        });
    }

    let mut bytes = READ_IDS_RECEIPT_DOMAIN.to_vec();
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
    let receipt_digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(receipt_digest.as_array());
    if bytes.len() > request.maximum_encoded_bytes {
        return Err(ReadIdsError::EncodedResultTooLarge {
            actual: bytes.len(),
            maximum: request.maximum_encoded_bytes,
        });
    }

    Ok(ReadIdsResultV1 {
        snapshot_digest: snapshot.snapshot_digest,
        request_binding_digest,
        included_fields,
        records,
        missing_ids,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
        canonical_bytes: bytes,
    })
}

fn encode_record(
    bytes: &mut Vec<u8>,
    record: &ReadProjectionRecordV1,
) -> Result<(), ReadIdsError> {
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
