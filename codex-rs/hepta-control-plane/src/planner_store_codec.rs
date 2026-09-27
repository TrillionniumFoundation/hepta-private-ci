use codex_hepta_types::Digest32;

use super::Entry;
use super::PlannerStoreError;
use super::RecordKind;

pub(super) const HEADER_BYTES: usize = 148;
const MAGIC: &[u8; 8] = b"HCPSTR01";
const FRAME_MAGIC: &[u8; 4] = b"HCPF";
const MAX_FRAME_BYTES: usize = 2 * 1024 * 1024 + 256;
const MIN_FRAME_BYTES: usize = 141;

#[derive(Clone, Copy, Debug)]
pub(super) struct Header {
    pub store_id: Digest32,
    pub base_sequence: u64,
    pub base_head: Digest32,
    pub archive_digest: Digest32,
}

impl Header {
    pub fn genesis(store_id: Digest32) -> Self {
        let mut material = b"hepta.control.planner-store-genesis.v1\0".to_vec();
        material.extend_from_slice(store_id.as_array());
        Self {
            store_id,
            base_sequence: 0,
            base_head: Digest32::of_bytes(&material),
            archive_digest: Digest32::ZERO,
        }
    }

    pub fn encode(self) -> Vec<u8> {
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(&1_u32.to_be_bytes());
        bytes.extend_from_slice(self.store_id.as_array());
        bytes.extend_from_slice(&self.base_sequence.to_be_bytes());
        bytes.extend_from_slice(self.base_head.as_array());
        bytes.extend_from_slice(self.archive_digest.as_array());
        let checksum = Digest32::of_bytes(&bytes);
        bytes.extend_from_slice(checksum.as_array());
        bytes
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, PlannerStoreError> {
        if bytes.len() < HEADER_BYTES || &bytes[..8] != MAGIC {
            return Err(PlannerStoreError::Corrupt);
        }
        let mut cursor = Cursor::new(&bytes[8..HEADER_BYTES]);
        if cursor.u32()? != 1 {
            return Err(PlannerStoreError::UnsupportedSchema);
        }
        let result = Self {
            store_id: cursor.digest()?,
            base_sequence: cursor.u64()?,
            base_head: cursor.digest()?,
            archive_digest: cursor.digest()?,
        };
        if result.store_id.is_zero()
            || result.base_head.is_zero()
            || cursor.digest()? != Digest32::of_bytes(&bytes[..HEADER_BYTES - 32])
            || (result.base_sequence == 0) != result.archive_digest.is_zero()
            || (result.base_sequence == 0
                && result.base_head != Self::genesis(result.store_id).base_head)
        {
            return Err(PlannerStoreError::Corrupt);
        }
        Ok(result)
    }
}

pub(super) fn make_entry(
    store_id: Digest32,
    sequence: u64,
    kind: RecordKind,
    identity: Digest32,
    target: Digest32,
    predecessor: Digest32,
    body: Vec<u8>,
) -> Result<Entry, PlannerStoreError> {
    let mut entry = Entry {
        sequence,
        kind,
        identity,
        target,
        predecessor,
        body,
        digest: Digest32::ZERO,
    };
    entry.digest = entry_digest(store_id, &entry)?;
    Ok(entry)
}

pub(super) fn encode_entry(
    store_id: Digest32,
    entry: &Entry,
) -> Result<Vec<u8>, PlannerStoreError> {
    let mut payload = entry_payload(entry)?;
    if entry.digest != entry_digest(store_id, entry)? {
        return Err(PlannerStoreError::Corrupt);
    }
    payload.extend_from_slice(entry.digest.as_array());
    if payload.len() > MAX_FRAME_BYTES {
        return Err(PlannerStoreError::LimitExceeded);
    }
    let length = u32::try_from(payload.len()).map_err(|_| PlannerStoreError::LimitExceeded)?;
    let mut frame = FRAME_MAGIC.to_vec();
    frame.extend_from_slice(&length.to_be_bytes());
    frame.extend_from_slice(&(!length).to_be_bytes());
    frame.extend_from_slice(&payload);
    Ok(frame)
}

fn entry_payload(entry: &Entry) -> Result<Vec<u8>, PlannerStoreError> {
    if entry.identity.is_zero() || entry.target.is_zero() || entry.predecessor.is_zero() {
        return Err(PlannerStoreError::Corrupt);
    }
    let length = u32::try_from(entry.body.len()).map_err(|_| PlannerStoreError::LimitExceeded)?;
    if entry.body.len() > MAX_FRAME_BYTES - MIN_FRAME_BYTES {
        return Err(PlannerStoreError::LimitExceeded);
    }
    let mut bytes = entry.sequence.to_be_bytes().to_vec();
    bytes.push(entry.kind.tag());
    bytes.extend_from_slice(entry.identity.as_array());
    bytes.extend_from_slice(entry.target.as_array());
    bytes.extend_from_slice(entry.predecessor.as_array());
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(&entry.body);
    Ok(bytes)
}

fn entry_digest(store_id: Digest32, entry: &Entry) -> Result<Digest32, PlannerStoreError> {
    let mut bytes = b"hepta.control.planner-store-entry.v1\0".to_vec();
    bytes.extend_from_slice(store_id.as_array());
    bytes.extend_from_slice(&entry_payload(entry)?);
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) struct DecodedSegment {
    pub header: Header,
    pub entries: Vec<Entry>,
    pub frame_ends: Vec<(u64, usize)>,
    pub complete_bytes: usize,
}

pub(super) fn decode_segment(bytes: &[u8]) -> Result<DecodedSegment, PlannerStoreError> {
    let header = Header::decode(bytes)?;
    let mut sequence = header.base_sequence;
    let mut predecessor = header.base_head;
    let mut offset = HEADER_BYTES;
    let mut entries = Vec::new();
    let mut frame_ends = Vec::new();
    while offset < bytes.len() {
        if entries.len() >= 4096 {
            return Err(PlannerStoreError::LimitExceeded);
        }
        if bytes.len() - offset < 12 {
            break;
        }
        if &bytes[offset..offset + 4] != FRAME_MAGIC {
            return Err(PlannerStoreError::Corrupt);
        }
        let mut prefix = Cursor::new(&bytes[offset + 4..offset + 12]);
        let length_u32 = prefix.u32()?;
        if prefix.u32()? != !length_u32 {
            return Err(PlannerStoreError::Corrupt);
        }
        let length = length_u32 as usize;
        if !(MIN_FRAME_BYTES..=MAX_FRAME_BYTES).contains(&length) {
            return Err(PlannerStoreError::Corrupt);
        }
        let end = offset.checked_add(12 + length).ok_or(PlannerStoreError::Corrupt)?;
        if end > bytes.len() {
            break;
        }
        let mut cursor = Cursor::new(&bytes[offset + 12..end]);
        let entry_sequence = cursor.u64()?;
        let kind = RecordKind::from_tag(cursor.byte()?)?;
        let identity = cursor.digest()?;
        let target = cursor.digest()?;
        let previous = cursor.digest()?;
        let body_len = cursor.u32()? as usize;
        if body_len != length - MIN_FRAME_BYTES {
            return Err(PlannerStoreError::Corrupt);
        }
        let body = cursor.take(body_len)?.to_vec();
        let digest = cursor.digest()?;
        sequence = sequence.checked_add(1).ok_or(PlannerStoreError::Corrupt)?;
        let entry = make_entry(header.store_id, sequence, kind, identity, target, previous, body)?;
        if entry_sequence != sequence || previous != predecessor || entry.digest != digest {
            return Err(PlannerStoreError::Corrupt);
        }
        predecessor = digest;
        frame_ends.push((sequence, end));
        entries.push(entry);
        offset = end;
    }
    Ok(DecodedSegment {
        header,
        entries,
        frame_ends,
        complete_bytes: offset,
    })
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Cursor<'a> {
    fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], PlannerStoreError> {
        let end = self.offset.checked_add(length).ok_or(PlannerStoreError::Corrupt)?;
        let bytes = self.bytes.get(self.offset..end).ok_or(PlannerStoreError::Corrupt)?;
        self.offset = end;
        Ok(bytes)
    }

    fn byte(&mut self) -> Result<u8, PlannerStoreError> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<u32, PlannerStoreError> {
        Ok(u32::from_be_bytes(self.take(4)?.try_into().map_err(|_| PlannerStoreError::Corrupt)?))
    }

    fn u64(&mut self) -> Result<u64, PlannerStoreError> {
        Ok(u64::from_be_bytes(self.take(8)?.try_into().map_err(|_| PlannerStoreError::Corrupt)?))
    }

    fn digest(&mut self) -> Result<Digest32, PlannerStoreError> {
        Ok(Digest32::from_array(self.take(32)?.try_into().map_err(|_| PlannerStoreError::Corrupt)?))
    }
}
