//! Exclusive bootstrap and typed storage selection under the original owner.
//!
//! Kept private beside the durable domain code so bootstrap I/O does not grow
//! the registry's semantic restore implementation. V4 relation images remain
//! selected and persisted by the existing owner.

use serde::Deserialize;
#[cfg(test)]
use std::cell::Cell;
use std::io::Read;
use std::path::Path;

use super::Access;
use super::DurableRegistryError;
use super::MAX_STATE_BYTES;
use super::Store;
use super::StoredAny;
use super::StoredV4;
use super::entry_exists;
use super::map_precommit_io;
use super::open_private;
use super::payloads;
use super::prepare_directory;
use crate::PromptRegistry;

#[derive(Deserialize)]
struct StoredSchema {
    schema: u32,
}

impl Store {
    pub(super) fn open(
        directory: &Path,
        maximum_records: usize,
    ) -> Result<(Self, Option<StoredAny>), DurableRegistryError> {
        let root = prepare_directory(directory)?;
        // Serialize bootstrap before a marker exists. Otherwise another opener
        // could acquire the new marker between its creation and file locking,
        // strand the creator, and leave an apparently initialized empty store.
        // The descriptor retains this lock for the owner's complete lifetime.
        root.try_lock()
            .map_err(|_| DurableRegistryError::StateLocked)?;
        let (lock, new_owner_marker) = match open_private(&root, "registry.lock", Access::CreateNew)
        {
            Ok(lock) => (lock, true),
            Err(error) => {
                if !entry_exists(&root, "registry.lock")? {
                    return Err(error);
                }
                (open_private(&root, "registry.lock", Access::Create)?, false)
            }
        };
        lock.try_lock()
            .map_err(|_| DurableRegistryError::StateLocked)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;

            // A contender can have opened the bootstrap lock before its owner
            // cleaned it up. It must not serve through that obsolete inode.
            if lock.metadata().map_err(map_precommit_io)?.nlink() != 1 {
                return Err(DurableRegistryError::StateLocked);
            }
        }
        let mut store = Self {
            root,
            _lock: lock,
            new_owner_marker,
            payloads: payloads::PayloadState::default(),
            #[cfg(test)]
            fail_directory_sync_after_rename_once: Cell::new(false),
            #[cfg(test)]
            fail_storage_full_before_rename_once: Cell::new(false),
        };
        let has_state = entry_exists(&store.root, "registry.json")?;
        if !has_state {
            if !store.new_owner_marker {
                return Err(DurableRegistryError::Corrupt);
            }
            return Ok((store, None));
        }
        store.new_owner_marker = false;
        let mut bytes = Vec::new();
        open_private(&store.root, "registry.json", Access::Read)?
            .take(MAX_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| DurableRegistryError::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_STATE_BYTES {
            return Err(DurableRegistryError::Corrupt);
        }
        // Probe only the header without materializing an untrusted JSON tree.
        // Decode the selected schema directly from bytes so duplicate members
        // at every typed record level are rejected rather than overwritten.
        let header: StoredSchema =
            serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?;
        let stored = match header.schema {
            1 => StoredAny::V1(
                serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?,
            ),
            2 => StoredAny::V2(
                serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?,
            ),
            3 => {
                let manifest =
                    serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?;
                let (payloads, state) =
                    payloads::PayloadState::hydrate(&store.root, manifest, maximum_records)?;
                store.payloads = payloads;
                StoredAny::V2(state)
            }
            4 => {
                let manifest: StoredV4 =
                    serde_json::from_slice(&bytes).map_err(|_| DurableRegistryError::Corrupt)?;
                if manifest.schema != 4 || manifest.relations.len() > crate::MAX_RECORDS {
                    return Err(DurableRegistryError::Corrupt);
                }
                // Reuse the unchanged extent verifier. Full V4 semantic digest
                // validation includes relations after hydration, before any trim.
                let (payloads, state) = payloads::PayloadState::hydrate(
                    &store.root,
                    payloads::StoredV3 {
                        schema: 3,
                        state: manifest.state,
                        payload_references: manifest.payload_references,
                    },
                    maximum_records,
                )?;
                store.payloads = payloads;
                StoredAny::V4(state, manifest.relations)
            }
            _ => return Err(DurableRegistryError::Corrupt),
        };
        Ok((store, Some(stored)))
    }

    pub(super) fn initialize(
        mut self,
        registry: &PromptRegistry,
    ) -> Result<Self, DurableRegistryError> {
        match self.persist(registry) {
            Ok(()) => {
                self.new_owner_marker = false;
                Ok(self)
            }
            Err(error) => {
                if self.new_owner_marker
                    && !matches!(error, DurableRegistryError::IndeterminateDurability)
                {
                    if entry_exists(&self.root, "registry.json")? {
                        return Err(DurableRegistryError::Corrupt);
                    }
                    #[cfg(unix)]
                    let cleanup = rustix::fs::unlinkat(
                        &self.root,
                        "registry.lock",
                        rustix::fs::AtFlags::empty(),
                    )
                    .map_err(|_| DurableRegistryError::Unavailable)
                    .and_then(|()| self.root.sync_all().map_err(map_precommit_io));
                    #[cfg(not(unix))]
                    let cleanup = Err(DurableRegistryError::UnsafeStateDirectory);
                    cleanup?;
                }
                Err(error)
            }
        }
    }
}
