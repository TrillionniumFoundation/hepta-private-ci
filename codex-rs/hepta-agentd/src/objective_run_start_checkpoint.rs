use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::fs::TryLockError;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_learning_ledger::RunStartAnchor;
use codex_hepta_learning_ledger::RunStartCheckpointOwnerV1;
use codex_hepta_learning_ledger::RunStartCheckpointV1;
use codex_hepta_learning_ledger::RunStartStoreError;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_trust::invalid;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 8 * 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointDocument {
    schema_version: u32,
    agent_id: String,
    binding: String,
    anchor_sequence: u64,
    anchor_digest: String,
    compacted_prefix_sequence: u64,
    compacted_prefix_digest: String,
    compacted_digest: String,
}

pub(crate) struct ObjectiveRunStartCheckpointFile {
    path: PathBuf,
    agent_id: String,
    binding: Digest32,
    _lock: File,
}

impl ObjectiveRunStartCheckpointFile {
    pub fn open(
        path: PathBuf,
        identity: &AgentdIdentity,
        binding: Digest32,
        initialize: bool,
    ) -> Result<Self, AgentdError> {
        validate_checkpoint_parent(&path, identity)?;
        let lock = acquire_checkpoint_lock(&path, identity)?;
        ensure_checkpoint_file(&path, identity, binding, initialize)?;
        validate_checkpoint_file(&path, identity)?;
        let file = Self {
            path,
            agent_id: identity.agent_id.to_string(),
            binding,
            _lock: lock,
        };
        file.read_checkpoint().map_err(checkpoint_error)?;
        Ok(file)
    }

    fn read_checkpoint(&self) -> Result<RunStartCheckpointV1, RunStartStoreError> {
        let bytes = read_private_file(&self.path)?;
        let document: CheckpointDocument =
            serde_json::from_slice(&bytes).map_err(|_| RunStartStoreError::Corrupt)?;
        if document.schema_version != CHECKPOINT_SCHEMA_VERSION
            || document.agent_id != self.agent_id
            || parse_digest(&document.binding)? != self.binding
        {
            return Err(RunStartStoreError::BindingMismatch);
        }
        let checkpoint = RunStartCheckpointV1 {
            anchor: RunStartAnchor {
                sequence: document.anchor_sequence,
                chain_digest: parse_digest(&document.anchor_digest)?,
            },
            compacted_prefix: RunStartAnchor {
                sequence: document.compacted_prefix_sequence,
                chain_digest: parse_digest(&document.compacted_prefix_digest)?,
            },
            compacted_digest: parse_digest(&document.compacted_digest)?,
        };
        if !checkpoint.is_well_formed() {
            return Err(RunStartStoreError::InvalidAnchor);
        }
        Ok(checkpoint)
    }

    fn replace_checkpoint(
        &self,
        expected: RunStartCheckpointV1,
        next: RunStartCheckpointV1,
    ) -> Result<(), RunStartStoreError> {
        let current = self.read_checkpoint()?;
        if current == next {
            return Ok(());
        }
        let append_transition = next.compacted_prefix == expected.compacted_prefix
            && next.compacted_digest == expected.compacted_digest
            && next.anchor.sequence
                == expected
                    .anchor
                    .sequence
                    .checked_add(1)
                    .ok_or(RunStartStoreError::Capacity)?;
        let compaction_transition = next.anchor == expected.anchor
            && next.compacted_prefix.sequence > expected.compacted_prefix.sequence
            && !next.compacted_digest.is_zero();
        if current != expected
            || !next.is_well_formed()
            || (!append_transition && !compaction_transition)
        {
            return Err(RunStartStoreError::RollbackDetected);
        }
        write_private_atomic(&self.path, &self.agent_id, self.binding, next)?;
        if self.read_checkpoint()? != next {
            return Err(RunStartStoreError::Indeterminate);
        }
        Ok(())
    }
}

impl RunStartCheckpointOwnerV1 for ObjectiveRunStartCheckpointFile {
    fn current_checkpoint(&self) -> Result<RunStartCheckpointV1, RunStartStoreError> {
        self.read_checkpoint()
    }

    fn compare_and_swap(
        &self,
        expected: RunStartCheckpointV1,
        next: RunStartCheckpointV1,
    ) -> Result<(), RunStartStoreError> {
        self.replace_checkpoint(expected, next)
    }
}

fn parse_digest(value: &str) -> Result<Digest32, RunStartStoreError> {
    Digest32::from_str(value).map_err(|_| RunStartStoreError::Corrupt)
}

fn checkpoint_error(error: RunStartStoreError) -> AgentdError {
    invalid(&format!("objective run-start checkpoint: {error}"))
}

#[cfg(unix)]
fn validate_checkpoint_parent(path: &Path, identity: &AgentdIdentity) -> Result<(), AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() || path.starts_with(&identity.home_root) {
        return Err(invalid(
            "objective run-start checkpoint must be an absolute path outside Agent home",
        ));
    }
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty() && *value != "." && *value != "..")
        .ok_or_else(|| invalid("objective run-start checkpoint filename must be UTF-8"))?;
    let parent = path
        .parent()
        .ok_or_else(|| invalid("objective run-start checkpoint has no parent"))?;
    if parent.canonicalize()? != parent || parent.join(name) != path {
        return Err(invalid(
            "objective run-start checkpoint parent must be canonical and symlink-free",
        ));
    }
    let home = std::fs::metadata(&identity.home_root)?;
    let directory = std::fs::symlink_metadata(parent)?;
    if !directory.is_dir()
        || directory.file_type().is_symlink()
        || directory.uid() != home.uid()
        || directory.mode() & 0o077 != 0
    {
        return Err(invalid(
            "objective run-start checkpoint parent must be private and owner-controlled",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_checkpoint_parent(_path: &Path, _identity: &AgentdIdentity) -> Result<(), AgentdError> {
    Err(invalid(
        "objective run-start checkpoint currently requires Unix ownership checks",
    ))
}

#[cfg(unix)]
fn checkpoint_lock_path(path: &Path) -> Result<PathBuf, AgentdError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("objective run-start checkpoint has no parent"))?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| invalid("objective run-start checkpoint filename must be UTF-8"))?;
    Ok(parent.join(format!(".{name}.lock")))
}

#[cfg(unix)]
fn acquire_checkpoint_lock(path: &Path, identity: &AgentdIdentity) -> Result<File, AgentdError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let lock_path = checkpoint_lock_path(path)?;
    let existed = lock_path.exists();
    let file = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(&lock_path)?;
    let opened = file.metadata()?;
    let linked = std::fs::symlink_metadata(&lock_path)?;
    let home = std::fs::metadata(&identity.home_root)?;
    if !opened.is_file()
        || linked.file_type().is_symlink()
        || linked.nlink() != 1
        || linked.uid() != home.uid()
        || linked.mode() & 0o077 != 0
        || opened.dev() != linked.dev()
        || opened.ino() != linked.ino()
    {
        return Err(invalid(
            "objective run-start checkpoint lock must be a private regular file",
        ));
    }
    match file.try_lock() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => {
            return Err(checkpoint_error(RunStartStoreError::Busy));
        }
        Err(TryLockError::Error(error)) => return Err(error.into()),
    }
    if !existed {
        file.sync_all()?;
        File::open(
            lock_path
                .parent()
                .ok_or_else(|| invalid("objective run-start checkpoint lock has no parent"))?,
        )?
        .sync_all()?;
    }
    Ok(file)
}

#[cfg(not(unix))]
fn acquire_checkpoint_lock(_path: &Path, _identity: &AgentdIdentity) -> Result<File, AgentdError> {
    Err(invalid(
        "objective run-start checkpoint currently requires Unix ownership checks",
    ))
}

fn ensure_checkpoint_file(
    path: &Path,
    identity: &AgentdIdentity,
    binding: Digest32,
    initialize: bool,
) -> Result<(), AgentdError> {
    if path.exists() {
        return Ok(());
    }
    if !initialize {
        return Err(checkpoint_error(RunStartStoreError::RollbackDetected));
    }
    create_checkpoint_file(path, identity.agent_id.as_str(), binding).map_err(checkpoint_error)
}

#[cfg(unix)]
fn create_checkpoint_file(
    path: &Path,
    agent_id: &str,
    binding: Digest32,
) -> Result<(), RunStartStoreError> {
    use std::os::unix::fs::OpenOptionsExt;

    let parent = path.parent().ok_or(RunStartStoreError::NotRegular)?;
    let payload = checkpoint_payload(agent_id, binding, RunStartCheckpointV1::ZERO)?;
    let result = (|| -> Result<(), RunStartStoreError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(path)?;
        file.write_all(&payload)?;
        file.sync_all()?;
        File::open(parent)?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(path);
        let _ = File::open(parent).and_then(|file| file.sync_all());
    }
    result
}

#[cfg(not(unix))]
fn create_checkpoint_file(
    _path: &Path,
    _agent_id: &str,
    _binding: Digest32,
) -> Result<(), RunStartStoreError> {
    Err(RunStartStoreError::NotRegular)
}

#[cfg(unix)]
fn validate_checkpoint_file(path: &Path, identity: &AgentdIdentity) -> Result<(), AgentdError> {
    use std::os::unix::fs::MetadataExt;

    let home = std::fs::metadata(&identity.home_root)?;
    validate_file_metadata(path, home.uid()).map_err(checkpoint_error)?;
    if path.canonicalize()? != path {
        return Err(invalid(
            "objective run-start checkpoint must be canonical and symlink-free",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_checkpoint_file(_path: &Path, _identity: &AgentdIdentity) -> Result<(), AgentdError> {
    Err(invalid(
        "objective run-start checkpoint currently requires Unix ownership checks",
    ))
}

#[cfg(unix)]
fn validate_file_metadata(path: &Path, owner_uid: u32) -> Result<(), RunStartStoreError> {
    use std::os::unix::fs::MetadataExt;

    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != owner_uid
        || metadata.mode() & 0o077 != 0
        || metadata.len() == 0
        || metadata.len() > MAX_CHECKPOINT_BYTES
    {
        return Err(RunStartStoreError::NotRegular);
    }
    Ok(())
}

#[cfg(unix)]
fn read_private_file(path: &Path) -> Result<Vec<u8>, RunStartStoreError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let before = std::fs::symlink_metadata(path)?;
    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)?;
    let opened = file.metadata()?;
    let identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(RunStartStoreError::Indeterminate);
    }
    let mut bytes = Vec::new();
    std::io::Read::by_ref(&mut file)
        .take(MAX_CHECKPOINT_BYTES + 1)
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if bytes.len() as u64 > MAX_CHECKPOINT_BYTES
        || identity(&after) != identity(&before)
        || identity(&file.metadata()?) != identity(&before)
    {
        return Err(RunStartStoreError::Indeterminate);
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_file(_path: &Path) -> Result<Vec<u8>, RunStartStoreError> {
    Err(RunStartStoreError::NotRegular)
}

fn checkpoint_payload(
    agent_id: &str,
    binding: Digest32,
    checkpoint: RunStartCheckpointV1,
) -> Result<Vec<u8>, RunStartStoreError> {
    let document = CheckpointDocument {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        agent_id: agent_id.to_string(),
        binding: binding.to_string(),
        anchor_sequence: checkpoint.anchor.sequence,
        anchor_digest: checkpoint.anchor.chain_digest.to_string(),
        compacted_prefix_sequence: checkpoint.compacted_prefix.sequence,
        compacted_prefix_digest: checkpoint.compacted_prefix.chain_digest.to_string(),
        compacted_digest: checkpoint.compacted_digest.to_string(),
    };
    let payload = serde_json::to_vec(&document).map_err(|_| RunStartStoreError::Corrupt)?;
    if payload.is_empty() || payload.len() as u64 > MAX_CHECKPOINT_BYTES {
        return Err(RunStartStoreError::Capacity);
    }
    Ok(payload)
}

#[cfg(unix)]
fn write_private_atomic(
    path: &Path,
    agent_id: &str,
    binding: Digest32,
    next: RunStartCheckpointV1,
) -> Result<(), RunStartStoreError> {
    use std::os::unix::fs::OpenOptionsExt;

    let parent = path.parent().ok_or(RunStartStoreError::NotRegular)?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(RunStartStoreError::NotRegular)?;
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| RunStartStoreError::Indeterminate)?
        .as_nanos();
    let temporary = parent.join(format!(
        ".{name}.{}.{}.{}.{}.tmp",
        std::process::id(),
        next.anchor.sequence,
        next.compacted_prefix.sequence,
        nonce
    ));
    let payload = checkpoint_payload(agent_id, binding, next)?;
    let result = (|| -> Result<(), RunStartStoreError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(&temporary)?;
        file.write_all(&payload)?;
        file.sync_all()?;
        std::fs::rename(&temporary, path)?;
        File::open(parent)?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(not(unix))]
fn write_private_atomic(
    _path: &Path,
    _agent_id: &str,
    _binding: Digest32,
    _next: RunStartCheckpointV1,
) -> Result<(), RunStartStoreError> {
    Err(RunStartStoreError::NotRegular)
}

#[cfg(test)]
#[path = "objective_run_start_checkpoint_tests.rs"]
mod tests;
