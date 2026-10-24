//! Held private-directory roles; existing candidates grant no store authority.

use super::Continuity;
use super::ParentAnchor;
use super::non_inherited;
use crate::mechanism;
use crate::mechanism::Identity;
use crate::mechanism::OpenObservation;
use crate::protected_descriptor::ProtectedDescriptor;
use crate::security::ObjectKind;
use crate::security::ValidationError;
use crate::security::validate_owner_descriptor;
use crate::volume::inspect_local_ntfs;
use std::fmt;
use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

/// A failed post-create readback retains the actual new directory and ancestry.
/// It grants no validated operations; dropping it only closes owned handles.
pub struct UnverifiedCreatedDirectory {
    _directory: HeldDirectory,
}

struct HeldDirectory {
    // Rust drops fields in declaration order: retain ancestry until this closes.
    file: File,
    parent: ParentAnchor,
}

/// Distinguishes no admitted creation handle from a held creation needing reconciliation.
/// A failed native attempt never authorizes assuming absence, retrying or resetting state.
pub enum CreationFailure {
    NotAdmitted(ValidationError),
    Created {
        directory: Box<UnverifiedCreatedDirectory>,
        error: ValidationError,
    },
}
impl fmt::Debug for CreationFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotAdmitted(error) => f.debug_tuple("NotAdmitted").field(error).finish(),
            Self::Created { error, .. } => {
                f.debug_tuple("CreatedButUnverified").field(error).finish()
            }
        }
    }
}
impl fmt::Display for CreationFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for CreationFailure {}

/// A newly created directory with the captured user's exact protected DACL.
///
/// No raw handle, path-adoption, clone or deserialization entry is provided.
/// This role does not qualify sync/power-loss, replay recovery or either owner
/// store. Those consumers keep their existing closed Windows factories.
pub struct FreshPrivateDirectory {
    context: Arc<Mutex<DirectoryContext>>,
}

/// An existing held private directory, pending the original store protocol.
///
/// This only admits bounded inspection and the subsequent original OS lock.
/// It does not prove an initialization marker, journal, frontier or authority.
/// No raw handle, cloning or conversion to the fresh-created role is provided.
pub struct ExistingPrivateDirectoryCandidate {
    context: Arc<Mutex<DirectoryContext>>,
}

struct DirectoryContext {
    directory: HeldDirectory,
    identity: Identity,
    continuity: Continuity,
}

impl HeldDirectory {
    fn inspect(&mut self) -> Result<Identity, ValidationError> {
        self.parent.revalidate()?;
        non_inherited(&self.file)?;
        let observed = validate_owner_descriptor(
            &self.file,
            self.parent.owner.current_user()?,
            ObjectKind::Directory,
        )?;
        if observed.identity.volume != self.parent.volume
            || inspect_local_ntfs(&self.file)?.object != observed.identity
        {
            return Err(ValidationError::UnsafeObject);
        }
        self.parent.revalidate()?;
        Ok(observed.identity)
    }
}

impl ParentAnchor {
    /// Create one new leaf with its protected owner descriptor already attached.
    /// FILE_CREATE never opens, repairs or resets an existing object.
    pub fn create_private_directory(
        mut self,
        leaf: &str,
    ) -> Result<FreshPrivateDirectory, CreationFailure> {
        let prepare = (|| {
            if leaf.len() > 128 {
                return Err(ValidationError::UnsafeObject);
            }
            mechanism::leaf_name(leaf)?;
            self.revalidate()?;
            ProtectedDescriptor::for_user(self.owner.current_user()?)
        })();
        let descriptor = prepare.map_err(CreationFailure::NotAdmitted)?;
        let mut event: Option<OpenObservation> = None;
        let file = mechanism::create_protected_directory(
            &self
                .ancestors
                .last()
                .ok_or(CreationFailure::NotAdmitted(ValidationError::UnsafeObject))?
                .file,
            leaf,
            &descriptor,
            |value| event = Some(value),
        )
        .map_err(|error| CreationFailure::NotAdmitted(error.into()))?;
        let mut directory = HeldDirectory { parent: self, file };
        let validate = (|| {
            let event = event.ok_or(ValidationError::UnsafeObject)?;
            if event.ntstatus != 0 || event.information != 2 {
                return Err(ValidationError::UnsafeObject);
            }
            directory.inspect()
        })();
        match validate {
            Ok(identity) => Ok(FreshPrivateDirectory {
                context: Arc::new(Mutex::new(DirectoryContext {
                    directory,
                    identity,
                    continuity: Continuity::Live,
                })),
            }),
            Err(error) => Err(CreationFailure::Created {
                directory: Box::new(UnverifiedCreatedDirectory {
                    _directory: directory,
                }),
                error,
            }),
        }
    }
}

impl ParentAnchor {
    /// Hold an existing private leaf solely for original cold-protocol validation.
    /// FILE_OPEN never creates, repairs, truncates or resets existing state.
    pub fn open_existing_candidate(
        mut self,
        leaf: &str,
    ) -> Result<ExistingPrivateDirectoryCandidate, ValidationError> {
        if leaf.len() > 128 {
            return Err(ValidationError::UnsafeObject);
        }
        mechanism::leaf_name(leaf)?;
        self.revalidate()?;
        let mut event = None;
        let file = mechanism::open_existing_owner_directory(
            &self
                .ancestors
                .last()
                .ok_or(ValidationError::UnsafeObject)?
                .file,
            leaf,
            |value| event = Some(value),
        )?;
        let event = event.ok_or(ValidationError::UnsafeObject)?;
        if event.ntstatus != 0 || event.information != 1 {
            return Err(ValidationError::UnsafeObject);
        }
        let mut directory = HeldDirectory { file, parent: self };
        let identity = directory.inspect()?;
        Ok(ExistingPrivateDirectoryCandidate {
            context: Arc::new(Mutex::new(DirectoryContext {
                directory,
                identity,
                continuity: Continuity::Live,
            })),
        })
    }
}

impl ExistingPrivateDirectoryCandidate {
    /// Re-read held identities, owner descriptor and live primary principal.
    /// Failure is sticky, including any shared-context poison.
    pub fn revalidate(&mut self) -> Result<(), ValidationError> {
        self.context
            .lock()
            .map_err(|_| ValidationError::UnsafeObject)?
            .revalidate()
    }
}

impl FreshPrivateDirectory {
    fn lock_context(&self) -> Result<MutexGuard<'_, DirectoryContext>, ValidationError> {
        self.context
            .lock()
            .map_err(|_| ValidationError::UnsafeObject)
    }

    /// Re-read the same held object's owner/DACL/volume and retained ancestry.
    /// Any error, drift or poisoned context permanently refuses access.
    pub fn revalidate(&mut self) -> Result<(), ValidationError> {
        self.lock_context()?.revalidate()
    }

    /// Flush this newly created directory's entry in its immediate held parent.
    /// A separate same-ID write handle preserves all retained query handles and
    /// no-delete sharing. Any native or identity error permanently refuses this role.
    pub fn sync_parent_namespace(&mut self) -> Result<(), ValidationError> {
        let mut context = self.lock_context()?;
        context.revalidate()?;
        context.continuity = Continuity::Refused;
        let parent = &context
            .directory
            .parent
            .ancestors
            .last()
            .ok_or(ValidationError::UnsafeObject)?
            .file;
        crate::namespace_flush::flush_held_namespace(parent)?;
        context.continuity = Continuity::Live;
        context.revalidate()
    }

    /// Flush this held writable directory's data and metadata with real OS I/O.
    ///
    /// Failure permanently refuses the role. This does not flush its ancestor's
    /// initialization entry or by itself establish power-loss qualification.
    pub fn sync_all(&mut self) -> Result<(), ValidationError> {
        let mut context = self.lock_context()?;
        context.revalidate()?;
        context.continuity = Continuity::Refused;
        context.directory.file.sync_all()?;
        context.continuity = Continuity::Live;
        context.revalidate()
    }
}

impl DirectoryContext {
    fn revalidate(&mut self) -> Result<(), ValidationError> {
        if let Continuity::Refused = self.continuity {
            return Err(ValidationError::UnsafeObject);
        }
        self.continuity = Continuity::Refused;
        if self.directory.inspect()? != self.identity {
            return Err(ValidationError::UnsafeObject);
        }
        self.continuity = Continuity::Live;
        Ok(())
    }
}

#[cfg(test)]
#[path = "fresh_private_directory_tests.rs"]
mod tests;

#[path = "private_owner_lock.rs"]
mod private_owner_lock;
pub use private_owner_lock::OwnerLock;
pub use private_owner_lock::OwnerLockError;
pub use private_owner_lock::OwnerLockOrigin;

pub use private_owner_lock::LockedPrivateFile;
pub use private_owner_lock::PrivateFileAccess;

pub use private_owner_lock::LockedStateStage;
pub use private_owner_lock::StageReplaceError;

pub use private_owner_lock::OriginalFileAccess;
pub use private_owner_lock::OriginalStoreFile;
pub use private_owner_lock::PrivateStoreDirectory;
