//! Protection shared by the account mutex and each per-home credential file.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_windows_sandbox::string_from_sid_bytes;
use codex_windows_sandbox::to_wide;
use std::ffi::c_void;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::GENERIC_ALL;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetSecurityInfo;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::Authorization::SE_OBJECT_TYPE;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetSecurityDescriptorOwner;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PSECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SE_DACL_PROTECTED;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::System::Threading::GetCurrentProcess;

pub(super) const SYSTEM_SID: &str = "S-1-5-18";
pub(super) const ADMINISTRATORS_SID: &str = "S-1-5-32-544";

pub(super) struct Descriptor(pub(super) PSECURITY_DESCRIPTOR);

impl Drop for Descriptor {
    fn drop(&mut self) {
        unsafe {
            LocalFree(self.0 as HLOCAL);
        }
    }
}

pub(super) fn sid_text(sid: *mut c_void) -> Result<String> {
    ensure!(
        !sid.is_null() && unsafe { IsValidSid(sid) } != 0,
        "invalid Windows identity SID"
    );
    let length = unsafe { GetLengthSid(sid) } as usize;
    ensure!(
        (8..=68).contains(&length),
        "invalid Windows identity SID length"
    );
    string_from_sid_bytes(unsafe { std::slice::from_raw_parts(sid.cast::<u8>(), length) })
        .map_err(anyhow::Error::msg)
}

pub(super) fn current_user_sid() -> Result<String> {
    #[link(name = "advapi32")]
    unsafe extern "system" {
        fn OpenProcessToken(process: HANDLE, desired_access: u32, token: *mut HANDLE) -> i32;
    }
    let mut token = 0;
    ensure!(
        unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } != 0,
        "query provisioning process identity: {}",
        unsafe { GetLastError() }
    );
    let token = unsafe { OwnedHandle::from_raw_handle(token as *mut c_void) };
    token_user_sid(token.as_raw_handle() as HANDLE)
}

pub(super) fn token_user_sid(token: HANDLE) -> Result<String> {
    let mut needed = 0;
    unsafe {
        GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut needed);
    }
    ensure!(
        needed as usize >= std::mem::size_of::<TOKEN_USER>() && needed <= 1024,
        "invalid process identity buffer length"
    );
    let mut words = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    ensure!(
        unsafe {
            GetTokenInformation(
                token,
                TokenUser,
                words.as_mut_ptr().cast(),
                needed,
                &mut needed,
            )
        } != 0,
        "read provisioning process identity: {}",
        unsafe { GetLastError() }
    );
    let user = unsafe { &*words.as_ptr().cast::<TOKEN_USER>() };
    sid_text(user.User.Sid)
}

pub(super) fn protected_descriptor(
    real_user_sid: Option<&str>,
    inheritance: &str,
) -> Result<Descriptor> {
    let mut sddl = format!("D:P(A;{inheritance};GA;;;SY)(A;{inheritance};GA;;;BA)");
    if let Some(sid) = real_user_sid {
        // The caller passes the canonical SID returned by Windows, not an account name.
        ensure!(
            sid.starts_with("S-1-")
                && sid
                    .bytes()
                    .all(|b| b.is_ascii_digit() || b == b'-' || b == b'S'),
            "invalid credential owner SID"
        );
        if sid != SYSTEM_SID && sid != ADMINISTRATORS_SID {
            sddl.push_str(&format!("(A;{inheritance};GA;;;{sid})"));
        }
    }
    let wide = to_wide(sddl);
    let mut descriptor = std::ptr::null_mut();
    ensure!(
        unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                wide.as_ptr(),
                SDDL_REVISION_1,
                &mut descriptor,
                std::ptr::null_mut(),
            )
        } != 0,
        "create protected identity descriptor: {}",
        unsafe { GetLastError() }
    );
    Ok(Descriptor(descriptor))
}

pub(super) fn handle_descriptor(handle: HANDLE, kind: SE_OBJECT_TYPE) -> Result<Descriptor> {
    let mut descriptor = std::ptr::null_mut();
    let status = unsafe {
        GetSecurityInfo(
            handle,
            kind,
            OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        )
    };
    if status != 0 {
        return Err(std::io::Error::from_raw_os_error(status as i32))
            .context("read identity object security");
    }
    ensure!(
        !descriptor.is_null(),
        "identity object has no security descriptor"
    );
    Ok(Descriptor(descriptor))
}

pub(super) fn validate_owner(descriptor: &Descriptor, real_user_sid: Option<&str>) -> Result<()> {
    let mut owner = std::ptr::null_mut();
    let mut defaulted = 0;
    ensure!(
        unsafe { GetSecurityDescriptorOwner(descriptor.0, &mut owner, &mut defaulted) } != 0,
        "read identity object owner"
    );
    let owner = sid_text(owner)?;
    ensure!(
        owner == SYSTEM_SID
            || owner == ADMINISTRATORS_SID
            || real_user_sid == Some(owner.as_str())
            || owner == current_user_sid()?,
        "identity object is owned by an unrelated principal"
    );
    Ok(())
}

pub(super) fn validate_protection(
    descriptor: &Descriptor,
    real_user_sid: Option<&str>,
    inheritance: u8,
    mapped_full_access: u32,
) -> Result<()> {
    validate_owner(descriptor, real_user_sid)?;
    let mut control = 0;
    let mut revision = 0;
    ensure!(
        unsafe { GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision) } != 0
            && control & SE_DACL_PROTECTED != 0,
        "identity object DACL is not protected"
    );
    let mut present = 0;
    let mut defaulted = 0;
    let mut acl = std::ptr::null_mut();
    ensure!(
        unsafe { GetSecurityDescriptorDacl(descriptor.0, &mut present, &mut acl, &mut defaulted) }
            != 0
            && present != 0
            && !acl.is_null(),
        "identity object has no restricting DACL"
    );
    let mut expected = vec![SYSTEM_SID.to_string(), ADMINISTRATORS_SID.to_string()];
    if let Some(sid) = real_user_sid {
        if !expected.iter().any(|known| known == sid) {
            expected.push(sid.to_string());
        }
    }
    ensure!(
        usize::from(unsafe { (*acl).AceCount }) == expected.len(),
        "identity object has unexpected ACL entries"
    );
    let mut actual = Vec::new();
    for index in 0..unsafe { (*acl).AceCount } {
        let mut ace = std::ptr::null_mut();
        ensure!(
            unsafe { GetAce(acl, u32::from(index), &mut ace) } != 0 && !ace.is_null(),
            "read identity ACL entry"
        );
        let allowed = unsafe { &*ace.cast::<ACCESS_ALLOWED_ACE>() };
        ensure!(
            allowed.Header.AceType == 0
                && allowed.Header.AceFlags == inheritance
                && (allowed.Mask == GENERIC_ALL || allowed.Mask == mapped_full_access)
                && usize::from(allowed.Header.AceSize) >= std::mem::size_of::<ACCESS_ALLOWED_ACE>(),
            "identity object has an unexpected access grant"
        );
        let sid = std::ptr::addr_of!(allowed.SidStart) as *mut c_void;
        ensure!(
            usize::from(allowed.Header.AceSize) >= 16,
            "identity ACL entry has no complete SID header"
        );
        let sid_header = unsafe { std::slice::from_raw_parts(sid.cast::<u8>(), 8) };
        let length = 8 + 4 * usize::from(sid_header[1]);
        ensure!(
            length <= 68 && 8 + length <= usize::from(allowed.Header.AceSize),
            "identity ACL SID exceeds its entry"
        );
        actual.push(sid_text(sid)?);
    }
    actual.sort();
    expected.sort();
    ensure!(
        actual == expected,
        "identity object grants access to unrelated principals"
    );
    Ok(())
}
