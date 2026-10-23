//! File-backed checkpoint persistence for the shared state owner.
//!
//! `StateCheckpointOwnerV1` owns the state transition rules and signatures;
//! this module owns the bytes that survive a process restart.  The format is
//! deliberately private, bounded, length-prefixed and authenticated by the
//! receipts carried inside it.  A snapshot is never accepted merely because
//! its outer file hash matches: every state and tombstone receipt is verified
//! again when it is reopened.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Write;
use std::io::{self};
use std::path::Path;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::ProductionOwnerError;
use crate::StateCheckpointOwnerV1;
use crate::StateCheckpointSnapshotV1;
use crate::StateCommitReceiptV1;
use crate::StateTombstoneReceiptV1;

const MAGIC: &[u8] = b"HEPTA-STATE-SNAPSHOT-V2\0";
const MAX_ENTRIES: usize = 16_384;
const MAX_TOMBSTONES: usize = 16_384;
const MAX_BYTES: usize = 256 * 1024 * 1024;
const MAX_FIELD: usize = 1024 * 1024;

#[derive(Debug)]
pub enum DurableStateError {
    Io(io::Error),
    Corrupt,
    PredecessorMismatch {
        expected: Option<Digest32>,
        actual: Option<Digest32>,
    },
    TooLarge,
    Owner(ProductionOwnerError),
}

impl fmt::Display for DurableStateError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for DurableStateError {}

impl From<io::Error> for DurableStateError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<ProductionOwnerError> for DurableStateError {
    fn from(value: ProductionOwnerError) -> Self {
        Self::Owner(value)
    }
}

/// Durable file owner for state snapshots.  The owner never grants route or
/// effect authority; it only persists and reopens already signed state facts.
#[derive(Clone, Copy, Debug, Default)]
pub struct DurableStateOwnerV1;

impl DurableStateOwnerV1 {
    pub fn persist(
        path: impl AsRef<Path>,
        snapshot: &StateCheckpointSnapshotV1,
    ) -> Result<Digest32, DurableStateError> {
        let encoded = encode(snapshot)?;
        let path = path.as_ref();
        let parent = path.parent().ok_or(DurableStateError::Corrupt)?;
        fs::create_dir_all(parent)?;
        let snapshot_digest = Digest32::of_bytes(&encoded);
        if fs::symlink_metadata(path)
            .map(|metadata| metadata.file_type().is_symlink())
            .unwrap_or(false)
        {
            return Err(DurableStateError::Corrupt);
        }
        let temporary =
            path.with_extension(format!("tmp-{}-{}", std::process::id(), snapshot_digest));
        if fs::symlink_metadata(&temporary)
            .map(|metadata| metadata.file_type().is_symlink())
            .unwrap_or(false)
        {
            return Err(DurableStateError::Corrupt);
        }
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary)?;
        file.write_all(&encoded)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, path)?;
        if let Ok(directory) = File::open(parent) {
            let _ = directory.sync_all();
        }
        Ok(snapshot_digest)
    }

    /// Return the encoded snapshot digest currently stored at `path`.
    ///
    /// The digest is over the complete private snapshot bytes, including all
    /// receipts, state bytes and active heads.  Callers can pass this value to
    /// [`Self::persist_if_digest`] when they hold a single-writer lease.
    pub fn snapshot_digest(path: impl AsRef<Path>) -> Result<Option<Digest32>, DurableStateError> {
        let path = path.as_ref();
        let metadata = match fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(DurableStateError::Corrupt);
        }
        if metadata.len() > MAX_BYTES as u64 {
            return Err(DurableStateError::TooLarge);
        }
        let mut file = File::open(path)?;
        let mut encoded = Vec::with_capacity(metadata.len() as usize);
        file.read_to_end(&mut encoded)?;
        // Validate before exposing a predecessor digest.  A corrupt file must
        // never become an accepted predecessor for a later publication.
        decode(&encoded)?;
        Ok(Some(Digest32::of_bytes(&encoded)))
    }

    /// Persist a snapshot only when the file still has `expected_digest`.
    ///
    /// `None` means that the caller expects the destination not to exist.  The
    /// existing [`Self::persist`] API remains an unconditional replacement for
    /// compatibility; new lifecycle owners should use this fenced variant.
    /// The compare-and-persist operation assumes the caller owns the external
    /// single-writer lease for `path`; callers that need cross-process locking
    /// must hold that lease around this method.
    pub fn persist_if_digest(
        path: impl AsRef<Path>,
        snapshot: &StateCheckpointSnapshotV1,
        expected_digest: Option<Digest32>,
    ) -> Result<Digest32, DurableStateError> {
        let path = path.as_ref();
        let actual_digest = Self::snapshot_digest(path)?;
        if actual_digest != expected_digest {
            return Err(DurableStateError::PredecessorMismatch {
                expected: expected_digest,
                actual: actual_digest,
            });
        }
        Self::persist(path, snapshot)
    }

    pub fn load(path: impl AsRef<Path>) -> Result<StateCheckpointSnapshotV1, DurableStateError> {
        let metadata = fs::symlink_metadata(path.as_ref())?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(DurableStateError::Corrupt);
        }
        if metadata.len() > MAX_BYTES as u64 {
            return Err(DurableStateError::TooLarge);
        }
        let mut file = File::open(path)?;
        let mut encoded = Vec::with_capacity(metadata.len() as usize);
        file.read_to_end(&mut encoded)?;
        decode(&encoded)
    }

    pub fn reopen(
        path: impl AsRef<Path>,
        owner_id: StableId,
        signing_key: SigningKey,
    ) -> Result<StateCheckpointOwnerV1, DurableStateError> {
        Ok(StateCheckpointOwnerV1::from_snapshot(
            Self::load(path)?,
            owner_id,
            signing_key,
        )?)
    }
}

fn encode(snapshot: &StateCheckpointSnapshotV1) -> Result<Vec<u8>, DurableStateError> {
    if snapshot.entries.len() > MAX_ENTRIES
        || snapshot.tombstones.len() > MAX_TOMBSTONES
        || snapshot.active_heads.len() > MAX_ENTRIES
    {
        return Err(DurableStateError::TooLarge);
    }
    let mut bytes = MAGIC.to_vec();
    put_u64(&mut bytes, snapshot.entries.len() as u64);
    for (receipt, state) in &snapshot.entries {
        encode_commit(&mut bytes, receipt, state)?;
    }
    put_u64(&mut bytes, snapshot.tombstones.len() as u64);
    for receipt in &snapshot.tombstones {
        encode_tombstone(&mut bytes, receipt)?;
    }
    put_u64(&mut bytes, snapshot.active_heads.len() as u64);
    for (cell_id, head) in &snapshot.active_heads {
        put_id(&mut bytes, cell_id)?;
        bytes.extend_from_slice(head.as_array());
    }
    if bytes.len() > MAX_BYTES {
        return Err(DurableStateError::TooLarge);
    }
    Ok(bytes)
}

fn encode_commit(
    bytes: &mut Vec<u8>,
    receipt: &StateCommitReceiptV1,
    state: &[u8],
) -> Result<(), DurableStateError> {
    put_id(bytes, &receipt.operation_id)?;
    put_id(bytes, &receipt.cell_id)?;
    put_u64(bytes, receipt.generation.get());
    for digest in [
        receipt.state_schema_digest,
        receipt.predecessor_state_digest,
        receipt.state_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    put_u64(bytes, receipt.encoded_size_bytes);
    put_u64(bytes, receipt.sequence.get());
    put_id(bytes, &receipt.owner_id)?;
    put_optional_digest(bytes, receipt.host_evidence_digest);
    put_optional_digest(bytes, receipt.observer_evidence_digest);
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
    bytes.extend_from_slice(&receipt.signature);
    put_bytes(bytes, state)?;
    Ok(())
}

fn encode_tombstone(
    bytes: &mut Vec<u8>,
    receipt: &StateTombstoneReceiptV1,
) -> Result<(), DurableStateError> {
    put_id(bytes, &receipt.cell_id)?;
    put_u64(bytes, receipt.generation.get());
    bytes.extend_from_slice(receipt.reason_digest.as_array());
    put_id(bytes, &receipt.owner_id)?;
    put_optional_digest(bytes, receipt.host_evidence_digest);
    put_optional_digest(bytes, receipt.observer_evidence_digest);
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
    bytes.extend_from_slice(&receipt.signature);
    Ok(())
}

fn decode(encoded: &[u8]) -> Result<StateCheckpointSnapshotV1, DurableStateError> {
    let mut cursor = Cursor {
        bytes: encoded,
        offset: 0,
    };
    if cursor.take(MAGIC.len())? != MAGIC {
        return Err(DurableStateError::Corrupt);
    }
    let entry_count = cursor.count(MAX_ENTRIES)?;
    let mut entries = Vec::with_capacity(entry_count);
    for _ in 0..entry_count {
        entries.push(decode_commit(&mut cursor)?);
    }
    let tombstone_count = cursor.count(MAX_TOMBSTONES)?;
    let mut tombstones = Vec::with_capacity(tombstone_count);
    for _ in 0..tombstone_count {
        tombstones.push(decode_tombstone(&mut cursor)?);
    }
    let active_count = cursor.count(MAX_ENTRIES)?;
    let mut active_heads = Vec::with_capacity(active_count);
    for _ in 0..active_count {
        let cell_id = cursor.id()?;
        let head = cursor.digest()?;
        active_heads.push((cell_id, head));
    }
    if cursor.offset != encoded.len() {
        return Err(DurableStateError::Corrupt);
    }
    Ok(StateCheckpointSnapshotV1 {
        entries,
        tombstones,
        active_heads,
    })
}

fn decode_commit(
    cursor: &mut Cursor<'_>,
) -> Result<(StateCommitReceiptV1, Vec<u8>), DurableStateError> {
    let operation_id = cursor.id()?;
    let cell_id = cursor.id()?;
    let generation = Generation::new(cursor.u64()?).map_err(|_| DurableStateError::Corrupt)?;
    let state_schema_digest = cursor.digest()?;
    let predecessor_state_digest = cursor.digest()?;
    let state_digest = cursor.digest()?;
    let encoded_size_bytes = cursor.u64()?;
    let sequence = LogicalSequence::new(cursor.u64()?).map_err(|_| DurableStateError::Corrupt)?;
    let owner_id = cursor.id()?;
    let host_evidence_digest = cursor.optional_digest()?;
    let observer_evidence_digest = cursor.optional_digest()?;
    let receipt_digest = cursor.digest()?;
    let signature = cursor.signature()?;
    let state = cursor.bytes()?;
    Ok((
        StateCommitReceiptV1 {
            operation_id,
            cell_id,
            generation,
            state_schema_digest,
            predecessor_state_digest,
            state_digest,
            encoded_size_bytes,
            sequence,
            owner_id,
            host_evidence_digest,
            observer_evidence_digest,
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
            receipt_digest,
            signature,
        },
        state,
    ))
}

fn decode_tombstone(cursor: &mut Cursor<'_>) -> Result<StateTombstoneReceiptV1, DurableStateError> {
    let cell_id = cursor.id()?;
    let generation = Generation::new(cursor.u64()?).map_err(|_| DurableStateError::Corrupt)?;
    let reason_digest = cursor.digest()?;
    let owner_id = cursor.id()?;
    let host_evidence_digest = cursor.optional_digest()?;
    let observer_evidence_digest = cursor.optional_digest()?;
    let receipt_digest = cursor.digest()?;
    let signature = cursor.signature()?;
    Ok(StateTombstoneReceiptV1 {
        cell_id,
        generation,
        reason_digest,
        owner_id,
        host_evidence_digest,
        observer_evidence_digest,
        authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        receipt_digest,
        signature,
    })
}

fn put_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), DurableStateError> {
    put_bytes(bytes, id.as_str().as_bytes())
}

fn put_bytes(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), DurableStateError> {
    if value.len() > MAX_FIELD {
        return Err(DurableStateError::TooLarge);
    }
    put_u64(bytes, value.len() as u64);
    bytes.extend_from_slice(value);
    Ok(())
}

fn put_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    bytes.push(u8::from(value.is_some()));
    if let Some(value) = value {
        bytes.extend_from_slice(value.as_array());
    }
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl Cursor<'_> {
    fn take(&mut self, count: usize) -> Result<&[u8], DurableStateError> {
        let end = self
            .offset
            .checked_add(count)
            .ok_or(DurableStateError::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(DurableStateError::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn u64(&mut self) -> Result<u64, DurableStateError> {
        let mut value = [0; 8];
        value.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(value))
    }
    fn count(&mut self, maximum: usize) -> Result<usize, DurableStateError> {
        let value = usize::try_from(self.u64()?).map_err(|_| DurableStateError::TooLarge)?;
        if value > maximum {
            return Err(DurableStateError::TooLarge);
        }
        Ok(value)
    }
    fn bytes(&mut self) -> Result<Vec<u8>, DurableStateError> {
        let length = self.count(MAX_FIELD)?;
        Ok(self.take(length)?.to_vec())
    }
    fn id(&mut self) -> Result<StableId, DurableStateError> {
        let raw = self.bytes()?;
        let value = String::from_utf8(raw).map_err(|_| DurableStateError::Corrupt)?;
        StableId::new(value).map_err(|_| DurableStateError::Corrupt)
    }
    fn digest(&mut self) -> Result<Digest32, DurableStateError> {
        let mut value = [0; 32];
        value.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(value))
    }
    fn optional_digest(&mut self) -> Result<Option<Digest32>, DurableStateError> {
        match self.take(1)?[0] {
            0 => Ok(None),
            1 => Ok(Some(self.digest()?)),
            _ => Err(DurableStateError::Corrupt),
        }
    }
    fn signature(&mut self) -> Result<[u8; 64], DurableStateError> {
        let mut value = [0; 64];
        value.copy_from_slice(self.take(64)?);
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn snapshot_round_trip_reopens_signed_bytes_and_active_head() {
        let key = SigningKey::from_bytes(&[31; 32]);
        let owner_id = StableId::new("durable.state.owner").expect("id");
        let cell_id = StableId::new("cell.durable").expect("id");
        let mut owner = StateCheckpointOwnerV1::new(owner_id.clone(), key.clone()).expect("owner");
        let receipt = owner
            .commit(
                StableId::new("operation.durable.1").expect("id"),
                cell_id.clone(),
                Generation::new(1).expect("generation"),
                Digest32::of_bytes(b"schema"),
                Digest32::ZERO,
                b"real-state".to_vec(),
                None,
                None,
            )
            .expect("commit");
        let directory =
            std::env::temp_dir().join(format!("hepta-durable-state-{}", std::process::id()));
        std::fs::create_dir_all(&directory).expect("directory");
        let path = directory.join("state.snapshot");
        let digest = DurableStateOwnerV1::persist(&path, &owner.snapshot()).expect("persist");
        assert!(!digest.is_zero());
        let reopened = DurableStateOwnerV1::reopen(&path, owner_id, key).expect("reopen");
        assert_eq!(
            reopened.reload(&cell_id, &receipt).expect("reload"),
            b"real-state"
        );
        std::fs::remove_dir_all(directory).expect("cleanup");
    }

    #[test]
    fn tampering_with_state_bytes_or_tombstone_receipt_is_rejected() {
        let key = SigningKey::from_bytes(&[32; 32]);
        let owner_id = StableId::new("durable.state.owner.tamper").expect("id");
        let cell_id = StableId::new("cell.durable.tamper").expect("id");
        let mut owner = StateCheckpointOwnerV1::new(owner_id.clone(), key.clone()).expect("owner");
        owner
            .commit(
                StableId::new("operation.durable.tamper").expect("id"),
                cell_id.clone(),
                Generation::new(1).expect("generation"),
                Digest32::of_bytes(b"schema"),
                Digest32::ZERO,
                b"state".to_vec(),
                None,
                None,
            )
            .expect("commit");
        owner
            .tombstone(
                cell_id,
                Generation::new(2).expect("generation"),
                Digest32::of_bytes(b"retire"),
            )
            .expect("tombstone");
        let directory =
            std::env::temp_dir().join(format!("hepta-durable-state-tamper-{}", std::process::id()));
        std::fs::create_dir_all(&directory).expect("directory");
        let path = directory.join("state.snapshot");
        DurableStateOwnerV1::persist(&path, &owner.snapshot()).expect("persist");
        let mut bytes = std::fs::read(&path).expect("read");
        let index = bytes.len().saturating_sub(80);
        bytes[index] ^= 1;
        std::fs::write(&path, bytes).expect("tamper");
        assert!(DurableStateOwnerV1::reopen(&path, owner_id, key).is_err());
        std::fs::remove_dir_all(directory).expect("cleanup");
    }

    #[test]
    fn fenced_snapshot_persist_rejects_stale_predecessor() {
        let key = SigningKey::from_bytes(&[34; 32]);
        let owner_id = StableId::new("durable.state.owner.fence").expect("id");
        let cell_id = StableId::new("cell.durable.fence").expect("id");
        let mut owner = StateCheckpointOwnerV1::new(owner_id, key).expect("owner");
        owner
            .commit(
                StableId::new("operation.durable.fence.1").expect("id"),
                cell_id.clone(),
                Generation::new(1).expect("generation"),
                Digest32::of_bytes(b"schema"),
                Digest32::ZERO,
                b"first".to_vec(),
                None,
                None,
            )
            .expect("commit");
        let directory =
            std::env::temp_dir().join(format!("hepta-durable-state-fence-{}", std::process::id()));
        std::fs::create_dir_all(&directory).expect("directory");
        let path = directory.join("state.snapshot");
        let first_digest = DurableStateOwnerV1::persist_if_digest(&path, &owner.snapshot(), None)
            .expect("initial fenced persist");
        assert_eq!(
            DurableStateOwnerV1::snapshot_digest(&path).expect("digest"),
            Some(first_digest)
        );

        let mut successor = owner.clone();
        let first = successor
            .snapshot()
            .entries
            .first()
            .map(|(receipt, _)| receipt.clone())
            .expect("first receipt");
        successor
            .commit(
                StableId::new("operation.durable.fence.2").expect("id"),
                cell_id,
                Generation::new(1).expect("generation"),
                Digest32::of_bytes(b"schema"),
                first.state_digest,
                b"second".to_vec(),
                None,
                None,
            )
            .expect("successor");
        let second_digest = DurableStateOwnerV1::persist_if_digest(
            &path,
            &successor.snapshot(),
            Some(first_digest),
        )
        .expect("successor fenced persist");
        assert_ne!(first_digest, second_digest);

        let stale =
            DurableStateOwnerV1::persist_if_digest(&path, &owner.snapshot(), Some(first_digest));
        assert!(matches!(
            stale,
            Err(DurableStateError::PredecessorMismatch {
                expected: Some(expected),
                actual: Some(actual),
            }) if expected == first_digest && actual == second_digest
        ));
        std::fs::remove_dir_all(directory).expect("cleanup");
    }

    #[test]
    fn snapshot_without_active_head_is_rejected_on_reopen() {
        let key = SigningKey::from_bytes(&[33; 32]);
        let owner_id = StableId::new("durable.state.owner.active-head").expect("id");
        let cell_id = StableId::new("cell.durable.active-head").expect("id");
        let mut owner = StateCheckpointOwnerV1::new(owner_id.clone(), key.clone()).expect("owner");
        owner
            .commit(
                StableId::new("operation.durable.active-head").expect("id"),
                cell_id,
                Generation::new(1).expect("generation"),
                Digest32::of_bytes(b"schema"),
                Digest32::ZERO,
                b"state".to_vec(),
                None,
                None,
            )
            .expect("commit");
        let mut snapshot = owner.snapshot();
        snapshot.active_heads.clear();
        let directory = std::env::temp_dir().join(format!(
            "hepta-durable-state-active-head-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&directory).expect("directory");
        let path = directory.join("state.snapshot");
        DurableStateOwnerV1::persist(&path, &snapshot).expect("persist");
        assert!(DurableStateOwnerV1::reopen(&path, owner_id, key).is_err());
        std::fs::remove_dir_all(directory).expect("cleanup");
    }
}
