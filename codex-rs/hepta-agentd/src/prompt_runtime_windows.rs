//! Prompt runtime persistence through a retained private Windows directory.

use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;
#[cfg(test)]
use std::sync::atomic::AtomicBool;
#[cfg(test)]
use std::sync::atomic::Ordering;

use codex_utils_path::windows_private_fs::PrivateDirectory;
use codex_utils_path::windows_private_fs::snapshot_private_file;

use super::AgentdPromptRuntimeError;
use super::LOCK_FILE;
use super::MAX_DURABLE_STATE_BYTES;
use super::NEXT_FILE;
use super::PromptRuntimeState;
use super::STATE_FILE;
use super::StoredPromptRuntimeState;
use super::restore_state;
use super::stored_state;

pub(super) struct PromptRuntimeStore {
    directory: PrivateDirectory,
    _lock: File,
    #[cfg(test)]
    pub(super) fail_directory_sync_after_rename_once: AtomicBool,
}

impl PromptRuntimeStore {
    pub(super) fn open(
        path: &Path,
    ) -> Result<(Self, PromptRuntimeState), AgentdPromptRuntimeError> {
        let directory = PrivateDirectory::open_or_create(path)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        let lock = directory
            .open_write(LOCK_FILE)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        lock.try_lock()
            .map_err(|_| AgentdPromptRuntimeError::StateLocked)?;
        let store = Self {
            directory,
            _lock: lock,
            #[cfg(test)]
            fail_directory_sync_after_rename_once: AtomicBool::new(false),
        };
        if !store
            .directory
            .entry_exists(STATE_FILE)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?
        {
            return Ok((store, PromptRuntimeState::default()));
        }
        let mut file = store
            .directory
            .open_read(STATE_FILE)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        let before =
            snapshot_private_file(&file).map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        if before.len() > MAX_DURABLE_STATE_BYTES {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        let mut bytes = Vec::new();
        Read::by_ref(&mut file)
            .take(MAX_DURABLE_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES
            || snapshot_private_file(&file).map_err(|_| AgentdPromptRuntimeError::Unavailable)?
                != before
        {
            return Err(AgentdPromptRuntimeError::CorruptState);
        }
        let stored: StoredPromptRuntimeState =
            serde_json::from_slice(&bytes).map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
        Ok((store, restore_state(stored)?))
    }

    pub(super) fn persist(
        &self,
        state: &PromptRuntimeState,
    ) -> Result<(), AgentdPromptRuntimeError> {
        let bytes = serde_json::to_vec(&stored_state(state))
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(AgentdPromptRuntimeError::CapacityExceeded);
        }
        // Validate the existing entry before any truncation. A path replacement
        // cannot redirect this write away from the retained directory handle.
        let mut next = self
            .directory
            .open_write(NEXT_FILE)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        next.set_len(0)
            .and_then(|()| next.write_all(&bytes))
            .and_then(|()| next.sync_all())
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        self.directory
            .replace(NEXT_FILE, STATE_FILE)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        #[cfg(test)]
        if self
            .fail_directory_sync_after_rename_once
            .swap(false, Ordering::AcqRel)
        {
            return Err(AgentdPromptRuntimeError::IndeterminateDurability);
        }
        self.directory
            .sync_all()
            .map_err(|_| AgentdPromptRuntimeError::IndeterminateDurability)
    }
}

#[cfg(test)]
#[path = "prompt_runtime_windows_tests.rs"]
mod tests;
