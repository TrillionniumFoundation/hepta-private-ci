use super::*;
use super::super::PrivateFileAccess;
use super::super::open_private_recovery_source;
use super::super::open_private_state_child;
use super::super::open_private_state_directory;
use std::os::windows::fs::OpenOptionsExt;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::AddAccessAllowedAceEx;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

#[test]
fn a_changed_but_still_private_dacl_changes_the_snapshot() -> io::Result<()> {
    let temporary = tempfile::tempdir()?;
    let root = temporary.path().join("source");
    let directory = open_private_state_directory(&root)?;
    drop(open_private_state_child(&directory, "data", PrivateFileAccess::Create)?);
    let file = open_private_recovery_source(&directory, std::ffi::OsStr::new("data"))?;
    let before = private_state_snapshot(&file)?;
    let user = CurrentUser::read()?;
    let sid_length = unsafe { GetLengthSid(user.sid()) } as usize;
    let ace_bytes = size_of::<ACCESS_ALLOWED_ACE>() - size_of::<u32>() + sid_length;
    let size = size_of::<ACL>() + 2 * ace_bytes;
    let mut words = vec![0_u32; size.div_ceil(size_of::<u32>())];
    let dacl = words.as_mut_ptr().cast::<ACL>();
    if unsafe { InitializeAcl(dacl, size as u32, ACL_REVISION) } == 0 {
        return Err(io::Error::last_os_error());
    }
    for mask in [FILE_ALL_ACCESS, FILE_GENERIC_READ] {
        if unsafe { AddAccessAllowedAceEx(dacl, ACL_REVISION, 0, mask, user.sid()) } == 0 {
            return Err(io::Error::last_os_error());
        }
    }
    // The same trusted user retains all access. A redundant read ACE makes
    // an actual valid ACL change; merely rechecking policy would miss it.
    let control = std::fs::OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(root.join("data"))?;
    let status = unsafe {
        SetSecurityInfo(
            control.as_raw_handle() as HANDLE,
            1,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(), ptr::null_mut(), dacl, ptr::null_mut(),
        )
    };
    if status != ERROR_SUCCESS {
        return Err(io::Error::from_raw_os_error(status as i32));
    }
    let after = private_state_snapshot(&file)?;
    assert_ne!(before.security, after.security);
    assert_ne!(before, after);
    Ok(())
}
