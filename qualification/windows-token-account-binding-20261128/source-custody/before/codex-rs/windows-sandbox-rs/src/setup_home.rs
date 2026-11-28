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
