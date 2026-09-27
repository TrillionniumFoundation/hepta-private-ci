//! Bounded planner-owned storage with an independently signed commit frontier.
//!
//! The anchor is a separately configured owner port, not a signing key owned by
//! this store. A successful write requires file durability AND an authenticated
//! compare-and-swap acknowledgement. Reopen discards only the unacknowledged
//! suffix; an incomplete acknowledged prefix or an older backup fails closed.
//! Full versioned envelope bodies are retained, not just their digests. This
//! storage primitive does not authenticate the domain meaning of arbitrary
//! bytes: a domain consumer must validate its canonical envelope before use.

use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

const MAGIC: &[u8; 8] = b"HCPSTR01";
const HEADER_BYTES: usize = 80;
pub const MAX_PLANNER_STORE_RECORDS: usize = 4096;
pub const MAX_PLANNER_ENVELOPE_BYTES: usize = 1024 * 1024;
pub const MAX_PLANNER_STORE_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlannerCheckpointV1 {
    pub store_id: Digest32,
    pub generation: u64,
    pub sequence: u64,
    pub root: Digest32,
}

impl PlannerCheckpointV1 {
    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.control.planner-checkpoint.v1\0".to_vec();
        bytes.extend_from_slice(self.store_id.as_array());
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        bytes.extend_from_slice(self.root.as_array());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug)]
pub struct SignedPlannerCheckpointV1 {
    pub checkpoint: PlannerCheckpointV1,
    pub signature: [u8; 64],
}

/// Trusted, authenticated CURRENT-state port of an independent evidence owner.
/// Implementations must linearize compare_exchange, reject stale expectations,
/// and return the current frontier (never an arbitrary historical signature).
/// An uncertain transport outcome is an error, not a successful commit.
pub trait PlannerAnchorV1: Send + Sync {
    fn current(
        &self,
        store_id: Digest32,
    ) -> Result<Option<SignedPlannerCheckpointV1>, PlannerStoreError>;

    fn compare_exchange(
        &self,
        expected: Option<PlannerCheckpointV1>,
        next: PlannerCheckpointV1,
    ) -> Result<SignedPlannerCheckpointV1, PlannerStoreError>;
}

#[derive(Debug)]
pub enum PlannerStoreError {
    Io(io::Error),
    Locked,
    Invalid(&'static str),
    LimitExceeded,
    IdentityConflict,
    AnchorUnavailable,
    AnchorMismatch,
    InvalidSignature,
    RollbackOrTruncation,
    Poisoned,
}

impl std::fmt::Display for PlannerStoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for PlannerStoreError {}

impl From<io::Error> for PlannerStoreError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlannerStoredReceiptV1 {
    pub identity: Digest32,
    pub payload_digest: Digest32,
    pub sequence: u64,
    pub checkpoint: PlannerCheckpointV1,
    pub idempotent: bool,
}

#[derive(Clone)]
pub struct PlannerBackupV1 {
    pub checkpoint: SignedPlannerCheckpointV1,
    pub bytes: Vec<u8>,
}

struct Record {
    identity: Digest32,
    payload: Vec<u8>,
}

/// Single-host, exclusive-writer profile. The owner supplies a private,
/// non-symlink directory; shared/network filesystems require separate admission.
/// No process-global singleton or mutable hidden configuration is used.
pub struct PlannerStoreV1 {
    directory: PathBuf,
    _lock: File,
    file: File,
    anchor: Arc<dyn PlannerAnchorV1>,
    verifying_key: VerifyingKey,
    checkpoint: SignedPlannerCheckpointV1,
    records: Vec<Record>,
    identities: BTreeMap<Digest32, usize>,
    committed_bytes: u64,
    poisoned: bool,
}

impl PlannerStoreV1 {
    pub fn create(
        directory: &Path,
        store_id: Digest32,
        verifying_key: VerifyingKey,
        anchor: Arc<dyn PlannerAnchorV1>,
    ) -> Result<Self, PlannerStoreError> {
        if store_id.is_zero() {
            return Err(PlannerStoreError::Invalid("store identity"));
        }
        let lock = lock_directory(directory)?;
        if anchor.current(store_id)?.is_some() {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        let header = header(store_id, 1, Digest32::ZERO);
        let next = PlannerCheckpointV1 {
            store_id,
            generation: 1,
            sequence: 0,
            root: Digest32::of_bytes(&header),
        };
        let path = generation_path(directory, 1);
        if path.exists() {
            // An interrupted create may be retried, but an unrelated file may
            // not be silently converted into this store.
            let mut file = open_regular(&path)?;
            let mut previous = [0_u8; HEADER_BYTES];
            file.read_exact(&mut previous)?;
            if previous.as_slice() != header.as_slice() {
                return Err(PlannerStoreError::Invalid("interrupted store identity"));
            }
        }
        atomic_replace(directory, &path, &header)?;
        let signed = anchor.compare_exchange(None, next)?;
        verify_checkpoint(&verifying_key, &signed, next)?;
        drop(lock);
        Self::open(directory, store_id, verifying_key, anchor)
    }

    pub fn open(
        directory: &Path,
        store_id: Digest32,
        verifying_key: VerifyingKey,
        anchor: Arc<dyn PlannerAnchorV1>,
    ) -> Result<Self, PlannerStoreError> {
        let lock = lock_directory(directory)?;
        let checkpoint = anchor
            .current(store_id)?
            .ok_or(PlannerStoreError::AnchorUnavailable)?;
        let expected = checkpoint.checkpoint;
        if expected.store_id != store_id || expected.generation == 0 {
            return Err(PlannerStoreError::AnchorMismatch);
        }
        verify_checkpoint(&verifying_key, &checkpoint, expected)?;
        let mut file = open_regular(&generation_path(directory, expected.generation))?;
        let (records, committed_bytes) = scan(&mut file, expected)?;
        // Only the independently acknowledged prefix is observable. Even a
        // complete suffix can be an append whose acknowledgement was lost.
        if file.metadata()?.len() != committed_bytes {
            file.set_len(committed_bytes)?;
            file.sync_all()?;
        }
        file.seek(SeekFrom::Start(committed_bytes))?;
        let identities = records
            .iter()
            .enumerate()
            .map(|(index, record)| (record.identity, index))
            .collect();
        Ok(Self {
            directory: directory.to_path_buf(),
            _lock: lock,
            file,
            anchor,
            verifying_key,
            checkpoint,
            records,
            identities,
            committed_bytes,
            poisoned: false,
        })
    }

    pub fn checkpoint(&self) -> Result<PlannerCheckpointV1, PlannerStoreError> {
        self.revalidate_anchor()?;
        Ok(self.checkpoint.checkpoint)
    }

    pub fn get(&self, identity: Digest32) -> Result<Option<&[u8]>, PlannerStoreError> {
        self.revalidate_anchor()?;
        Ok(self
            .identities
            .get(&identity)
            .map(|index| self.records[*index].payload.as_slice()))
    }

    /// Append a complete, caller-validated versioned domain envelope. The
    /// identity is an operation identity, not permission to execute an effect.
    pub fn append(
        &mut self,
        identity: Digest32,
        payload: &[u8],
    ) -> Result<PlannerStoredReceiptV1, PlannerStoreError> {
        self.revalidate_anchor()?;
        if identity.is_zero() || payload.is_empty() {
            return Err(PlannerStoreError::Invalid("empty record identity or envelope"));
        }
        if payload.len() > MAX_PLANNER_ENVELOPE_BYTES {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let payload_digest = Digest32::of_bytes(payload);
        if let Some(&index) = self.identities.get(&identity) {
            if self.records[index].payload != payload {
                return Err(PlannerStoreError::IdentityConflict);
            }
            return Ok(PlannerStoredReceiptV1 {
                identity,
                payload_digest,
                sequence: index as u64 + 1,
                checkpoint: self.checkpoint.checkpoint,
                idempotent: true,
            });
        }
        if self.records.len() >= MAX_PLANNER_STORE_RECORDS {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let previous = self.checkpoint.checkpoint;
        let sequence = previous.sequence + 1;
        let (frame, root) = frame(previous.root, sequence, identity, payload);
        let length = self
            .committed_bytes
            .checked_add(frame.len() as u64)
            .filter(|length| *length <= MAX_PLANNER_STORE_BYTES)
            .ok_or(PlannerStoreError::LimitExceeded)?;
        let next = PlannerCheckpointV1 { sequence, root, ..previous };
        // Any error after the first byte, including an uncertain anchor reply,
        // requires reopen/reconciliation. Never continue on a dirty writer.
        self.poisoned = true;
        self.file.write_all(&frame)?;
        self.file.sync_all()?;
        let signed = self.anchor.compare_exchange(Some(previous), next)?;
        verify_checkpoint(&self.verifying_key, &signed, next)?;
        self.identities.insert(identity, self.records.len());
        self.records.push(Record { identity, payload: payload.to_vec() });
        self.committed_bytes = length;
        self.checkpoint = signed;
        self.poisoned = false;
        Ok(PlannerStoredReceiptV1 {
            identity,
            payload_digest,
            sequence,
            checkpoint: next,
            idempotent: false,
        })
    }

    /// Rewrite the complete live history into a new schema generation. All
    /// operation identities and revocation envelopes survive compaction; this
    /// bounded profile rejects capacity exhaustion instead of forgetting them.
    pub fn compact(&mut self) -> Result<PlannerCheckpointV1, PlannerStoreError> {
        self.revalidate_anchor()?;
        let previous = self.checkpoint.checkpoint;
        let generation = previous.generation.checked_add(1)
            .ok_or(PlannerStoreError::LimitExceeded)?;
        let mut bytes = header(previous.store_id, generation, previous.root);
        let mut root = Digest32::of_bytes(&bytes);
        for (index, record) in self.records.iter().enumerate() {
            let (encoded, next) = frame(root, index as u64 + 1, record.identity, &record.payload);
            bytes.extend_from_slice(&encoded);
            root = next;
        }
        let next = PlannerCheckpointV1 { generation, root, ..previous };
        let path = generation_path(&self.directory, generation);
        self.poisoned = true;
        atomic_replace(&self.directory, &path, &bytes)?;
        let signed = self.anchor.compare_exchange(Some(previous), next)?;
        verify_checkpoint(&self.verifying_key, &signed, next)?;
        let mut file = open_regular(&path)?;
        file.seek(SeekFrom::End(0))?;
        self.file = file;
        self.committed_bytes = bytes.len() as u64;
        self.checkpoint = signed;
        self.poisoned = false;
        Ok(next)
    }

    pub fn backup(&self) -> Result<PlannerBackupV1, PlannerStoreError> {
        self.revalidate_anchor()?;
        let mut file = open_regular(&generation_path(
            &self.directory, self.checkpoint.checkpoint.generation,
        ))?;
        let mut bytes = Vec::new();
        file.by_ref().take(MAX_PLANNER_STORE_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 != self.committed_bytes {
            return Err(PlannerStoreError::RollbackOrTruncation);
        }
        Ok(PlannerBackupV1 { checkpoint: self.checkpoint.clone(), bytes })
    }

    /// Restore only the independently current generation. An older, correctly
    /// signed backup is still stale and must not resurrect an older decision.
    pub fn restore_current(
        directory: &Path,
        backup: &PlannerBackupV1,
        verifying_key: VerifyingKey,
        anchor: Arc<dyn PlannerAnchorV1>,
    ) -> Result<Self, PlannerStoreError> {
        let expected = backup.checkpoint.checkpoint;
        verify_checkpoint(&verifying_key, &backup.checkpoint, expected)?;
        if backup.bytes.len() as u64 > MAX_PLANNER_STORE_BYTES {
            return Err(PlannerStoreError::LimitExceeded);
        }
        let lock = lock_directory(directory)?;
        let current = anchor.current(expected.store_id)?
            .ok_or(PlannerStoreError::AnchorUnavailable)?;
        verify_checkpoint(&verifying_key, &current, expected)?;
        let path = generation_path(directory, expected.generation);
        if path.exists() {
            return Err(PlannerStoreError::Invalid("restore destination is not empty"));
        }
        atomic_replace(directory, &path, &backup.bytes)?;
        // Validate before returning a usable store; a corrupt backup never
        // changes the external checkpoint and cannot become a successful open.
        let mut file = open_regular(&path)?;
        scan(&mut file, expected)?;
        drop(file);
        drop(lock);
        Self::open(directory, expected.store_id, verifying_key, anchor)
    }

    /// Keep a bounded number of generation files. The current generation
    /// retains every record, so deleting old physical generations loses no
    /// decision body, idempotency identity or revocation history.
    pub fn retain_generations(&self, keep: u64) -> Result<usize, PlannerStoreError> {
        self.revalidate_anchor()?;
        if !(1..=16).contains(&keep) {
            return Err(PlannerStoreError::Invalid("retention generation count"));
        }
        let current = self.checkpoint.checkpoint;
        let mut file = open_regular(&generation_path(&self.directory, current.generation))?;
        scan(&mut file, current)?;
        let mut entries = Vec::new();
        for entry in fs::read_dir(&self.directory)? {
            if entries.len() >= 64 {
                return Err(PlannerStoreError::LimitExceeded);
            }
            entries.push(entry?);
        }
        let mut removed = 0;
        for entry in entries {
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            let Some(number) = name.strip_prefix("generation-").and_then(|v| v.strip_suffix(".hcp")) else { continue };
            let Ok(generation) = number.parse::<u64>() else { continue };
            if generation < current.generation && current.generation - generation >= keep {
                reject_symlink(&entry.path())?;
                fs::remove_file(entry.path())?;
                removed += 1;
            }
        }
        File::open(&self.directory)?.sync_all()?;
        Ok(removed)
    }

    fn revalidate_anchor(&self) -> Result<(), PlannerStoreError> {
        if self.poisoned {
            return Err(PlannerStoreError::Poisoned);
        }
        let current = self.anchor.current(self.checkpoint.checkpoint.store_id)?
            .ok_or(PlannerStoreError::AnchorUnavailable)?;
        verify_checkpoint(&self.verifying_key, &current, self.checkpoint.checkpoint)
    }
}

fn verify_checkpoint(
    key: &VerifyingKey,
    signed: &SignedPlannerCheckpointV1,
    expected: PlannerCheckpointV1,
) -> Result<(), PlannerStoreError> {
    if signed.checkpoint != expected {
        return Err(PlannerStoreError::AnchorMismatch);
    }
    key.verify_strict(expected.digest().as_array(), &Signature::from_bytes(&signed.signature))
        .map_err(|_| PlannerStoreError::InvalidSignature)
}

fn generation_path(directory: &Path, generation: u64) -> PathBuf {
    directory.join(format!("generation-{generation}.hcp"))
}

fn header(store_id: Digest32, generation: u64, predecessor: Digest32) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    bytes.extend_from_slice(store_id.as_array());
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(predecessor.as_array());
    bytes
}

fn frame(previous: Digest32, sequence: u64, identity: Digest32, payload: &[u8]) -> (Vec<u8>, Digest32) {
    let mut contents = sequence.to_be_bytes().to_vec();
    contents.extend_from_slice(identity.as_array());
    contents.extend_from_slice(payload);
    let mut binding = b"hepta.control.planner-store-frame.v1\0".to_vec();
    binding.extend_from_slice(previous.as_array());
    binding.extend_from_slice(&contents);
    let root = Digest32::of_bytes(&binding);
    let mut bytes = ((contents.len() + 32) as u32).to_be_bytes().to_vec();
    bytes.extend_from_slice(&contents);
    bytes.extend_from_slice(root.as_array());
    (bytes, root)
}

fn scan(file: &mut File, expected: PlannerCheckpointV1) -> Result<(Vec<Record>, u64), PlannerStoreError> {
    if expected.sequence > MAX_PLANNER_STORE_RECORDS as u64 || file.metadata()?.len() > MAX_PLANNER_STORE_BYTES {
        return Err(PlannerStoreError::LimitExceeded);
    }
    file.seek(SeekFrom::Start(0))?;
    let mut head = [0_u8; HEADER_BYTES];
    file.read_exact(&mut head).map_err(|_| PlannerStoreError::RollbackOrTruncation)?;
    if &head[..8] != MAGIC || &head[8..40] != expected.store_id.as_array()
        || head[40..48] != expected.generation.to_be_bytes()
    {
        return Err(PlannerStoreError::Invalid("store schema, identity or generation"));
    }
    let mut root = Digest32::of_bytes(&head);
    let mut records = Vec::new();
    let mut identities = BTreeMap::new();
    for sequence in 1..=expected.sequence {
        let mut size = [0_u8; 4];
        file.read_exact(&mut size).map_err(|_| PlannerStoreError::RollbackOrTruncation)?;
        let length = u32::from_be_bytes(size) as usize;
        if !(73..=MAX_PLANNER_ENVELOPE_BYTES + 72).contains(&length) {
            return Err(PlannerStoreError::Invalid("frame length"));
        }
        let mut bytes = vec![0_u8; length];
        file.read_exact(&mut bytes).map_err(|_| PlannerStoreError::RollbackOrTruncation)?;
        if bytes[..8] != sequence.to_be_bytes() {
            return Err(PlannerStoreError::Invalid("frame sequence"));
        }
        let identity = Digest32::from_array(bytes[8..40].try_into()
            .map_err(|_| PlannerStoreError::Invalid("frame identity"))?);
        if identity.is_zero() || identities.insert(identity, ()).is_some() {
            return Err(PlannerStoreError::IdentityConflict);
        }
        let payload = &bytes[40..length - 32];
        let (_, next) = frame(root, sequence, identity, payload);
        if bytes[length - 32..] != *next.as_array() {
            return Err(PlannerStoreError::Invalid("frame checksum"));
        }
        root = next;
        records.push(Record { identity, payload: payload.to_vec() });
    }
    if root != expected.root {
        return Err(PlannerStoreError::AnchorMismatch);
    }
    Ok((records, file.stream_position()?))
}

fn reject_symlink(path: &Path) -> Result<(), PlannerStoreError> {
    if fs::symlink_metadata(path)?.file_type().is_symlink() {
        return Err(PlannerStoreError::Invalid("symlink in planner store"));
    }
    Ok(())
}

fn open_regular(path: &Path) -> Result<File, PlannerStoreError> {
    reject_symlink(path)?;
    let file = OpenOptions::new().read(true).write(true).open(path)?;
    if !file.metadata()?.is_file() {
        return Err(PlannerStoreError::Invalid("non-regular planner file"));
    }
    Ok(file)
}

fn lock_directory(directory: &Path) -> Result<File, PlannerStoreError> {
    if !directory.exists() {
        let mut builder = fs::DirBuilder::new();
        builder.recursive(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(directory)?;
    }
    reject_symlink(directory)?;
    if !directory.is_dir() {
        return Err(PlannerStoreError::Invalid("planner directory"));
    }
    let path = directory.join("writer.lock");
    if path.exists() { reject_symlink(&path)?; }
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(&path)?;
    match file.try_lock() {
        Ok(()) => {},
        Err(TryLockError::WouldBlock) => return Err(PlannerStoreError::Locked),
        Err(TryLockError::Error(error)) => return Err(PlannerStoreError::Io(error)),
    }
    file.sync_all()?;
    File::open(directory)?.sync_all()?;
    Ok(file)
}

fn atomic_replace(directory: &Path, destination: &Path, bytes: &[u8]) -> Result<(), PlannerStoreError> {
    if bytes.len() as u64 > MAX_PLANNER_STORE_BYTES { return Err(PlannerStoreError::LimitExceeded); }
    let temporary = directory.join("generation.pending");
    if temporary.exists() {
        reject_symlink(&temporary)?;
        fs::remove_file(&temporary)?;
    }
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temporary)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(file);
    fs::rename(&temporary, destination)?;
    File::open(directory)?.sync_all()?;
    Ok(())
}

#[cfg(test)]
#[path = "planner_store_tests.rs"]
mod tests;
