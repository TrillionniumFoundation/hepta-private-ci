//! Owner-local, module-native bounded read projection.
//!
//! This encoding is not registered in `CONTRACTS.json` or
//! `PROTOCOL_SCHEMAS.json`, is not a `ModulePort`, and is not a durable or wire
//! protocol.  It only gives this crate a deterministic byte representation for
//! an authority-free shadow result.  A future cross-module consumer requires a
//! separate docs-first protocol-admission work package.

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
use crate::MAX_RESULTS;
use crate::ReadRequest;
use crate::read;

const MAX_SNAPSHOT_RECORDS: usize = 16_384;
const MAX_CITATIONS: usize = 64;
const READ_RECEIPT_V2_DOMAIN: &[u8] = b"hepta.cognitive.read.receipt.v2";
const READ_RECEIPT_V2_FIXED_BYTES: usize =
    READ_RECEIPT_V2_DOMAIN.len() + 4 + 32 + 32 + 4 + 8 + 1 + 32;

/// Hard ceiling for the complete module-native V2 read-result envelope.
pub const MAX_ENCODED_READ_RESULT_BYTES_V2: usize = 1024 * 1024;

/// A V1 read request paired with a stricter, caller-selected encoded-byte cap.
///
/// The selected cap cannot exceed [`MAX_ENCODED_READ_RESULT_BYTES_V2`]. It is a
/// resource limit only; it is not a caller assertion that a snapshot is fresh,
/// complete, or current against an external revocation frontier.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadRequestV2 {
    pub read_request: ReadRequest,
    pub maximum_encoded_bytes: usize,
}

impl ReadRequestV2 {
    /// Digest of the complete caller-supplied query and selected byte ceiling.
    ///
    /// This is an integrity binding, not source authentication or authorization.
    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        digest_read_request_v2(self)
    }
}

/// A module-native, byte-bounded V2 read result.
///
/// The module-canonical bytes contain the complete result envelope: the supplied
/// snapshot digest, an exact query binding, every returned record field, the
/// implementation-computed omitted count, the deny-all authority posture, and
/// the receipt digest. A valid result proves canonical encoding and internal
/// digest consistency only. It does not authenticate the source, certify
/// completeness beyond the supplied snapshot, or attest current revocation
/// state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadResultV2 {
    snapshot_digest: Digest32,
    request_binding_digest: Digest32,
    records: Vec<MemoryRecord>,
    omitted_count: usize,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
    canonical_bytes: Vec<u8>,
}

impl ReadResultV2 {
    #[must_use]
    pub const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub const fn request_binding_digest(&self) -> Digest32 {
        self.request_binding_digest
    }

    #[must_use]
    pub fn records(&self) -> &[MemoryRecord] {
        &self.records
    }

    #[must_use]
    pub const fn omitted_count(&self) -> usize {
        self.omitted_count
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

    /// Parses a module-native result and binds it to the exact expected query.
    ///
    /// Success proves only bounded decoding, local digest consistency, and
    /// conformance to the expected query's byte, result-count, kind, tombstone,
    /// and snapshot constraints. It does not authenticate a producer, establish
    /// external freshness, or grant any authority.
    pub fn from_canonical_bytes_for_request(
        bytes: &[u8],
        expected_request: &ReadRequestV2,
    ) -> Result<Self, ReadV2Error> {
        validate_encoded_byte_limit(expected_request.maximum_encoded_bytes)?;
        if bytes.len() > expected_request.maximum_encoded_bytes {
            return Err(ReadV2Error::EncodedResultTooLarge {
                actual: bytes.len(),
                maximum: expected_request.maximum_encoded_bytes,
            });
        }
        if expected_request.read_request.maximum_results == 0
            || expected_request.read_request.maximum_results > MAX_RESULTS
        {
            return Err(ReadV2Error::Read(Error::InvalidMaximumResults));
        }
        let mut allowed_kinds = BTreeSet::new();
        for kind in &expected_request.read_request.allowed_kinds {
            if !allowed_kinds.insert(*kind) {
                return Err(ReadV2Error::Read(Error::DuplicateKind));
            }
        }

        let result = decode_read_result_v2(bytes)?;
        if result.request_binding_digest != expected_request.binding_digest() {
            return Err(ReadV2Error::RequestBindingMismatch);
        }
        if result.snapshot_digest != expected_request.read_request.snapshot_digest
            || result.records.len() > expected_request.read_request.maximum_results
            || result.records.iter().any(|record| {
                (!allowed_kinds.is_empty() && !allowed_kinds.contains(&record.kind))
                    || (!expected_request.read_request.include_tombstones
                        && record.state == RecordState::Tombstone)
            })
        {
            return Err(ReadV2Error::ResultViolatesRequest);
        }
        Ok(result)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReadV2Error {
    Read(Error),
    InvalidMaximumEncodedBytes { requested: usize, maximum: usize },
    EncodedResultLimitTooSmall { requested: usize, minimum: usize },
    EncodedResultTooLarge { actual: usize, maximum: usize },
    InvalidCanonicalEncoding,
    UnknownMemoryKind(u8),
    UnknownRecordState(u8),
    UnknownAuthorityBits(u8),
    RequestBindingMismatch,
    ResultViolatesRequest,
    ReceiptDigestMismatch,
}

impl fmt::Display for ReadV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ReadV2Error {}

impl From<Error> for ReadV2Error {
    fn from(error: Error) -> Self {
        Self::Read(error)
    }
}

/// Reads the same current-head projection as [`read`] while bounding the
/// complete module-native output envelope, not an estimate of record frames.
///
/// Records form a canonical prefix. If the next record would exceed the
/// selected byte limit, that record and every later eligible record are counted
/// as omitted. The returned bytes are always checked against both the selected
/// limit and the one-MiB hard ceiling.
pub fn read_v2(
    snapshot: &CognitiveSnapshot,
    request: ReadRequestV2,
) -> Result<ReadResultV2, ReadV2Error> {
    validate_encoded_byte_limit(request.maximum_encoded_bytes)?;

    let request_binding_digest = request.binding_digest();

    // Reuse V1 selection verbatim so V2 cannot silently reinterpret snapshots
    // as full history or change V1 validation and digest behavior.
    let receipt = read(snapshot, request.read_request)?;
    let selected_count = receipt.records.len();
    let mut records = Vec::new();
    let mut encoded_records = Vec::new();
    let mut encoded_length = READ_RECEIPT_V2_FIXED_BYTES;
    for mut record in receipt.records {
        record.citations.sort();
        let encoded_record = encode_record_v2(&record);
        let candidate_length = encoded_length
            .checked_add(4)
            .and_then(|length| length.checked_add(encoded_record.len()))
            .ok_or(ReadV2Error::InvalidCanonicalEncoding)?;
        if candidate_length > request.maximum_encoded_bytes {
            break;
        }
        encoded_length = candidate_length;
        records.push(record);
        encoded_records.push(encoded_record);
    }

    let byte_omitted = selected_count
        .checked_sub(records.len())
        .ok_or(ReadV2Error::InvalidCanonicalEncoding)?;
    let omitted_count = receipt
        .omitted_count
        .checked_add(byte_omitted)
        .ok_or(ReadV2Error::InvalidCanonicalEncoding)?;
    let (canonical_bytes, receipt_digest) = encode_read_result_v2(
        receipt.snapshot_digest,
        request_binding_digest,
        &encoded_records,
        omitted_count,
    )?;
    if canonical_bytes.len() > request.maximum_encoded_bytes {
        return Err(ReadV2Error::EncodedResultTooLarge {
            actual: canonical_bytes.len(),
            maximum: request.maximum_encoded_bytes,
        });
    }

    Ok(ReadResultV2 {
        snapshot_digest: receipt.snapshot_digest,
        request_binding_digest,
        records,
        omitted_count,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
        canonical_bytes,
    })
}

fn validate_encoded_byte_limit(maximum_encoded_bytes: usize) -> Result<(), ReadV2Error> {
    if maximum_encoded_bytes == 0 || maximum_encoded_bytes > MAX_ENCODED_READ_RESULT_BYTES_V2 {
        return Err(ReadV2Error::InvalidMaximumEncodedBytes {
            requested: maximum_encoded_bytes,
            maximum: MAX_ENCODED_READ_RESULT_BYTES_V2,
        });
    }
    if maximum_encoded_bytes < READ_RECEIPT_V2_FIXED_BYTES {
        return Err(ReadV2Error::EncodedResultLimitTooSmall {
            requested: maximum_encoded_bytes,
            minimum: READ_RECEIPT_V2_FIXED_BYTES,
        });
    }
    Ok(())
}

fn encode_read_result_v2(
    snapshot_digest: Digest32,
    request_binding_digest: Digest32,
    encoded_records: &[Vec<u8>],
    omitted_count: usize,
) -> Result<(Vec<u8>, Digest32), ReadV2Error> {
    let records_bytes = encoded_records.iter().try_fold(0usize, |total, record| {
        total.checked_add(4)?.checked_add(record.len())
    });
    let Some(total_length) = records_bytes
        .and_then(|records_bytes| READ_RECEIPT_V2_FIXED_BYTES.checked_add(records_bytes))
    else {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    };
    if total_length > MAX_ENCODED_READ_RESULT_BYTES_V2 {
        return Err(ReadV2Error::EncodedResultTooLarge {
            actual: total_length,
            maximum: MAX_ENCODED_READ_RESULT_BYTES_V2,
        });
    }

    let encoded_total_length =
        u32::try_from(total_length).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    let record_count =
        u32::try_from(encoded_records.len()).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    let omitted_count =
        u64::try_from(omitted_count).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    let mut bytes = Vec::with_capacity(total_length);
    bytes.extend_from_slice(READ_RECEIPT_V2_DOMAIN);
    bytes.extend_from_slice(&encoded_total_length.to_be_bytes());
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(request_binding_digest.as_array());
    bytes.extend_from_slice(&record_count.to_be_bytes());
    for record in encoded_records {
        let record_length =
            u32::try_from(record.len()).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
        bytes.extend_from_slice(&record_length.to_be_bytes());
        bytes.extend_from_slice(record);
    }
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    bytes.push(0); // AuthorityPosture::DENY_ALL, with all eight bits denied.
    let receipt_digest = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(receipt_digest.as_array());
    Ok((bytes, receipt_digest))
}

fn encode_record_v2(record: &MemoryRecord) -> Vec<u8> {
    let mut bytes = Vec::new();
    push_id_v2(&mut bytes, &record.record_id);
    bytes.extend_from_slice(&record.revision.get().to_be_bytes());
    bytes.push(kind_code_v2(record.kind));
    bytes.push(state_code_v2(record.state));
    bytes.extend_from_slice(record.content_digest.as_array());
    match record.predecessor_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(
        &u32::try_from(record.citations.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for citation in &record.citations {
        push_id_v2(&mut bytes, &citation.source_id);
        bytes.extend_from_slice(citation.source_digest.as_array());
    }
    bytes
}

fn decode_read_result_v2(bytes: &[u8]) -> Result<ReadResultV2, ReadV2Error> {
    if bytes.len() > MAX_ENCODED_READ_RESULT_BYTES_V2 {
        return Err(ReadV2Error::EncodedResultTooLarge {
            actual: bytes.len(),
            maximum: MAX_ENCODED_READ_RESULT_BYTES_V2,
        });
    }
    if bytes.len() < READ_RECEIPT_V2_FIXED_BYTES {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }

    let mut decoder = Decoder::new(bytes);
    if decoder.take(READ_RECEIPT_V2_DOMAIN.len())? != READ_RECEIPT_V2_DOMAIN {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }
    let declared_length =
        usize::try_from(decoder.take_u32()?).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    if declared_length != bytes.len() {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }
    let snapshot_digest = Digest32::from_array(decoder.take_array()?);
    if snapshot_digest.is_zero() {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }
    let request_binding_digest = Digest32::from_array(decoder.take_array()?);
    if request_binding_digest.is_zero() {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }
    let record_count =
        usize::try_from(decoder.take_u32()?).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    if record_count > MAX_RESULTS {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }

    let mut records = Vec::with_capacity(record_count);
    for _ in 0..record_count {
        let record_length = usize::try_from(decoder.take_u32()?)
            .map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
        let mut record_decoder = Decoder::new(decoder.take(record_length)?);
        let record = decode_record_v2(&mut record_decoder)?;
        if !record_decoder.is_finished() {
            return Err(ReadV2Error::InvalidCanonicalEncoding);
        }
        if records
            .last()
            .is_some_and(|previous: &MemoryRecord| previous.record_id >= record.record_id)
        {
            return Err(ReadV2Error::InvalidCanonicalEncoding);
        }
        records.push(record);
    }

    let omitted_count =
        usize::try_from(decoder.take_u64()?).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    let Some(source_record_count) = records.len().checked_add(omitted_count) else {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    };
    if source_record_count > MAX_SNAPSHOT_RECORDS {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }
    let authority_bits = decoder.take_u8()?;
    if authority_bits != 0 {
        return Err(ReadV2Error::UnknownAuthorityBits(authority_bits));
    }
    if decoder.remaining() != 32 {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }
    let receipt_digest = Digest32::from_array(decoder.take_array()?);
    let digest_offset = bytes.len() - 32;
    if Digest32::of_bytes(&bytes[..digest_offset]) != receipt_digest {
        return Err(ReadV2Error::ReceiptDigestMismatch);
    }

    Ok(ReadResultV2 {
        snapshot_digest,
        request_binding_digest,
        records,
        omitted_count,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
        canonical_bytes: bytes.to_vec(),
    })
}

fn digest_read_request_v2(request: &ReadRequestV2) -> Digest32 {
    let mut allowed_kinds = request.read_request.allowed_kinds.clone();
    allowed_kinds.sort();
    let mut bytes = b"hepta.cognitive.read.request.v2".to_vec();
    bytes.extend_from_slice(request.read_request.snapshot_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(request.read_request.maximum_results)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.push(u8::from(request.read_request.include_tombstones));
    bytes.extend_from_slice(
        &u64::try_from(request.maximum_encoded_bytes)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u32::try_from(allowed_kinds.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for kind in allowed_kinds {
        bytes.push(kind_code_v2(kind));
    }
    Digest32::of_bytes(&bytes)
}

fn decode_record_v2(decoder: &mut Decoder<'_>) -> Result<MemoryRecord, ReadV2Error> {
    let record_id = decoder.take_id()?;
    let revision =
        Revision::new(decoder.take_u64()?).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    let kind = match decoder.take_u8()? {
        0 => MemoryKind::Episode,
        1 => MemoryKind::Fact,
        2 => MemoryKind::Preference,
        3 => MemoryKind::Procedure,
        value => return Err(ReadV2Error::UnknownMemoryKind(value)),
    };
    let state = match decoder.take_u8()? {
        0 => RecordState::Live,
        1 => RecordState::Tombstone,
        value => return Err(ReadV2Error::UnknownRecordState(value)),
    };
    let content_digest = Digest32::from_array(decoder.take_array()?);
    let predecessor_digest = match decoder.take_u8()? {
        0 => None,
        1 => Some(Digest32::from_array(decoder.take_array()?)),
        _ => return Err(ReadV2Error::InvalidCanonicalEncoding),
    };
    let citation_count =
        usize::try_from(decoder.take_u32()?).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    if citation_count > MAX_CITATIONS {
        return Err(ReadV2Error::InvalidCanonicalEncoding);
    }
    let mut citations = Vec::with_capacity(citation_count);
    for _ in 0..citation_count {
        let citation = Citation {
            source_id: decoder.take_id()?,
            source_digest: Digest32::from_array(decoder.take_array()?),
        };
        if citations
            .last()
            .is_some_and(|previous: &Citation| previous >= &citation)
        {
            return Err(ReadV2Error::InvalidCanonicalEncoding);
        }
        citations.push(citation);
    }
    let record = MemoryRecord {
        record_id,
        revision,
        kind,
        content_digest,
        predecessor_digest,
        citations,
        state,
    };
    record
        .validate()
        .map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
    Ok(record)
}

fn push_id_v2(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn kind_code_v2(value: MemoryKind) -> u8 {
    match value {
        MemoryKind::Episode => 0,
        MemoryKind::Fact => 1,
        MemoryKind::Preference => 2,
        MemoryKind::Procedure => 3,
    }
}

fn state_code_v2(value: RecordState) -> u8 {
    match value {
        RecordState::Live => 0,
        RecordState::Tombstone => 1,
    }
}

struct Decoder<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Decoder<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], ReadV2Error> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(ReadV2Error::InvalidCanonicalEncoding)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(ReadV2Error::InvalidCanonicalEncoding)?;
        self.offset = end;
        Ok(value)
    }

    fn take_array<const LENGTH: usize>(&mut self) -> Result<[u8; LENGTH], ReadV2Error> {
        let mut value = [0; LENGTH];
        value.copy_from_slice(self.take(LENGTH)?);
        Ok(value)
    }

    fn take_u8(&mut self) -> Result<u8, ReadV2Error> {
        Ok(self.take_array::<1>()?[0])
    }

    fn take_u32(&mut self) -> Result<u32, ReadV2Error> {
        Ok(u32::from_be_bytes(self.take_array()?))
    }

    fn take_u64(&mut self) -> Result<u64, ReadV2Error> {
        Ok(u64::from_be_bytes(self.take_array()?))
    }

    fn take_id(&mut self) -> Result<StableId, ReadV2Error> {
        let length =
            usize::try_from(self.take_u32()?).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| ReadV2Error::InvalidCanonicalEncoding)?;
        StableId::new(value).map_err(|_| ReadV2Error::InvalidCanonicalEncoding)
    }

    const fn remaining(&self) -> usize {
        self.bytes.len() - self.offset
    }

    const fn is_finished(&self) -> bool {
        self.remaining() == 0
    }
}
