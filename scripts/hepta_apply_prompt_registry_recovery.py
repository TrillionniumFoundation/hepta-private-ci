#!/usr/bin/env python3
"""Apply the reviewed prompt.registry guarded-recovery convergence patch."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DURABLE = ROOT / "codex-rs/hepta-prompt-registry/src/durable.rs"
RECOVERY = ROOT / "codex-rs/hepta-prompt-registry/src/durable_recovery.rs"
TESTS = ROOT / "codex-rs/hepta-prompt-registry/src/durable_payloads_tests.rs"

source = DURABLE.read_text()
old = '''#[path = "durable_payloads.rs"]
mod payloads;
'''
new = '''#[path = "durable_payloads.rs"]
mod payloads;
#[path = "durable_recovery.rs"]
mod recovery;
'''
assert source.count(old) == 1
source = source.replace(old, new, 1)

old = '''pub struct DurablePromptRegistry {
    registry: PromptRegistry,
    store: Store,
    poisoned: bool,
}
'''
new = '''pub struct DurablePromptRegistry {
    registry: PromptRegistry,
    store: Store,
    recovery: Option<recovery::RecoveryCheckpointStore>,
    poisoned: bool,
}
'''
assert source.count(old) == 1
source = source.replace(old, new, 1)

old = '''impl DurablePromptRegistry {
    pub fn open_state_dir(
        directory: &Path,
        maximum_records: usize,
    ) -> Result<Self, DurableRegistryError> {
        // Validate caller policy before touching the state directory. A rejected
        // first open must not leave a lock sentinel that makes a corrected retry
        // look like a previously initialized store whose manifest disappeared.
        if maximum_records == 0 {
            return Err(DurableRegistryError::Core(Error::ZeroCapacity));
        }
        let (mut store, stored) = Store::open(directory)?;
        let registry = match stored {
            Some(StoredAny::V2(stored)) => restore_v2(stored, maximum_records)?,
            Some(StoredAny::V1(stored)) => migrate_v1(stored, maximum_records)?,
            None => PromptRegistry::new(maximum_records).map_err(DurableRegistryError::Core)?,
        };
        if store.payloads.is_initialized() {
            store.payloads.discard_unselected_tail(&store.root)?;
        } else {
            store.persist(&registry)?;
        }
        Ok(Self {
            registry,
            store,
            poisoned: false,
        })
    }
'''
new = '''impl DurablePromptRegistry {
    pub fn open_state_dir(
        directory: &Path,
        maximum_records: usize,
    ) -> Result<Self, DurableRegistryError> {
        Self::open_state_dir_internal(directory, maximum_records, None)
    }

    /// Open the authoritative registry with an independently retained recovery
    /// checkpoint. The checkpoint must live outside the registry backup domain;
    /// a coherent but older registry backup is rejected instead of blessed.
    pub fn open_state_dir_with_recovery_checkpoint(
        directory: &Path,
        checkpoint_file: &Path,
        owner_id: &str,
        maximum_records: usize,
    ) -> Result<Self, DurableRegistryError> {
        if !checkpoint_file.is_absolute()
            || (directory.is_absolute() && checkpoint_file.starts_with(directory))
        {
            return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
        }
        Self::open_state_dir_internal(
            directory,
            maximum_records,
            Some((checkpoint_file, owner_id)),
        )
    }

    fn open_state_dir_internal(
        directory: &Path,
        maximum_records: usize,
        recovery: Option<(&Path, &str)>,
    ) -> Result<Self, DurableRegistryError> {
        // Validate caller policy before touching the state directory. A rejected
        // first open must not leave a lock sentinel that makes a corrected retry
        // look like a previously initialized store whose manifest disappeared.
        if maximum_records == 0 {
            return Err(DurableRegistryError::Core(Error::ZeroCapacity));
        }
        let (mut store, stored) = Store::open(directory)?;
        let registry = match stored {
            Some(StoredAny::V2(stored)) => restore_v2(stored, maximum_records)?,
            Some(StoredAny::V1(stored)) => migrate_v1(stored, maximum_records)?,
            None => PromptRegistry::new(maximum_records).map_err(DurableRegistryError::Core)?,
        };
        if store.payloads.is_initialized() {
            store.payloads.discard_unselected_tail(&store.root)?;
        } else {
            store.persist(&registry)?;
        }
        let recovery = recovery
            .map(|(checkpoint_file, owner_id)| {
                recovery::RecoveryCheckpointStore::open(checkpoint_file, owner_id, &registry)
            })
            .transpose()?;
        Ok(Self {
            registry,
            store,
            recovery,
            poisoned: false,
        })
    }
'''
assert source.count(old) == 1
source = source.replace(old, new, 1)

old = '''        let mut next = self.registry.clone();
        let receipt = mutation(&mut next).map_err(DurableRegistryError::Core)?;
        if receipt.disposition != crate::MutationDisposition::Unchanged {
            match self.store.persist(&next) {
                Ok(()) => self.registry = next,
                Err(DurableRegistryError::IndeterminateDurability) => {
                    self.poisoned = true;
                    return Err(DurableRegistryError::IndeterminateDurability);
                }
                Err(error) => return Err(error),
            }
        }
        Ok(receipt)
'''
new = '''        let mut next = self.registry.clone();
        let receipt = mutation(&mut next).map_err(DurableRegistryError::Core)?;
        if receipt.disposition != crate::MutationDisposition::Unchanged {
            let checkpoint_prepared = if let Some(recovery) = self.recovery.as_mut() {
                recovery.prepare(&next)?;
                true
            } else {
                false
            };
            match self.store.persist(&next) {
                Ok(()) => {
                    if let Some(recovery) = self.recovery.as_mut()
                        && let Err(error) = recovery.promote(&next)
                    {
                        self.poisoned = true;
                        return Err(error);
                    }
                    self.registry = next;
                }
                Err(DurableRegistryError::IndeterminateDurability) => {
                    self.poisoned = true;
                    return Err(DurableRegistryError::IndeterminateDurability);
                }
                Err(error) => {
                    if checkpoint_prepared
                        && let Some(recovery) = self.recovery.as_mut()
                        && recovery.abort(&self.registry).is_err()
                    {
                        self.poisoned = true;
                        return Err(DurableRegistryError::IndeterminateDurability);
                    }
                    return Err(error);
                }
            }
        }
        Ok(receipt)
'''
assert source.count(old) == 1
source = source.replace(old, new, 1)

old = '''    UnsafeStateDirectory,
    StateLocked,
'''
new = '''    UnsafeStateDirectory,
    UnsafeRecoveryCheckpoint,
    RecoveryCheckpointMismatch,
    RecoveryCheckpointCorrupt,
    StateLocked,
'''
assert source.count(old) == 1
source = source.replace(old, new, 1)
DURABLE.write_text(source)

RECOVERY.write_text(r'''//! Independently retained prompt-registry recovery checkpoint.
//!
//! The registry store and checkpoint use a two-phase relation: the checkpoint
//! first records the exact pending successor, then the registry publishes, then
//! the checkpoint promotes. Reopen accepts only the selected predecessor or the
//! exact pending successor. A coherent older registry backup therefore cannot
//! erase a revocation while the checkpoint remains current.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

use super::DurableRegistryError;
use super::map_precommit_io;
use crate::PromptRegistry;

const CHECKPOINT_SCHEMA: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 64 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RecoveryPoint {
    revision: u64,
    registry_digest: [u8; 32],
    lifecycle_frontier: u64,
    revocation_frontier: u64,
}

impl RecoveryPoint {
    fn from_registry(registry: &PromptRegistry) -> Self {
        Self {
            revision: registry.revision().get(),
            registry_digest: registry.snapshot_digest().into_array(),
            lifecycle_frontier: registry.lifecycle_frontier(),
            revocation_frontier: registry.revocation_frontier(),
        }
    }

    fn validate(&self) -> Result<(), DurableRegistryError> {
        if self.revision == 0
            || self.registry_digest == [0; 32]
            || self.revocation_frontier > self.lifecycle_frontier
            || self.lifecycle_frontier > self.revision
        {
            return Err(DurableRegistryError::RecoveryCheckpointCorrupt);
        }
        Ok(())
    }

    fn is_strict_successor_of(&self, predecessor: &Self) -> bool {
        self.revision > predecessor.revision
            && self.lifecycle_frontier >= predecessor.lifecycle_frontier
            && self.revocation_frontier >= predecessor.revocation_frontier
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredRecoveryCheckpoint {
    schema: u32,
    owner_id: String,
    current: RecoveryPoint,
    pending: Option<RecoveryPoint>,
}

pub(super) struct RecoveryCheckpointStore {
    checkpoint_file: PathBuf,
    next_file: PathBuf,
    parent: PathBuf,
    _lock: File,
    stored: StoredRecoveryCheckpoint,
}

impl RecoveryCheckpointStore {
    pub(super) fn open(
        checkpoint_file: &Path,
        owner_id: &str,
        registry: &PromptRegistry,
    ) -> Result<Self, DurableRegistryError> {
        validate_owner_id(owner_id)?;
        let parent = checkpoint_file
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
            .ok_or(DurableRegistryError::UnsafeRecoveryCheckpoint)?
            .to_path_buf();
        prepare_parent(&parent)?;
        let lock_file = sibling(checkpoint_file, ".lock")?;
        let lock = open_private_file(&lock_file, true)?;
        lock.try_lock()
            .map_err(|_| DurableRegistryError::StateLocked)?;
        let next_file = sibling(checkpoint_file, ".next")?;
        let current_point = RecoveryPoint::from_registry(registry);
        current_point.validate()?;
        let stored = if checkpoint_file.exists() {
            read_checkpoint(checkpoint_file)?
        } else {
            let stored = StoredRecoveryCheckpoint {
                schema: CHECKPOINT_SCHEMA,
                owner_id: owner_id.to_owned(),
                current: current_point.clone(),
                pending: None,
            };
            persist_checkpoint(checkpoint_file, &next_file, &parent, &stored)?;
            stored
        };
        if stored.schema != CHECKPOINT_SCHEMA || stored.owner_id != owner_id {
            return Err(DurableRegistryError::RecoveryCheckpointMismatch);
        }
        stored.current.validate()?;
        if let Some(pending) = &stored.pending {
            pending.validate()?;
            if !pending.is_strict_successor_of(&stored.current) {
                return Err(DurableRegistryError::RecoveryCheckpointCorrupt);
            }
        }
        let mut value = Self {
            checkpoint_file: checkpoint_file.to_path_buf(),
            next_file,
            parent,
            _lock: lock,
            stored,
        };
        value.reconcile(&current_point)?;
        Ok(value)
    }

    fn reconcile(&mut self, registry: &RecoveryPoint) -> Result<(), DurableRegistryError> {
        match self.stored.pending.clone() {
            Some(pending) if &pending == registry => {
                self.stored.current = pending;
                self.stored.pending = None;
                self.persist()
            }
            Some(_) if &self.stored.current == registry => {
                self.stored.pending = None;
                self.persist()
            }
            None if &self.stored.current == registry => Ok(()),
            _ => Err(DurableRegistryError::RecoveryCheckpointMismatch),
        }
    }

    pub(super) fn prepare(
        &mut self,
        successor: &PromptRegistry,
    ) -> Result<(), DurableRegistryError> {
        if self.stored.pending.is_some() {
            return Err(DurableRegistryError::RecoveryCheckpointCorrupt);
        }
        let successor = RecoveryPoint::from_registry(successor);
        successor.validate()?;
        if !successor.is_strict_successor_of(&self.stored.current) {
            return Err(DurableRegistryError::RecoveryCheckpointMismatch);
        }
        self.stored.pending = Some(successor);
        self.persist()
    }

    pub(super) fn promote(
        &mut self,
        successor: &PromptRegistry,
    ) -> Result<(), DurableRegistryError> {
        let successor = RecoveryPoint::from_registry(successor);
        if self.stored.pending.as_ref() != Some(&successor) {
            return Err(DurableRegistryError::RecoveryCheckpointMismatch);
        }
        self.stored.current = successor;
        self.stored.pending = None;
        self.persist()
    }

    pub(super) fn abort(
        &mut self,
        predecessor: &PromptRegistry,
    ) -> Result<(), DurableRegistryError> {
        if self.stored.current != RecoveryPoint::from_registry(predecessor)
            || self.stored.pending.is_none()
        {
            return Err(DurableRegistryError::RecoveryCheckpointMismatch);
        }
        self.stored.pending = None;
        self.persist()
    }

    fn persist(&self) -> Result<(), DurableRegistryError> {
        persist_checkpoint(
            &self.checkpoint_file,
            &self.next_file,
            &self.parent,
            &self.stored,
        )
    }
}

fn validate_owner_id(owner_id: &str) -> Result<(), DurableRegistryError> {
    if owner_id.is_empty() || owner_id.len() > 256 || owner_id.as_bytes().contains(&0) {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    Ok(())
}

fn sibling(path: &Path, suffix: &str) -> Result<PathBuf, DurableRegistryError> {
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(DurableRegistryError::UnsafeRecoveryCheckpoint)?;
    Ok(path.with_file_name(format!("{name}{suffix}")))
}

fn read_checkpoint(path: &Path) -> Result<StoredRecoveryCheckpoint, DurableRegistryError> {
    let mut bytes = Vec::new();
    open_private_file(path, false)?
        .take(MAX_CHECKPOINT_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| DurableRegistryError::Unavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_CHECKPOINT_BYTES {
        return Err(DurableRegistryError::RecoveryCheckpointCorrupt);
    }
    serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::RecoveryCheckpointCorrupt)
}

fn persist_checkpoint(
    checkpoint_file: &Path,
    next_file: &Path,
    parent: &Path,
    stored: &StoredRecoveryCheckpoint,
) -> Result<(), DurableRegistryError> {
    let bytes = serde_json::to_vec(stored).map_err(|_| DurableRegistryError::Unavailable)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_CHECKPOINT_BYTES {
        return Err(DurableRegistryError::RecoveryCheckpointCorrupt);
    }
    let mut next = open_private_file(next_file, true)?;
    next.set_len(0).map_err(map_precommit_io)?;
    next.write_all(&bytes)
        .and_then(|()| next.sync_all())
        .map_err(map_precommit_io)?;
    std::fs::rename(next_file, checkpoint_file).map_err(map_precommit_io)?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| DurableRegistryError::IndeterminateDurability)
}

#[cfg(unix)]
fn prepare_parent(path: &Path) -> Result<(), DurableRegistryError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(path)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(DurableRegistryError::Unavailable);
    }
    let metadata = std::fs::metadata(path).map_err(|_| DurableRegistryError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(DurableRegistryError::UnsafeRecoveryCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn prepare_parent(_path: &Path) -> Result<(), DurableRegistryError> {
    Err(DurableRegistryError::UnsafeRecoveryCheckpoint)
}

#[cfg(unix)]
fn open_private_file(path: &Path, create: bool) -> Result<File, DurableRegistryError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let mut options = OpenOptions::new();
    options.read(true).write(create).create(create).mode(0o600);
    let file = options.open(path).map_err(map_precommit_io)?;
    let metadata = file
        .metadata()
        .map_err(|_| DurableRegistryError::Unavailable)?;
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
fn open_private_file(_path: &Path, _create: bool) -> Result<File, DurableRegistryError> {
    Err(DurableRegistryError::UnsafeRecoveryCheckpoint)
}
''')

tests = TESTS.read_text()
append = r'''

#[test]
fn guarded_reopen_rejects_valid_pre_revocation_backup() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let checkpoint = temp.path().join("witness").join("registry-checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test:prompt.registry",
        64,
    )
    .must("guarded owner");
    owner
        .commit(|core| add_payload(core, 0))
        .must("seed admitted payload");
    let old_metadata = std::fs::read(path.join("registry.json")).must("old metadata");
    let old_payloads = std::fs::read(path.join(payloads::FILE_NAME)).must("old payloads");
    owner
        .revoke_factor(
            &id("factor:0"),
            &id("operator:test"),
            digest("revocation"),
            1,
        )
        .must("revoke");
    drop(owner);

    std::fs::write(path.join("registry.json"), old_metadata).must("restore old metadata");
    std::fs::write(path.join(payloads::FILE_NAME), old_payloads).must("restore old payloads");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
            &path,
            &checkpoint,
            "agent:test:prompt.registry",
            64,
        ),
        Err(DurableRegistryError::RecoveryCheckpointMismatch)
    ));
}

#[test]
fn guarded_reopen_reconciles_exact_pending_successor() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let checkpoint = temp.path().join("witness").join("registry-checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test:prompt.registry",
        64,
    )
    .must("guarded owner");
    owner
        .commit(|core| add_payload(core, 0))
        .must("seed admitted payload");
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.revoke_factor(
            &id("factor:0"),
            &id("operator:test"),
            digest("revocation"),
            1,
        ),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(owner.requires_reopen());
    drop(owner);

    let reopened = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test:prompt.registry",
        64,
    )
    .must("reconcile exact pending successor");
    assert_eq!(
        reopened
            .registry()
            .must("registry")
            .factor(&id("factor:0"))
            .must("factor")
            .lifecycle,
        Lifecycle::Revoked
    );
}
'''
assert "fn guarded_reopen_rejects_valid_pre_revocation_backup" not in tests
TESTS.write_text(tests + append)
