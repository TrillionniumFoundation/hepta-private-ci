//! Cross-process exclusion between original Fleet publication and effect entry.
//!
//! The stable, empty lock file is coordination only. Lifecycle records remain
//! the sole generation authority; no grant, queue or outcome is stored here.

use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::ErrorKind;
use std::path::Path;

use codex_hepta_contracts::AgentId;

use crate::FleetRegistry;
use crate::FleetRegistryError;

/// A shared generation fence retained through the bounded transport entry.
///
/// This guard does not authorize an effect. The caller must still validate its
/// original run, cancellation, deadline and FinalUse under their owning locks.
/// It is intentionally neither cloneable nor serializable.
#[derive(Debug)]
#[must_use = "retain the generation fence through physical effect entry"]
pub struct FleetEntryGuard {
    _file: File,
}

impl FleetRegistry {
    /// Fence the exact observed generation against a concurrent publication.
    /// Contention is retryable and never blocks the async runtime thread.
    pub fn try_enter_generation(
        &self,
        agent_id: &AgentId,
        expected_generation: u64,
    ) -> Result<FleetEntryGuard, FleetRegistryError> {
        let file = open_lock(self.layout().agent(agent_id).run_root())?;
        file.try_lock_shared()
            .map_err(|error| lock_error(agent_id, error))?;
        let current = self.load_agent(agent_id)?.lifecycle.generation;
        if current != expected_generation {
            return Err(FleetRegistryError::StaleGeneration {
                agent_id: agent_id.clone(),
                expected: expected_generation,
                current,
            });
        }
        Ok(FleetEntryGuard { _file: file })
    }
}

pub(crate) fn try_transition(
    run_root: &Path,
    agent_id: &AgentId,
) -> Result<File, FleetRegistryError> {
    let file = open_lock(run_root)?;
    file.try_lock()
        .map_err(|error| lock_error(agent_id, error))?;
    Ok(file)
}

fn lock_error(agent_id: &AgentId, error: TryLockError) -> FleetRegistryError {
    match error {
        TryLockError::WouldBlock => FleetRegistryError::LifecycleBusy {
            agent_id: agent_id.clone(),
        },
        TryLockError::Error(error) => FleetRegistryError::Io(error),
    }
}

fn open_lock(run_root: &Path) -> Result<File, FleetRegistryError> {
    // Like the existing writer/supervisor locks, this inode belongs to the
    // protected Fleet directory. Owners must never unlink or replace it while
    // the Fleet is live. create_new permits a compatible first open of old
    // registries without ever truncating or rotating an existing lock.
    if !std::fs::symlink_metadata(run_root)?.file_type().is_dir() {
        return Err(FleetRegistryError::Corrupt("lifecycle lock root is not a physical directory".to_owned()));
    }
    let path = run_root.join("lifecycle.lock");
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = match options.open(&path) {
        Ok(file) => {
            file.sync_all()?;
            #[cfg(unix)]
            File::open(run_root)?.sync_all()?;
            file
        }
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {
            if !std::fs::symlink_metadata(&path)?.file_type().is_file() {
                return Err(FleetRegistryError::Corrupt("lifecycle lock is not a regular file".to_owned()));
            }
            OpenOptions::new().read(true).write(true).open(&path)?
        }
        Err(error) => return Err(error.into()),
    };
    let opened = file.metadata()?;
    let named = std::fs::symlink_metadata(&path)?;
    if !opened.is_file() || !named.file_type().is_file() || opened.len() != 0 {
        return Err(FleetRegistryError::Corrupt("lifecycle lock is not an empty regular file".to_owned()));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if opened.dev() != named.dev() || opened.ino() != named.ino() || opened.nlink() != 1 {
            return Err(FleetRegistryError::Corrupt("lifecycle lock inode changed".to_owned()));
        }
    }
    Ok(file)
}
