//! Durable single-writer host for the prompt registry.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdmissionRequest;
use crate::Error;
use crate::PromptFactor;
use crate::PromptRealizationBindingV2;
use crate::PromptRegistry;
use crate::RegistryReceipt;
use crate::protocol::decode_registry_state;
use crate::protocol::encode_registry_state;

const STATE_FILE: &str = "prompt-registry.json";
const TEMP_FILE: &str = ".prompt-registry.json.tmp";
const BACKUP_FILE: &str = ".prompt-registry.json.bak";
const WRITER_LOCK_FILE: &str = ".prompt-registry.writer.lock";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptRegistryStoreError {
    Io(String),
    Protocol(String),
    Registry(Error),
    Authority(String),
    StateMissing,
    WriterBusy,
    StateDiverged,
    CapacityMismatch { requested: usize, stored: usize },
}

impl std::fmt::Display for PromptRegistryStoreError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PromptRegistryStoreError {}

impl From<Error> for PromptRegistryStoreError {
    fn from(value: Error) -> Self {
        Self::Registry(value)
    }
}

#[derive(Debug)]
pub struct DurablePromptRegistry {
    directory: PathBuf,
    registry: PromptRegistry,
    _writer_lock: File,
}

impl DurablePromptRegistry {
    pub fn open_or_create(
        directory: &Path,
        maximum_records: usize,
    ) -> Result<Self, PromptRegistryStoreError> {
        fs::create_dir_all(directory).map_err(io_error)?;
        let writer_lock = acquire_writer_lock(directory)?;
        recover_interrupted_commit(directory)?;
        let path = directory.join(STATE_FILE);
        if path.exists() {
            let host = Self::open_with_lock(directory, writer_lock)?;
            if host.registry.maximum_records != maximum_records.min(crate::registry::MAX_RECORDS) {
                return Err(PromptRegistryStoreError::CapacityMismatch {
                    requested: maximum_records.min(crate::registry::MAX_RECORDS),
                    stored: host.registry.maximum_records,
                });
            }
            if host.persist_if_needed()? {
                host.registry.validate_integrity()?;
            }
            return Ok(host);
        }
        let registry = PromptRegistry::new(maximum_records)?;
        let host = Self {
            directory: directory.to_path_buf(),
            registry,
            _writer_lock: writer_lock,
        };
        host.persist_registry(&host.registry)?;
        Ok(host)
    }

    pub fn open(directory: &Path) -> Result<Self, PromptRegistryStoreError> {
        fs::create_dir_all(directory).map_err(io_error)?;
        let writer_lock = acquire_writer_lock(directory)?;
        recover_interrupted_commit(directory)?;
        Self::open_with_lock(directory, writer_lock)
    }

    fn open_with_lock(
        directory: &Path,
        writer_lock: File,
    ) -> Result<Self, PromptRegistryStoreError> {
        let path = directory.join(STATE_FILE);
        if !path.exists() {
            return Err(PromptRegistryStoreError::StateMissing);
        }
        let bytes = fs::read(&path).map_err(io_error)?;
        let decoded = decode_registry_state(&bytes)
            .map_err(|error| PromptRegistryStoreError::Protocol(error.to_string()))?;
        let host = Self {
            directory: directory.to_path_buf(),
            registry: decoded.registry,
            _writer_lock: writer_lock,
        };
        if decoded.migrated {
            host.persist_registry(&host.registry)?;
        }
        host.cleanup_verified_backup()?;
        Ok(host)
    }

    pub fn registry(&self) -> &PromptRegistry {
        &self.registry
    }

    pub fn register_factor(
        &mut self,
        factor: PromptFactor,
    ) -> Result<RegistryReceipt, PromptRegistryStoreError> {
        self.mutate(|registry| registry.register_factor(factor))
    }

    pub fn admit_factor_authorized(
        &mut self,
        authority: &FinalUseAuthority,
        token: VerifiedUseToken,
        request: AdmissionRequest,
    ) -> Result<RegistryReceipt, PromptRegistryStoreError> {
        self.ensure_persisted_generation_matches_current()?;
        let expected = self.registry.admission_binding(&request)?;
        authority
            .with_verified_use(token, &expected, || {
                let mut next = self.registry.clone();
                let receipt = next.admit_factor_verified(request)?;
                self.persist_registry(&next)?;
                self.registry = next;
                Ok::<RegistryReceipt, PromptRegistryStoreError>(receipt)
            })
            .map_err(|error| PromptRegistryStoreError::Authority(error.to_string()))?
    }

    pub fn register_realization_v2(
        &mut self,
        binding: PromptRealizationBindingV2,
        payload: Vec<u8>,
    ) -> Result<RegistryReceipt, PromptRegistryStoreError> {
        self.mutate(|registry| registry.register_realization_v2(binding, payload))
    }

    pub fn retire_factor_with_reason(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
    ) -> Result<RegistryReceipt, PromptRegistryStoreError> {
        self.mutate(|registry| {
            registry.retire_factor_with_reason(factor_id, actor_id, reason_digest)
        })
    }

    pub fn revoke_factor_with_reason(
        &mut self,
        factor_id: &StableId,
        actor_id: &StableId,
        reason_digest: Digest32,
        cutoff_unix_ms: u64,
    ) -> Result<RegistryReceipt, PromptRegistryStoreError> {
        self.mutate(|registry| {
            registry.revoke_factor_with_reason(factor_id, actor_id, reason_digest, cutoff_unix_ms)
        })
    }

    fn mutate(
        &mut self,
        mutation: impl FnOnce(&mut PromptRegistry) -> Result<RegistryReceipt, Error>,
    ) -> Result<RegistryReceipt, PromptRegistryStoreError> {
        self.ensure_persisted_generation_matches_current()?;
        let mut next = self.registry.clone();
        let receipt = mutation(&mut next)?;
        if next != self.registry {
            self.persist_registry(&next)?;
            self.registry = next;
        }
        Ok(receipt)
    }

    fn cleanup_verified_backup(&self) -> Result<(), PromptRegistryStoreError> {
        let backup = self.directory.join(BACKUP_FILE);
        if backup.exists() {
            remove_file_if_exists(&backup)?;
            sync_directory(&self.directory)?;
        }
        Ok(())
    }

    fn ensure_persisted_generation_matches_current(
        &self,
    ) -> Result<(), PromptRegistryStoreError> {
        let bytes = fs::read(self.directory.join(STATE_FILE)).map_err(io_error)?;
        let decoded = decode_registry_state(&bytes)
            .map_err(|error| PromptRegistryStoreError::Protocol(error.to_string()))?;
        if decoded.migrated || decoded.registry != self.registry {
            return Err(PromptRegistryStoreError::StateDiverged);
        }
        Ok(())
    }

    fn persist_if_needed(&self) -> Result<bool, PromptRegistryStoreError> {
        let path = self.directory.join(STATE_FILE);
        let stored = fs::read(&path).map_err(io_error)?;
        let canonical = encode_registry_state(&self.registry)
            .map_err(|error| PromptRegistryStoreError::Protocol(error.to_string()))?;
        if stored == canonical {
            return Ok(false);
        }
        atomic_write(&self.directory, &canonical)?;
        Ok(true)
    }

    fn persist_registry(&self, registry: &PromptRegistry) -> Result<(), PromptRegistryStoreError> {
        let bytes = encode_registry_state(registry)
            .map_err(|error| PromptRegistryStoreError::Protocol(error.to_string()))?;
        atomic_write(&self.directory, &bytes)
    }
}

fn acquire_writer_lock(directory: &Path) -> Result<File, PromptRegistryStoreError> {
    let path = directory.join(WRITER_LOCK_FILE);
    let file = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(path)
        .map_err(io_error)?;
    match file.try_lock() {
        Ok(()) => Ok(file),
        Err(std::fs::TryLockError::WouldBlock) => Err(PromptRegistryStoreError::WriterBusy),
        Err(std::fs::TryLockError::Error(error)) => Err(io_error(error)),
    }
}

fn recover_interrupted_commit(directory: &Path) -> Result<(), PromptRegistryStoreError> {
    let temporary = directory.join(TEMP_FILE);
    let destination = directory.join(STATE_FILE);
    let backup = directory.join(BACKUP_FILE);

    if destination.exists() {
        // Keep a predecessor until the current image has been decoded and its
        // registry integrity verified. A corrupt current image must fail closed
        // without silently rolling back, but the last known predecessor remains
        // available for diagnosis or explicit operator recovery.
        remove_file_if_exists(&temporary)?;
        return Ok(());
    }

    if backup.exists() {
        fs::rename(&backup, &destination).map_err(io_error)?;
        sync_directory(directory)?;
        remove_file_if_exists(&temporary)?;
        return Ok(());
    }

    remove_file_if_exists(&temporary)?;
    Ok(())
}

fn atomic_write(directory: &Path, bytes: &[u8]) -> Result<(), PromptRegistryStoreError> {
    fs::create_dir_all(directory).map_err(io_error)?;
    let temporary = directory.join(TEMP_FILE);
    let destination = directory.join(STATE_FILE);
    let backup = directory.join(BACKUP_FILE);

    remove_file_if_exists(&temporary)?;
    let mut file = File::create(&temporary).map_err(io_error)?;
    file.write_all(bytes).map_err(io_error)?;
    file.sync_all().map_err(io_error)?;
    drop(file);

    let had_destination = destination.exists();
    if had_destination {
        remove_file_if_exists(&backup)?;
        fs::rename(&destination, &backup).map_err(io_error)?;
        sync_directory(directory)?;
    }

    if let Err(error) = fs::rename(&temporary, &destination) {
        if had_destination && !destination.exists() && backup.exists() {
            let _ = fs::rename(&backup, &destination);
            let _ = sync_directory(directory);
        }
        let _ = fs::remove_file(&temporary);
        return Err(io_error(error));
    }

    sync_directory(directory)?;
    if had_destination {
        let _ = fs::remove_file(&backup);
        let _ = sync_directory(directory);
    }
    Ok(())
}

fn remove_file_if_exists(path: &Path) -> Result<(), PromptRegistryStoreError> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(io_error(error)),
    }
}

#[cfg(unix)]
fn sync_directory(directory: &Path) -> Result<(), PromptRegistryStoreError> {
    let file = File::open(directory).map_err(io_error)?;
    file.sync_all().map_err(io_error)
}

#[cfg(not(unix))]
fn sync_directory(_directory: &Path) -> Result<(), PromptRegistryStoreError> {
    // File contents are synced before each rename. The backup/current naming
    // protocol makes an interrupted replacement recoverable on reopen.
    Ok(())
}

fn io_error(error: std::io::Error) -> PromptRegistryStoreError {
    PromptRegistryStoreError::Io(error.to_string())
}

#[cfg(test)]
#[path = "store_tests.rs"]
mod tests;
