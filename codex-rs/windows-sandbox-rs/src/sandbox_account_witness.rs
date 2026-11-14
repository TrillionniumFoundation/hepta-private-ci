use crate::sandbox_account::AccountMutex;
use crate::sandbox_account::SETUP_MUTATION_MUTEX_NAME;
use anyhow::Context;
use anyhow::Result;
use serde::Deserialize;
use serde::Serialize;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::Foundation::FILETIME;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::Security::Cryptography::BCRYPT_USE_SYSTEM_PREFERRED_RNG;
use windows_sys::Win32::Security::Cryptography::BCryptGenRandom;
use windows_sys::Win32::System::Threading::CreateEventW;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetCurrentProcessId;
use windows_sys::Win32::System::Threading::GetProcessTimes;
use windows_sys::Win32::System::Threading::OpenEventW;
use windows_sys::Win32::System::Threading::OpenProcess;
use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;
use windows_sys::Win32::System::Threading::SetEvent;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

/// Binds an elevated setup request to one live account lifecycle lease.
///
/// The event is an availability/lifetime witness, not authority to perform
/// setup: the helper retains all existing caller, path and elevation checks.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct SandboxAccountLeaseWitness {
    parent_process_id: u32,
    parent_creation_time: u64,
    closed_event: String,
}

pub(crate) struct LeaseClosedEvent {
    event: OwnedHandle,
    witness: SandboxAccountLeaseWitness,
}

impl LeaseClosedEvent {
    pub(crate) fn create() -> Result<Self> {
        let mut random = [0u8; 16];
        let status = unsafe {
            BCryptGenRandom(
                std::ptr::null_mut(),
                random.as_mut_ptr(),
                random.len() as u32,
                BCRYPT_USE_SYSTEM_PREFERRED_RNG,
            )
        };
        anyhow::ensure!(status >= 0, "create account lease nonce: {status:#x}");
        let id = u128::from_le_bytes(random);
        let closed_event = format!("Global\\CodexSandboxAccountLease-{id:032x}");
        let name = crate::winutil::to_wide(&closed_event);
        let handle = unsafe {
            CreateEventW(
                std::ptr::null(),
                /*bmanualreset*/ 1,
                /*binitialstate*/ 0,
                name.as_ptr(),
            )
        };
        let error = unsafe { GetLastError() };
        anyhow::ensure!(
            handle != 0,
            "create account lease event: {}",
            std::io::Error::from_raw_os_error(error as i32)
        );
        // SAFETY: CreateEventW returned a new owned handle.
        let event = unsafe { OwnedHandle::from_raw_handle(handle as _) };
        anyhow::ensure!(
            error != ERROR_ALREADY_EXISTS,
            "account lease event already exists"
        );
        let witness = SandboxAccountLeaseWitness {
            parent_process_id: unsafe { GetCurrentProcessId() },
            parent_creation_time: process_creation_time(unsafe { GetCurrentProcess() })?,
            closed_event,
        };
        Ok(Self { event, witness })
    }

    pub(crate) fn witness(&self) -> SandboxAccountLeaseWitness {
        self.witness.clone()
    }
}

impl Drop for LeaseClosedEvent {
    fn drop(&mut self) {
        // Signal before the lifecycle mutex is released. If this cannot be
        // recorded, process death invalidates the other half of every witness.
        if unsafe { SetEvent(self.event.as_raw_handle() as HANDLE) } == 0 {
            crate::logging::debug_log("failed to close sandbox account lease event", None);
            std::process::abort();
        }
    }
}

/// Holds setup mutations until marker/secret publication has fully completed.
///
/// Acquisition drains any older helper before checking its request witness.
/// A newly acquired lifecycle lease cannot overtake an orphaned helper that
/// already entered setup; a late helper cannot start after its lease closes.
pub struct SandboxAccountSetupGuard {
    _mutation: AccountMutex,
    _parent: OwnedHandle,
    _closed_event: OwnedHandle,
}

impl SandboxAccountSetupGuard {
    pub fn acquire(witness: &SandboxAccountLeaseWitness) -> Result<Self> {
        let mutation = AccountMutex::acquire(SETUP_MUTATION_MUTEX_NAME)
            .context("acquire sandbox setup mutation lease")?;
        let name = crate::winutil::to_wide(&witness.closed_event);
        let event = unsafe {
            OpenEventW(
                PROCESS_SYNCHRONIZE,
                /*binherithandle*/ 0,
                name.as_ptr(),
            )
        };
        anyhow::ensure!(
            event != 0,
            "open setup account lease event: {}",
            std::io::Error::last_os_error()
        );
        // SAFETY: OpenEventW returned a new owned handle.
        let closed_event = unsafe { OwnedHandle::from_raw_handle(event as _) };
        let parent = unsafe {
            OpenProcess(
                PROCESS_SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                /*binherithandle*/ 0,
                witness.parent_process_id,
            )
        };
        anyhow::ensure!(
            parent != 0,
            "open setup account lease parent: {}",
            std::io::Error::last_os_error()
        );
        // SAFETY: OpenProcess returned a new owned handle.
        let parent = unsafe { OwnedHandle::from_raw_handle(parent as _) };
        anyhow::ensure!(
            process_creation_time(parent.as_raw_handle() as HANDLE)?
                == witness.parent_creation_time,
            "setup account lease parent identity changed"
        );
        anyhow::ensure!(
            unsafe {
                WaitForSingleObject(parent.as_raw_handle() as HANDLE, /*dwmilliseconds*/ 0)
            } == WAIT_TIMEOUT,
            "setup account lease parent is no longer running"
        );
        anyhow::ensure!(
            unsafe {
                WaitForSingleObject(
                    closed_event.as_raw_handle() as HANDLE,
                    /*dwmilliseconds*/ 0,
                )
            } == WAIT_TIMEOUT,
            "setup account lease is closed"
        );
        Ok(Self {
            _mutation: mutation,
            _parent: parent,
            _closed_event: closed_event,
        })
    }
}

fn process_creation_time(process: HANDLE) -> Result<u64> {
    let mut created: FILETIME = unsafe { std::mem::zeroed() };
    let mut exited = created;
    let mut kernel = created;
    let mut user = created;
    anyhow::ensure!(
        unsafe { GetProcessTimes(process, &mut created, &mut exited, &mut kernel, &mut user) } != 0,
        "query account lease parent creation time: {}",
        std::io::Error::last_os_error()
    );
    Ok((u64::from(created.dwHighDateTime) << 32) | u64::from(created.dwLowDateTime))
}

#[cfg(test)]
#[path = "sandbox_account_witness_tests.rs"]
mod tests;
