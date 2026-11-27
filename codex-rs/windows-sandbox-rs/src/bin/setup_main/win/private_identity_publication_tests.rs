use super::super::no_reparse_dir::open_or_create_private_no_reparse;
use super::*;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::System::WindowsProgramming::GetUserNameW;

fn actual_user() -> Result<String> {
    let mut username = [0u16; 257];
    let mut size = username.len() as u32;
    ensure!(
        unsafe { GetUserNameW(username.as_mut_ptr(), &mut size) } != 0,
        "read actual publication test account"
    );
    Ok(String::from_utf16(&username[..size as usize - 1])?)
}

fn set_owned_directory_descriptor(
    directory: &OwnedHandle,
    descriptor: &super::super::private_identity_security::Descriptor,
) -> Result<()> {
    let mut present = 0;
    let mut defaulted = 0;
    let mut acl = std::ptr::null_mut();
    ensure!(
        unsafe { GetSecurityDescriptorDacl(descriptor.0, &mut present, &mut acl, &mut defaulted) }
            != 0
            && present != 0
            && !acl.is_null(),
        "owned negative descriptor has no DACL"
    );
    ensure!(
        unsafe {
            SetSecurityInfo(
                directory.as_raw_handle() as _,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                acl,
                std::ptr::null_mut(),
            )
        } == 0,
        "set owned publication negative descriptor"
    );
    Ok(())
}

#[test]
fn unsafe_existing_directory_is_refused_without_narrowing() -> Result<()> {
    let home = tempfile::TempDir::new()?;
    let path = sandbox_secrets_dir(home.path());
    let wide = protected_descriptor(Some("S-1-1-0"), "OICI")?;
    let original_handle = open_or_create_private_no_reparse(&path, wide.0)?;
    let before = handle_descriptor(original_handle.as_raw_handle() as _, SE_FILE_OBJECT)?;
    validate_protection(&before, Some("S-1-1-0"), 3, FILE_ALL_ACCESS)?;
    ensure!(
        PrivateSecrets::prepare(home.path(), &actual_user()?).is_err(),
        "existing broad directory was narrowed and accepted"
    );
    let after = handle_descriptor(original_handle.as_raw_handle() as _, SE_FILE_OBJECT)?;
    validate_protection(&after, Some("S-1-1-0"), 3, FILE_ALL_ACCESS)?;
    ensure!(
        !path.join("sandbox_users.json").exists(),
        "refused broad directory received a credential file"
    );
    Ok(())
}

#[test]
fn changed_parent_dacl_is_refused_before_any_secret_write() -> Result<()> {
    let home = tempfile::TempDir::new()?;
    let publication = PrivateSecrets::prepare(home.path(), &actual_user()?)?;
    let wide = protected_descriptor(Some("S-1-1-0"), "OICI")?;
    set_owned_directory_descriptor(&publication.directory, &wide)?;
    ensure!(
        publication.publish(b"must never be written").is_err(),
        "changed directory protection was accepted"
    );
    ensure!(
        !publication.path.join("sandbox_users.json").exists(),
        "rejected directory permissions still published secret bytes"
    );
    Ok(())
}

#[test]
fn protected_leaf_is_independent_of_later_parent_permissions() -> Result<()> {
    let home = tempfile::TempDir::new()?;
    let publication = PrivateSecrets::prepare(home.path(), &actual_user()?)?;
    publication.publish(b"owned leaf descriptor control")?;
    let path = publication.path.join("sandbox_users.json");
    let before = File::open(&path)?;
    publication.validate_file(&before)?;
    drop(before);
    let wide = protected_descriptor(Some("S-1-1-0"), "OICI")?;
    set_owned_directory_descriptor(&publication.directory, &wide)?;
    let after = File::open(&path)?;
    publication.validate_file(&after)?;
    ensure!(
        std::fs::read(&path)? == b"owned leaf descriptor control",
        "directory change modified the already-private file"
    );
    Ok(())
}
