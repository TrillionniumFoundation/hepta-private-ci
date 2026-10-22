//! Supplemental fixture only: use an already enabled, owner-eligible token SID.
//! Never enable privileges, alter token groups, or repair an existing object.

use std::fs::OpenOptions;
use std::mem::size_of;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::ptr;

use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::Authorization::SetSecurityInfo;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_INFORMATION_CLASS;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_OWNER;
use windows_sys::Win32::System::SystemServices::SE_GROUP_ENABLED;
use windows_sys::Win32::System::SystemServices::SE_GROUP_OWNER;
use windows_sys::Win32::System::SystemServices::SE_GROUP_USE_FOR_DENY_ONLY;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;

use super::owner;

struct Token(HANDLE);
impl Drop for Token {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}

struct Information {
    words: Vec<usize>,
    length: usize,
}
impl Information {
    fn query(token: &Token, class: TOKEN_INFORMATION_CLASS) -> Self {
        let mut length = 0;
        let result =
            unsafe { GetTokenInformation(token.0, class, ptr::null_mut(), 0, &mut length) };
        let error = unsafe { GetLastError() };
        assert_eq!(result, 0);
        assert_eq!(
            error, ERROR_INSUFFICIENT_BUFFER,
            "token query setup must succeed"
        );
        assert!(
            length > 0 && length <= 1_048_576,
            "bounded token information"
        );
        let capacity = length as usize;
        let mut words = vec![0_usize; capacity.div_ceil(size_of::<usize>())];
        assert_ne!(
            unsafe {
                GetTokenInformation(
                    token.0,
                    class,
                    words.as_mut_ptr().cast(),
                    length,
                    &mut length,
                )
            },
            0,
            "token information query must succeed"
        );
        assert!(length as usize <= capacity);
        Self {
            words,
            length: length as usize,
        }
    }

    fn as_ptr<T>(&self) -> *const T {
        assert!(self.length >= size_of::<T>());
        self.words.as_ptr().cast()
    }

    fn sid(&self, sid: *mut std::ffi::c_void) -> Vec<u32> {
        let start = self.words.as_ptr() as usize;
        let offset = (sid as usize)
            .checked_sub(start)
            .expect("SID lies inside query buffer");
        assert!(offset.checked_add(8).is_some_and(|end| end <= self.length));
        let count = unsafe { *sid.cast::<u8>().add(1) } as usize;
        assert!(count <= 15, "bounded Windows SID");
        let length = 8 + 4 * count;
        assert!(
            offset
                .checked_add(length)
                .is_some_and(|end| end <= self.length)
        );
        assert_ne!(unsafe { IsValidSid(sid) }, 0);
        let mut words = vec![0_u32; length.div_ceil(size_of::<u32>())];
        unsafe {
            ptr::copy_nonoverlapping(sid.cast::<u8>(), words.as_mut_ptr().cast::<u8>(), length)
        };
        words
    }
}

fn eligible(attributes: u32, same_user: bool) -> bool {
    attributes & SE_GROUP_OWNER as u32 != 0
        && attributes & SE_GROUP_ENABLED as u32 != 0
        && attributes & SE_GROUP_USE_FOR_DENY_ONLY as u32 == 0
        && !same_user
}

fn observed_owner_sid() -> (Vec<u32>, Vec<u32>) {
    codex_utils_path::require_non_impersonating_thread().expect("fixture must not impersonate");
    let mut raw = 0;
    assert_ne!(
        unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut raw) },
        0
    );
    let token = Token(raw);
    let user_info = Information::query(&token, TokenUser);
    let mut user = user_info.sid(unsafe { (*user_info.as_ptr::<TOKEN_USER>()).User.Sid });
    let group_info = Information::query(&token, TokenGroups);
    let groups = group_info.as_ptr::<TOKEN_GROUPS>();
    let count = unsafe { (*groups).GroupCount } as usize;
    assert!(count <= 4096, "bounded fixture group census");
    let first = unsafe { ptr::addr_of!((*groups).Groups).cast::<SID_AND_ATTRIBUTES>() };
    let offset = (first as usize) - (group_info.words.as_ptr() as usize);
    assert!(
        offset
            .checked_add(count.checked_mul(size_of::<SID_AND_ATTRIBUTES>()).unwrap())
            .is_some_and(|end| end <= group_info.length)
    );
    for index in 0..count {
        let group = unsafe { ptr::read(first.add(index)) };
        let mut sid = group_info.sid(group.Sid);
        let same_user = unsafe { EqualSid(user.as_mut_ptr().cast(), sid.as_mut_ptr().cast()) } != 0;
        if eligible(group.Attributes, same_user) {
            eprintln!(
                "owner-fixture observed SID words={sid:?} attributes={:#x}",
                group.Attributes
            );
            return (user, sid);
        }
    }
    panic!(
        "SETUP_UNAVAILABLE: no enabled, non-deny-only SE_GROUP_OWNER SID distinct from TokenUser; never a passing rejection"
    );
}

pub(crate) fn change_owner_to_enabled_group(path: &Path) {
    let (mut user, mut selected) = observed_owner_sid();
    let dacl_before = super::dacl_bytes(path);
    let file = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_OWNER)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)
        .expect("new private fixture must already grant WRITE_OWNER; no privilege enabling");
    let mut original = owner(&file);
    assert_ne!(
        unsafe { EqualSid(original.as_mut_ptr().cast(), user.as_mut_ptr().cast()) },
        0,
        "positive fixture owner must really be process TokenUser"
    );
    let status = unsafe {
        SetSecurityInfo(
            file.as_raw_handle() as HANDLE,
            1,
            OWNER_SECURITY_INFORMATION,
            selected.as_mut_ptr().cast(),
            ptr::null_mut(),
            ptr::null_mut(),
            ptr::null_mut(),
        )
    };
    assert_eq!(
        status, ERROR_SUCCESS,
        "SETUP_FAILED: actual owner assignment must succeed, denial is not checker proof"
    );
    let mut actual = owner(&file);
    assert_ne!(
        unsafe { EqualSid(actual.as_mut_ptr().cast(), selected.as_mut_ptr().cast()) },
        0
    );
    assert_eq!(
        unsafe { EqualSid(actual.as_mut_ptr().cast(), user.as_mut_ptr().cast()) },
        0
    );
    assert_eq!(
        super::dacl_bytes(path),
        dacl_before,
        "owner-only mutation must preserve DACL"
    );
    codex_utils_path::require_non_impersonating_thread().expect("fixture identity unchanged");
}

#[cfg(test)]
#[path = "windows_custody_owner_fixture_tests.rs"]
mod tests;
