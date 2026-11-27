use super::machine_identity_mutex::ProvisionGuard;
use super::no_reparse_dir::retain_no_reparse;
use anyhow::Result;
use anyhow::ensure;
use codex_windows_sandbox::sandbox_dir;
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

/// Holds one physical home's setup transaction through marker publication.
///
/// This uses a separate key domain from machine credential provisioning. Paths
/// with different spelling for the same live directory share the same lock;
/// different homes do not wait for one another's full provisioning transaction.
pub(super) struct HomeSetupGuard {
    _transaction: ProvisionGuard,
    _directory: OwnedHandle,
}

impl HomeSetupGuard {
    pub(super) fn acquire(codex_home: &Path) -> Result<Self> {
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
        let key = format!("HomeSetup.v1.{volume:016x}.{identity:032x}");
        // The existing protected mutex implementation checks the owner and
        // exact DACL even when another process created the named object.
        let transaction = ProvisionGuard::acquire(&key)?;
        Ok(Self {
            _transaction: transaction,
            _directory: directory,
        })
    }
}

#[cfg(test)]
#[path = "home_setup_transaction_tests.rs"]
mod tests;
