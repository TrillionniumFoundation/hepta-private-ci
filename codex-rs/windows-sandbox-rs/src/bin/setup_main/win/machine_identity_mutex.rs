use super::private_identity_security::handle_descriptor;
use super::private_identity_security::protected_descriptor;
use super::private_identity_security::validate_protection;
use anyhow::Result;
use anyhow::ensure;
use codex_windows_sandbox::to_wide;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_ABANDONED;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Security::Authorization::SE_KERNEL_OBJECT;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::System::Threading::INFINITE;
use windows_sys::Win32::System::Threading::MUTEX_ALL_ACCESS;
use windows_sys::Win32::System::Threading::ReleaseMutex;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

pub(super) struct ProvisionGuard {
    handle: HANDLE,
    acquired: bool,
}

impl ProvisionGuard {
    pub(super) fn acquire(identity_key: &str) -> Result<Self> {
        Self::acquire_with_owner(identity_key, None)
    }

    pub(super) fn acquire_for_user(identity_key: &str, real_user_sid: &str) -> Result<Self> {
        Self::acquire_with_owner(identity_key, Some(real_user_sid))
    }

    fn acquire_with_owner(identity_key: &str, real_user_sid: Option<&str>) -> Result<Self> {
        let descriptor = protected_descriptor(real_user_sid, "")?;
        let attributes = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: descriptor.0,
            bInheritHandle: 0,
        };
        let name = to_wide(format!("Global\\CodexSandbox.Identity.v1.{identity_key}"));
        let handle = unsafe { CreateMutexW(&attributes, 0, name.as_ptr()) };
        ensure!(handle != 0, "open machine identity mutex: {}", unsafe {
            GetLastError()
        });
        let mut guard = Self {
            handle,
            acquired: false,
        };
        // CreateMutex may open an existing object. Validate it before waiting.
        let actual = handle_descriptor(handle, SE_KERNEL_OBJECT)?;
        validate_protection(&actual, real_user_sid, 0, MUTEX_ALL_ACCESS)?;
        let status = unsafe { WaitForSingleObject(handle, INFINITE) };
        ensure!(
            status == WAIT_OBJECT_0 || status == WAIT_ABANDONED,
            "acquire machine identity mutex: {}",
            unsafe { GetLastError() }
        );
        guard.acquired = true;
        Ok(guard)
    }
}

impl Drop for ProvisionGuard {
    fn drop(&mut self) {
        unsafe {
            if self.acquired {
                ReleaseMutex(self.handle);
            }
            CloseHandle(self.handle);
        }
    }
}
