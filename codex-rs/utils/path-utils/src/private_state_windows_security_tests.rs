//! Native Windows creation-security regressions; run with normal and elevated tokens.

use super::*;
use pretty_assertions::assert_eq;
use windows_sys::Win32::Security::GetKernelObjectSecurity;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetSecurityDescriptorOwner;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_OWNER;
use windows_sys::Win32::Security::TokenOwner;

fn descriptor(file: &File) -> io::Result<Vec<u8>> {
    let mut length = 0;
    let information = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as HANDLE,
            information,
            ptr::null_mut(),
            /*nlength*/ 0,
            &mut length,
        );
    }
    if length == 0 {
        return Err(io::Error::last_os_error());
    }
    let mut bytes = vec![0_u8; length as usize];
    if unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as HANDLE,
            information,
            bytes.as_mut_ptr().cast(),
            length,
            &mut length,
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(bytes)
}

fn read_only_descriptor(security: &SECURITY_ATTRIBUTES) -> io::Result<()> {
    let mut present = 0;
    let mut defaulted = 0;
    let mut dacl = ptr::null_mut();
    if unsafe {
        GetSecurityDescriptorDacl(
            security.lpSecurityDescriptor,
            &mut present,
            &mut dacl,
            &mut defaulted,
        )
    } == 0
        || present == 0
        || dacl.is_null()
    {
        return Err(io::Error::last_os_error());
    }
    let mut ace = ptr::null_mut();
    if unsafe {
        GetAce(dacl, /*dwaceindex*/ 0, &mut ace)
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    // Restrict only this new fixture's descriptor before creation. No existing
    // object is made public or has its owner/security changed for this test.
    unsafe { (*(ace as *mut ACCESS_ALLOWED_ACE)).Mask = FILE_GENERIC_READ };
    Ok(())
}

#[test]
fn new_directory_and_child_have_explicit_token_user_ownership() {
    let current_user = CurrentUser::read().expect("current user");
    let mut length = 0;
    unsafe {
        GetTokenInformation(
            current_user.token,
            TokenOwner,
            ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut length,
        );
    }
    assert!(length > 0);
    let mut default_owner = vec![0_u8; length as usize];
    assert_ne!(
        unsafe {
            GetTokenInformation(
                current_user.token,
                TokenOwner,
                default_owner.as_mut_ptr().cast(),
                length,
                &mut length,
            )
        },
        0
    );
    let token_owner = unsafe { ptr::read_unaligned(default_owner.as_ptr().cast::<TOKEN_OWNER>()) };
    eprintln!(
        "token_default_owner_matches_user={}",
        unsafe { EqualSid(token_owner.Owner, current_user.sid()) } != 0
    );

    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("owner");
    let directory = open_private_state_directory(&root).expect("private directory");
    let child = open_private_state_child(&directory, "state", PrivateFileAccess::Create)
        .expect("private child");
    for file in [&directory, &child] {
        let mut bytes = descriptor(file).expect("created security descriptor");
        let mut owner = ptr::null_mut();
        let mut defaulted = 1;
        assert_ne!(
            unsafe {
                GetSecurityDescriptorOwner(bytes.as_mut_ptr().cast(), &mut owner, &mut defaulted)
            },
            0
        );
        assert_ne!(unsafe { EqualSid(owner, current_user.sid()) }, 0);
        assert_eq!(defaulted, 0);
        validate_private_owner_and_dacl(file).expect("private owner and DACL");
    }
}

#[test]
fn opening_existing_objects_never_rewrites_their_security() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let restricted_root = temporary.path().join("read-only-root");
    let wide = wide_path(&restricted_root).expect("wide root");
    with_private_security(|security| {
        read_only_descriptor(security)?;
        if unsafe { CreateDirectoryW(wide.as_ptr(), security) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    })
    .expect("read-only fixture directory");
    let restricted_directory = OpenOptions::new()
        .read(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(&restricted_root)
        .expect("read descriptor handle");
    let before = descriptor(&restricted_directory).expect("original directory security");
    // A privileged token may open this directory despite the read-only DACL.
    // Either outcome must leave the existing descriptor exactly unchanged.
    drop(open_private_state_directory(&restricted_root));
    assert_eq!(
        descriptor(&restricted_directory).expect("after open"),
        before
    );

    let directory = open_private_state_directory(&temporary.path().join("private-root"))
        .expect("private directory");
    let wide =
        wide_path(&child_path(&directory, "state").expect("child path")).expect("wide child");
    let child = with_private_security(|security| {
        read_only_descriptor(security)?;
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                FILE_GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                security,
                CREATE_NEW,
                FILE_FLAG_OPEN_REPARSE_POINT,
                /*htemplatefile*/ 0,
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        Ok(unsafe { File::from_raw_handle(handle as *mut c_void) })
    })
    .expect("read-only fixture child");
    let before = descriptor(&child).expect("original child security");
    drop(open_private_state_child(
        &directory,
        "state",
        PrivateFileAccess::Create,
    ));
    assert_eq!(descriptor(&child).expect("after open"), before);
}

#[test]
fn native_creation_rejects_nul_without_creating_a_prefix_path() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let error = open_private_state_directory(&temporary.path().join("prefix\0suffix"))
        .expect_err("NUL must not terminate the Win32 path early");
    assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
    assert!(!temporary.path().join("prefix").exists());
    let directory = open_private_state_directory(&temporary.path().join("private-root"))
        .expect("private directory");
    let error = open_private_state_child(&directory, "prefix\0suffix", PrivateFileAccess::Create)
        .expect_err("NUL child must not be created");
    assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
    assert!(!private_state_child_exists(&directory, "prefix").expect("prefix absent"));
}
