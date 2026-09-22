#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_evidence::ReplayCheckpoint;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_trust::invalid;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 4096;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointDocument {
    schema_version: u32,
    agent_id: String,
    generation: u64,
    digest: String,
}

pub(crate) struct ReplayCheckpointFile {
    path: PathBuf,
    agent_id: String,
}

impl ReplayCheckpointFile {
    pub fn open(
        path: PathBuf,
        identity: &AgentdIdentity,
    ) -> Result<(Self, ReplayCheckpoint), AgentdError> {
        validate_path(&path, identity)?;
        let file = Self {
            path,
            agent_id: identity.agent_id.to_string(),
        };
        let checkpoint = file.read()?;
        Ok((file, checkpoint))
    }

    pub fn read(&self) -> Result<ReplayCheckpoint, AgentdError> {
        let bytes = read_private_file(&self.path)?;
        let document: CheckpointDocument = serde_json::from_slice(&bytes)?;
        if document.schema_version != CHECKPOINT_SCHEMA_VERSION
            || document.agent_id != self.agent_id
            || document.generation == 0
        {
            return Err(invalid("external replay checkpoint identity/schema is invalid"));
        }
        let digest = document
            .digest
            .parse::<Digest32>()
            .map_err(|_| invalid("external replay checkpoint digest is invalid"))?;
        if digest.is_zero() {
            return Err(invalid("external replay checkpoint digest is empty"));
        }
        Ok(ReplayCheckpoint {
            generation: document.generation,
            digest,
        })
    }

    /// Atomically replace the independently retained witness. The old file must
    /// still contain the exact predecessor; a lost response is idempotent when
    /// the file already contains the requested next checkpoint.
    pub fn replace(
        &self,
        expected: ReplayCheckpoint,
        next: ReplayCheckpoint,
    ) -> Result<(), AgentdError> {
        let current = self.read()?;
        if current == next {
            return Ok(());
        }
        if current != expected
            || next.generation
                != expected
                    .generation
                    .checked_add(1)
                    .ok_or_else(|| invalid("external replay checkpoint generation overflow"))?
            || next.digest.is_zero()
        {
            return Err(invalid("external replay checkpoint CAS mismatch"));
        }
        write_private_atomic(&self.path, &self.agent_id, next)?;
        if self.read()? != next {
            return Err(invalid(
                "external replay checkpoint changed during publication",
            ));
        }
        Ok(())
    }
}

#[cfg(unix)]
fn validate_path(path: &Path, identity: &AgentdIdentity) -> Result<(), AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() || path.starts_with(&identity.home_root) {
        return Err(invalid(
            "external replay checkpoint must be an absolute path outside Agent home",
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| invalid("external replay checkpoint has no parent"))?;
    if parent.canonicalize()? != parent {
        return Err(invalid(
            "external replay checkpoint parent must be canonical and symlink-free",
        ));
    }
    let home = std::fs::metadata(&identity.home_root)?;
    let directory = std::fs::metadata(parent)?;
    if !directory.is_dir()
        || directory.uid() != home.uid()
        || directory.mode() & 0o077 != 0
    {
        return Err(invalid(
            "external replay checkpoint parent must be a private owner-controlled directory",
        ));
    }
    validate_file_metadata(path, home.uid())?;
    if path.canonicalize()? != path {
        return Err(invalid(
            "external replay checkpoint must be canonical and symlink-free",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_path(_path: &Path, _identity: &AgentdIdentity) -> Result<(), AgentdError> {
    Err(invalid(
        "external replay checkpoint currently requires Unix ownership checks",
    ))
}

#[cfg(unix)]
fn validate_file_metadata(path: &Path, owner_uid: u32) -> Result<(), AgentdError> {
    use std::os::unix::fs::MetadataExt;

    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != owner_uid
        || metadata.mode() & 0o077 != 0
        || metadata.len() > MAX_CHECKPOINT_BYTES
    {
        return Err(invalid(
            "external replay checkpoint must be a private owner-controlled regular file",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn read_private_file(path: &Path) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    let before = std::fs::symlink_metadata(path)?;
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(invalid("external replay checkpoint changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(MAX_CHECKPOINT_BYTES + 1)
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if bytes.len() as u64 > MAX_CHECKPOINT_BYTES
        || identity(&after) != identity(&before)
        || identity(&file.metadata()?) != identity(&before)
    {
        return Err(invalid("external replay checkpoint changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_file(_path: &Path) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "external replay checkpoint currently requires Unix ownership checks",
    ))
}

#[cfg(unix)]
fn write_private_atomic(
    path: &Path,
    agent_id: &str,
    next: ReplayCheckpoint,
) -> Result<(), AgentdError> {
    use std::os::unix::fs::OpenOptionsExt;

    let parent = path
        .parent()
        .ok_or_else(|| invalid("external replay checkpoint has no parent"))?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| invalid("external replay checkpoint filename must be UTF-8"))?;
    let temporary = parent.join(format!(
        ".{name}.{}.{}.tmp",
        std::process::id(),
        next.generation
    ));
    let document = CheckpointDocument {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        agent_id: agent_id.to_string(),
        generation: next.generation,
        digest: next.digest.to_string(),
    };
    let payload = serde_json::to_vec(&document)?;
    if payload.len() as u64 > MAX_CHECKPOINT_BYTES {
        return Err(invalid("external replay checkpoint encoding is too large"));
    }
    let result = (|| -> Result<(), AgentdError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
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
    _next: ReplayCheckpoint,
) -> Result<(), AgentdError> {
    Err(invalid(
        "external replay checkpoint currently requires Unix ownership checks",
    ))
}
