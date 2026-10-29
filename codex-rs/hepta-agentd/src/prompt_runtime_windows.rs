//! Native held-I/O for the ordinary Agentd prompt-pipeline initialization.
//! Paths locate parents only; actual OS capture, namespace inspection and the
//! original marker/schema protocols produce and retain both store owners.

use super::AgentdPromptRuntimeError;
use super::LOCK_FILE;
use super::MAX_DURABLE_STATE_BYTES;
use super::NEXT_FILE;
use super::PromptRuntimeState;
use super::PromptRuntimeStore;
use super::STATE_FILE;
use super::StoredPromptRuntimeState;
use super::restore_state;
use super::stored_state;
use super::validate_state;
use codex_hepta_contracts::windows_private_owner::CreationFailure;
use codex_hepta_contracts::windows_private_owner::OriginalFileAccess;
use codex_hepta_contracts::windows_private_owner::OwnerLockError;
use codex_hepta_contracts::windows_private_owner::OwnerLockOrigin;
use codex_hepta_contracts::windows_private_owner::ParentAnchor;
use codex_hepta_contracts::windows_private_owner::PrivateStoreDirectory;
use codex_hepta_contracts::windows_private_owner::StageReplaceError;
use std::io::Write;
use std::os::windows::ffi::OsStrExt;
use std::path::Component;
use std::path::Path;
#[cfg(test)]
use std::sync::atomic::AtomicBool;
#[cfg(test)]
use std::sync::atomic::Ordering;

fn directory_input(directory: &Path) -> Result<PrivateStoreDirectory, AgentdPromptRuntimeError> {
    if directory.as_os_str().encode_wide().count() > 8192 {
        return Err(AgentdPromptRuntimeError::Unavailable);
    }
    let mut components = directory.components();
    let Some(Component::Normal(leaf)) = components.next_back() else {
        return Err(AgentdPromptRuntimeError::Unavailable);
    };
    let leaf = leaf.to_str().ok_or(AgentdPromptRuntimeError::Unavailable)?;
    let parent = ParentAnchor::for_create_only(components.as_path())
        .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
    match parent.prepare_private_store_directory(leaf) {
        Ok(input) => Ok(input),
        Err(CreationFailure::NotAdmitted(_)) => Err(AgentdPromptRuntimeError::Unavailable),
        Err(CreationFailure::Created {
            directory,
            error: _,
        }) => {
            // Retain the actual unverified-created role until this factory
            // refuses. Normal RAII then only closes its handles: no deletion,
            // retry, rebuild or ACL repair. The public error does not carry
            // custody beyond this return; it grants no reconciliation authority.
            let _created_until_refusal = directory;
            Err(AgentdPromptRuntimeError::Unavailable)
        }
    }
}

impl PromptRuntimeStore {
    pub(super) fn open(
        directory: &Path,
    ) -> Result<(Self, PromptRuntimeState), AgentdPromptRuntimeError> {
        let root = directory_input(directory)?
            .lock_original_marker(LOCK_FILE)
            .map_err(|error| match error {
                OwnerLockError::StateLocked => AgentdPromptRuntimeError::StateLocked,
                OwnerLockError::Rejected(_) => AgentdPromptRuntimeError::Unavailable,
            })?;
        let initialized = root.origin() == &OwnerLockOrigin::Existing;
        let store = Self {
            root,
            #[cfg(test)]
            fail_directory_sync_after_rename_once: AtomicBool::new(false),
        };
        if !store
            .root
            .entry_exists(STATE_FILE)
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?
        {
            // An existing marker can never initialize/reset missing state.
            // This also refuses cold reopen after any failed fresh setup that
            // left only a directory, marker or unpublished stage behind.
            if initialized {
                return Err(AgentdPromptRuntimeError::CorruptState);
            }
            let state = PromptRuntimeState::default();
            validate_state(&state)?;
            store.persist(&state)?;
            return Ok((store, state));
        }
        let bytes = store
            .root
            .read_bounded(
                STATE_FILE,
                /*maximum*/ MAX_DURABLE_STATE_BYTES as usize,
            )
            .map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
        let stored: StoredPromptRuntimeState =
            serde_json::from_slice(&bytes).map_err(|_| AgentdPromptRuntimeError::CorruptState)?;
        let state = restore_state(stored)?;
        store
            .root
            .revalidate_shared()
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        Ok((store, state))
    }

    pub(super) fn persist(
        &self,
        state: &PromptRuntimeState,
    ) -> Result<(), AgentdPromptRuntimeError> {
        self.root
            .revalidate_shared()
            .map_err(|_| AgentdPromptRuntimeError::ReopenRequired)?;
        let bytes = serde_json::to_vec(&stored_state(state))
            .map_err(|_| AgentdPromptRuntimeError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(AgentdPromptRuntimeError::CapacityExceeded);
        }
        // The original eight-MiB cap applies before opening/truncating a stage.
        // A pre-existing oversized or unsafe stage is refused, never repaired.
        let mut next = self
            .root
            .open_original_file(
                NEXT_FILE,
                /*maximum*/ MAX_DURABLE_STATE_BYTES as usize,
                OriginalFileAccess::Stage,
            )
            .map_err(|_| AgentdPromptRuntimeError::ReopenRequired)?;
        next.set_len(0)
            .and_then(|()| next.write_all(&bytes))
            .and_then(|()| next.sync_all())
            .map_err(|_| AgentdPromptRuntimeError::ReopenRequired)?;
        next.replace_synced(STATE_FILE)
            .map_err(|error| match error {
                StageReplaceError::BeforePublication(_) => AgentdPromptRuntimeError::ReopenRequired,
                StageReplaceError::Indeterminate(_) => {
                    AgentdPromptRuntimeError::IndeterminateDurability
                }
            })?;
        #[cfg(test)]
        if self
            .fail_directory_sync_after_rename_once
            .swap(false, Ordering::AcqRel)
        {
            return Err(AgentdPromptRuntimeError::IndeterminateDurability);
        }
        self.root
            .sync_all()
            .map_err(|_| AgentdPromptRuntimeError::IndeterminateDurability)
    }
}
