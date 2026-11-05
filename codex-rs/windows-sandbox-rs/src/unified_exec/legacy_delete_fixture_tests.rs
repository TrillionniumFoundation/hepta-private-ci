//! Ordinary-user ACL prerequisites for the legacy delete fixture.

use crate::acl::ensure_allow_write_aces;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;

pub(super) fn grant_writable_roots_to_current_user(roots: [&Path; 3]) {
    let mut raw_token = 0;
    assert_ne!(
        // SAFETY: the process pseudo-handle is valid and raw_token is writable.
        unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw_token) },
        0,
        "open fixture TokenUser: {}",
        std::io::Error::last_os_error(),
    );
    // SAFETY: successful OpenProcessToken transfers this owned handle.
    let token = unsafe { OwnedHandle::from_raw_handle(raw_token as _) };
    let mut required = 0;
    // SAFETY: this is the documented size query on the retained query handle.
    let query = unsafe {
        GetTokenInformation(
            token.as_raw_handle() as _,
            TokenUser,
            std::ptr::null_mut(),
            0,
            &mut required,
        )
    };
    assert_eq!(query, 0, "TokenUser size query must request storage");
    assert_eq!(
        std::io::Error::last_os_error().raw_os_error(),
        Some(ERROR_INSUFFICIENT_BUFFER as i32),
        "query fixture TokenUser storage size",
    );
    assert!(required as usize >= size_of::<TOKEN_USER>());

    // usize storage provides TOKEN_USER alignment while retaining its SID bytes.
    let mut storage = vec![0usize; (required as usize).div_ceil(size_of::<usize>())];
    let mut returned = 0;
    assert_ne!(
        // SAFETY: storage is aligned and has at least required writable bytes;
        // the query handle and output length remain valid throughout this call.
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as _,
                TokenUser,
                storage.as_mut_ptr().cast(),
                required,
                &mut returned,
            )
        },
        0,
        "read fixture TokenUser: {}",
        std::io::Error::last_os_error(),
    );
    assert!(returned as usize >= size_of::<TOKEN_USER>() && returned <= required);
    // SAFETY: the successful query populated this aligned TOKEN_USER and its
    // SID inside storage, which remains owned until all grants have completed.
    let user = unsafe { &*storage.as_ptr().cast::<TOKEN_USER>() };
    assert_ne!(
        unsafe { IsValidSid(user.User.Sid) },
        0,
        "fixture TokenUser SID must be valid",
    );

    // The production grant inherits RWX + DELETE, never FILE_DELETE_CHILD.
    // Grant only the three fresh positive roots before their children exist;
    // the outside root and production capability/token policy are untouched.
    for root in roots {
        // SAFETY: the query buffer retains the validated SID for this call and
        // the caller supplies the three existing, test-owned writable roots.
        unsafe { ensure_allow_write_aces(root, &[user.User.Sid]) }
            .unwrap_or_else(|error| panic!("grant ordinary access to {}: {error}", root.display()));
    }
}
