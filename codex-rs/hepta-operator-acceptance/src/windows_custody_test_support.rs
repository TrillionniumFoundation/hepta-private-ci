//! Native adversarial fixtures only; never linked into product admission.

use std::fs::File;
use std::fs::OpenOptions;
use std::mem::size_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;

use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::AddAccessAllowedAceEx;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::CreateWellKnownSid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::WinWorldSid;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

pub(crate) fn control(path: &Path) -> File {
    OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
        .expect("fixture owner must be able to inspect/change only its new object's DACL")
}

fn owner(file: &File) -> Vec<u32> {
    let mut owner = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            OWNER_SECURITY_INFORMATION,
            &mut owner,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    assert_eq!(status, ERROR_SUCCESS, "fixture owner query must succeed");
    assert!(!owner.is_null());
    let length = unsafe { GetLengthSid(owner) } as usize;
    assert!(length > 0);
    let mut words = vec![0_u32; length.div_ceil(size_of::<u32>())];
    unsafe {
        ptr::copy_nonoverlapping(owner.cast::<u8>(), words.as_mut_ptr().cast::<u8>(), length)
    };
    unsafe { LocalFree(descriptor as HLOCAL) };
    words
}

pub(crate) fn world_sid() -> Vec<u32> {
    let mut words = vec![0_u32; 17];
    let mut length = (words.len() * size_of::<u32>()) as u32;
    assert_ne!(
        unsafe {
            CreateWellKnownSid(
                WinWorldSid,
                ptr::null_mut(),
                words.as_mut_ptr().cast(),
                &mut length,
            )
        },
        0,
        "world SID fixture must be valid"
    );
    words
}

/// Retains the real owner full-access ACE plus one caller-selected allow ACE.
/// Callers must first prove a private positive control, then assert rejection.
pub(crate) fn grant(path: &Path, mut sid: Vec<u32>, mask: u32, flags: u32) {
    let file = control(path);
    let mut owner = owner(&file);
    let owner = owner.as_mut_ptr().cast();
    let sid = sid.as_mut_ptr().cast();
    let size = size_of::<ACL>()
        + 2 * (size_of::<ACCESS_ALLOWED_ACE>() - size_of::<u32>())
        + unsafe { GetLengthSid(owner) + GetLengthSid(sid) } as usize;
    let mut words = vec![0_u32; size.div_ceil(size_of::<u32>())];
    let acl = words.as_mut_ptr().cast::<ACL>();
    assert_ne!(unsafe { InitializeAcl(acl, size as u32, ACL_REVISION) }, 0);
    assert_ne!(
        unsafe { AddAccessAllowedAceEx(acl, ACL_REVISION, 0, FILE_ALL_ACCESS, owner) },
        0
    );
    assert_ne!(
        unsafe { AddAccessAllowedAceEx(acl, ACL_REVISION, flags, mask, sid) },
        0
    );
    let status = unsafe {
        SetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            acl,
            ptr::null_mut(),
        )
    };
    assert_eq!(
        status, ERROR_SUCCESS,
        "ACL attack setup must succeed, not count as rejection"
    );
}

pub(crate) fn change_private_dacl(path: &Path) {
    let sid = owner(&control(path));
    grant(path, sid, FILE_ALL_ACCESS, /*flags*/ 0);
}

pub(crate) fn null_dacl(path: &Path) {
    let file = control(path);
    let status = unsafe {
        SetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
        )
    };
    assert_eq!(
        status, ERROR_SUCCESS,
        "null-DACL fixture mutation must succeed"
    );
}

#[cfg(feature = "windows-custody-privileged-tests")]
#[path = "windows_custody_owner_fixture.rs"]
mod owner_fixture;

#[cfg(feature = "windows-custody-privileged-tests")]
pub(crate) use owner_fixture::change_owner_to_enabled_group;

pub(crate) fn write_private_fixture(path: &Path, bytes: &[u8]) {
    use std::io::Write;
    let directory = codex_utils_path::open_existing_private_state_directory(path.parent().unwrap())
        .expect("existing private fixture parent");
    let mut file =
        codex_utils_path::create_private_recovery_copy(&directory, path.file_name().unwrap())
            .expect("create-only current-user-owned fixture");
    file.write_all(bytes).expect("fixture bytes");
}

pub(crate) fn write_inheriting_fixture(path: &Path) {
    use std::io::Write;
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::FromRawHandle;
    use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
    use windows_sys::Win32::Security::InitializeSecurityDescriptor;
    use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
    use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
    use windows_sys::Win32::Security::SetSecurityDescriptorOwner;
    use windows_sys::Win32::Storage::FileSystem::CREATE_NEW;
    use windows_sys::Win32::Storage::FileSystem::CreateFileW;
    use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
    use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
    let mut owner = owner(&control(path.parent().unwrap()));
    let mut descriptor: SECURITY_DESCRIPTOR = unsafe { std::mem::zeroed() };
    let descriptor_ptr = (&mut descriptor as *mut SECURITY_DESCRIPTOR).cast();
    assert_ne!(
        unsafe { InitializeSecurityDescriptor(descriptor_ptr, 1) },
        0
    );
    assert_ne!(
        unsafe { SetSecurityDescriptorOwner(descriptor_ptr, owner.as_mut_ptr().cast(), 0) },
        0
    );
    // Explicit current-user owner, but deliberately no supplied/protected DACL:
    // the new object inherits the genuinely unsafe ACE from its parent.
    let security = SECURITY_ATTRIBUTES {
        nLength: size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: descriptor_ptr,
        bInheritHandle: 0,
    };
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let handle = unsafe {
        CreateFileW(
            wide.as_ptr(),
            FILE_GENERIC_READ | FILE_GENERIC_WRITE,
            7,
            &security,
            CREATE_NEW,
            FILE_FLAG_OPEN_REPARSE_POINT,
            0,
        )
    };
    assert_ne!(
        handle, INVALID_HANDLE_VALUE,
        "inheriting fixture creation must succeed"
    );
    let mut file = unsafe { File::from_raw_handle(handle as *mut std::ffi::c_void) };
    file.write_all(b"sealed").unwrap();
    drop(file);
    assert_inherited_world_ace(path);
}

fn assert_inherited_world_ace(path: &Path) {
    use windows_sys::Win32::Security::EqualSid;
    use windows_sys::Win32::Security::GetAce;
    use windows_sys::Win32::Security::INHERITED_ACE;
    let file = control(path);
    let mut dacl: *mut ACL = ptr::null_mut();
    let mut descriptor = ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    assert_eq!(status, ERROR_SUCCESS);
    assert!(!dacl.is_null());
    let mut sid = world_sid();
    let mut inherited = false;
    for index in 0..u32::from(unsafe { (*dacl).AceCount }) {
        let mut ace = ptr::null_mut();
        assert_ne!(unsafe { GetAce(dacl, index, &mut ace) }, 0);
        let allowed = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
        if allowed.Header.AceType == 0
            && u32::from(allowed.Header.AceFlags) & INHERITED_ACE != 0
            && allowed.Header.AceFlags & 0x08 == 0 // not INHERIT_ONLY
            && allowed.Mask != 0
        {
            let ace_sid = ptr::addr_of!(allowed.SidStart).cast_mut().cast();
            inherited |= unsafe { EqualSid(ace_sid, sid.as_mut_ptr().cast()) } != 0;
        }
    }
    unsafe { LocalFree(descriptor as HLOCAL) };
    assert!(
        inherited,
        "must observe an actual effective inherited untrusted ACE before rejection"
    );
}

pub(crate) fn security_bytes(path: &Path) -> Vec<u8> {
    descriptor_bytes(path, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION)
}

#[cfg(feature = "windows-custody-privileged-tests")]
pub(crate) fn dacl_bytes(path: &Path) -> Vec<u8> {
    descriptor_bytes(path, DACL_SECURITY_INFORMATION)
}

fn descriptor_bytes(path: &Path, information: u32) -> Vec<u8> {
    use windows_sys::Win32::Security::GetSecurityDescriptorLength;
    let file = control(path);
    let mut descriptor = ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            information,
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
            &mut descriptor,
        )
    };
    assert_eq!(status, ERROR_SUCCESS);
    assert!(!descriptor.is_null());
    let length = unsafe { GetSecurityDescriptorLength(descriptor) } as usize;
    let bytes = unsafe { std::slice::from_raw_parts(descriptor.cast::<u8>(), length) }.to_vec();
    unsafe { LocalFree(descriptor as HLOCAL) };
    bytes
}
