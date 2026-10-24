//! Held ancestry for create-only provisioning; no legacy store adoption.

use crate::mechanism;
use crate::namespace_acl;
use crate::primary_owner::CapturedPrimaryOwner;
use crate::security::ValidationError;
use crate::volume::inspect_local_ntfs;
use std::fs::File;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::path::Prefix;
use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::GetFinalPathNameByHandleW;
use windows_sys::Win32::Storage::FileSystem::VOLUME_NAME_GUID;

const MAX_ANCESTORS: usize = 32;
struct Ancestor {
    file: File,
    identity: mechanism::Identity,
}
enum Continuity {
    Live,
    Refused,
}

fn require_volume_root(file: &File) -> Result<(), ValidationError> {
    let mut name = [0_u16; 64];
    // SAFETY: the retained handle and fixed writable output remain live. GUID
    // spelling comes from this object, never from a caller's drive-letter claim.
    let size = unsafe {
        GetFinalPathNameByHandleW(
            file.as_raw_handle() as HANDLE,
            name.as_mut_ptr(),
            name.len() as u32,
            VOLUME_NAME_GUID,
        )
    } as usize;
    if size == 0 {
        return Err(io::Error::last_os_error().into());
    }
    let prefix: Vec<u16> = r"\\?\Volume{".encode_utf16().collect();
    if size != 49 || name[..prefix.len()] != prefix || name[47..49] != [125, 92] || name[49] != 0 {
        return Err(ValidationError::UnsafeObject);
    }
    for (index, unit) in name[11..47].iter().enumerate() {
        let valid = if matches!(index, 8 | 13 | 18 | 23) {
            *unit == 45
        } else {
            u8::try_from(*unit).is_ok_and(|byte| byte.is_ascii_hexdigit())
        };
        if !valid {
            return Err(ValidationError::UnsafeObject);
        }
    }
    Ok(())
}

fn opened(
    file: File,
    event: Option<mechanism::OpenObservation>,
    user: &crate::security::CurrentUser,
    volume: u32,
) -> Result<Ancestor, ValidationError> {
    let event = event.ok_or(ValidationError::UnsafeObject)?;
    if event.ntstatus != 0 || event.information != 1 {
        return Err(ValidationError::UnsafeObject);
    }
    non_inherited(&file)?;
    let identity = namespace_acl::observe_directory(&file, user)?;
    if identity.volume != volume {
        return Err(ValidationError::UnsafeObject);
    }
    Ok(Ancestor { file, identity })
}

fn non_inherited(file: &File) -> Result<(), ValidationError> {
    let mut flags = u32::MAX;
    // SAFETY: file remains held; the initialized flags output has exact size.
    if unsafe { GetHandleInformation(file.as_raw_handle() as HANDLE, &mut flags) } == 0 {
        return Err(io::Error::last_os_error().into());
    }
    if flags != 0 {
        return Err(ValidationError::UnsafeObject);
    }
    Ok(())
}

/// Holds the actual local NTFS ancestry under a live primary administrator.
///
/// This capability supports only subsequent atomic create-only provisioning.
/// It has no arbitrary-File, supplied-SID, receipt, Clone, or Serde constructor,
/// and exposes no raw handles. It does not adopt an existing private store or
/// revoke historical handles. Cold store recovery still needs its existing
/// initialization marker/frontier protocol and independent native qualification.
pub struct ParentAnchor {
    owner: CapturedPrimaryOwner,
    ancestors: Vec<Ancestor>,
    volume: u32,
    continuity: Continuity,
}

impl ParentAnchor {
    /// Traverse the actual volume root and at most 31 literal child components.
    /// Every open is synchronous, non-inherited, no-reparse and denies delete
    /// sharing; every held descriptor is checked against the ancestor policy.
    pub fn for_create_only(path: &Path) -> Result<Self, ValidationError> {
        if path.as_os_str().encode_wide().count() > 8192 {
            return Err(ValidationError::UnsafeObject);
        }
        let mut components = path.components();
        let prefix = match components.next() {
            Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::Disk(_)) => prefix,
            _ => return Err(ValidationError::UnsafeObject),
        };
        if components.next() != Some(Component::RootDir) {
            return Err(ValidationError::UnsafeObject);
        }
        let mut root = PathBuf::from(prefix.as_os_str());
        root.push(r"\");
        let leaves: Vec<_> = components.take(MAX_ANCESTORS).collect();
        if leaves.len() >= MAX_ANCESTORS
            || leaves
                .iter()
                .any(|part| !matches!(part, Component::Normal(_)))
        {
            return Err(ValidationError::UnsafeObject);
        }
        let mut owner = CapturedPrimaryOwner::capture()?;
        let mut event = None;
        let file = mechanism::open_namespace_volume(&root, |value| event = Some(value))?;
        require_volume_root(&file)?; // Reject SUBST/subdirectory aliases that skip parents.
        let volume = inspect_local_ntfs(&file)?.object.volume;
        let root = opened(file, event, owner.current_user()?, volume)?;
        let mut ancestors = vec![root];
        for leaf in leaves {
            let Component::Normal(name) = leaf else {
                return Err(ValidationError::UnsafeObject);
            };
            let mut event = None;
            let file = mechanism::open_namespace_child(
                &ancestors.last().ok_or(ValidationError::UnsafeObject)?.file,
                name,
                |value| event = Some(value),
            )?;
            ancestors.push(opened(file, event, owner.current_user()?, volume)?);
        }
        let mut anchor = Self {
            owner,
            ancestors,
            volume,
            continuity: Continuity::Live,
        };
        anchor.revalidate()?;
        Ok(anchor)
    }

    /// Recheck every retained identity/descriptor and the actual volume.
    /// Failure permanently refuses the same anchor; no path lookup or repair.
    pub fn revalidate(&mut self) -> Result<(), ValidationError> {
        if let Continuity::Refused = self.continuity {
            return Err(ValidationError::UnsafeObject);
        }
        self.continuity = Continuity::Refused;
        for ancestor in &self.ancestors {
            non_inherited(&ancestor.file)?;
            if namespace_acl::observe_directory(&ancestor.file, self.owner.current_user()?)?
                != ancestor.identity
            {
                return Err(ValidationError::UnsafeObject);
            }
        }
        let root = &self
            .ancestors
            .first()
            .ok_or(ValidationError::UnsafeObject)?
            .file;
        require_volume_root(root)?;
        if inspect_local_ntfs(root)?.object.volume != self.volume {
            return Err(ValidationError::UnsafeObject);
        }
        self.owner.revalidate()?;
        self.continuity = Continuity::Live;
        Ok(())
    }
}

#[cfg(test)]
#[path = "parent_anchor_tests.rs"]
mod tests;

#[path = "fresh_private_directory.rs"]
mod fresh_private_directory;
pub use fresh_private_directory::CreationFailure;
pub use fresh_private_directory::FreshPrivateDirectory;
pub use fresh_private_directory::UnverifiedCreatedDirectory;
