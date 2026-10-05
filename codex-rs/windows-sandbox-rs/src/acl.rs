use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use std::ffi::c_void;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACCESS_DENIED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_SIZE_INFORMATION;
use windows_sys::Win32::Security::AclSizeInformation;
use windows_sys::Win32::Security::Authorization::EXPLICIT_ACCESS_W;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SetEntriesInAclW;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
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
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::ReOpenFile;
use windows_sys::Win32::Storage::FileSystem::SECURITY_IDENTIFICATION;
use windows_sys::Win32::Storage::FileSystem::SECURITY_SQOS_PRESENT;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;
const SE_KERNEL_OBJECT: u32 = 6;
const INHERIT_ONLY_ACE: u8 = 0x08;
const INHERITED_ACE: u8 = 0x10;
const ACCESS_ALLOWED_ACE_TYPE: u8 = 0;
const ACCESS_DENIED_ACE_TYPE: u8 = 1;
const DENY_ACCESS: i32 = 3;

fn acl_api_result(path: &Path, operation: &str, code: u32) -> Result<()> {
    if code == ERROR_SUCCESS {
        Ok(())
    } else {
        Err(anyhow!("{operation} failed for {}: {code}", path.display()))
    }
}

/// Fetch DACL via handle-based query; caller must LocalFree the returned SD.
///
/// # Safety
/// Caller must free the returned security descriptor with `LocalFree` and pass an existing path.
pub unsafe fn fetch_dacl_handle(path: &Path) -> Result<(*mut ACL, *mut c_void)> {
    let wpath = to_wide(path);
    let h = CreateFileW(
        wpath.as_ptr(),
        READ_CONTROL,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        std::ptr::null_mut(),
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        0,
    );
    if h == INVALID_HANDLE_VALUE {
        return Err(anyhow!("CreateFileW failed for {}", path.display()));
    }
    let mut p_sd: *mut c_void = std::ptr::null_mut();
    let mut p_dacl: *mut ACL = std::ptr::null_mut();
    let code = GetSecurityInfo(
        h,
        1, // SE_FILE_OBJECT
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut p_dacl,
        std::ptr::null_mut(),
        &mut p_sd,
    );
    CloseHandle(h);
    if code != ERROR_SUCCESS {
        return Err(anyhow!(
            "GetSecurityInfo failed for {}: {}",
            path.display(),
            code
        ));
    }
    Ok((p_dacl, p_sd))
}

/// Fast mask-based check: does an ACE for provided SIDs grant the desired mask? Skips inherit-only.
/// When `require_all_bits` is true, all bits in `desired_mask` must be present; otherwise any bit suffices.
pub unsafe fn dacl_mask_allows(
    p_dacl: *mut ACL,
    psids: &[*mut c_void],
    desired_mask: u32,
    require_all_bits: bool,
) -> bool {
    dacl_mask_allows_with_scope(
        p_dacl,
        psids,
        desired_mask,
        require_all_bits,
        AceScope::Effective,
    )
}

#[derive(Clone, Copy)]
enum AceScope {
    Effective,
    Explicit,
}

unsafe fn dacl_mask_allows_with_scope(
    p_dacl: *mut ACL,
    psids: &[*mut c_void],
    desired_mask: u32,
    require_all_bits: bool,
    scope: AceScope,
) -> bool {
    if p_dacl.is_null() {
        return false;
    }
    let mut info: ACL_SIZE_INFORMATION = std::mem::zeroed();
    let ok = GetAclInformation(
        p_dacl as *const ACL,
        &mut info as *mut _ as *mut c_void,
        std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
        AclSizeInformation,
    );
    if ok == 0 {
        return false;
    }
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    for i in 0..(info.AceCount as usize) {
        let mut p_ace: *mut c_void = std::ptr::null_mut();
        if GetAce(p_dacl as *const ACL, i as u32, &mut p_ace) == 0 {
            continue;
        }
        let hdr = &*(p_ace as *const ACE_HEADER);
        if hdr.AceType != ACCESS_ALLOWED_ACE_TYPE {
            continue; // not ACCESS_ALLOWED
        }
        if (hdr.AceFlags & INHERIT_ONLY_ACE) != 0 {
            continue;
        }
        // SET_ACCESS cannot replace an ACE inherited from an ancestor, so it cannot make
        // an explicit-only repair converge when that inherited ACE contains stale rights.
        if matches!(scope, AceScope::Explicit) && (hdr.AceFlags & INHERITED_ACE) != 0 {
            continue;
        }
        let base = p_ace as usize;
        let sid_ptr =
            (base + std::mem::size_of::<ACE_HEADER>() + std::mem::size_of::<u32>()) as *mut c_void;
        let mut matched = false;
        for sid in psids {
            if EqualSid(sid_ptr, *sid) != 0 {
                matched = true;
                break;
            }
        }
        if !matched {
            continue;
        }
        let ace = &*(p_ace as *const ACCESS_ALLOWED_ACE);
        let mut mask = ace.Mask;
        MapGenericMask(&mut mask, &mapping);
        if (require_all_bits && (mask & desired_mask) == desired_mask)
            || (!require_all_bits && (mask & desired_mask) != 0)
        {
            return true;
        }
    }
    false
}

/// Path-based wrapper around the mask check (single DACL fetch).
pub fn path_mask_allows(
    path: &Path,
    psids: &[*mut c_void],
    desired_mask: u32,
    require_all_bits: bool,
) -> Result<bool> {
    path_mask_allows_with_scope(
        path,
        psids,
        desired_mask,
        require_all_bits,
        AceScope::Effective,
    )
}

fn path_mask_allows_with_scope(
    path: &Path,
    psids: &[*mut c_void],
    desired_mask: u32,
    require_all_bits: bool,
    scope: AceScope,
) -> Result<bool> {
    unsafe {
        let (p_dacl, sd) = fetch_dacl_handle(path)?;
        let has = dacl_mask_allows_with_scope(p_dacl, psids, desired_mask, require_all_bits, scope);
        if !sd.is_null() {
            LocalFree(sd as HLOCAL);
        }
        Ok(has)
    }
}

pub unsafe fn dacl_has_write_allow_for_sid(p_dacl: *mut ACL, psid: *mut c_void) -> bool {
    if p_dacl.is_null() {
        return false;
    }
    let mut info: ACL_SIZE_INFORMATION = std::mem::zeroed();
    let ok = GetAclInformation(
        p_dacl as *const ACL,
        &mut info as *mut _ as *mut c_void,
        std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
        AclSizeInformation,
    );
    if ok == 0 {
        return false;
    }
    let count = info.AceCount as usize;
    for i in 0..count {
        let mut p_ace: *mut c_void = std::ptr::null_mut();
        if GetAce(p_dacl as *const ACL, i as u32, &mut p_ace) == 0 {
            continue;
        }
        let hdr = &*(p_ace as *const ACE_HEADER);
        if hdr.AceType != ACCESS_ALLOWED_ACE_TYPE {
            continue; // ACCESS_ALLOWED_ACE_TYPE
        }
        // Ignore ACEs that are inherit-only (do not apply to the current object)
        if (hdr.AceFlags & INHERIT_ONLY_ACE) != 0 {
            continue;
        }
        let ace = &*(p_ace as *const ACCESS_ALLOWED_ACE);
        let mask = ace.Mask;
        let base = p_ace as usize;
        let sid_ptr =
            (base + std::mem::size_of::<ACE_HEADER>() + std::mem::size_of::<u32>()) as *mut c_void;
        let eq = EqualSid(sid_ptr, psid);
        if eq != 0 && (mask & FILE_GENERIC_WRITE) != 0 {
            return true;
        }
    }
    false
}

// SAFETY: callers retain a valid ACL (or null) and valid SID throughout this query.
unsafe fn dacl_has_complete_deny_for_sid(
    p_dacl: *mut ACL,
    psid: *mut c_void,
    mut required_mask: u32,
    inheritance: u32,
) -> bool {
    if p_dacl.is_null() {
        return false;
    }
    let mut info: ACL_SIZE_INFORMATION = std::mem::zeroed();
    let ok = GetAclInformation(
        p_dacl as *const ACL,
        &mut info as *mut _ as *mut c_void,
        std::mem::size_of::<ACL_SIZE_INFORMATION>() as u32,
        AclSizeInformation,
    );
    if ok == 0 {
        return false;
    }
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    // Older ACLs may contain generic rights. Compare the same specific/standard
    // rights as the concrete mask installed by the current constructor.
    // SAFETY: both pointers refer to initialized stack values retained for the call.
    MapGenericMask(&mut required_mask, &mapping);
    for i in 0..info.AceCount {
        let mut p_ace: *mut c_void = std::ptr::null_mut();
        if GetAce(p_dacl as *const ACL, i, &mut p_ace) == 0 {
            return false;
        }
        let hdr = &*(p_ace as *const ACE_HEADER);
        // Only trust the leading explicit, unconditional deny ACEs. An earlier
        // allow can satisfy access before a later deny; unknown ACE types and
        // noncanonical order conservatively require installing the full deny.
        if hdr.AceType != ACCESS_DENIED_ACE_TYPE || (hdr.AceFlags & INHERITED_ACE) != 0 {
            return false;
        }
        // Files require an effective self-only ACE; directories also require
        // recursive inheritance. Inherit-only or no-propagate is insufficient.
        if hdr.AceFlags != inheritance as u8 {
            continue;
        }
        let ace = &*(p_ace as *const ACCESS_DENIED_ACE);
        let base = p_ace as usize;
        let sid_ptr =
            (base + std::mem::size_of::<ACE_HEADER>() + std::mem::size_of::<u32>()) as *mut c_void;
        let mut mask = ace.Mask;
        // SAFETY: both pointers refer to initialized stack values retained for the call.
        MapGenericMask(&mut mask, &mapping);
        if EqualSid(sid_ptr, psid) != 0 && (mask & required_mask) == required_mask {
            return true;
        }
    }
    false
}

// Grant DELETE on each inheriting descendant instead of FILE_DELETE_CHILD on
// its parent. A parent delete-child grant would bypass a direct deny-write ACE
// on protected children such as `.git` or an explicit read-only subpath.
const WRITE_ALLOW_MASK: u32 =
    FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE;

unsafe fn dacl_allow_mask_needs_refresh(
    p_dacl: *mut ACL,
    psid: *mut c_void,
    allow_mask: u32,
    disallow_mask: u32,
) -> bool {
    !dacl_mask_allows(p_dacl, &[psid], allow_mask, /*require_all_bits*/ true)
        || dacl_mask_allows_with_scope(
            p_dacl,
            &[psid],
            disallow_mask,
            /*require_all_bits*/ false,
            AceScope::Explicit,
        )
}

/// Returns whether any provided SID needs its writable-root allow ACE refreshed.
pub fn path_write_aces_need_refresh(path: &Path, psids: &[*mut c_void]) -> Result<bool> {
    unsafe {
        let (p_dacl, p_sd) = fetch_dacl_handle(path)?;
        let needs_refresh = psids.iter().any(|psid| {
            dacl_allow_mask_needs_refresh(p_dacl, *psid, WRITE_ALLOW_MASK, FILE_DELETE_CHILD)
        });
        if !p_sd.is_null() {
            LocalFree(p_sd as HLOCAL);
        }
        Ok(needs_refresh)
    }
}

unsafe fn ensure_allow_mask_aces_with_inheritance_impl(
    path: &Path,
    sids: &[*mut c_void],
    allow_mask: u32,
    disallow_mask: u32,
    inheritance: u32,
) -> Result<bool> {
    let (p_dacl, p_sd) = fetch_dacl_handle(path)?;
    let mut entries: Vec<EXPLICIT_ACCESS_W> = Vec::new();
    for sid in sids {
        if !dacl_allow_mask_needs_refresh(p_dacl, *sid, allow_mask, disallow_mask) {
            continue;
        }
        entries.push(EXPLICIT_ACCESS_W {
            grfAccessPermissions: allow_mask,
            grfAccessMode: 2, // SET_ACCESS
            grfInheritance: inheritance,
            Trustee: TRUSTEE_W {
                pMultipleTrustee: std::ptr::null_mut(),
                MultipleTrusteeOperation: 0,
                TrusteeForm: TRUSTEE_IS_SID,
                TrusteeType: TRUSTEE_IS_UNKNOWN,
                ptstrName: *sid as *mut u16,
            },
        });
    }
    let mut added = false;
    if !entries.is_empty() {
        let mut p_new_dacl: *mut ACL = std::ptr::null_mut();
        let code2 = SetEntriesInAclW(
            entries.len() as u32,
            entries.as_ptr(),
            p_dacl,
            &mut p_new_dacl,
        );
        if code2 == ERROR_SUCCESS {
            let code3 = SetNamedSecurityInfoW(
                to_wide(path).as_ptr() as *mut u16,
                1,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                p_new_dacl,
                std::ptr::null_mut(),
            );
            if code3 == ERROR_SUCCESS {
                added = true;
                if !p_new_dacl.is_null() {
                    LocalFree(p_new_dacl as HLOCAL);
                }
            } else {
                if !p_new_dacl.is_null() {
                    LocalFree(p_new_dacl as HLOCAL);
                }
                if !p_sd.is_null() {
                    LocalFree(p_sd as HLOCAL);
                }
                return Err(anyhow!("SetNamedSecurityInfoW failed: {code3}"));
            }
        } else {
            if !p_sd.is_null() {
                LocalFree(p_sd as HLOCAL);
            }
            return Err(anyhow!("SetEntriesInAclW failed: {code2}"));
        }
    }
    if !p_sd.is_null() {
        LocalFree(p_sd as HLOCAL);
    }
    Ok(added)
}

/// Ensure all provided SIDs have an allow ACE with the requested mask on the path.
/// Returns true if any ACE was added.
///
/// # Safety
/// Caller must pass valid SID pointers and an existing path; free the returned security descriptor with `LocalFree`.
pub unsafe fn ensure_allow_mask_aces_with_inheritance(
    path: &Path,
    sids: &[*mut c_void],
    allow_mask: u32,
    inheritance: u32,
) -> Result<bool> {
    ensure_allow_mask_aces_with_inheritance_impl(
        path,
        sids,
        allow_mask,
        /*disallow_mask*/ 0,
        inheritance,
    )
}

/// Ensure all provided SIDs have an allow ACE with the requested mask on the path.
/// Returns true if any ACE was added.
///
/// # Safety
/// Caller must pass valid SID pointers and an existing path; free the returned security descriptor with `LocalFree`.
pub unsafe fn ensure_allow_mask_aces(
    path: &Path,
    sids: &[*mut c_void],
    allow_mask: u32,
) -> Result<bool> {
    ensure_allow_mask_aces_with_inheritance(
        path,
        sids,
        allow_mask,
        CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
    )
}

/// Ensure all provided SIDs have a write-capable allow ACE on the path.
/// Returns true if any ACE was added.
///
/// # Safety
/// Caller must pass valid SID pointers and an existing path; free the returned security descriptor with `LocalFree`.
pub unsafe fn ensure_allow_write_aces(path: &Path, sids: &[*mut c_void]) -> Result<bool> {
    ensure_allow_mask_aces_with_inheritance_impl(
        path,
        sids,
        WRITE_ALLOW_MASK,
        FILE_DELETE_CHILD,
        CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
    )
}

/// Adds an allow ACE granting read/write/execute to the given SID on the target path.
///
/// # Safety
/// Caller must ensure `psid` points to a valid SID and `path` refers to an existing file or directory.
pub unsafe fn add_allow_ace(path: &Path, psid: *mut c_void) -> Result<bool> {
    let mut p_sd: *mut c_void = std::ptr::null_mut();
    let mut p_dacl: *mut ACL = std::ptr::null_mut();
    let code = GetNamedSecurityInfoW(
        to_wide(path).as_ptr(),
        1,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut p_dacl,
        std::ptr::null_mut(),
        &mut p_sd,
    );
    if let Err(err) = acl_api_result(path, "GetNamedSecurityInfoW", code) {
        if !p_sd.is_null() {
            LocalFree(p_sd as HLOCAL);
        }
        return Err(err);
    }
    // Already has write? Skip costly DACL rewrite.
    if dacl_has_write_allow_for_sid(p_dacl, psid) {
        if !p_sd.is_null() {
            LocalFree(p_sd as HLOCAL);
        }
        return Ok(false);
    }
    // Always ensure write is present: if an allow ACE exists without write, add one with write+RX.
    let trustee = TRUSTEE_W {
        pMultipleTrustee: std::ptr::null_mut(),
        MultipleTrusteeOperation: 0,
        TrusteeForm: TRUSTEE_IS_SID,
        TrusteeType: TRUSTEE_IS_UNKNOWN,
        ptstrName: psid as *mut u16,
    };
    let mut explicit: EXPLICIT_ACCESS_W = std::mem::zeroed();
    explicit.grfAccessPermissions = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE;
    explicit.grfAccessMode = 2; // SET_ACCESS
    explicit.grfInheritance = CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE;
    explicit.Trustee = trustee;
    let mut p_new_dacl: *mut ACL = std::ptr::null_mut();
    let code2 = SetEntriesInAclW(1, &explicit, p_dacl, &mut p_new_dacl);
    let result = if let Err(err) = acl_api_result(path, "SetEntriesInAclW", code2) {
        Err(err)
    } else {
        let code3 = SetNamedSecurityInfoW(
            to_wide(path).as_ptr() as *mut u16,
            1,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            p_new_dacl,
            std::ptr::null_mut(),
        );
        acl_api_result(path, "SetNamedSecurityInfoW", code3)
            .map(|()| !dacl_has_write_allow_for_sid(p_dacl, psid))
    };
    if !p_new_dacl.is_null() {
        LocalFree(p_new_dacl as HLOCAL);
    }
    if !p_sd.is_null() {
        LocalFree(p_sd as HLOCAL);
    }
    result
}

/// Adds a deny ACE to prevent write/append/delete for the given SID on the target path.
///
/// # Safety
/// Caller must ensure `psid` points to a valid SID and `path` refers to an existing file or directory.
pub unsafe fn add_deny_write_ace(path: &Path, psid: *mut c_void) -> Result<bool> {
    add_deny_ace(path, psid, DenyAceKind::Write)
}

#[derive(Clone, Copy)]
enum DenyAceKind {
    Read,
    Write,
}

impl DenyAceKind {
    fn mask(self) -> u32 {
        match self {
            // Inheritable GENERIC_* bits can be materialized as separate
            // inherit-only and effective ACEs. Install their concrete file
            // rights so one complete explicit ACE remains recognizable.
            Self::Read => FILE_GENERIC_READ,
            Self::Write => FILE_GENERIC_WRITE | DELETE | FILE_DELETE_CHILD,
        }
    }

    unsafe fn already_present(self, p_dacl: *mut ACL, psid: *mut c_void, inheritance: u32) -> bool {
        dacl_has_complete_deny_for_sid(p_dacl, psid, self.mask(), inheritance)
    }
}

unsafe fn add_deny_ace(path: &Path, psid: *mut c_void, kind: DenyAceKind) -> Result<bool> {
    // Determine scope and update the DACL through the same filesystem object.
    // A name-based reopen after metadata could replace a file with a directory
    // and mistakenly install a self-only ACE on the replacement directory.
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | FILE_READ_ATTRIBUTES)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .security_qos_flags(SECURITY_IDENTIFICATION)
        .open(path)
        .with_context(|| format!("open filesystem object for deny ACL on {}", path.display()))?;
    let metadata = file
        .metadata()
        .with_context(|| format!("read file type for deny ACL on {}", path.display()))?;
    let inheritance = if metadata.is_dir() {
        CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE
    } else {
        0
    };
    let mut p_sd: *mut c_void = std::ptr::null_mut();
    let mut p_dacl: *mut ACL = std::ptr::null_mut();
    let code = GetSecurityInfo(
        file.as_raw_handle() as HANDLE,
        1,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut p_dacl,
        std::ptr::null_mut(),
        &mut p_sd,
    );
    if code != ERROR_SUCCESS {
        if !p_sd.is_null() {
            LocalFree(p_sd as HLOCAL);
        }
        return Err(anyhow!(
            "GetSecurityInfo failed for {}: {code}",
            path.display()
        ));
    }
    let result = if kind.already_present(p_dacl, psid, inheritance) {
        Ok(false)
    } else {
        let trustee = TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: psid as *mut u16,
        };
        let mut explicit: EXPLICIT_ACCESS_W = std::mem::zeroed();
        explicit.grfAccessPermissions = kind.mask();
        explicit.grfAccessMode = DENY_ACCESS;
        explicit.grfInheritance = inheritance;
        explicit.Trustee = trustee;
        let mut p_new_dacl: *mut ACL = std::ptr::null_mut();
        let code2 = SetEntriesInAclW(1, &explicit, p_dacl, &mut p_new_dacl);
        let result = if let Err(err) = acl_api_result(path, "SetEntriesInAclW", code2) {
            Err(err)
        } else {
            // ReOpenFile retains the object's identity. Request WRITE_DAC only
            // for repairs; checking an already-complete deny needs no write access.
            let write_handle = ReOpenFile(
                file.as_raw_handle() as HANDLE,
                WRITE_DAC,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                FILE_FLAG_BACKUP_SEMANTICS | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION,
            );
            if write_handle == INVALID_HANDLE_VALUE {
                Err(anyhow!(
                    "ReOpenFile failed for {}: {}",
                    path.display(),
                    GetLastError(),
                ))
            } else {
                let write_file = File::from_raw_handle(write_handle as *mut c_void);
                let code3 = SetSecurityInfo(
                    write_file.as_raw_handle() as HANDLE,
                    1,
                    DACL_SECURITY_INFORMATION,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    p_new_dacl,
                    std::ptr::null_mut(),
                );
                acl_api_result(path, "SetSecurityInfo", code3).map(|()| true)
            }
        };
        if !p_new_dacl.is_null() {
            LocalFree(p_new_dacl as HLOCAL);
        }
        result
    };
    if !p_sd.is_null() {
        LocalFree(p_sd as HLOCAL);
    }
    result
}

/// Adds a deny ACE to prevent reads for the given SID on the target path.
///
/// `SetEntriesInAclW` places newly-created deny ACEs before allow ACEs, which
/// keeps the resulting DACL in the order Windows expects for denies to win.
/// The ACE is inheritable so a deny applied to a materialized directory also
/// covers files and directories later created underneath it.
///
/// # Safety
/// Caller must ensure `psid` points to a valid SID and `path` refers to an existing file or directory.
pub unsafe fn add_deny_read_ace(path: &Path, psid: *mut c_void) -> Result<bool> {
    add_deny_ace(path, psid, DenyAceKind::Read)
}

#[cfg(test)]
#[path = "acl_tests.rs"]
mod tests;

pub unsafe fn revoke_ace(path: &Path, psid: *mut c_void) {
    let mut p_sd: *mut c_void = std::ptr::null_mut();
    let mut p_dacl: *mut ACL = std::ptr::null_mut();
    let code = GetNamedSecurityInfoW(
        to_wide(path).as_ptr(),
        1,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut p_dacl,
        std::ptr::null_mut(),
        &mut p_sd,
    );
    if code != ERROR_SUCCESS {
        if !p_sd.is_null() {
            LocalFree(p_sd as HLOCAL);
        }
        return;
    }
    let trustee = TRUSTEE_W {
        pMultipleTrustee: std::ptr::null_mut(),
        MultipleTrusteeOperation: 0,
        TrusteeForm: TRUSTEE_IS_SID,
        TrusteeType: TRUSTEE_IS_UNKNOWN,
        ptstrName: psid as *mut u16,
    };
    let mut explicit: EXPLICIT_ACCESS_W = std::mem::zeroed();
    explicit.grfAccessPermissions = 0;
    explicit.grfAccessMode = 4; // REVOKE_ACCESS
    explicit.grfInheritance = CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE;
    explicit.Trustee = trustee;
    let mut p_new_dacl: *mut ACL = std::ptr::null_mut();
    let code2 = SetEntriesInAclW(1, &explicit, p_dacl, &mut p_new_dacl);
    if code2 == ERROR_SUCCESS {
        let _ = SetNamedSecurityInfoW(
            to_wide(path).as_ptr() as *mut u16,
            1,
            DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            p_new_dacl,
            std::ptr::null_mut(),
        );
        if !p_new_dacl.is_null() {
            LocalFree(p_new_dacl as HLOCAL);
        }
    }
    if !p_sd.is_null() {
        LocalFree(p_sd as HLOCAL);
    }
}

/// Grants RX to the null device for the given SID to support stdout/stderr redirection.
///
/// # Safety
/// Caller must ensure `psid` is a valid SID pointer.
pub unsafe fn allow_null_device(psid: *mut c_void) {
    let desired = 0x00020000 | 0x00040000; // READ_CONTROL | WRITE_DAC
    let h = CreateFileW(
        to_wide(r"\\\\.\\NUL").as_ptr(),
        desired,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        std::ptr::null_mut(),
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        0,
    );
    if h == 0 || h == INVALID_HANDLE_VALUE {
        return;
    }
    let mut p_sd: *mut c_void = std::ptr::null_mut();
    let mut p_dacl: *mut ACL = std::ptr::null_mut();
    let code = GetSecurityInfo(
        h,
        SE_KERNEL_OBJECT as i32,
        DACL_SECURITY_INFORMATION,
        std::ptr::null_mut(),
        std::ptr::null_mut(),
        &mut p_dacl,
        std::ptr::null_mut(),
        &mut p_sd,
    );
    if code == ERROR_SUCCESS {
        let trustee = TRUSTEE_W {
            pMultipleTrustee: std::ptr::null_mut(),
            MultipleTrusteeOperation: 0,
            TrusteeForm: TRUSTEE_IS_SID,
            TrusteeType: TRUSTEE_IS_UNKNOWN,
            ptstrName: psid as *mut u16,
        };
        let mut explicit: EXPLICIT_ACCESS_W = std::mem::zeroed();
        explicit.grfAccessPermissions =
            FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE;
        explicit.grfAccessMode = 2; // SET_ACCESS
        explicit.grfInheritance = 0;
        explicit.Trustee = trustee;
        let mut p_new_dacl: *mut ACL = std::ptr::null_mut();
        let code2 = SetEntriesInAclW(1, &explicit, p_dacl, &mut p_new_dacl);
        if code2 == ERROR_SUCCESS {
            let _ = SetSecurityInfo(
                h,
                SE_KERNEL_OBJECT as i32,
                DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                p_new_dacl,
                std::ptr::null_mut(),
            );
            if !p_new_dacl.is_null() {
                LocalFree(p_new_dacl as HLOCAL);
            }
        }
    }
    if !p_sd.is_null() {
        LocalFree(p_sd as HLOCAL);
    }
    CloseHandle(h);
}
const CONTAINER_INHERIT_ACE: u32 = 0x2;
const OBJECT_INHERIT_ACE: u32 = 0x1;
