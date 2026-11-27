//! Install a complete deny on the object inspected by the same retained handle.

use std::ffi::c_void;
use std::fs::OpenOptions;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;

use anyhow::Result;
use anyhow::anyhow;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_DENIED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::DENY_ACCESS;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

use super::ACCESS_DENIED_ACE_TYPE;
use super::CONTAINER_INHERIT_ACE;
use super::INHERITED_ACE;
use super::OBJECT_INHERIT_ACE;
use super::acl_api_result;

#[derive(Clone, Copy)]
pub(super) enum DenyAceKind {
    Read,
    Write,
}

#[derive(Clone, Copy)]
pub(super) enum DenyScope {
    ObjectOnly,
    DirectoryTree,
}

impl DenyScope {
    fn inheritance(self) -> u32 {
        match self {
            Self::ObjectOnly => 0,
            Self::DirectoryTree => CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
        }
    }
}

impl DenyAceKind {
    pub(super) fn mask(self) -> u32 {
        // These are already the complete mapped file rights. Adding redundant
        // GENERIC_* bits can make Windows split effective and inherit-only ACEs.
        match self {
            Self::Read => FILE_GENERIC_READ,
            Self::Write => FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD,
        }
    }

    fn mask_for_scope(self, scope: DenyScope) -> u32 {
        match scope {
            DenyScope::ObjectOnly => self.mask() & !FILE_DELETE_CHILD,
            DenyScope::DirectoryTree => self.mask(),
        }
    }

    // SAFETY: The caller retains the ACL allocation and a valid SID.
    pub(super) unsafe fn already_present(
        self,
        dacl: *mut ACL,
        sid: *mut c_void,
        scope: DenyScope,
    ) -> bool {
        if dacl.is_null() {
            return false;
        }
        let mut info: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
        if unsafe {
            GetAclInformation(
                dacl,
                std::ptr::addr_of_mut!(info).cast(),
                std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
                AclSizeInformation,
            )
        } == 0
        {
            return false;
        }
        let required = self.mask_for_scope(scope);
        let mapping = GENERIC_MAPPING {
            GenericRead: FILE_GENERIC_READ,
            GenericWrite: FILE_GENERIC_WRITE,
            GenericExecute: FILE_GENERIC_EXECUTE,
            GenericAll: FILE_ALL_ACCESS,
        };
        for index in 0..info.AceCount {
            let mut pointer: *mut c_void = std::ptr::null_mut();
            if unsafe { GetAce(dacl, index, &mut pointer) } == 0 {
                return false;
            }
            let header = unsafe { &*pointer.cast::<ACE_HEADER>() };
            // Keep the original canonical-order requirement. Inherited,
            // conditional, or post-allow denies cannot justify a no-op repair.
            if header.AceType != ACCESS_DENIED_ACE_TYPE || header.AceFlags & INHERITED_ACE != 0 {
                return false;
            }
            if u32::from(header.AceFlags) != scope.inheritance() {
                continue;
            }
            let ace = unsafe { &*pointer.cast::<ACCESS_DENIED_ACE>() };
            let mut mask = ace.Mask;
            unsafe { MapGenericMask(&mut mask, &mapping) };
            let ace_sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast();
            if unsafe { EqualSid(ace_sid, sid) } != 0 && mask & required == required {
                return true;
            }
        }
        false
    }
}

// SAFETY: The caller supplies a valid SID for the duration of this operation.
pub(super) unsafe fn install(path: &Path, sid: *mut c_void, kind: DenyAceKind) -> Result<bool> {
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC | FILE_READ_ATTRIBUTES)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    let metadata = file.metadata()?;
    if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(anyhow!(
            "deny ACL target is a reparse point: {}",
            path.display()
        ));
    }
    let scope = if metadata.is_dir() {
        DenyScope::DirectoryTree
    } else if metadata.is_file() {
        DenyScope::ObjectOnly
    } else {
        return Err(anyhow!("deny ACL target is not a file or directory"));
    };
    let handle = file.as_raw_handle() as _;
    let mut descriptor: *mut c_void = std::ptr::null_mut();
    let mut dacl: *mut ACL = std::ptr::null_mut();
    let code = unsafe {
        GetSecurityInfo(
            handle,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut dacl,
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    let mut replacement: *mut ACL = std::ptr::null_mut();
    let result = (|| {
        acl_api_result(path, "GetSecurityInfo", code)?;
        if unsafe { kind.already_present(dacl, sid, scope) } {
            return Ok(false);
        }
        let entry = EXPLICIT_ACCESS_W {
            grfAccessPermissions: kind.mask_for_scope(scope),
            grfAccessMode: DENY_ACCESS,
            grfInheritance: scope.inheritance(),
            Trustee: TRUSTEE_W {
                pMultipleTrustee: std::ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid.cast(),
            },
        };
        let code = unsafe {
            SetEntriesInAclW(
                /*ccountofexplicitentries*/ 1,
                &entry,
                dacl,
                &mut replacement,
            )
        };
        acl_api_result(path, "SetEntriesInAclW", code)?;
        let code = unsafe {
            SetSecurityInfo(
                handle,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                replacement,
                std::ptr::null_mut(),
            )
        };
        acl_api_result(path, "SetSecurityInfo", code)?;
        Ok(true)
    })();
    // The descriptor owns dacl; the new ACL is a separate local allocation.
    if !replacement.is_null() {
        unsafe { LocalFree(replacement as HLOCAL) };
    }
    if !descriptor.is_null() {
        unsafe { LocalFree(descriptor as HLOCAL) };
    }
    result
}
