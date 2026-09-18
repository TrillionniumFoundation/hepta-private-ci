//! Create-only snapshots and candidate payloads over host-authorized targets.
//! The host authenticates target paths, receipts, current revocations and selection.

use std::error::Error;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactLifecycleEventV1;
use crate::ArtifactLifecycleJournalRecordV2;
use crate::ArtifactLifecycleJournalSnapshotV2;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactLifecycleStateV1;
use crate::ArtifactManifest;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalDomainV1;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRegistry;
use crate::LifecycleActorEvidenceV2;
use crate::LifecycleActorRoleV2;
use crate::RegistryAppendDisposition;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessV1;
use crate::StateChange;

const MAX_SNAPSHOT: usize = 8 * 1024 * 1024;
const MAX_PAYLOAD: usize = 64 * 1024 * 1024;
const MAX_HEAD: usize = 4096;
const MAGIC: &str = "HEPTAR01";
const HEAD_MAGIC: &str = "HEPTAH01";
const WITHDRAWAL_MAGIC: &str = "HEPTAW01";
const LIFECYCLE_MAGIC: &str = "HEPTAL02";

/// A file proven to have been atomically created by this module.
///
/// Safe callers cannot construct this capability from an arbitrary `File` or
/// extract/clone its handle. Creation fails when the final path component already
/// exists, including when it is empty, truncated, or a symbolic link. Trusted
/// parent traversal and containing-directory durability remain host obligations.
pub struct CreateOnlyArtifactFile(File);

impl fmt::Debug for CreateOnlyArtifactFile {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("CreateOnlyArtifactFile(<opaque>)")
    }
}

impl CreateOnlyArtifactFile {
    pub fn create(path: impl AsRef<Path>) -> Result<Self, ArtifactStorageError> {
        let mut options = OpenOptions::new();
        options.read(true).write(true).create_new(true);
        #[cfg(unix)]
        options.mode(0o600);
        match options.open(path) {
            Ok(file) => Ok(Self(file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                Err(ArtifactStorageError::AlreadyExists)
            }
            Err(error) => Err(error.into()),
        }
    }

    /// Create one final component under a host-authorized, non-symlink parent.
    ///
    /// This closes lexical traversal and direct parent-symlink mistakes. It does
    /// not replace target-OS directory-handle/openat2 qualification for hostile
    /// ancestor replacement.
    pub fn create_in(
        parent: impl AsRef<Path>,
        file_name: impl AsRef<Path>,
    ) -> Result<Self, ArtifactStorageError> {
        let path = contained_child(parent.as_ref(), file_name.as_ref())?;
        Self::create(path)
    }
}

/// Exact bytes and history witness. This is not a signature or acceptance.
/// Retain and authenticate it outside the suspect file; never derive an expected
/// receipt from the file being checked. The host enforces latest revocation state.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RegistrySnapshotReceipt {
    pub binding: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

/// Exact bytes and validation witness for the host-published current registry
/// head.  The file is only a distribution channel: the caller still supplies
/// an independently authenticated witness and requirement, and this crate
/// grants no selection, activation or release authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RegistryHeadWitnessReceipt {
    pub binding: Digest32,
    pub witness_digest: Digest32,
    pub file_digest: Digest32,
    pub encoded_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DatasetWithdrawalSnapshotReceiptV1 {
    pub binding: Digest32,
    pub domain_digest: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LifecycleJournalSnapshotReceiptV2 {
    pub binding: Digest32,
    pub head_digest: Digest32,
    pub file_digest: Digest32,
    pub records: usize,
    pub encoded_bytes: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactStorageError {
    InvalidBinding,
    InvalidPath,
    InvalidReceipt,
    InvalidHeadWitness,
    HeadWitnessMismatch,
    Busy,
    NotRegular,
    AlreadyExists,
    Capacity,
    Corrupt,
    Semantic,
    Unavailable,
    PayloadMismatch,
    NotOrphan,
    Indeterminate,
    Io(io::ErrorKind),
}

impl fmt::Display for ArtifactStorageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for ArtifactStorageError {}
impl From<io::Error> for ArtifactStorageError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

fn contained_child(
    parent: &Path,
    file_name: &Path,
) -> Result<std::path::PathBuf, ArtifactStorageError> {
    let parent_metadata = fs::symlink_metadata(parent).map_err(ArtifactStorageError::from)?;
    if !parent_metadata.is_dir() || parent_metadata.file_type().is_symlink() {
        return Err(ArtifactStorageError::InvalidPath);
    }
    let mut components = file_name.components();
    let valid =
        matches!(components.next(), Some(Component::Normal(_))) && components.next().is_none();
    if !valid || file_name.as_os_str().is_empty() {
        return Err(ArtifactStorageError::InvalidPath);
    }
    Ok(parent.join(file_name))
}

/// Remove only a zero-length regular-file orphan under a trusted parent.
///
/// The caller must have independently established that no successful receipt
/// references this path. Non-empty files, symlinks, directories and multi-level
/// names fail closed.
pub fn remove_zero_length_orphan_in(
    parent: impl AsRef<Path>,
    file_name: impl AsRef<Path>,
) -> Result<(), ArtifactStorageError> {
    let path = contained_child(parent.as_ref(), file_name.as_ref())?;
    let metadata = fs::symlink_metadata(&path).map_err(ArtifactStorageError::from)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() != 0 {
        return Err(ArtifactStorageError::NotOrphan);
    }
    let file = OpenOptions::new().read(true).write(true).open(&path)?;
    let guard = lock(file, LockKind::Exclusive)?;
    let locked = guard.0.metadata()?;
    if !locked.is_file() || locked.len() != 0 {
        return Err(ArtifactStorageError::NotOrphan);
    }
    // Windows cannot unlink an ordinary file while this handle is open.
    // The host is required to serialize reconciliation under its writer fence;
    // release the cooperative lock/handle only after the final zero-length check.
    drop(guard);
    fs::remove_file(&path).map_err(ArtifactStorageError::from)
}

/// Write a new immutable snapshot; an existing file is never overwritten.
/// Directory durability, witness publication, retention and selection are host work.
pub fn write_registry_snapshot(
    file: CreateOnlyArtifactFile,
    registry: &ArtifactRegistry,
    binding: Digest32,
) -> Result<RegistrySnapshotReceipt, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let bytes = encode_snapshot(registry, binding)?;
    let receipt = RegistrySnapshotReceipt {
        binding,
        head_digest: registry.snapshot().head_digest,
        file_digest: Digest32::of_bytes(&bytes),
        records: registry.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

/// Publish one validated current-head witness through a create-only file.
/// Validation happens before bytes are written; a stale or malformed witness
/// therefore cannot become a current-head distribution record by accident.
pub fn write_registry_head_witness(
    file: CreateOnlyArtifactFile,
    witness: &RegistryHeadWitnessV1,
    requirement: &RegistryHeadRequirementV1,
    binding: Digest32,
) -> Result<RegistryHeadWitnessReceipt, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let validated = crate::validate_registry_head_witness(witness, requirement)
        .map_err(|_| ArtifactStorageError::InvalidHeadWitness)?;
    let bytes = encode_head_witness(witness, binding)?;
    let receipt = RegistryHeadWitnessReceipt {
        binding,
        witness_digest: validated.witness_digest,
        file_digest: Digest32::of_bytes(&bytes),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

/// Read and revalidate a distributed current-head witness.  The caller must
/// retain the receipt independently of the file and provide the current
/// requirement; an old self-consistent file is rejected by that requirement.
pub fn read_registry_head_witness(
    file: File,
    expected: RegistryHeadWitnessReceipt,
    requirement: &RegistryHeadRequirementV1,
) -> Result<RegistryHeadWitnessV1, ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.witness_digest.is_zero()
        || expected.file_digest.is_zero()
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_HEAD
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_HEAD,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if bytes.len() != expected.encoded_bytes || Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let witness = decode_head_witness(&bytes, expected.binding)?;
    let validated = crate::validate_registry_head_witness(&witness, requirement)
        .map_err(|_| ArtifactStorageError::HeadWitnessMismatch)?;
    if validated.witness_digest != expected.witness_digest
        || encode_head_witness(&witness, expected.binding)? != bytes
    {
        return Err(ArtifactStorageError::HeadWitnessMismatch);
    }
    Ok(witness)
}

/// Rebuild the same canonical registry and revocation lineage from exact bytes.
/// Accepts a read-only file and uses a shared lock, never a writer recovery path.
/// There is no repair, initialization, old-snapshot fallback or selected pointer.
pub fn read_registry_snapshot(
    file: File,
    expected: RegistrySnapshotReceipt,
) -> Result<ArtifactRegistry, ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.file_digest.is_zero()
        || expected.records > crate::MAX_DURABLE_RECORDS
        || expected.encoded_bytes > MAX_SNAPSHOT
        || expected.encoded_bytes == 0
        || (expected.records == 0) != expected.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_SNAPSHOT,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if bytes.len() != expected.encoded_bytes || Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let text = std::str::from_utf8(&bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(MAGIC)
        || lines.next() != Some(expected.binding.to_string().as_str())
        || lines.next() != Some(expected.records.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let mut registry = ArtifactRegistry::new();
    for line in lines {
        if registry.records().len() >= expected.records || line.len() > 2048 {
            return Err(ArtifactStorageError::Corrupt);
        }
        let receipt = registry
            .append(decode_event(line)?)
            .map_err(|_| ArtifactStorageError::Semantic)?;
        if receipt.disposition != RegistryAppendDisposition::Appended {
            return Err(ArtifactStorageError::Corrupt);
        }
    }
    if registry.records().len() != expected.records
        || registry.snapshot().head_digest != expected.head_digest
        || encode_snapshot(&registry, expected.binding)? != bytes
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

pub fn write_dataset_withdrawal_snapshot(
    file: CreateOnlyArtifactFile,
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<DatasetWithdrawalSnapshotReceiptV1, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let bytes = encode_withdrawal_snapshot(registry, binding)?;
    let snapshot = registry.snapshot();
    let domain_digest = registry
        .domain_binding_digest()
        .map_err(|_| ArtifactStorageError::Semantic)?
        .unwrap_or(Digest32::ZERO);
    let receipt = DatasetWithdrawalSnapshotReceiptV1 {
        binding,
        domain_digest,
        head_digest: snapshot.head_digest,
        file_digest: Digest32::of_bytes(&bytes),
        records: snapshot.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_dataset_withdrawal_snapshot(
    file: File,
    expected: DatasetWithdrawalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.file_digest.is_zero()
        || expected.records > crate::MAX_DURABLE_RECORDS
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_SNAPSHOT
        || (expected.records == 0) != expected.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_SNAPSHOT,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let registry = decode_withdrawal_snapshot(&bytes, expected)?;
    if encode_withdrawal_snapshot(&registry, expected.binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

pub fn write_lifecycle_journal_snapshot(
    file: CreateOnlyArtifactFile,
    journal: &ArtifactLifecycleJournalV2,
    binding: Digest32,
) -> Result<LifecycleJournalSnapshotReceiptV2, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let bytes = encode_lifecycle_snapshot(journal, binding)?;
    let receipt = LifecycleJournalSnapshotReceiptV2 {
        binding,
        head_digest: journal.head_digest(),
        file_digest: Digest32::of_bytes(&bytes),
        records: journal.records().len(),
        encoded_bytes: bytes.len(),
    };
    write_new(file, &bytes)?;
    Ok(receipt)
}

pub fn read_lifecycle_journal_snapshot(
    file: File,
    expected: LifecycleJournalSnapshotReceiptV2,
    replay_now: u64,
) -> Result<ArtifactLifecycleJournalV2, ArtifactStorageError> {
    if expected.binding.is_zero()
        || expected.file_digest.is_zero()
        || expected.records > crate::MAX_DURABLE_RECORDS
        || expected.encoded_bytes == 0
        || expected.encoded_bytes > MAX_SNAPSHOT
        || (expected.records == 0) != expected.head_digest.is_zero()
    {
        return Err(ArtifactStorageError::InvalidReceipt);
    }
    let bytes = read_bounded(
        file,
        MAX_SNAPSHOT,
        expected.encoded_bytes as u64,
        ArtifactStorageError::Corrupt,
    )?;
    if Digest32::of_bytes(&bytes) != expected.file_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let journal = decode_lifecycle_snapshot(&bytes, expected, replay_now)?;
    if encode_lifecycle_snapshot(&journal, expected.binding)? != bytes {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(journal)
}

/// Persist exactly the bytes of a currently eligible candidate, never select it.
pub fn write_candidate_payload(
    file: CreateOnlyArtifactFile,
    registry: &ArtifactRegistry,
    artifact: &StableId,
    bytes: &[u8],
) -> Result<Digest32, ArtifactStorageError> {
    let manifest = eligible_manifest(registry, artifact)?;
    validate_payload(manifest, bytes)?;
    write_new(file, bytes)?;
    Ok(manifest.content_digest)
}

/// Load candidate bytes using a CURRENT host-authenticated registry snapshot.
/// A read-only handle is sufficient. Successful loading is not authority to
/// execute, install or select the bytes, nor proof of continued revocation freshness.
pub fn read_candidate_payload(
    file: File,
    registry: &ArtifactRegistry,
    artifact: &StableId,
) -> Result<Vec<u8>, ArtifactStorageError> {
    let manifest = eligible_manifest(registry, artifact)?;
    let bytes = read_bounded(
        file,
        MAX_PAYLOAD,
        manifest.encoded_size_bytes,
        ArtifactStorageError::PayloadMismatch,
    )?;
    validate_payload(manifest, &bytes)?;
    Ok(bytes)
}

fn eligible_manifest<'a>(
    registry: &'a ArtifactRegistry,
    artifact: &StableId,
) -> Result<&'a ArtifactManifest, ArtifactStorageError> {
    if !registry.is_eligible(artifact) {
        return Err(ArtifactStorageError::Unavailable);
    }
    registry
        .manifest(artifact)
        .ok_or(ArtifactStorageError::Unavailable)
}

fn validate_payload(manifest: &ArtifactManifest, bytes: &[u8]) -> Result<(), ArtifactStorageError> {
    if bytes.is_empty() || bytes.len() > MAX_PAYLOAD {
        return Err(ArtifactStorageError::Capacity);
    }
    if bytes.len() as u64 != manifest.encoded_size_bytes
        || Digest32::of_bytes(bytes) != manifest.content_digest
    {
        return Err(ArtifactStorageError::PayloadMismatch);
    }
    Ok(())
}

enum LockKind {
    Shared,
    Exclusive,
}

struct LockedFile(File);

impl Drop for LockedFile {
    fn drop(&mut self) {
        // Normal close alone can leave a lock on a transient inherited open
        // description. Release only the lock this guard successfully acquired.
        // This is not a commit acknowledgement or a forced-exit guarantee.
        let _ = self.0.unlock();
    }
}

fn lock(file: File, kind: LockKind) -> Result<LockedFile, ArtifactStorageError> {
    if !file.metadata()?.is_file() {
        return Err(ArtifactStorageError::NotRegular);
    }
    let result = match kind {
        LockKind::Shared => file.try_lock_shared(),
        LockKind::Exclusive => file.try_lock(),
    };
    match result {
        Ok(()) => Ok(LockedFile(file)),
        Err(TryLockError::WouldBlock) => Err(ArtifactStorageError::Busy),
        Err(TryLockError::Error(error)) => Err(error.into()),
    }
}

fn write_new(file: CreateOnlyArtifactFile, bytes: &[u8]) -> Result<(), ArtifactStorageError> {
    let mut guard = lock(file.0, LockKind::Exclusive)?;
    if guard.0.metadata()?.len() != 0 {
        // Atomic creation already proved the target did not exist. Bytes appearing
        // before the guarded write are interference, so completion is unknown.
        return Err(ArtifactStorageError::Indeterminate);
    }
    guard.0.seek(SeekFrom::Start(0))?;
    guard
        .0
        .write_all(bytes)
        .and_then(|()| guard.0.sync_all())
        .map_err(|_| ArtifactStorageError::Indeterminate)
}

fn read_bounded(
    file: File,
    limit: usize,
    expected_bytes: u64,
    mismatch: ArtifactStorageError,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if expected_bytes > limit as u64 {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut guard = lock(file, LockKind::Shared)?;
    let observed_bytes = guard.0.metadata()?.len();
    // A tiny pin must not force a full global-quota read of a different file.
    // Check under the shared lock before seeking, allocating or hashing bytes.
    validate_read_length(observed_bytes, expected_bytes, limit, mismatch)?;
    guard.0.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    (&mut guard.0)
        .take(expected_bytes + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err(ArtifactStorageError::Capacity);
    }
    // Locks are advisory on some hosts. Refuse observed growth/truncation too;
    // the caller still verifies the full digest against its independent pin.
    validate_read_length(guard.0.metadata()?.len(), expected_bytes, limit, mismatch)?;
    if bytes.len() as u64 != expected_bytes {
        return Err(mismatch);
    }
    Ok(bytes)
}

fn validate_read_length(
    observed_bytes: u64,
    expected_bytes: u64,
    limit: usize,
    mismatch: ArtifactStorageError,
) -> Result<(), ArtifactStorageError> {
    if observed_bytes > limit as u64
        || (observed_bytes == 0 && mismatch == ArtifactStorageError::PayloadMismatch)
    {
        return Err(ArtifactStorageError::Capacity);
    }
    if observed_bytes != expected_bytes {
        return Err(mismatch);
    }
    Ok(())
}

fn encode_head_witness(
    witness: &RegistryHeadWitnessV1,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if binding.is_zero() {
        return Err(ArtifactStorageError::InvalidBinding);
    }
    let text = format!(
        "{HEAD_MAGIC}\n{binding}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n",
        witness.registry_id,
        witness.generation.get(),
        witness.head_digest,
        witness.predecessor_head_digest,
        witness.authority_epoch,
        witness.signer_id,
        witness.signing_key_digest,
        witness.issued_at,
        witness.expires_at,
    );
    let bytes = text.into_bytes();
    if bytes.len() > MAX_HEAD {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(bytes)
}

fn decode_head_witness(
    bytes: &[u8],
    expected_binding: Digest32,
) -> Result<RegistryHeadWitnessV1, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let fields: Vec<_> = text.lines().collect();
    if fields.len() != 11 || fields[0] != HEAD_MAGIC || fields[1] != expected_binding.to_string() {
        return Err(ArtifactStorageError::Corrupt);
    }
    let parse_digest =
        |value: &str| Digest32::from_str(value).map_err(|_| ArtifactStorageError::Corrupt);
    let parse_id =
        |value: &str| StableId::new(value.to_owned()).map_err(|_| ArtifactStorageError::Corrupt);
    let parse_u64 = |value: &str| {
        value
            .parse::<u64>()
            .map_err(|_| ArtifactStorageError::Corrupt)
    };
    Ok(RegistryHeadWitnessV1 {
        registry_id: parse_id(fields[2])?,
        generation: Generation::new(parse_u64(fields[3])?)
            .map_err(|_| ArtifactStorageError::Corrupt)?,
        head_digest: parse_digest(fields[4])?,
        predecessor_head_digest: parse_digest(fields[5])?,
        authority_epoch: parse_u64(fields[6])?,
        signer_id: parse_id(fields[7])?,
        signing_key_digest: parse_digest(fields[8])?,
        issued_at: parse_u64(fields[9])?,
        expires_at: parse_u64(fields[10])?,
    })
}

fn encode_withdrawal_snapshot(
    registry: &DatasetWithdrawalRegistry,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    let snapshot = registry.snapshot();
    if snapshot.records().len() > crate::MAX_DURABLE_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let domain_line = match registry.domain() {
        Some(domain) => format!(
            "S|{}|{}|{}",
            domain.registry_id, domain.scope_digest, domain.authority_domain_digest
        ),
        None => "U".to_string(),
    };
    let mut text = format!(
        "{WITHDRAWAL_MAGIC}\n{binding}\n{domain_line}\n{}\n{}\n",
        snapshot.records().len(),
        snapshot.head_digest
    );
    for record in snapshot.records() {
        let n = &record.notice;
        text.push_str(&format!(
            "W|{}|{}|{}|{}|{}|{}|{}|{}\n",
            n.notice_id,
            n.dataset_digest,
            n.source_tombstone_digest,
            n.authority_id,
            n.credential_chain_digest,
            n.signing_key_digest,
            n.authority_epoch,
            n.issued_at,
        ));
    }
    if text.len() > MAX_SNAPSHOT {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_withdrawal_snapshot(
    bytes: &[u8],
    expected: DatasetWithdrawalSnapshotReceiptV1,
) -> Result<DatasetWithdrawalRegistry, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(WITHDRAWAL_MAGIC)
        || lines.next() != Some(expected.binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let domain_line = lines.next().ok_or(ArtifactStorageError::Corrupt)?;
    let mut registry = if domain_line == "U" {
        if !expected.domain_digest.is_zero() {
            return Err(ArtifactStorageError::Corrupt);
        }
        DatasetWithdrawalRegistry::new()
    } else {
        let fields: Vec<_> = domain_line.split('|').collect();
        if fields.len() != 4 || fields[0] != "S" {
            return Err(ArtifactStorageError::Corrupt);
        }
        let domain = DatasetWithdrawalDomainV1 {
            registry_id: parse_id(fields[1])?,
            scope_digest: parse_digest(fields[2])?,
            authority_domain_digest: parse_digest(fields[3])?,
        };
        let observed = domain
            .binding_digest()
            .map_err(|_| ArtifactStorageError::Semantic)?;
        if observed != expected.domain_digest {
            return Err(ArtifactStorageError::Corrupt);
        }
        DatasetWithdrawalRegistry::new_scoped(domain).map_err(|_| ArtifactStorageError::Semantic)?
    };
    let count = parse_usize(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    let head = parse_digest(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    if count != expected.records || head != expected.head_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    for line in lines {
        if registry.snapshot().records().len() >= count {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 9 || fields[0] != "W" {
            return Err(ArtifactStorageError::Corrupt);
        }
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: parse_id(fields[1])?,
                dataset_digest: parse_digest(fields[2])?,
                source_tombstone_digest: parse_digest(fields[3])?,
                authority_id: parse_id(fields[4])?,
                credential_chain_digest: parse_digest(fields[5])?,
                signing_key_digest: parse_digest(fields[6])?,
                authority_epoch: parse_u64(fields[7])?,
                issued_at: parse_u64(fields[8])?,
            })
            .map_err(|_| ArtifactStorageError::Semantic)?;
    }
    let snapshot = registry.snapshot();
    if snapshot.records().len() != count || snapshot.head_digest != head {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(registry)
}

fn encode_lifecycle_snapshot(
    journal: &ArtifactLifecycleJournalV2,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    if journal.records().len() > crate::MAX_DURABLE_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!(
        "{LIFECYCLE_MAGIC}\n{binding}\n{}\n{}\n",
        journal.records().len(),
        journal.head_digest()
    );
    for record in journal.records() {
        let a = &record.actor;
        let e = &record.event;
        text.push_str(&format!(
            "L|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}\n",
            record.sequence,
            record.predecessor_head_digest,
            record.event_digest,
            record.chain_digest,
            record.producer_id,
            a.actor_id,
            a.credential_digest,
            lifecycle_role_tag(a.role),
            a.authority_epoch,
            a.verified_at,
            a.expires_at,
            e.event_id,
            e.artifact_id,
            lifecycle_state_tag(e.prior_state),
            lifecycle_state_tag(e.next_state),
            e.actor_id,
            e.actor_credential_digest,
            e.evidence_digest,
            e.authority_epoch,
            e.occurred_at,
        ));
    }
    if text.len() > MAX_SNAPSHOT {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_lifecycle_snapshot(
    bytes: &[u8],
    expected: LifecycleJournalSnapshotReceiptV2,
    replay_now: u64,
) -> Result<ArtifactLifecycleJournalV2, ArtifactStorageError> {
    let text = std::str::from_utf8(bytes).map_err(|_| ArtifactStorageError::Corrupt)?;
    let mut lines = text.lines();
    if lines.next() != Some(LIFECYCLE_MAGIC)
        || lines.next() != Some(expected.binding.to_string().as_str())
    {
        return Err(ArtifactStorageError::Corrupt);
    }
    let count = parse_usize(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    let head = parse_digest(lines.next().ok_or(ArtifactStorageError::Corrupt)?)?;
    if count != expected.records || head != expected.head_digest {
        return Err(ArtifactStorageError::Corrupt);
    }
    let mut records = Vec::with_capacity(count);
    for line in lines {
        if records.len() >= count {
            return Err(ArtifactStorageError::Corrupt);
        }
        let fields: Vec<_> = line.split('|').collect();
        if fields.len() != 21 || fields[0] != "L" {
            return Err(ArtifactStorageError::Corrupt);
        }
        let actor = LifecycleActorEvidenceV2 {
            actor_id: parse_id(fields[6])?,
            credential_digest: parse_digest(fields[7])?,
            role: parse_lifecycle_role(fields[8])?,
            authority_epoch: parse_u64(fields[9])?,
            verified_at: parse_u64(fields[10])?,
            expires_at: parse_u64(fields[11])?,
        };
        let event = ArtifactLifecycleEventV1 {
            event_id: parse_id(fields[12])?,
            artifact_id: parse_id(fields[13])?,
            prior_state: parse_lifecycle_state(fields[14])?,
            next_state: parse_lifecycle_state(fields[15])?,
            actor_id: parse_id(fields[16])?,
            actor_credential_digest: parse_digest(fields[17])?,
            evidence_digest: parse_digest(fields[18])?,
            authority_epoch: parse_u64(fields[19])?,
            occurred_at: parse_u64(fields[20])?,
        };
        records.push(ArtifactLifecycleJournalRecordV2 {
            sequence: parse_u64(fields[1])?,
            predecessor_head_digest: parse_digest(fields[2])?,
            event_digest: parse_digest(fields[3])?,
            chain_digest: parse_digest(fields[4])?,
            producer_id: parse_id(fields[5])?,
            actor,
            event,
        });
    }
    let journal = ArtifactLifecycleJournalV2::from_snapshot(
        ArtifactLifecycleJournalSnapshotV2 {
            records,
            head_digest: head,
        },
        replay_now,
    )
    .map_err(|_| ArtifactStorageError::Semantic)?;
    if journal.records().len() != count || journal.head_digest() != head {
        return Err(ArtifactStorageError::Corrupt);
    }
    Ok(journal)
}

fn lifecycle_role_tag(role: LifecycleActorRoleV2) -> u8 {
    match role {
        LifecycleActorRoleV2::Producer => 0,
        LifecycleActorRoleV2::Evaluator => 1,
        LifecycleActorRoleV2::ShadowOperator => 2,
        LifecycleActorRoleV2::CanaryOperator => 3,
        LifecycleActorRoleV2::HumanOperator => 4,
        LifecycleActorRoleV2::Selector => 5,
        LifecycleActorRoleV2::QuarantineAuthority => 6,
        LifecycleActorRoleV2::RevocationAuthority => 7,
        LifecycleActorRoleV2::RetirementAuthority => 8,
    }
}

fn parse_lifecycle_role(value: &str) -> Result<LifecycleActorRoleV2, ArtifactStorageError> {
    match value {
        "0" => Ok(LifecycleActorRoleV2::Producer),
        "1" => Ok(LifecycleActorRoleV2::Evaluator),
        "2" => Ok(LifecycleActorRoleV2::ShadowOperator),
        "3" => Ok(LifecycleActorRoleV2::CanaryOperator),
        "4" => Ok(LifecycleActorRoleV2::HumanOperator),
        "5" => Ok(LifecycleActorRoleV2::Selector),
        "6" => Ok(LifecycleActorRoleV2::QuarantineAuthority),
        "7" => Ok(LifecycleActorRoleV2::RevocationAuthority),
        "8" => Ok(LifecycleActorRoleV2::RetirementAuthority),
        _ => Err(ArtifactStorageError::Corrupt),
    }
}

fn lifecycle_state_tag(state: ArtifactLifecycleStateV1) -> u8 {
    match state {
        ArtifactLifecycleStateV1::Proposed => 0,
        ArtifactLifecycleStateV1::Trained => 1,
        ArtifactLifecycleStateV1::Evaluated => 2,
        ArtifactLifecycleStateV1::Shadow => 3,
        ArtifactLifecycleStateV1::Canary => 4,
        ArtifactLifecycleStateV1::OperatorAccepted => 5,
        ArtifactLifecycleStateV1::Selected => 6,
        ArtifactLifecycleStateV1::Quarantined => 7,
        ArtifactLifecycleStateV1::Revoked => 8,
        ArtifactLifecycleStateV1::Retired => 9,
    }
}

fn parse_lifecycle_state(value: &str) -> Result<ArtifactLifecycleStateV1, ArtifactStorageError> {
    match value {
        "0" => Ok(ArtifactLifecycleStateV1::Proposed),
        "1" => Ok(ArtifactLifecycleStateV1::Trained),
        "2" => Ok(ArtifactLifecycleStateV1::Evaluated),
        "3" => Ok(ArtifactLifecycleStateV1::Shadow),
        "4" => Ok(ArtifactLifecycleStateV1::Canary),
        "5" => Ok(ArtifactLifecycleStateV1::OperatorAccepted),
        "6" => Ok(ArtifactLifecycleStateV1::Selected),
        "7" => Ok(ArtifactLifecycleStateV1::Quarantined),
        "8" => Ok(ArtifactLifecycleStateV1::Revoked),
        "9" => Ok(ArtifactLifecycleStateV1::Retired),
        _ => Err(ArtifactStorageError::Corrupt),
    }
}

fn parse_id(value: &str) -> Result<StableId, ArtifactStorageError> {
    StableId::new(value.to_owned()).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_digest(value: &str) -> Result<Digest32, ArtifactStorageError> {
    Digest32::from_str(value).map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_u64(value: &str) -> Result<u64, ArtifactStorageError> {
    value
        .parse::<u64>()
        .map_err(|_| ArtifactStorageError::Corrupt)
}

fn parse_usize(value: &str) -> Result<usize, ArtifactStorageError> {
    value
        .parse::<usize>()
        .map_err(|_| ArtifactStorageError::Corrupt)
}

fn encode_snapshot(
    registry: &ArtifactRegistry,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    let count = registry.records().len();
    if count > crate::MAX_DURABLE_RECORDS {
        return Err(ArtifactStorageError::Capacity);
    }
    let mut text = format!("{MAGIC}\n{binding}\n{count}\n");
    for record in registry.records() {
        match &record.event {
            ArtifactEvent::Register {
                event_id,
                manifest: m,
            } => {
                let predecessor = m.predecessor_id.as_ref().map_or("", StableId::as_str);
                text.push_str(&format!(
                    "R|{event_id}|{}|{}|{}|{predecessor}|{}|{}|{}|{}|{}|{}\n",
                    m.artifact_id,
                    m.kind.tag(),
                    m.generation.get(),
                    m.content_digest,
                    m.objective_digest,
                    m.support_digest,
                    m.producer_id,
                    m.compatibility_digest,
                    m.encoded_size_bytes,
                ));
            }
            ArtifactEvent::Quarantine(change) | ArtifactEvent::Revoke(change) => {
                let tag = match &record.event {
                    ArtifactEvent::Quarantine(_) => "Q",
                    ArtifactEvent::Revoke(_) => "V",
                    ArtifactEvent::Register { .. } => return Err(ArtifactStorageError::Semantic),
                };
                text.push_str(&format!(
                    "{tag}|{}|{}|{}|{}\n",
                    change.event_id, change.artifact_id, change.evaluator_id, change.reason_digest
                ));
            }
        }
    }
    if text.len() > MAX_SNAPSHOT {
        return Err(ArtifactStorageError::Capacity);
    }
    Ok(text.into_bytes())
}

fn decode_event(line: &str) -> Result<ArtifactEvent, ArtifactStorageError> {
    let fields: Vec<&str> = line.split('|').collect();
    let id = |s: &str| StableId::new(s).map_err(|_| ArtifactStorageError::Corrupt);
    let digest = |s: &str| {
        s.parse::<Digest32>()
            .map_err(|_| ArtifactStorageError::Corrupt)
    };
    let number = |s: &str| s.parse::<u64>().map_err(|_| ArtifactStorageError::Corrupt);
    match fields.as_slice() {
        [
            "R",
            event,
            artifact,
            kind,
            generation,
            predecessor,
            content,
            objective,
            support,
            producer,
            compatibility,
            size,
        ] => {
            let kind = match *kind {
                "0" => ArtifactKind::Prompt,
                "1" => ArtifactKind::Policy,
                "2" => ArtifactKind::Model,
                "3" => ArtifactKind::Workflow,
                "4" => ArtifactKind::Skill,
                "5" => ArtifactKind::Parameters,
                "6" => ArtifactKind::Topology,
                "7" => ArtifactKind::Code,
                "8" => ArtifactKind::ExternalAdapter,
                _ => return Err(ArtifactStorageError::Corrupt),
            };
            Ok(ArtifactEvent::Register {
                event_id: id(event)?,
                manifest: ArtifactManifest {
                    artifact_id: id(artifact)?,
                    kind,
                    generation: Generation::new(number(generation)?)
                        .map_err(|_| ArtifactStorageError::Corrupt)?,
                    predecessor_id: if predecessor.is_empty() {
                        None
                    } else {
                        Some(id(predecessor)?)
                    },
                    content_digest: digest(content)?,
                    objective_digest: digest(objective)?,
                    support_digest: digest(support)?,
                    producer_id: id(producer)?,
                    compatibility_digest: digest(compatibility)?,
                    encoded_size_bytes: number(size)?,
                },
            })
        }
        [tag @ ("Q" | "V"), event, artifact, evaluator, reason] => {
            let change = StateChange {
                event_id: id(event)?,
                artifact_id: id(artifact)?,
                evaluator_id: id(evaluator)?,
                reason_digest: digest(reason)?,
            };
            Ok(if *tag == "Q" {
                ArtifactEvent::Quarantine(change)
            } else {
                ArtifactEvent::Revoke(change)
            })
        }
        _ => Err(ArtifactStorageError::Corrupt),
    }
}

#[cfg(test)]
#[path = "storage_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "storage_lock_tests.rs"]
mod lock_tests;

#[cfg(test)]
#[path = "storage_budget_tests.rs"]
mod budget_tests;
