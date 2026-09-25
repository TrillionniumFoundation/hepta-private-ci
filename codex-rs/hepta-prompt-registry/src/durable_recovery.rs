//! Independently retained recovery checkpoint for rollback-resistant registry reopen.
//!
//! The registry manifest and payload extents remain one atomic owner state. This
//! checkpoint is intentionally stored outside that directory. Every semantic
//! mutation first publishes an exact pending successor here, then commits the
//! registry, then promotes the successor. Reopen reconciles only the exact
//! predecessor or pending successor; any other relation fails closed.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::DurableRegistryError;
use crate::PromptRegistry;

const CHECKPOINT_SCHEMA: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 16 * 1024;
const CHECKPOINT_DOMAIN: &[u8] = b"hepta.prompt-registry.recovery-checkpoint.v1\0";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredCheckpoint {
    generation: u64,
    revision: u64,
    lifecycle_frontier: u64,
    revocation_frontier: u64,
    registry_digest: [u8; 32],
    witness_digest: [u8; 32],
}

impl StoredCheckpoint {
    fn from_registry(owner_id: &str, generation: u64, registry: &PromptRegistry) -> Self {
        let mut value = Self {
            generation,
            revision: registry.revision().get(),
            lifecycle_frontier: registry.lifecycle_frontier(),
            revocation_frontier: registry.revocation_frontier(),
            registry_digest: registry.snapshot_digest().into_array(),
            witness_digest: [0; 32],
        };
        value.witness_digest = value.compute_digest(owner_id).into_array();
        value
    }

    fn validate(&self, owner_id: &str) -> Result<(), DurableRegistryError> {
        if self.generation == 0
            || self.revision == 0
            || self.revocation_frontier > self.lifecycle_frontier
            || self.lifecycle_frontier > self.revision
            || Digest32::from_array(self.registry_digest).is_zero()
            || Digest32::from_array(self.witness_digest).is_zero()
            || self.compute_digest(owner_id) != Digest32::from_array(self.witness_digest)
        {
            return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
        }
        Ok(())
    }

    fn matches_registry(&self, registry: &PromptRegistry) -> bool {
        self.revision == registry.revision().get()
            && self.lifecycle_frontier == registry.lifecycle_frontier()
            && self.revocation_frontier == registry.revocation_frontier()
            && Digest32::from_array(self.registry_digest) == registry.snapshot_digest()
    }

    fn compute_digest(&self, owner_id: &str) -> Digest32 {
        let owner = owner_id.as_bytes();
        Digest32::of_parts(&[
            CHECKPOINT_DOMAIN,
            &(owner.len() as u64).to_be_bytes(),
            owner,
            &self.generation.to_be_bytes(),
            &self.revision.to_be_bytes(),
            &self.lifecycle_frontier.to_be_bytes(),
            &self.revocation_frontier.to_be_bytes(),
            &self.registry_digest,
        ])
    }
}

#[derive(Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointDocument {
    schema: u32,
    owner_id: String,
    current: StoredCheckpoint,
    pending: Option<StoredCheckpoint>,
}

impl CheckpointDocument {
    fn validate(&self, owner_id: &str) -> Result<(), DurableRegistryError> {
        if self.schema != CHECKPOINT_SCHEMA || self.owner_id != owner_id {
            return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
        }
        self.current.validate(owner_id)?;
        if let Some(pending) = &self.pending {
            pending.validate(owner_id)?;
            if pending.generation
                != self
                    .current
                    .generation
                    .checked_add(1)
                    .ok_or(DurableRegistryError::CapacityExceeded)?
                || pending.revision <= self.current.revision
                || pending.lifecycle_frontier < self.current.lifecycle_frontier
                || pending.revocation_frontier < self.current.revocation_frontier
            {
                return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
            }
        }
        Ok(())
    }
}

pub(super) struct RecoveryCheckpointFile {
    path: PathBuf,
    owner_id: String,
    _lock: File,
}

impl RecoveryCheckpointFile {
    /// Pure preflight before Store::open creates its first lock. Invalid caller
    /// configuration must not strand an otherwise uninitialized directory.
    pub(super) fn validate_open_configuration(
        path: &Path,
        registry_directory: &Path,
        owner_id: &str,
    ) -> Result<(), DurableRegistryError> {
        validate_owner(owner_id)?;
        if !path.is_absolute()
            || !registry_directory.is_absolute()
            || path
                .components()
                .any(|value| value == std::path::Component::ParentDir)
            || registry_directory
                .components()
                .any(|value| value == std::path::Component::ParentDir)
            || checkpoint_parent(path)?.starts_with(registry_directory)
            || path.file_name().is_none()
        {
            return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
        }
        // Reject unsafe or uncreatable parents before Store::open can create
        // a writer-lock sentinel. This is preflight only; open revalidates the
        // actual directory and file after acquiring the owner locks.
        let parent = checkpoint_parent(path)?;
        let resolved_parent = resolve_directory_for_preflight(parent)?;
        let resolved_registry = resolve_directory_for_preflight(registry_directory)?;
        if resolved_parent.starts_with(&resolved_registry) {
            return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
        }
        #[cfg(unix)]
        if parent.exists() {
            use std::os::unix::fs::MetadataExt;
            let metadata = std::fs::metadata(parent)
                .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
            if !metadata.is_dir()
                || metadata.mode() & 0o077 != 0
                || metadata.uid() != rustix::process::geteuid().as_raw()
            {
                return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
            }
        }
        if path.exists() && !registry_directory.join("registry.json").exists() {
            // A retained witness is not permission to create an empty replacement.
            return Err(DurableRegistryError::RecoveryCheckpointRequired);
        }
        Ok(())
    }
    pub(super) fn open_or_initialize(
        path: &Path,
        registry_directory: &Path,
        owner_id: &str,
        checkpoint_required: bool,
        registry: &PromptRegistry,
    ) -> Result<Self, DurableRegistryError> {
        validate_owner(owner_id)?;
        let parent = prepare_checkpoint_parent(path, registry_directory)?;
        let lock_path = sibling(path, "lock")?;
        let lock = open_private_file(&lock_path, true, true)?;
        lock.try_lock()
            .map_err(|_| DurableRegistryError::StateLocked)?;
        let file = Self {
            path: path.to_path_buf(),
            owner_id: owner_id.to_owned(),
            _lock: lock,
        };
        if path.exists() {
            file.reconcile(registry)?;
        } else {
            if checkpoint_required {
                return Err(DurableRegistryError::RecoveryCheckpointRequired);
            }
            let current = StoredCheckpoint::from_registry(owner_id, 1, registry);
            let document = CheckpointDocument {
                schema: CHECKPOINT_SCHEMA,
                owner_id: owner_id.to_owned(),
                current,
                pending: None,
            };
            file.write(&parent, &document)?;
        }
        Ok(file)
    }

    pub(super) fn prepare(
        &self,
        current_registry: &PromptRegistry,
        next_registry: &PromptRegistry,
    ) -> Result<StoredCheckpoint, DurableRegistryError> {
        let mut document = self.read()?;
        document.validate(&self.owner_id)?;
        if document.pending.is_some() || !document.current.matches_registry(current_registry) {
            return Err(DurableRegistryError::RollbackDetected);
        }
        let generation = document
            .current
            .generation
            .checked_add(1)
            .ok_or(DurableRegistryError::CapacityExceeded)?;
        let pending = StoredCheckpoint::from_registry(&self.owner_id, generation, next_registry);
        if pending.revision <= document.current.revision
            || pending.lifecycle_frontier < document.current.lifecycle_frontier
            || pending.revocation_frontier < document.current.revocation_frontier
        {
            return Err(DurableRegistryError::RollbackDetected);
        }
        document.pending = Some(pending.clone());
        let parent = checkpoint_parent(&self.path)?;
        self.write(parent, &document)?;
        Ok(pending)
    }

    pub(super) fn promote(&self, expected: &StoredCheckpoint) -> Result<(), DurableRegistryError> {
        let mut document = self.read()?;
        document.validate(&self.owner_id)?;
        if document.pending.as_ref() != Some(expected) {
            return Err(DurableRegistryError::RollbackDetected);
        }
        document.current = expected.clone();
        document.pending = None;
        let parent = checkpoint_parent(&self.path)?;
        self.write(parent, &document)
    }

    pub(super) fn abort(
        &self,
        expected: &StoredCheckpoint,
        current_registry: &PromptRegistry,
    ) -> Result<(), DurableRegistryError> {
        let mut document = self.read()?;
        document.validate(&self.owner_id)?;
        if document.pending.as_ref() != Some(expected)
            || !document.current.matches_registry(current_registry)
        {
            return Err(DurableRegistryError::RollbackDetected);
        }
        document.pending = None;
        let parent = checkpoint_parent(&self.path)?;
        self.write(parent, &document)
    }

    fn reconcile(&self, registry: &PromptRegistry) -> Result<(), DurableRegistryError> {
        let mut document = self.read()?;
        document.validate(&self.owner_id)?;
        if document.current.matches_registry(registry) {
            if document.pending.take().is_some() {
                let parent = checkpoint_parent(&self.path)?;
                self.write(parent, &document)?;
            }
            return Ok(());
        }
        if document
            .pending
            .as_ref()
            .is_some_and(|pending| pending.matches_registry(registry))
        {
            document.current = document
                .pending
                .take()
                .ok_or(DurableRegistryError::RollbackDetected)?;
            let parent = checkpoint_parent(&self.path)?;
            self.write(parent, &document)?;
            return Ok(());
        }
        Err(DurableRegistryError::RollbackDetected)
    }

    fn read(&self) -> Result<CheckpointDocument, DurableRegistryError> {
        let file = open_private_file(&self.path, false, false)?;
        let mut bytes = Vec::new();
        file.take(MAX_CHECKPOINT_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_CHECKPOINT_BYTES {
            return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
        }
        let document: CheckpointDocument = serde_json::from_slice(&bytes)
            .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
        document.validate(&self.owner_id)?;
        Ok(document)
    }

    fn write(
        &self,
        parent: &Path,
        document: &CheckpointDocument,
    ) -> Result<(), DurableRegistryError> {
        document.validate(&self.owner_id)?;
        let bytes = serde_json::to_vec(document)
            .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_CHECKPOINT_BYTES {
            return Err(DurableRegistryError::CapacityExceeded);
        }
        let next_path = sibling(&self.path, "next")?;
        let mut next = open_private_file(&next_path, true, true)?;
        next.set_len(0)
            .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
        next.write_all(&bytes)
            .and_then(|()| next.sync_all())
            .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
        std::fs::rename(&next_path, &self.path)
            .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
        if self.read()? != *document {
            return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
        }
        Ok(())
    }
}

// Resolve an existing directory or the single not-yet-created final component.
// The later open only creates that component, never an implicit parent tree.
fn resolve_directory_for_preflight(path: &Path) -> Result<PathBuf, DurableRegistryError> {
    match path.canonicalize() {
        Ok(resolved) => Ok(resolved),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let parent = path
                .parent()
                .ok_or(DurableRegistryError::UnsafeRecoveryCheckpoint)?;
            let name = path
                .file_name()
                .ok_or(DurableRegistryError::UnsafeRecoveryCheckpoint)?;
            Ok(parent
                .canonicalize()
                .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?
                .join(name))
        }
        Err(_) => Err(DurableRegistryError::UnsafeRecoveryCheckpoint),
    }
}

fn validate_owner(owner_id: &str) -> Result<(), DurableRegistryError> {
    if owner_id.is_empty() || owner_id.len() > 256 || owner_id.as_bytes().contains(&0) {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    Ok(())
}

#[cfg(unix)]
fn prepare_checkpoint_parent(
    checkpoint_path: &Path,
    registry_directory: &Path,
) -> Result<PathBuf, DurableRegistryError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    if !checkpoint_path.is_absolute() || !registry_directory.is_absolute() {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    let parent = checkpoint_parent(checkpoint_path)?;
    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(parent)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    let canonical_parent = parent
        .canonicalize()
        .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
    let canonical_registry = registry_directory
        .canonicalize()
        .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
    if canonical_parent == canonical_registry || canonical_parent.starts_with(&canonical_registry) {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    let metadata = std::fs::metadata(&canonical_parent)
        .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    Ok(canonical_parent)
}

#[cfg(not(unix))]
fn prepare_checkpoint_parent(
    _checkpoint_path: &Path,
    _registry_directory: &Path,
) -> Result<PathBuf, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeRecoveryCheckpoint)
}

fn checkpoint_parent(path: &Path) -> Result<&Path, DurableRegistryError> {
    path.parent()
        .ok_or(DurableRegistryError::UnsafeRecoveryCheckpoint)
}

fn sibling(path: &Path, suffix: &str) -> Result<PathBuf, DurableRegistryError> {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(DurableRegistryError::UnsafeRecoveryCheckpoint)?;
    Ok(path.with_file_name(format!("{name}.{suffix}")))
}

#[cfg(unix)]
fn open_private_file(
    path: &Path,
    create: bool,
    writable: bool,
) -> Result<File, DurableRegistryError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let mut options = OpenOptions::new();
    options
        .read(true)
        .write(writable)
        .create(create)
        .mode(0o600);
    let file = options
        .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
        .open(path)
        .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
    let metadata = file
        .metadata()
        .map_err(|_| DurableRegistryError::UnsafeRecoveryCheckpoint)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    Ok(file)
}

#[cfg(not(unix))]
fn open_private_file(
    _path: &Path,
    _create: bool,
    _writable: bool,
) -> Result<File, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeRecoveryCheckpoint)
}
