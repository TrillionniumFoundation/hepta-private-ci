//! Durable terminal receipts for control.engineering plasticity coordination.
//!
//! The journal is append-only, checksum chained, single-writer locked and scoped
//! to one frozen source/objective/grammar context. It stores only terminal proposal
//! receipts and never owns a plasticity proposal registry or activation authority.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io::Cursor;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;

use codex_hepta_plasticity::AppendDisposition;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HPTITR01";
const VERSION: u16 = 1;
const HEADER_SIZE: usize = 8 + 2 + 32 + 4;
const MAX_RECORDS: usize = 4_096;
const MAX_FRAME_BYTES: usize = 4 * 1024;
const MAX_FILE_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IterationPlasticityKindV1 {
    Parameter,
    Topology,
}

impl IterationPlasticityKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Parameter => 0,
            Self::Topology => 1,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, IterationPlasticityJournalErrorV1> {
        match tag {
            0 => Ok(Self::Parameter),
            1 => Ok(Self::Topology),
            _ => Err(IterationPlasticityJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IterationPlasticityTerminalV1 {
    UpdateCandidates,
    NoAdmissibleUpdate,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
    TopologyProposal,
}

impl IterationPlasticityTerminalV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::UpdateCandidates => 0,
            Self::NoAdmissibleUpdate => 1,
            Self::ZeroEligibleSignals => 2,
            Self::PolicyDisabledUpdates => 3,
            Self::TopologyProposal => 4,
        }
    }

    fn from_tag(tag: u8) -> Result<Self, IterationPlasticityJournalErrorV1> {
        match tag {
            0 => Ok(Self::UpdateCandidates),
            1 => Ok(Self::NoAdmissibleUpdate),
            2 => Ok(Self::ZeroEligibleSignals),
            3 => Ok(Self::PolicyDisabledUpdates),
            4 => Ok(Self::TopologyProposal),
            _ => Err(IterationPlasticityJournalErrorV1::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationPlasticityTerminalReceiptV1 {
    pub sequence: u64,
    pub envelope_id: StableId,
    pub envelope_digest: Digest32,
    pub candidate_generation: Generation,
    pub proposal_id: StableId,
    pub product_composition_digest: Digest32,
    pub kind: IterationPlasticityKindV1,
    pub terminal: IterationPlasticityTerminalV1,
    pub record_digest: Digest32,
    pub predecessor_frame_digest: Digest32,
    pub frame_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IterationPlasticityJournalAppendV1 {
    pub receipt: IterationPlasticityTerminalReceiptV1,
    pub disposition: AppendDisposition,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct IterationPlasticityJournalAnchorV1 {
    pub sequence: u64,
    pub frame_digest: Digest32,
}

#[derive(Debug, Eq, PartialEq)]
pub enum IterationPlasticityJournalErrorV1 {
    Busy,
    NotRegular,
    InvalidScope,
    InvalidLimit,
    ContextMismatch,
    Corrupt,
    Capacity,
    Conflict,
    Poisoned,
    Indeterminate,
    Io(std::io::ErrorKind),
}

impl fmt::Display for IterationPlasticityJournalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for IterationPlasticityJournalErrorV1 {}
impl From<std::io::Error> for IterationPlasticityJournalErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

struct LockedFile(File);
impl LockedFile {
    fn acquire(file: File) -> Result<Self, IterationPlasticityJournalErrorV1> {
        if !file.metadata()?.is_file() {
            return Err(IterationPlasticityJournalErrorV1::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(IterationPlasticityJournalErrorV1::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
impl Deref for LockedFile {
    type Target = File;
    fn deref(&self) -> &File {
        &self.0
    }
}
impl DerefMut for LockedFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}
impl Drop for LockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct IterationPlasticityTerminalJournalV1 {
    file: LockedFile,
    scope_digest: Digest32,
    maximum_records: usize,
    records: Vec<IterationPlasticityTerminalReceiptV1>,
    poisoned: bool,
}

impl IterationPlasticityTerminalJournalV1 {
    pub fn open(
        file: File,
        scope_digest: Digest32,
        maximum_records: usize,
    ) -> Result<Self, IterationPlasticityJournalErrorV1> {
        if scope_digest.is_zero() {
            return Err(IterationPlasticityJournalErrorV1::InvalidScope);
        }
        if !(1..=MAX_RECORDS).contains(&maximum_records) {
            return Err(IterationPlasticityJournalErrorV1::InvalidLimit);
        }
        let mut file = LockedFile::acquire(file)?;
        let length = file.metadata()?.len();
        if length > MAX_FILE_BYTES {
            return Err(IterationPlasticityJournalErrorV1::Capacity);
        }
        let header = encode_header(scope_digest, maximum_records)?;
        if length == 0 {
            file.write_all(&header)
                .and_then(|_| file.sync_all())
                .map_err(|_| IterationPlasticityJournalErrorV1::Indeterminate)?;
        } else {
            if length < HEADER_SIZE as u64 {
                return Err(IterationPlasticityJournalErrorV1::Corrupt);
            }
            let mut actual = vec![0_u8; HEADER_SIZE];
            file.seek(SeekFrom::Start(0))?;
            file.read_exact(&mut actual)?;
            if actual != header {
                return Err(IterationPlasticityJournalErrorV1::ContextMismatch);
            }
        }

        let mut journal = Self {
            file,
            scope_digest,
            maximum_records,
            records: Vec::new(),
            poisoned: false,
        };
        let physical_length = journal.file.metadata()?.len();
        let mut offset = HEADER_SIZE as u64;
        let mut incomplete_tail = false;
        while offset < physical_length {
            if physical_length - offset < 4 {
                incomplete_tail = true;
                break;
            }
            journal.file.seek(SeekFrom::Start(offset))?;
            let frame_length = read_u32(&mut journal.file)? as usize;
            if frame_length == 0 || frame_length > MAX_FRAME_BYTES {
                return Err(IterationPlasticityJournalErrorV1::Corrupt);
            }
            let total = 4_u64
                .checked_add(frame_length as u64)
                .ok_or(IterationPlasticityJournalErrorV1::Capacity)?;
            if physical_length - offset < total {
                incomplete_tail = true;
                break;
            }
            if journal.records.len() >= maximum_records {
                return Err(IterationPlasticityJournalErrorV1::Capacity);
            }
            let mut frame = vec![0_u8; frame_length];
            journal.file.read_exact(&mut frame)?;
            let expected_sequence = journal.records.len() as u64 + 1;
            let expected_predecessor = journal
                .records
                .last()
                .map(|receipt| receipt.frame_digest)
                .unwrap_or(Digest32::ZERO);
            let receipt = decode_frame(&frame, expected_sequence, expected_predecessor)?;
            if journal
                .find_key(
                    receipt.envelope_digest,
                    receipt.candidate_generation,
                    &receipt.proposal_id,
                )
                .is_some()
            {
                return Err(IterationPlasticityJournalErrorV1::Corrupt);
            }
            journal.records.push(receipt);
            offset = offset
                .checked_add(total)
                .ok_or(IterationPlasticityJournalErrorV1::Capacity)?;
        }
        if incomplete_tail {
            journal
                .file
                .set_len(offset)
                .and_then(|_| journal.file.sync_all())
                .map_err(|_| IterationPlasticityJournalErrorV1::Indeterminate)?;
        }
        Ok(journal)
    }

    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    pub fn current_anchor(&self) -> Option<IterationPlasticityJournalAnchorV1> {
        self.records
            .last()
            .map(|receipt| IterationPlasticityJournalAnchorV1 {
                sequence: receipt.sequence,
                frame_digest: receipt.frame_digest,
            })
    }

    pub fn get(
        &self,
        envelope_digest: Digest32,
        generation: Generation,
        proposal_id: &StableId,
    ) -> Option<&IterationPlasticityTerminalReceiptV1> {
        self.find_key(envelope_digest, generation, proposal_id)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn append(
        &mut self,
        envelope_id: StableId,
        envelope_digest: Digest32,
        candidate_generation: Generation,
        proposal_id: StableId,
        product_composition_digest: Digest32,
        kind: IterationPlasticityKindV1,
        terminal: IterationPlasticityTerminalV1,
    ) -> Result<IterationPlasticityJournalAppendV1, IterationPlasticityJournalErrorV1> {
        if self.poisoned {
            return Err(IterationPlasticityJournalErrorV1::Poisoned);
        }
        if envelope_digest.is_zero() || product_composition_digest.is_zero() {
            return Err(IterationPlasticityJournalErrorV1::Corrupt);
        }
        if let Some(existing) =
            self.find_key(envelope_digest, candidate_generation, &proposal_id)
        {
            if existing.envelope_id == envelope_id
                && existing.product_composition_digest == product_composition_digest
                && existing.kind == kind
                && existing.terminal == terminal
            {
                return Ok(IterationPlasticityJournalAppendV1 {
                    receipt: existing.clone(),
                    disposition: AppendDisposition::Unchanged,
                });
            }
            return Err(IterationPlasticityJournalErrorV1::Conflict);
        }
        if self.records.len() >= self.maximum_records {
            return Err(IterationPlasticityJournalErrorV1::Capacity);
        }
        let sequence = self.records.len() as u64 + 1;
        let predecessor_frame_digest = self
            .records
            .last()
            .map(|receipt| receipt.frame_digest)
            .unwrap_or(Digest32::ZERO);
        let mut receipt = IterationPlasticityTerminalReceiptV1 {
            sequence,
            envelope_id,
            envelope_digest,
            candidate_generation,
            proposal_id,
            product_composition_digest,
            kind,
            terminal,
            record_digest: Digest32::ZERO,
            predecessor_frame_digest,
            frame_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.record_digest = digest_record(&receipt)?;
        let frame = encode_frame(&receipt)?;
        receipt.frame_digest = frame_digest(&frame[..frame.len() - 32]);
        let encoded = encode_frame(&receipt)?;
        let length = u32::try_from(encoded.len())
            .map_err(|_| IterationPlasticityJournalErrorV1::Capacity)?;
        self.file.seek(SeekFrom::End(0))?;
        if self
            .file
            .write_all(&length.to_be_bytes())
            .and_then(|_| self.file.write_all(&encoded))
            .and_then(|_| self.file.sync_all())
            .is_err()
        {
            self.poisoned = true;
            return Err(IterationPlasticityJournalErrorV1::Indeterminate);
        }
        self.records.push(receipt.clone());
        Ok(IterationPlasticityJournalAppendV1 {
            receipt,
            disposition: AppendDisposition::Inserted,
        })
    }

    fn find_key(
        &self,
        envelope_digest: Digest32,
        generation: Generation,
        proposal_id: &StableId,
    ) -> Option<&IterationPlasticityTerminalReceiptV1> {
        self.records.iter().find(|receipt| {
            receipt.envelope_digest == envelope_digest
                && receipt.candidate_generation == generation
                && &receipt.proposal_id == proposal_id
        })
    }
}

fn encode_header(
    scope_digest: Digest32,
    maximum_records: usize,
) -> Result<Vec<u8>, IterationPlasticityJournalErrorV1> {
    let maximum_records = u32::try_from(maximum_records)
        .map_err(|_| IterationPlasticityJournalErrorV1::InvalidLimit)?;
    let mut bytes = Vec::with_capacity(HEADER_SIZE);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&VERSION.to_be_bytes());
    bytes.extend_from_slice(scope_digest.as_array());
    bytes.extend_from_slice(&maximum_records.to_be_bytes());
    Ok(bytes)
}

fn encode_frame(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<Vec<u8>, IterationPlasticityJournalErrorV1> {
    let payload = encode_payload(receipt)?;
    let mut frame = Vec::new();
    frame.extend_from_slice(&receipt.sequence.to_be_bytes());
    frame.extend_from_slice(receipt.predecessor_frame_digest.as_array());
    let payload_length = u32::try_from(payload.len())
        .map_err(|_| IterationPlasticityJournalErrorV1::Capacity)?;
    frame.extend_from_slice(&payload_length.to_be_bytes());
    frame.extend_from_slice(&payload);
    frame.extend_from_slice(receipt.record_digest.as_array());
    let digest = frame_digest(&frame);
    frame.extend_from_slice(digest.as_array());
    Ok(frame)
}

fn decode_frame(
    frame: &[u8],
    expected_sequence: u64,
    expected_predecessor: Digest32,
) -> Result<IterationPlasticityTerminalReceiptV1, IterationPlasticityJournalErrorV1> {
    if frame.len() < 8 + 32 + 4 + 32 + 32 {
        return Err(IterationPlasticityJournalErrorV1::Corrupt);
    }
    let (body, digest_bytes) = frame.split_at(frame.len() - 32);
    if frame_digest(body) != digest_from_slice(digest_bytes)? {
        return Err(IterationPlasticityJournalErrorV1::Corrupt);
    }
    let mut cursor = Cursor::new(body);
    let sequence = read_u64(&mut cursor)?;
    let predecessor_frame_digest = read_digest(&mut cursor)?;
    if sequence != expected_sequence || predecessor_frame_digest != expected_predecessor {
        return Err(IterationPlasticityJournalErrorV1::Corrupt);
    }
    let payload_length = read_u32(&mut cursor)? as usize;
    let remaining = body
        .len()
        .checked_sub(cursor.position() as usize)
        .ok_or(IterationPlasticityJournalErrorV1::Corrupt)?;
    if remaining != payload_length + 32 {
        return Err(IterationPlasticityJournalErrorV1::Corrupt);
    }
    let mut payload = vec![0_u8; payload_length];
    cursor.read_exact(&mut payload)?;
    let record_digest = read_digest(&mut cursor)?;
    let mut receipt = decode_payload(&payload)?;
    receipt.sequence = sequence;
    receipt.predecessor_frame_digest = predecessor_frame_digest;
    receipt.record_digest = record_digest;
    receipt.frame_digest = digest_from_slice(digest_bytes)?;
    if receipt.authority.grants_any() || digest_record(&receipt)? != record_digest {
        return Err(IterationPlasticityJournalErrorV1::Corrupt);
    }
    Ok(receipt)
}

fn encode_payload(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<Vec<u8>, IterationPlasticityJournalErrorV1> {
    let mut bytes = Vec::new();
    bytes.push(receipt.kind.tag());
    bytes.push(receipt.terminal.tag());
    push_id(&mut bytes, &receipt.envelope_id)?;
    bytes.extend_from_slice(receipt.envelope_digest.as_array());
    bytes.extend_from_slice(&receipt.candidate_generation.get().to_be_bytes());
    push_id(&mut bytes, &receipt.proposal_id)?;
    bytes.extend_from_slice(receipt.product_composition_digest.as_array());
    Ok(bytes)
}

fn decode_payload(
    payload: &[u8],
) -> Result<IterationPlasticityTerminalReceiptV1, IterationPlasticityJournalErrorV1> {
    let mut cursor = Cursor::new(payload);
    let kind = IterationPlasticityKindV1::from_tag(read_u8(&mut cursor)?)?;
    let terminal = IterationPlasticityTerminalV1::from_tag(read_u8(&mut cursor)?)?;
    let envelope_id = read_id(&mut cursor)?;
    let envelope_digest = read_digest(&mut cursor)?;
    let candidate_generation = Generation::new(read_u64(&mut cursor)?)
        .map_err(|_| IterationPlasticityJournalErrorV1::Corrupt)?;
    let proposal_id = read_id(&mut cursor)?;
    let product_composition_digest = read_digest(&mut cursor)?;
    if cursor.position() as usize != payload.len()
        || envelope_digest.is_zero()
        || product_composition_digest.is_zero()
    {
        return Err(IterationPlasticityJournalErrorV1::Corrupt);
    }
    Ok(IterationPlasticityTerminalReceiptV1 {
        sequence: 0,
        envelope_id,
        envelope_digest,
        candidate_generation,
        proposal_id,
        product_composition_digest,
        kind,
        terminal,
        record_digest: Digest32::ZERO,
        predecessor_frame_digest: Digest32::ZERO,
        frame_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn digest_record(
    receipt: &IterationPlasticityTerminalReceiptV1,
) -> Result<Digest32, IterationPlasticityJournalErrorV1> {
    let mut bytes = b"hepta.agentd.iteration-plasticity-terminal.v1\0".to_vec();
    bytes.extend_from_slice(&encode_payload(receipt)?);
    Ok(Digest32::of_bytes(&bytes))
}

fn frame_digest(bytes: &[u8]) -> Digest32 {
    let mut material = b"hepta.agentd.iteration-plasticity-frame.v1\0".to_vec();
    material.extend_from_slice(bytes);
    Digest32::of_bytes(&material)
}

fn push_id(
    bytes: &mut Vec<u8>,
    id: &StableId,
) -> Result<(), IterationPlasticityJournalErrorV1> {
    let raw = id.as_str().as_bytes();
    let length =
        u32::try_from(raw.len()).map_err(|_| IterationPlasticityJournalErrorV1::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn read_id(
    cursor: &mut Cursor<&[u8]>,
) -> Result<StableId, IterationPlasticityJournalErrorV1> {
    let length = read_u32(cursor)? as usize;
    if length == 0 || length > MAX_FRAME_BYTES {
        return Err(IterationPlasticityJournalErrorV1::Corrupt);
    }
    let mut raw = vec![0_u8; length];
    cursor.read_exact(&mut raw)?;
    let value =
        String::from_utf8(raw).map_err(|_| IterationPlasticityJournalErrorV1::Corrupt)?;
    StableId::new(value).map_err(|_| IterationPlasticityJournalErrorV1::Corrupt)
}

fn read_u8(reader: &mut impl Read) -> Result<u8, IterationPlasticityJournalErrorV1> {
    let mut bytes = [0_u8; 1];
    reader.read_exact(&mut bytes)?;
    Ok(bytes[0])
}
fn read_u32(reader: &mut impl Read) -> Result<u32, IterationPlasticityJournalErrorV1> {
    let mut bytes = [0_u8; 4];
    reader.read_exact(&mut bytes)?;
    Ok(u32::from_be_bytes(bytes))
}
fn read_u64(reader: &mut impl Read) -> Result<u64, IterationPlasticityJournalErrorV1> {
    let mut bytes = [0_u8; 8];
    reader.read_exact(&mut bytes)?;
    Ok(u64::from_be_bytes(bytes))
}
fn read_digest(reader: &mut impl Read) -> Result<Digest32, IterationPlasticityJournalErrorV1> {
    let mut bytes = [0_u8; 32];
    reader.read_exact(&mut bytes)?;
    Ok(Digest32::from_array(bytes))
}
fn digest_from_slice(bytes: &[u8]) -> Result<Digest32, IterationPlasticityJournalErrorV1> {
    let value: [u8; 32] = bytes
        .try_into()
        .map_err(|_| IterationPlasticityJournalErrorV1::Corrupt)?;
    Ok(Digest32::from_array(value))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;
    use std::path::PathBuf;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    struct TestFile(PathBuf);
    impl TestFile {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos();
            Self(std::env::temp_dir().join(format!(
                "hepta-iteration-plasticity-{}-{nonce}.journal",
                std::process::id()
            )))
        }
        fn create(&self) -> File {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(&self.0)
                .expect("create")
        }
        fn open(&self) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&self.0)
                .expect("open")
        }
    }
    impl Drop for TestFile {
        fn drop(&mut self) {
            let _ = std::fs::remove_file(&self.0);
        }
    }
    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }
    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    #[test]
    fn terminal_journal_reopens_and_replays_idempotently() {
        let file = TestFile::new();
        let scope = digest(b"scope");
        let first = {
            let mut journal =
                IterationPlasticityTerminalJournalV1::open(file.create(), scope, 8)
                    .expect("open");
            journal
                .append(
                    id("envelope:1"),
                    digest(b"envelope"),
                    generation(2),
                    id("proposal:1"),
                    digest(b"product"),
                    IterationPlasticityKindV1::Parameter,
                    IterationPlasticityTerminalV1::UpdateCandidates,
                )
                .expect("append")
        };
        assert_eq!(first.disposition, AppendDisposition::Inserted);
        let mut journal =
            IterationPlasticityTerminalJournalV1::open(file.open(), scope, 8).expect("reopen");
        let replay = journal
            .append(
                id("envelope:1"),
                digest(b"envelope"),
                generation(2),
                id("proposal:1"),
                digest(b"product"),
                IterationPlasticityKindV1::Parameter,
                IterationPlasticityTerminalV1::UpdateCandidates,
            )
            .expect("replay");
        assert_eq!(replay.disposition, AppendDisposition::Unchanged);
        assert_eq!(replay.receipt.frame_digest, first.receipt.frame_digest);
    }
}
