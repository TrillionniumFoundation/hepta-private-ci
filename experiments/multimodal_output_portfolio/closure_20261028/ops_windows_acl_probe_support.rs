use crate::acl;
use crate::winutil;
use anyhow::anyhow;
use anyhow::Result;
use std::ffi::c_void;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::DENY_ACCESS;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_SID;
use windows_sys::Win32::Security::Authorization::TRUSTEE_IS_UNKNOWN;
use windows_sys::Win32::Security::Authorization::TRUSTEE_W;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetAclInformation;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::ImpersonateLoggedOnUser;
use windows_sys::Win32::Security::IsTokenRestricted;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::MapGenericMask;
use windows_sys::Win32::Security::RevertToSelf;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::CONTAINER_INHERIT_ACE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::OBJECT_INHERIT_ACE;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_APPEND_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;

pub struct OwnedToken(pub HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

struct LocalAllocation(*mut c_void);

impl Drop for LocalAllocation {
    fn drop(&mut self) {
        unsafe { LocalFree(self.0 as HLOCAL) };
    }
}

pub struct Impersonation;

impl Impersonation {
    pub fn enter(token: &OwnedToken) -> Result<Self> {
        if unsafe { ImpersonateLoggedOnUser(token.0) } == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(Self)
    }
}

impl Drop for Impersonation {
    fn drop(&mut self) {
        if unsafe { RevertToSelf() } == 0 {
            std::process::abort();
        }
    }
}

pub fn check(label: &str, passed: bool) {
    println!("CHECK\t{label}\t{passed}");
}

pub fn operation<T>(label: &str, result: &std::io::Result<T>) -> bool {
    match result {
        Ok(_) => println!("OP\t{label}\ttrue\t0\tNone"),
        Err(error) => println!(
            "OP\t{label}\tfalse\t{}\t{:?}",
            error.raw_os_error().unwrap_or(-1),
            error.kind()
        ),
    }
    result.is_ok()
}

pub fn permission_denied<T>(result: &std::io::Result<T>) -> bool {
    result
        .as_ref()
        .is_err_and(|error| error.kind() == std::io::ErrorKind::PermissionDenied)
}

unsafe fn sid_string(sid: *mut c_void) -> Result<String> {
    if unsafe { IsValidSid(sid) } == 0 {
        return Err(anyhow!("invalid SID returned by native security API"));
    }
    let length = unsafe { GetLengthSid(sid) } as usize;
    let bytes = unsafe { std::slice::from_raw_parts(sid.cast::<u8>(), length) };
    winutil::string_from_sid_bytes(bytes).map_err(|error| anyhow!(error))
}

pub fn dump_token(label: &str, token: &OwnedToken) -> Result<()> {
    println!(
        "FLAG\t{label}\trestricted\t{}",
        unsafe { IsTokenRestricted(token.0) } != 0
    );
    for (class, kind) in [
        (TokenUser, "user"),
        (TokenGroups, "normal"),
        (TokenRestrictedSids, "restricting"),
    ] {
        let mut needed = 0;
        unsafe { GetTokenInformation(token.0, class, std::ptr::null_mut(), 0, &mut needed) };
        anyhow::ensure!(needed >= 4, "token group size query failed");
        // GetTokenInformation contains aligned pointers, so use aligned storage.
        let mut buffer = vec![0_usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
        if unsafe {
            GetTokenInformation(
                token.0,
                class,
                buffer.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } == 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        let start = buffer.as_ptr().cast::<u8>();
        let (count, offset) = if class == TokenUser {
            (1, 0)
        } else {
            let count = unsafe { std::ptr::read_unaligned(start.cast::<u32>()) } as usize;
            let alignment = std::mem::align_of::<SID_AND_ATTRIBUTES>();
            (
                count,
                std::mem::size_of::<u32>().div_ceil(alignment) * alignment,
            )
        };
        anyhow::ensure!(
            count == 0
                || offset + count * std::mem::size_of::<SID_AND_ATTRIBUTES>() <= needed as usize,
            "invalid native group buffer"
        );
        println!("GROUPS\t{label}\t{kind}\t{count}");
        for index in 0..count {
            let entry = unsafe {
                std::ptr::read_unaligned(start.add(offset).cast::<SID_AND_ATTRIBUTES>().add(index))
            };
            let sid = unsafe { sid_string(entry.Sid)? };
            println!(
                "TOKEN\t{label}\t{kind}\t{index}\t{:08x}\t{sid}",
                entry.Attributes
            );
        }
    }
    Ok(())
}

pub fn dump_acl(label: &str, path: &Path) -> Result<()> {
    let (dacl, descriptor) = unsafe { acl::fetch_dacl_handle(path)? };
    let _descriptor = LocalAllocation(descriptor);
    anyhow::ensure!(!dacl.is_null(), "unexpected null DACL");
    let mut info: ACL_SIZE_INFORMATION = unsafe { std::mem::zeroed() };
    if unsafe {
        GetAclInformation(
            dacl,
            (&mut info as *mut ACL_SIZE_INFORMATION).cast(),
            std::mem::size_of_val(&info) as u32,
            AclSizeInformation,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().into());
    }
    println!("ACL\t{label}\t{}", info.AceCount);
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    for index in 0..info.AceCount {
        let mut pointer = std::ptr::null_mut();
        if unsafe { GetAce(dacl, index, &mut pointer) } == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let header = unsafe { &*pointer.cast::<ACE_HEADER>() };
        let (mask, mapped, sid) = if header.AceType == 0 || header.AceType == 1 {
            anyhow::ensure!(
                header.AceSize as usize >= std::mem::size_of::<ACCESS_ALLOWED_ACE>(),
                "short native ACE"
            );
            let ace = unsafe { &*pointer.cast::<ACCESS_ALLOWED_ACE>() };
            let mut mapped = ace.Mask;
            unsafe { MapGenericMask(&mut mapped, &mapping) };
            let sid = unsafe { sid_string((&ace.SidStart as *const u32).cast_mut().cast())? };
            (ace.Mask, mapped, sid)
        } else {
            (0, 0, "not-simple-allow-or-deny".to_owned())
        };
        println!(
            "ACE\t{label}\t{index}\t{}\t{:02x}\t{mask:08x}\t{mapped:08x}\t{sid}",
            header.AceType, header.AceFlags
        );
    }
    Ok(())
}

pub fn seed_partial_deny(path: &Path, sid: *mut c_void) -> Result<()> {
    let entry = EXPLICIT_ACCESS_W {
        grfAccessPermissions: DELETE,
        grfAccessMode: DENY_ACCESS,
        grfInheritance: OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
        Trustee: TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: sid.cast(),
        },
    };
    let (dacl, descriptor) = unsafe { acl::fetch_dacl_handle(path)? };
    let _descriptor = LocalAllocation(descriptor);
    let mut partial = std::ptr::null_mut();
    let code = unsafe { SetEntriesInAclW(1, &entry, dacl, &mut partial) };
    let _partial = LocalAllocation(partial.cast());
    anyhow::ensure!(
        code == ERROR_SUCCESS,
        "partial deny construction failed: {code}"
    );
    let code = unsafe {
        SetNamedSecurityInfoW(
            winutil::to_wide(path).as_ptr().cast_mut(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            partial,
            std::ptr::null_mut(),
        )
    };
    anyhow::ensure!(
        code == ERROR_SUCCESS,
        "partial deny persistence failed: {code}"
    );
    Ok(())
}

pub fn open_matrix(label: &str, path: &Path) {
    for (access, mask) in [
        ("read_data", FILE_READ_DATA),
        ("write_data_or_add_file", FILE_WRITE_DATA),
        ("append_data_or_add_directory", FILE_APPEND_DATA),
        ("write_attributes", FILE_WRITE_ATTRIBUTES),
        ("read_control", READ_CONTROL),
        ("delete", DELETE),
        ("delete_and_write_data", DELETE | FILE_WRITE_DATA),
        ("delete_child", FILE_DELETE_CHILD),
        (
            "delete_child_and_add_file",
            FILE_DELETE_CHILD | FILE_WRITE_DATA,
        ),
        ("generic_read", 0x8000_0000),
        ("generic_write", 0x4000_0000),
        ("generic_all", 0x1000_0000),
    ] {
        let handle = unsafe {
            CreateFileW(
                winutil::to_wide(path).as_ptr(),
                mask,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                0,
            )
        };
        let succeeded = handle != INVALID_HANDLE_VALUE;
        let error = if succeeded {
            0
        } else {
            unsafe { GetLastError() }
        };
        if succeeded {
            unsafe { CloseHandle(handle) };
        }
        println!("OPEN\t{label}\t{access}\t{mask:08x}\t{succeeded}\t{error}");
    }
}
