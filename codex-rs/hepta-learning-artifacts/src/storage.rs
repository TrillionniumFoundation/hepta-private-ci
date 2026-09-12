//! Create-only snapshots and candidate payloads over host-authorized targets.
//! The host authenticates target paths, receipts, current revocations and selection.

use std::error::Error;
use std::fmt;
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
use std::path::Path;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactRegistry;
use crate::RegistryAppendDisposition;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessV1;
use crate::StateChange;

const MAX_SNAPSHOT: usize = 8 * 1024 * 1024;
const MAX_PAYLOAD: usize = 64 * 1024 * 1024;
const MAX_RECORDS: usize = 4096;
const MAX_HEAD: usize = 4096;
const MAGIC: &str = "HEPTAR01";
const HEAD_MAGIC: &str = "HEPTAH01";

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
pub enum ArtifactStorageError {
    InvalidBinding,
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
        || expected.records > MAX_RECORDS
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

fn encode_snapshot(
    registry: &ArtifactRegistry,
    binding: Digest32,
) -> Result<Vec<u8>, ArtifactStorageError> {
    let count = registry.records().len();
    if count > MAX_RECORDS {
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
