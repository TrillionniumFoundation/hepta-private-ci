use super::LocalAllocation;
use super::grant_read_capability_for_root;
use super::verify_read_only_dacl;
use crate::token::LocalSid;
use anyhow::Result;
use pretty_assertions::assert_eq;
use std::ffi::c_void;
use std::fs;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

const READ_SID: &str = "S-1-5-21-111-222-333-444";

fn descriptor(sddl: &str) -> Result<(LocalAllocation, *mut ACL)> {
    let mut descriptor = LocalAllocation(ptr::null_mut());
    anyhow::ensure!(
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                crate::winutil::to_wide(sddl).as_ptr(),
                SDDL_REVISION_1,
                &mut descriptor.0,
                ptr::null_mut(),
            )
        } != 0,
        "create fixture descriptor: {}",
        std::io::Error::last_os_error()
    );
    let mut present = 0;
    let mut defaulted = 0;
    let mut dacl = ptr::null_mut();
    anyhow::ensure!(
        unsafe { GetSecurityDescriptorDacl(descriptor.0, &mut present, &mut dacl, &mut defaulted) }
            != 0
            && present != 0
            && !dacl.is_null(),
        "fixture DACL missing"
    );
    Ok((descriptor, dacl))
}

fn dacl_bytes(path: &Path) -> Result<Vec<u8>> {
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(path)?;
    let mut descriptor = LocalAllocation(ptr::null_mut());
    let mut dacl = ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            &mut dacl,
            ptr::null_mut(),
            &mut descriptor.0,
        )
    };
    anyhow::ensure!(
        status == ERROR_SUCCESS && !dacl.is_null(),
        "read fixture ACL: {status}"
    );
    Ok(
        unsafe { std::slice::from_raw_parts(dacl.cast::<u8>(), usize::from((*dacl).AclSize)) }
            .to_vec(),
    )
}

#[test]
fn inherit_only_read_capability_write_is_rejected_before_acl_mutation() -> Result<()> {
    let root = tempfile::TempDir::new()?;
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(root.path())?;
    let (_descriptor, dacl) = descriptor(&format!(
        "D:(A;OICI;FA;;;WD)(A;;FRFX;;;{READ_SID})(A;OICIIO;FWSD;;;{READ_SID})"
    ))?;
    let status = unsafe {
        SetSecurityInfo(
            file.as_raw_handle() as _,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            ptr::null_mut(),
            ptr::null_mut(),
            dacl,
            ptr::null_mut(),
        )
    };
    assert_eq!(status, ERROR_SUCCESS);
    let existing = root.path().join("existing.txt");
    fs::write(&existing, "retained content")?;
    let before = dacl_bytes(root.path())?;
    let read_sid = LocalSid::from_string(READ_SID)?;
    let group = LocalSid::from_string("S-1-1-0")?;
    let error =
        unsafe { grant_read_capability_for_root(root.path(), group.as_ptr(), read_sid.as_ptr()) }
            .expect_err("inherit-only write grant must reject read-capability admission");
    assert_eq!(
        (
            error.to_string().contains("validate read capability"),
            dacl_bytes(root.path())?,
            fs::read_to_string(existing)?
        ),
        (true, before, "retained content".to_string()),
    );
    Ok(())
}

#[test]
fn read_capability_grant_repairs_noninheritable_read_access() -> Result<()> {
    let root = tempfile::TempDir::new()?;
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
        .open(root.path())?;
    let (_descriptor, dacl) = descriptor(&format!("D:(A;OICI;FA;;;WD)(A;;FRFX;;;{READ_SID})"))?;
    assert_eq!(
        unsafe {
            SetSecurityInfo(
                file.as_raw_handle() as _,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                ptr::null_mut(),
                ptr::null_mut(),
                dacl,
                ptr::null_mut(),
            )
        },
        ERROR_SUCCESS
    );
    let read_sid = LocalSid::from_string(READ_SID)?;
    let group = LocalSid::from_string("S-1-1-0")?;
    unsafe { grant_read_capability_for_root(root.path(), group.as_ptr(), read_sid.as_ptr()) }?;
    let child = root.path().join("new-child.txt");
    fs::write(&child, "child content")?;
    assert_eq!(
        crate::acl::path_mask_allows(
            &child,
            &[read_sid.as_ptr()],
            FILE_GENERIC_READ | FILE_GENERIC_EXECUTE,
            /*require_all_bits*/ true
        )?,
        true
    );
    Ok(())
}

#[test]
fn unsupported_allow_ace_forms_fail_closed() -> Result<()> {
    let (_descriptor, dacl) = descriptor(&format!("D:(A;;FRFX;;;{READ_SID})"))?;
    let read_sid = LocalSid::from_string(READ_SID)?;
    unsafe { verify_read_only_dacl(dacl, read_sid.as_ptr()) }?;
    let mut ace: *mut c_void = ptr::null_mut();
    anyhow::ensure!(
        unsafe {
            GetAce(dacl, /*dwaceindex*/ 0, &mut ace)
        } != 0,
        "get fixture ACE"
    );
    // A callback allow entry must not be classified as an ordinary absent grant.
    unsafe {
        *ace.cast::<u8>() = 9;
    }
    assert!(unsafe { verify_read_only_dacl(dacl, read_sid.as_ptr()) }.is_err());
    Ok(())
}
