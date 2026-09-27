//! Immutable terminal archive for runtime.codex operations.
//!
//! Live operation directories retain crash-recovery responsibility. Only an
//! exact terminal receipt may move into the sibling archive. The complete
//! manifest and receipt remain available for exact duplicate lookup, so archive
//! compaction never makes a historical run identity safe to dispatch again.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::MAX_PROCESS_OUTPUT_BYTES;
use super::ProcessRuntimeCodexExecutorV1;
use super::RuntimeCodexExecutionInputV1;
use super::RuntimeCodexExecutionReceiptV1;
use super::RuntimeCodexOwnerV1;
use super::persistence;
use super::persistence::RuntimeCodexJobManifestV1;
use crate::AgentdError;

const ARCHIVE_SCHEMA_VERSION: u32 = 1;
const ARCHIVE_HIGH_WATERMARK: usize = 768;
const ARCHIVE_LOW_WATERMARK: usize = 512;
const MAX_ARCHIVED_IDENTITIES: usize = 16_384;
const MAX_ARCHIVE_ENTRY_BYTES: usize = MAX_PROCESS_OUTPUT_BYTES + 128 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RuntimeCodexArchiveEntryV1 {
    schema_version: u32,
    manifest: RuntimeCodexJobManifestV1,
    receipt: RuntimeCodexExecutionReceiptV1,
    witness_digest: String,
}

pub(super) fn archive_root_for(journal_root: &Path) -> Result<PathBuf, AgentdError> {
    let parent = journal_root.parent().ok_or_else(|| {
        AgentdError::Invalid("runtime.codex journal root has no parent".to_string())
    })?;
    let name = journal_root
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| {
            AgentdError::Invalid("runtime.codex journal root name is not UTF-8".to_string())
        })?;
    Ok(parent.join(format!("{name}.terminal-archive-v1")))
}

pub(super) fn read_archived_receipt(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
    input: &RuntimeCodexExecutionInputV1,
    input_digest: Digest32,
) -> Result<Option<RuntimeCodexExecutionReceiptV1>, AgentdError> {
    let path = archive_path(executor, input.run_id().as_str());
    let entry: RuntimeCodexArchiveEntryV1 = match read_bounded_json(&path) {
        Ok(value) => value,
        Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(None);
        }
        Err(error) => return Err(error),
    };
    validate_entry(&entry, owner, executor.worker_artifact_digest())?;
    if entry.manifest.run_id != input.run_id().as_str()
        || entry.manifest.expected_revision != input.expected_revision()
        || entry.manifest.context_digest != input.context_digest().to_string()
        || entry.manifest.envelope_digest != input.envelope_digest().to_string()
        || entry.manifest.model != input.model()
        || entry.manifest.deadline_ms != input.deadline_ms()
        || entry.manifest.input_digest != input_digest.to_string()
    {
        return Err(AgentdError::Protocol(
            "archived runtime.codex identity was reused with semantic drift".to_string(),
        ));
    }
    Ok(Some(entry.receipt))
}

pub(super) fn compact_terminal_operations(
    executor: &ProcessRuntimeCodexExecutorV1,
    owner: &RuntimeCodexOwnerV1,
) -> Result<usize, AgentdError> {
    let mut entries = operation_directories(executor.journal_root())?;
    if entries.len() <= ARCHIVE_HIGH_WATERMARK {
        return Ok(0);
    }
    let archive_count = std::fs::read_dir(executor.archive_root())?
        .collect::<Result<Vec<_>, _>>()?
        .len();
    if archive_count >= MAX_ARCHIVED_IDENTITIES {
        return Err(AgentdError::Protocol(
            "runtime.codex terminal archive identity capacity is exhausted".to_string(),
        ));
    }
    entries.sort();
    let mut archived = 0usize;
    for directory in entries {
        if operation_directories(executor.journal_root())?.len() <= ARCHIVE_LOW_WATERMARK {
            break;
        }
        let paths = persistence::OperationPaths::for_directory(&directory);
        let manifest = persistence::read_manifest(&paths.manifest)?;
        persistence::validate_manifest_owner(
            &manifest,
            owner,
            executor.worker_artifact_digest(),
        )?;
        let Some(receipt) =
            persistence::read_receipt_if_present(&paths.receipt, &manifest)?
        else {
            continue;
        };
        let witness_digest = witness_digest(&manifest, &receipt)?;
        let entry = RuntimeCodexArchiveEntryV1 {
            schema_version: ARCHIVE_SCHEMA_VERSION,
            manifest: manifest.clone(),
            receipt: receipt.clone(),
            witness_digest: witness_digest.to_string(),
        };
        let archive_path = archive_path(executor, &manifest.run_id);
        publish_archive(&archive_path, &entry)?;
        let observed: RuntimeCodexArchiveEntryV1 = read_bounded_json(&archive_path)?;
        validate_entry(&observed, owner, executor.worker_artifact_digest())?;
        if observed != entry {
            return Err(AgentdError::Protocol(
                "runtime.codex archive publication changed terminal evidence".to_string(),
            ));
        }
        std::fs::remove_dir_all(&directory)?;
        sync_directory(executor.journal_root())?;
        archived = archived
            .checked_add(1)
            .ok_or_else(|| AgentdError::Protocol("archive counter overflow".to_string()))?;
    }
    Ok(archived)
}

fn operation_directories(root: &Path) -> Result<Vec<PathBuf>, AgentdError> {
    let mut directories = Vec::new();
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        if file_type.is_symlink() || !file_type.is_dir() {
            return Err(AgentdError::Protocol(format!(
                "unexpected runtime.codex journal entry during archive scan: {}",
                entry.path().display()
            )));
        }
        directories.push(entry.path());
    }
    Ok(directories)
}

fn archive_path(executor: &ProcessRuntimeCodexExecutorV1, run_id: &str) -> PathBuf {
    let key = Digest32::of_bytes(run_id.as_bytes());
    executor.archive_root().join(format!("{key}.json"))
}

fn validate_entry(
    entry: &RuntimeCodexArchiveEntryV1,
    owner: &RuntimeCodexOwnerV1,
    expected_worker_digest: Digest32,
) -> Result<(), AgentdError> {
    if entry.schema_version != ARCHIVE_SCHEMA_VERSION {
        return Err(AgentdError::Protocol(
            "unsupported runtime.codex archive schema".to_string(),
        ));
    }
    persistence::validate_manifest_owner(&entry.manifest, owner, expected_worker_digest)?;
    if entry.receipt.schema_version != entry.manifest.schema_version
        || entry.receipt.run_id != entry.manifest.run_id
        || entry.receipt.input_digest != entry.manifest.input_digest
        || entry.receipt.worker_artifact_digest != entry.manifest.worker_artifact_digest
        || !entry.receipt.output.terminal_observed
        || entry.receipt.output_digest.parse::<Digest32>().is_err()
        || entry.receipt.output_digest
            != Digest32::of_bytes(&serde_json::to_vec(&entry.receipt.output)?).to_string()
    {
        return Err(AgentdError::Protocol(
            "runtime.codex archive receipt does not match its manifest".to_string(),
        ));
    }
    let expected = witness_digest(&entry.manifest, &entry.receipt)?;
    if entry.witness_digest != expected.to_string() {
        return Err(AgentdError::Protocol(
            "runtime.codex terminal archive witness digest mismatch".to_string(),
        ));
    }
    Ok(())
}

fn witness_digest(
    manifest: &RuntimeCodexJobManifestV1,
    receipt: &RuntimeCodexExecutionReceiptV1,
) -> Result<Digest32, AgentdError> {
    #[derive(Serialize)]
    struct Witness<'a> {
        domain: &'static str,
        manifest: &'a RuntimeCodexJobManifestV1,
        receipt: &'a RuntimeCodexExecutionReceiptV1,
    }
    Ok(Digest32::of_bytes(&serde_json::to_vec(&Witness {
        domain: "hepta.runtime-codex.terminal-archive.v1",
        manifest,
        receipt,
    })?))
}

fn publish_archive(path: &Path, entry: &RuntimeCodexArchiveEntryV1) -> Result<(), AgentdError> {
    match read_bounded_json::<RuntimeCodexArchiveEntryV1>(path) {
        Ok(existing) => {
            return if existing == *entry {
                Ok(())
            } else {
                Err(AgentdError::Protocol(
                    "runtime.codex archive identity conflicts with existing evidence"
                        .to_string(),
                ))
            };
        }
        Err(AgentdError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error),
    }
    let parent = path.parent().ok_or_else(|| {
        AgentdError::Protocol("runtime.codex archive path has no parent".to_string())
    })?;
    let bytes = serde_json::to_vec(entry)?;
    if bytes.is_empty() || bytes.len() > MAX_ARCHIVE_ENTRY_BYTES {
        return Err(AgentdError::Protocol(
            "runtime.codex archive entry exceeded its byte bound".to_string(),
        ));
    }
    let mut staging = None;
    for suffix in 0_u8..16 {
        let candidate = parent.join(format!(
            ".{}.{}.{}.tmp",
            path.file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("archive"),
            std::process::id(),
            suffix
        ));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        match options.open(&candidate) {
            Ok(mut file) => {
                file.write_all(&bytes)?;
                file.sync_all()?;
                staging = Some(candidate);
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.into()),
        }
    }
    let staging = staging.ok_or_else(|| {
        AgentdError::Io(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "unable to allocate runtime.codex archive staging path",
        ))
    })?;
    match std::fs::hard_link(&staging, path) {
        Ok(()) => {
            sync_directory(parent)?;
            let _ = std::fs::remove_file(&staging);
            Ok(())
        }
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            let _ = std::fs::remove_file(&staging);
            let existing: RuntimeCodexArchiveEntryV1 = read_bounded_json(path)?;
            if existing == *entry {
                Ok(())
            } else {
                Err(AgentdError::Protocol(
                    "runtime.codex archive publication raced with conflicting evidence"
                        .to_string(),
                ))
            }
        }
        Err(error) => {
            let _ = std::fs::remove_file(&staging);
            Err(error.into())
        }
    }
}

fn read_bounded_json<T>(path: &Path) -> Result<T, AgentdError>
where
    T: for<'de> Deserialize<'de>,
{
    let metadata = std::fs::symlink_metadata(path)?;
    let maximum = u64::try_from(MAX_ARCHIVE_ENTRY_BYTES)
        .map_err(|_| AgentdError::Protocol("archive byte bound overflow".to_string()))?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.len() == 0
        || metadata.len() > maximum
    {
        return Err(AgentdError::Protocol(
            "invalid runtime.codex terminal archive entry".to_string(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o022 != 0 {
            return Err(AgentdError::Protocol(
                "runtime.codex archive entry is group/other writable".to_string(),
            ));
        }
    }
    let mut file = File::open(path)?;
    let capacity = usize::try_from(metadata.len()).unwrap_or(MAX_ARCHIVE_ENTRY_BYTES);
    let mut bytes = Vec::with_capacity(capacity.min(MAX_ARCHIVE_ENTRY_BYTES));
    file.take(maximum.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_ARCHIVE_ENTRY_BYTES {
        return Err(AgentdError::Protocol(
            "runtime.codex archive entry exceeded its read bound".to_string(),
        ));
    }
    Ok(serde_json::from_slice(&bytes)?)
}

fn sync_directory(path: &Path) -> Result<(), AgentdError> {
    File::open(path)?.sync_all()?;
    Ok(())
}
