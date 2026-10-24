//! Atomic fresh-directory creation only; no existing-store or journal factory.

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

/// A failed post-create readback retains the actual new directory and ancestry.
/// It grants no validated operations; dropping it only closes owned handles.
pub struct UnverifiedCreatedDirectory {
    parent: ParentAnchor,
    file: File,
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
    created: UnverifiedCreatedDirectory,
    identity: Identity,
    continuity: Continuity,
}

impl UnverifiedCreatedDirectory {
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
        let mut created = UnverifiedCreatedDirectory { parent: self, file };
        let validate = (|| {
            let event = event.ok_or(ValidationError::UnsafeObject)?;
            if event.ntstatus != 0 || event.information != 2 {
                return Err(ValidationError::UnsafeObject);
            }
            created.inspect()
        })();
        match validate {
            Ok(identity) => Ok(FreshPrivateDirectory {
                created,
                identity,
                continuity: Continuity::Live,
            }),
            Err(error) => Err(CreationFailure::Created {
                directory: Box::new(created),
                error,
            }),
        }
    }
}

impl FreshPrivateDirectory {
    /// Re-read the same held object's owner/DACL/volume and retained ancestry.
    /// Any error or drift permanently refuses this role.
    pub fn revalidate(&mut self) -> Result<(), ValidationError> {
        if let Continuity::Refused = self.continuity {
            return Err(ValidationError::UnsafeObject);
        }
        self.continuity = Continuity::Refused;
        if self.created.inspect()? != self.identity {
            return Err(ValidationError::UnsafeObject);
        }
        self.continuity = Continuity::Live;
        Ok(())
    }
}

#[cfg(test)]
#[path = "fresh_private_directory_tests.rs"]
mod tests;
