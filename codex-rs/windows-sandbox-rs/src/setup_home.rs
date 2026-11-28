//! One physical-home boundary shared by full setup and its readiness reader.
//!
//! The security and no-reparse implementations below are the same source files
//! used by machine credential provisioning. Machine identity still uses its
//! original SYSTEM/Administrators-only lock; this home lock also admits the
//! actual caller SID so a non-elevated parent can validate a completed helper.
#[path = "bin/setup_main/win/machine_identity_mutex.rs"]
mod machine_identity_mutex;
#[allow(dead_code)] // The shared source also supplies private directory creation to the helper.
#[path = "bin/setup_main/win/no_reparse_dir.rs"]
mod no_reparse_dir;
#[path = "bin/setup_main/win/private_identity_security.rs"]
mod private_identity_security;

use crate::sandbox_dir;
use anyhow::Result;
use anyhow::ensure;
use machine_identity_mutex::ProvisionGuard;
use no_reparse_dir::retain_no_reparse;
use private_identity_security::current_user_sid;
use std::ffi::c_void;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows_sys::Win32::Storage::FileSystem::FileIdInfo;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandleEx;

/// Retains the exact directory and serializes its setup state, including reads.
#[doc(hidden)]
pub struct HomeSetupGuard {
    _transaction: ProvisionGuard,
    _directory: OwnedHandle,
}

fn retained_home_key(codex_home: &Path) -> Result<(OwnedHandle, String)> {
    let directory = retain_no_reparse(&sandbox_dir(codex_home))?;
    let mut info: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    let read = unsafe {
        GetFileInformationByHandleEx(
            directory.as_raw_handle() as HANDLE,
            FileIdInfo,
            &mut info as *mut FILE_ID_INFO as *mut c_void,
            size_of::<FILE_ID_INFO>() as u32,
        )
    };
    ensure!(read != 0, "read setup home identity: {}", unsafe {
        GetLastError()
    });
    let volume = info.VolumeSerialNumber;
    let identity = u128::from_le_bytes(info.FileId.Identifier);
    ensure!(
        identity != 0,
        "setup home has no supported stable file identity"
    );
    // Keep the original physical-home name. An old incompatible descriptor must
    // fail closed, rather than permit two different lock domains for one home.
    Ok((
        directory,
        format!("HomeSetup.v1.{volume:016x}.{identity:032x}"),
    ))
}

impl HomeSetupGuard {
    /// The original administrator-only transaction, retained for its original controls.
    pub fn acquire(codex_home: &Path) -> Result<Self> {
        let (directory, key) = retained_home_key(codex_home)?;
        let transaction = ProvisionGuard::acquire(&key)?;
        Ok(Self {
            _transaction: transaction,
            _directory: directory,
        })
    }

    /// Full setup uses the canonical SID resolved from its actual caller.
    pub fn acquire_for_user(codex_home: &Path, real_user_sid: &str) -> Result<Self> {
        let (directory, key) = retained_home_key(codex_home)?;
        let transaction = ProvisionGuard::acquire_for_user(&key, real_user_sid)?;
        Ok(Self {
            _transaction: transaction,
            _directory: directory,
        })
    }

    /// A parent reads current readiness under the same lock, after its child exits.
    pub fn acquire_for_current_user(codex_home: &Path) -> Result<Self> {
        Self::acquire_for_user(codex_home, &current_user_sid()?)
    }
}

#[cfg(test)]
#[path = "setup_home_tests.rs"]
mod tests;

/// Bind full setup to the real process token, including in an environment-cleared
/// process host. USERNAME is caller-controlled text and cannot select an ACL owner.
pub(crate) fn current_setup_account() -> Result<String> {
    use std::ffi::c_void;
    use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::Foundation::HLOCAL;
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Authorization::ConvertStringSidToSidW;
    use windows_sys::Win32::Security::LookupAccountSidW;
    use windows_sys::Win32::Security::SID_NAME_USE;

    struct LocalSid(*mut c_void);
    impl Drop for LocalSid {
        fn drop(&mut self) {
            unsafe {
                LocalFree(self.0 as HLOCAL);
            }
        }
    }

    let expected = current_user_sid()?;
    let mut raw = std::ptr::null_mut();
    ensure!(
        unsafe { ConvertStringSidToSidW(crate::to_wide(&expected).as_ptr(), &mut raw) } != 0,
        "convert actual setup process identity: {}",
        unsafe { GetLastError() }
    );
    let sid = LocalSid(raw);
    let mut name_len = 0;
    let mut domain_len = 0;
    let mut kind: SID_NAME_USE = 0;
    let first = unsafe {
        LookupAccountSidW(
            std::ptr::null(),
            sid.0,
            std::ptr::null_mut(),
            &mut name_len,
            std::ptr::null_mut(),
            &mut domain_len,
            &mut kind,
        )
    };
    ensure!(
        first == 0 && unsafe { GetLastError() } == ERROR_INSUFFICIENT_BUFFER,
        "query actual setup account extent"
    );
    ensure!(
        (1..=32768).contains(&name_len) && (1..=32768).contains(&domain_len),
        "actual setup account name is unbounded"
    );
    let mut name = vec![0u16; name_len as usize];
    let mut domain = vec![0u16; domain_len as usize];
    ensure!(
        unsafe {
            LookupAccountSidW(
                std::ptr::null(),
                sid.0,
                name.as_mut_ptr(),
                &mut name_len,
                domain.as_mut_ptr(),
                &mut domain_len,
                &mut kind,
            )
        } != 0,
        "resolve actual setup process account: {}",
        unsafe { GetLastError() }
    );
    ensure!(
        name_len as usize <= name.len() && domain_len as usize <= domain.len(),
        "actual setup account exceeds captured extent"
    );
    let name = String::from_utf16(&name[..name_len as usize])?;
    let domain = String::from_utf16(&domain[..domain_len as usize])?;
    let name = name.trim_end_matches('\0');
    let domain = domain.trim_end_matches('\0');
    ensure!(
        !name.is_empty()
            && !domain.is_empty()
            && !name.contains('\0')
            && !domain.contains('\0')
            && !name.contains('\\')
            && !domain.contains('\\'),
        "actual setup account is not one complete qualified identity"
    );
    let account = format!("{domain}\\{name}");
    let resolved = crate::string_from_sid_bytes(&crate::winutil::resolve_sid(&account)?)
        .map_err(anyhow::Error::msg)?;
    ensure!(
        resolved == expected,
        "actual setup account changed during resolution"
    );
    Ok(account)
}
