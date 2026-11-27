//! The original empty marker and OS lock, without store-protocol admission.

use super::Continuity;
use super::DirectoryContext;
use super::ExistingPrivateDirectoryCandidate;
use super::FreshPrivateDirectory;
use super::non_inherited;
use crate::mechanism;
use crate::mechanism::Identity;
use crate::protected_descriptor::ProtectedDescriptor;
use crate::security::ObjectKind;
use crate::security::ValidationError;
use crate::security::validate_owner_descriptor;
use crate::volume::inspect_local_ntfs;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::sync::Arc;
use std::sync::Mutex;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;

/// Kernel-observed marker origin, never a caller-supplied initialization grant.
#[derive(Debug, Eq, PartialEq)]
pub enum OwnerLockOrigin {
    Created,
    Existing,
}

/// Only native lock contention is StateLocked; access/sharing errors stay distinct.
#[derive(Debug)]
pub enum OwnerLockError {
    StateLocked,
    Rejected(ValidationError),
}
impl From<ValidationError> for OwnerLockError {
    fn from(error: ValidationError) -> Self {
        Self::Rejected(error)
    }
}
impl fmt::Display for OwnerLockError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for OwnerLockError {}

/// A genuine exclusive OS lock held until this file handle closes.
///
/// No raw File, clone, inherited handle, manual unlock or authority conversion
/// is exposed. The original marker/snapshot/journal/frontier recovery remains
/// mandatory before either store can admit authority.
pub struct OwnerLock {
    // Close/unlock the original file before releasing retained directory context.
    file: File,
    context: Arc<Mutex<DirectoryContext>>,
    identity: Identity,
    origin: OwnerLockOrigin,
}

enum MarkerMode {
    CreateOrOpen,
    ExistingOnly,
}

fn inspect(file: &File, context: &mut DirectoryContext) -> Result<Identity, ValidationError> {
    non_inherited(file)?;
    let observed = validate_owner_descriptor(
        file,
        context.directory.parent.owner.current_user()?,
        ObjectKind::SingleLinkFile,
    )?;
    if observed.identity.volume != context.identity.volume
        || inspect_local_ntfs(file)?.object != observed.identity
        || file.metadata()?.len() != 0
    {
        return Err(ValidationError::UnsafeObject);
    }
    Ok(observed.identity)
}

fn acquire(
    context: &Arc<Mutex<DirectoryContext>>,
    leaf: &str,
    mode: MarkerMode,
) -> Result<OwnerLock, OwnerLockError> {
    let mut held = context.lock().map_err(|_| ValidationError::UnsafeObject)?;
    held.revalidate()?;
    held.continuity = Continuity::Refused;
    if leaf.len() > 128 {
        return Err(ValidationError::UnsafeObject.into());
    }
    mechanism::leaf_name(leaf).map_err(ValidationError::from)?;
    let mut origin = OwnerLockOrigin::Existing;
    let created = match mode {
        MarkerMode::ExistingOnly => None,
        MarkerMode::CreateOrOpen => {
            let descriptor =
                ProtectedDescriptor::for_user(held.directory.parent.owner.current_user()?)?;
            let mut event = None;
            let result = mechanism::create_protected_file(
                &held.directory.file,
                leaf,
                &descriptor,
                |value| event = Some(value),
            );
            match (result, event) {
                (Ok(file), Some(event)) if event.ntstatus == 0 && event.information == 2 => {
                    origin = OwnerLockOrigin::Created;
                    Some(file)
                }
                // STATUS_OBJECT_NAME_COLLISION alone permits opening the existing marker.
                (Err(_), Some(event)) if event.ntstatus == 0xC000_0035_u32 as i32 => None,
                (Err(error), _) => return Err(ValidationError::from(error).into()),
                (Ok(_), _) => return Err(ValidationError::UnsafeObject.into()),
            }
        }
    };
    let file = match created {
        Some(file) => file,
        None => {
            let mut event = None;
            let file = mechanism::open_relative(
                &held.directory.file,
                leaf,
                FILE_GENERIC_READ | FILE_GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                mechanism::FILE_OPEN,
                |value| event = Some(value),
            )
            .map_err(ValidationError::from)?;
            if !matches!(event, Some(event) if event.ntstatus == 0 && event.information == 1) {
                return Err(ValidationError::UnsafeObject.into());
            }
            file
        }
    };
    let identity = inspect(&file, &mut held)?;
    match file.try_lock() {
        Ok(()) => (),
        Err(TryLockError::WouldBlock) => return Err(OwnerLockError::StateLocked),
        Err(TryLockError::Error(error)) => return Err(ValidationError::from(error).into()),
    }
    if inspect(&file, &mut held)? != identity {
        return Err(ValidationError::UnsafeObject.into());
    }
    held.continuity = Continuity::Live;
    held.revalidate()?;
    Ok(OwnerLock {
        file,
        context: Arc::clone(context),
        identity,
        origin,
    })
}

impl FreshPrivateDirectory {
    /// Atomically create the exact private marker or inspect an existing marker,
    /// then acquire its real nonblocking OS lock. Never truncate or repair it.
    pub fn lock_owner(&mut self, leaf: &str) -> Result<OwnerLock, OwnerLockError> {
        acquire(&self.context, leaf, MarkerMode::CreateOrOpen)
    }
}
impl ExistingPrivateDirectoryCandidate {
    /// Lock the existing original marker without creating missing state.
    pub fn lock_existing_owner(&mut self, leaf: &str) -> Result<OwnerLock, OwnerLockError> {
        acquire(&self.context, leaf, MarkerMode::ExistingOnly)
    }
}
impl OwnerLock {
    pub fn origin(&self) -> &OwnerLockOrigin {
        &self.origin
    }

    /// Revalidate the actual locked empty marker and shared held namespace.
    /// Any identity/descriptor/principal drift or poison permanently refuses it.
    pub fn revalidate(&mut self) -> Result<(), ValidationError> {
        self.revalidate_shared()
    }

    /// Revalidate this same retained owner for shared store read barriers.
    /// Interior locking preserves sticky refusal without cloning authority or
    /// changing the original exclusive revalidate API and its callers.
    pub fn revalidate_shared(&self) -> Result<(), ValidationError> {
        let mut held = self
            .context
            .lock()
            .map_err(|_| ValidationError::UnsafeObject)?;
        self.validate_locked(&mut held)
    }

    fn validate_locked(&self, held: &mut DirectoryContext) -> Result<(), ValidationError> {
        held.revalidate()?;
        held.continuity = Continuity::Refused;
        if inspect(&self.file, held)? != self.identity {
            return Err(ValidationError::UnsafeObject);
        }
        held.continuity = Continuity::Live;
        held.revalidate()
    }
}

#[cfg(test)]
#[path = "private_owner_lock_tests.rs"]
mod tests;

#[path = "owner_read.rs"]
mod owner_read;

#[path = "owner_file.rs"]
mod owner_file;
pub use owner_file::LockedPrivateFile;
pub use owner_file::PrivateFileAccess;

#[path = "owner_stage.rs"]
mod owner_stage;
pub use owner_stage::LockedStateStage;
pub use owner_stage::StageReplaceError;

#[path = "original_store_file.rs"]
mod original_store_file;
pub use original_store_file::OriginalFileAccess;
pub use original_store_file::OriginalStoreFile;
pub use original_store_file::PrivateStoreDirectory;
