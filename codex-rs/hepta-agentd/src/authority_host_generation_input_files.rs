//! Open-only path checks and retained descriptor checks for the fixed loader.
//! No helper initializes an Artifact, FinalUse journal or protected frontier.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Component;
use std::path::Path;

use codex_hepta_contracts::RootAuthorityDirectory;

use super::LoadPurpose;
use super::RootHostInitialGenerationFilesV1;
use super::invalid;
use crate::AgentdError;

#[derive(Clone, Copy)]
enum Access {
    ReadOnly,
    ReadWrite,
}

pub(super) fn require_descriptors(
    files: &RootHostInitialGenerationFilesV1,
    purpose: LoadPurpose,
) -> Result<(), AgentdError> {
    let mut identities = BTreeSet::new();
    for (file, access) in [
        (&files.registry_snapshot, Access::ReadOnly),
        (&files.selected_payload, Access::ReadOnly),
        (&files.withdrawal_snapshot, Access::ReadOnly),
        (&files.target_journal, Access::ReadWrite),
        (&files.target_witness, Access::ReadWrite),
    ] {
        let metadata = file.metadata()?;
        require_private_file(&metadata)?;
        // SAFETY: F_GETFL inspects this borrowed, still-owned descriptor.
        let flags = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_GETFL) };
        let expected = match access { Access::ReadOnly => libc::O_RDONLY, Access::ReadWrite => libc::O_RDWR };
        if flags < 0 || flags & libc::O_ACCMODE != expected
            || flags & libc::O_APPEND != 0
            || !identities.insert((metadata.dev(), metadata.ino()))
        {
            return Err(invalid("original generation descriptors must be distinct and have fixed access"));
        }
    }
    if matches!(purpose, LoadPurpose::Recover)
        && (files.target_journal.metadata()?.len() == 0 || files.target_witness.metadata()?.len() < 112)
    {
        return Err(invalid("original recovery cannot initialize an empty journal or witness"));
    }
    Ok(())
}

pub(super) fn require_artifact_directory(state: &Path, artifact: &Path) -> Result<(), AgentdError> {
    require_private_child(state, artifact)?;
    for name in ["writer", "transactions", "payloads", "registries", "witnesses", "heads"] {
        RootAuthorityDirectory::open(&artifact.join(name)).map_err(invalid)?;
    }
    let lock = open_private(&artifact.join("writer/owner.lock"))?;
    require_private_file(&lock.metadata()?)?;
    Ok(())
}

pub(super) fn require_existing_consumer(state: &Path, consumer: &Path) -> Result<(), AgentdError> {
    require_private_child(state, consumer)?;
    // These exact existing names distinguish this loader from the original
    // store's explicit first-start path. Do not call a genesis constructor.
    let lock = open_private(&consumer.join("authority.lock"))?;
    let claims = open_private(&consumer.join("authority.claims"))?;
    require_private_file(&lock.metadata()?)?;
    require_private_file(&claims.metadata()?)?;
    let mut header = open_private(&consumer.join("authority.json"))?;
    let before = header.metadata()?;
    if before.len() == 0 || before.len() > 8 * 1024 * 1024 {
        return Err(invalid("existing FinalUse state is absent or outside its original bound"));
    }
    let mut bytes = Vec::new();
    header.by_ref().take(8 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
    let after = header.metadata()?;
    if bytes.len() as u64 != before.len()
        || before.dev() != after.dev() || before.ino() != after.ino()
        || before.len() != after.len() || before.mtime() != after.mtime()
        || before.mtime_nsec() != after.mtime_nsec() || before.ctime() != after.ctime()
        || before.ctime_nsec() != after.ctime_nsec()
    {
        return Err(invalid("existing FinalUse header changed during bounded observation"));
    }
    let value: serde_json::Value = serde_json::from_slice(&bytes).map_err(invalid)?;
    if value.get("schema").and_then(serde_json::Value::as_u64) != Some(3) {
        return Err(invalid("this open-only loader requires the existing FinalUse journal schema"));
    }
    // Full trust, head and every nonce are subsequently verified by the actual
    // original FinalUse factory. This header observation grants no authority.
    Ok(())
}

fn require_private_child(state: &Path, path: &Path) -> Result<(), AgentdError> {
    if !state.is_absolute() || !path.is_absolute() || path == state || !path.starts_with(state)
        || path.components().any(|part| !matches!(part, Component::RootDir | Component::Normal(_)))
    {
        return Err(invalid("generation state must be an existing private child of the same Root state"));
    }
    RootAuthorityDirectory::open(path).map_err(invalid)?;
    Ok(())
}

fn open_private(path: &Path) -> Result<File, AgentdError> {
    let parent = path.parent().ok_or_else(|| invalid("missing original state parent"))?;
    RootAuthorityDirectory::open(parent).map_err(invalid)?;
    let file = OpenOptions::new().read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK).open(path)?;
    require_private_file(&file.metadata()?)?;
    Ok(file)
}

fn require_private_file(metadata: &std::fs::Metadata) -> Result<(), AgentdError> {
    if !metadata.is_file() || metadata.uid() != 0
        || metadata.mode() & 0o777 != 0o600 || metadata.nlink() != 1
    {
        return Err(invalid("original generation input must be a Root0600 single-link regular file"));
    }
    Ok(())
}
