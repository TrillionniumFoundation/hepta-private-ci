use std::fs;
use std::io;
use std::io::Write;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsHandle;
use std::path::Path;
use std::ptr;

use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetNamedSecurityInfoW;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;

use super::LocalDescriptor;
use super::current_user_sid;
use crate::windows_private_fs::PrivateDirectory;

fn grant_world_read(path: &Path) -> io::Result<()> {
    let user = current_user_sid()?.to_sddl();
    let descriptor =
        LocalDescriptor::from_sddl(&format!("O:{user}D:P(A;;FA;;;{user})(A;;GR;;;WD)"))?;
    let mut dacl = ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    let path: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    // SAFETY: this test owns the path and the descriptor outlives the call.
    // Keep full control for the creating user so TempDir cleanup is unchanged.
    unsafe {
        if GetSecurityDescriptorDacl(descriptor.as_ptr(), &mut present, &mut dacl, &mut defaulted)
            == 0
        {
            return Err(io::Error::last_os_error());
        }
        let status = SetNamedSecurityInfoW(
            path.as_ptr(),
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            dacl,
            ptr::null(),
        );
        if status != 0 {
            return Err(io::Error::from_raw_os_error(status as i32));
        }
    }
    Ok(())
}

fn dacl_bytes(file: &fs::File) -> io::Result<Vec<u8>> {
    let descriptor = LocalDescriptor::from_handle(file.as_handle(), DACL_SECURITY_INFORMATION)?;
    // SAFETY: the validated descriptor owns exactly the OS-reported size.
    Ok(unsafe {
        std::slice::from_raw_parts(
            descriptor.as_ptr().cast(),
            GetSecurityDescriptorLength(descriptor.as_ptr()) as usize,
        )
        .to_vec()
    })
}

#[test]
fn unsafe_directory_acl_is_rejected_without_repairing_it() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("state");
    let directory = PrivateDirectory::open_or_create(&root)?;
    grant_world_read(&root)?;
    let before = dacl_bytes(directory.as_file())?;
    assert_eq!(
        directory.validate().unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(
        PrivateDirectory::open_or_create(&root).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(dacl_bytes(directory.as_file())?, before);
    Ok(())
}

#[test]
fn unsafe_file_acl_is_rejected_before_write_or_replacement() -> io::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("state");
    let directory = PrivateDirectory::open_or_create(&root)?;
    let mut file = directory.create_new("state.json")?;
    file.write_all(b"unchanged")?;
    file.sync_all()?;
    grant_world_read(&root.join("state.json"))?;
    let before = dacl_bytes(&file)?;
    assert_eq!(
        directory.open_write("state.json").unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    let mut next = directory.create_new("state.next")?;
    next.write_all(b"new state")?;
    next.sync_all()?;
    assert_eq!(
        directory
            .replace("state.next", "state.json")
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    assert_eq!(fs::read(root.join("state.json"))?, b"unchanged");
    assert_eq!(dacl_bytes(&file)?, before);
    assert!(directory.entry_exists("state.next")?);
    Ok(())
}
