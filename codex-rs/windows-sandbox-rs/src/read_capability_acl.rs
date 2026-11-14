use anyhow::Context;
use anyhow::Result;
use std::ffi::c_void;
use std::fs::OpenOptions;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GRANT_ACCESS;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SET_ACCESS;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_APPEND_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_EA;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;

const FORBIDDEN_RIGHTS: u32 = FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_WRITE_ATTRIBUTES
    | FILE_DELETE_CHILD
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER;

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                LocalFree(self.0 as HLOCAL);
            }
        }
    }
}

/// Grants an exact inheritable read capability through one retained root handle.
///
/// Existing effective, inherit-only and inherited write grants for this SID are
/// rejected before mutation. Unsupported ACE forms also fail closed. This root
/// check does not certify explicit ACLs on independently protected descendants.
///
/// # Safety
/// Both SID pointers must identify live, valid SIDs for the complete call.
pub unsafe fn grant_read_capability_for_root(
    root: &Path,
    sandbox_group: *mut c_void,
    read_sid: *mut c_void,
) -> Result<()> {
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(root)
        .with_context(|| format!("open read capability root {}", root.display()))?;
    let metadata = file.metadata()?;
    anyhow::ensure!(
        metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT == 0,
        "read capability root is a reparse point: {}",
        root.display()
    );
    let handle = file.as_raw_handle() as _;
    let mut old_dacl = ptr::null_mut();
    let mut descriptor = LocalAllocation(ptr::null_mut());
    let status = unsafe {
        GetSecurityInfo(
            handle,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            &mut old_dacl,
            ptr::null_mut(),
            &mut descriptor.0,
        )
    };
    anyhow::ensure!(
        status == ERROR_SUCCESS,
        "read capability ACL query failed on {}: {status}",
        root.display()
    );
    unsafe { verify_read_only_dacl(old_dacl, read_sid) }
        .with_context(|| format!("validate read capability on {}", root.display()))?;
    let inheritance = if metadata.is_dir() {
        OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE
    } else {
        0
    };
    // Preserve normal-account rights from other active launches. The restricting
    // SID receives SET_ACCESS so a non-inheritable RX grant cannot suppress repair.
    let entries = [(sandbox_group, GRANT_ACCESS), (read_sid, SET_ACCESS)].map(|(sid, mode)| {
        EXPLICIT_ACCESS_W {
            grfAccessPermissions: FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
            grfAccessMode: mode,
            grfInheritance: inheritance,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: sid as *mut u16,
            },
        }
    });
    let mut new_dacl = ptr::null_mut();
    let status = unsafe {
        SetEntriesInAclW(
            entries.len() as u32,
            entries.as_ptr(),
            old_dacl,
            &mut new_dacl,
        )
    };
    let _new_dacl = LocalAllocation(new_dacl.cast());
    anyhow::ensure!(
        status == ERROR_SUCCESS,
        "build read capability ACL failed on {}: {status}",
        root.display()
    );
    unsafe { verify_read_only_dacl(new_dacl, read_sid) }?;
    let status = unsafe {
        SetSecurityInfo(
            handle,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            new_dacl,
            ptr::null_mut(),
        )
    };
    anyhow::ensure!(
        status == ERROR_SUCCESS,
        "grant read capability failed on {}: {status}",
        root.display()
    );
    Ok(())
}

unsafe fn verify_read_only_dacl(dacl: *mut ACL, read_sid: *mut c_void) -> Result<()> {
    anyhow::ensure!(!dacl.is_null(), "read root must have a DACL");
    let mut info: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    let ok = unsafe {
        GetAclInformation(
            dacl,
            (&mut info as *mut ACL_SIZE_INFORMATION).cast(),
            std::mem::size_of_val(&info) as u32,
            AclSizeInformation,
        )
    };
    anyhow::ensure!(
        ok != 0,
        "inspect read root DACL: {}",
        std::io::Error::last_os_error()
    );
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    for index in 0..info.AceCount {
        let mut ace = ptr::null_mut();
        anyhow::ensure!(
            unsafe { GetAce(dacl, index, &mut ace) } != 0,
            "inspect read root ACE: {}",
            std::io::Error::last_os_error()
        );
        let header = unsafe { &*ace.cast::<ACE_HEADER>() };
        // Ordinary deny entries cannot grant access. Unknown allow/object/
        // callback forms are not silently treated as absence of write rights.
        if header.AceType == 1 {
            continue;
        }
        anyhow::ensure!(
            header.AceType == 0,
            "unsupported read root ACE type {}",
            header.AceType
        );
        let length = usize::from(header.AceSize);
        anyhow::ensure!(length >= 16, "short read root allow ACE");
        let bytes = ace.cast::<u8>();
        let sid = unsafe { bytes.add(8).cast::<c_void>() };
        let sub_authorities = unsafe { *bytes.add(9) } as usize;
        anyhow::ensure!(
            8usize.saturating_add(8 + sub_authorities * 4) <= length,
            "read root ACE SID exceeds its bounds"
        );
        anyhow::ensure!(unsafe { IsValidSid(sid) } != 0, "invalid read root ACE SID");
        anyhow::ensure!(
            unsafe { GetLengthSid(sid) } as usize <= length - 8,
            "read root ACE SID length exceeds its bounds"
        );
        if unsafe { EqualSid(sid, read_sid) } != 0 {
            let mut mask = unsafe { ptr::read_unaligned(bytes.add(4).cast::<u32>()) };
            unsafe { MapGenericMask(&mut mask, &mapping) };
            anyhow::ensure!(
                mask & FORBIDDEN_RIGHTS == 0,
                "read capability has effective or inheritable write rights"
            );
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "read_capability_acl_tests.rs"]
mod tests;
