//! The original registry store's platform I/O boundary. Windows path opens
//! produce the same held native namespace proof required by opaque inputs.

use super::DurableRegistryError;
#[cfg(windows)]
pub(super) use codex_hepta_contracts::windows_private_owner::OwnerLock as Directory;
#[cfg(not(windows))]
use std::fs::File;
#[cfg(not(windows))]
pub(super) use std::fs::File as Directory;
use std::path::Path;

pub(super) struct LockedDirectory {
    pub(super) root: Directory,
    pub(super) initialized: bool,
    #[cfg(not(windows))]
    pub(super) lock: File,
}
#[cfg(not(windows))]
pub(super) fn lock_directory(path: &Path) -> Result<LockedDirectory, DurableRegistryError> {
    let root = super::prepare_directory(path)?;
    let initialized = super::entry_exists(&root, "registry.lock")?;
    let lock = super::open_private(&root, "registry.lock", super::Access::Create)?;
    lock.try_lock()
        .map_err(|_| DurableRegistryError::StateLocked)?;
    Ok(LockedDirectory {
        root,
        initialized,
        lock,
    })
}
#[cfg(windows)]
pub(super) fn lock_directory(path: &Path) -> Result<LockedDirectory, DurableRegistryError> {
    use codex_hepta_contracts::windows_private_owner::CreationFailure;
    use codex_hepta_contracts::windows_private_owner::ParentAnchor;
    use std::os::windows::ffi::OsStrExt;
    use std::path::Component;

    if path.as_os_str().encode_wide().nth(/*n*/ 8192).is_some() {
        return Err(DurableRegistryError::UnsafeStateDirectory);
    }
    let mut components = path.components();
    let Some(Component::Normal(leaf)) = components.next_back() else {
        return Err(DurableRegistryError::UnsafeStateDirectory);
    };
    let leaf = leaf
        .to_str()
        .ok_or(DurableRegistryError::UnsafeStateDirectory)?;
    let parent = ParentAnchor::for_create_only(components.as_path())
        .map_err(|_| DurableRegistryError::UnsafeStateDirectory)?;
    let directory = match parent.prepare_private_store_directory(leaf) {
        Ok(directory) => directory,
        Err(CreationFailure::NotAdmitted(_)) => {
            return Err(DurableRegistryError::UnsafeStateDirectory);
        }
        Err(CreationFailure::Created {
            directory,
            error: _,
        }) => {
            // Hold the actual unverified-created role until this factory refuses.
            // RAII only closes its handles; no deletion, retry, reset or ACL repair.
            // The public error does not carry custody beyond this return.
            let _created_until_refusal = directory;
            return Err(DurableRegistryError::UnsafeStateDirectory);
        }
    };
    LockedDirectory::from_windows(directory)
}
#[cfg(windows)]
impl LockedDirectory {
    fn from_windows(
        input: codex_hepta_contracts::windows_private_owner::PrivateStoreDirectory,
    ) -> Result<Self, DurableRegistryError> {
        use codex_hepta_contracts::windows_private_owner::OwnerLockError;
        use codex_hepta_contracts::windows_private_owner::OwnerLockOrigin;
        let root = input
            .lock_original_marker("registry.lock")
            .map_err(|error| match error {
                OwnerLockError::StateLocked => DurableRegistryError::StateLocked,
                OwnerLockError::Rejected(_) => DurableRegistryError::UnsafeStateDirectory,
            })?;
        let initialized = root.origin() == &OwnerLockOrigin::Existing;
        Ok(Self { root, initialized })
    }
}
#[cfg(windows)]
pub(super) fn open_private<'owner>(
    directory: &'owner Directory,
    name: &str,
    access: super::Access,
) -> Result<
    codex_hepta_contracts::windows_private_owner::OriginalStoreFile<'owner>,
    DurableRegistryError,
> {
    use codex_hepta_contracts::windows_private_owner::OriginalFileAccess;
    let access = match access {
        super::Access::Read => OriginalFileAccess::Read,
        super::Access::Create if name == "registry.next" => OriginalFileAccess::Stage,
        super::Access::Create => OriginalFileAccess::Create,
    };
    directory
        .open_original_file(name, 64 * 1024 * 1024, access)
        .map_err(|_| DurableRegistryError::Unavailable)
}
#[cfg(windows)]
pub(super) fn entry_exists(
    directory: &Directory,
    name: &str,
) -> Result<bool, DurableRegistryError> {
    directory
        .entry_exists(name)
        .map_err(|_| DurableRegistryError::Unavailable)
}
pub(super) fn sync_directory(directory: &Directory) -> Result<(), DurableRegistryError> {
    #[cfg(not(windows))]
    {
        directory.sync_all().map_err(super::map_precommit_io)
    }
    #[cfg(windows)]
    {
        directory.sync_all().map_err(|error| match error {
            codex_hepta_contracts::windows_private_owner::ValidationError::Os(error) => {
                super::map_precommit_io(error)
            }
            codex_hepta_contracts::windows_private_owner::ValidationError::MalformedDescriptor
            | codex_hepta_contracts::windows_private_owner::ValidationError::WrongOwner
            | codex_hepta_contracts::windows_private_owner::ValidationError::UnprotectedDacl
            | codex_hepta_contracts::windows_private_owner::ValidationError::NonCanonicalDacl
            | codex_hepta_contracts::windows_private_owner::ValidationError::UnsafeObject
            | codex_hepta_contracts::windows_private_owner::ValidationError::PrincipalChanged => {
                DurableRegistryError::UnsafeStateDirectory
            }
        })
    }
}

#[cfg(windows)]
impl super::DurablePromptRegistry {
    /// Open the existing V3 extent store from a live opaque private namespace.
    /// Full original schema/configuration/digest validation precedes orphan-tail
    /// recovery or migration writes. The path factory must produce the same live
    /// native namespace proof; a path alone never admits store authority.
    pub fn open_windows_private(
        directory: codex_hepta_contracts::windows_private_owner::PrivateStoreDirectory,
        maximum_records: usize,
    ) -> Result<Self, DurableRegistryError> {
        let (mut store, stored) =
            super::Store::open_locked(LockedDirectory::from_windows(directory)?)?;
        let registry = match stored {
            Some(super::StoredAny::V2(stored)) => super::restore_v2(stored, maximum_records)?,
            Some(super::StoredAny::V1(stored)) => super::migrate_v1(stored, maximum_records)?,
            None => {
                super::PromptRegistry::new(maximum_records).map_err(DurableRegistryError::Core)?
            }
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
}

#[cfg(all(test, windows))]
#[path = "durable_windows_tests.rs"]
mod tests;

#[cfg(all(test, windows))]
#[path = "ordinary_windows_factory_tests.rs"]
mod ordinary_windows_factory_tests;
