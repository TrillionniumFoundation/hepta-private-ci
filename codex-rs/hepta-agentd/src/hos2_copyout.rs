//! Explicit native qualification at the original synchronous FileTransport.
//!
//! This module changes only the copyout address for one exact, already prepared
//! Install frame. It never supplies a result, issues a grant, retries an ioctl,
//! or settles an outbox. An actual EFAULT still requires the original owner's
//! history query to determine whether the native effect happened.

use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fs::File;
use std::os::fd::AsRawFd;
use std::sync::Mutex;

const INSTALL_FRAME_BYTES: usize = 96;
const OUTPUT_CAPACITY: usize = 128;

pub(crate) type AfterCopyoutFault =
    Box<dyn FnOnce(&NativeCopyoutDiagnostic) -> Result<(), String> + Send>;

/// Observed only at the actual device syscall boundary. This is diagnostic
/// data, not proof of an applied effect or permission to create a new D.
#[derive(Clone, Debug, Serialize)]
pub(crate) struct NativeCopyoutDiagnostic {
    pub(crate) install_ioctl_count: u64,
    pub(crate) selected_ioctl_count: u64,
    pub(crate) efault_count: u64,
    pub(crate) request_sha256: [u8; 32],
    pub(crate) request_bytes: usize,
    pub(crate) response_capacity: usize,
    pub(crate) syscall_return: i32,
    pub(crate) errno: Option<i32>,
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct NativeCopyoutSnapshot {
    pub(crate) install_ioctl_count: u64,
    pub(crate) selected_ioctl_count: u64,
    pub(crate) efault_count: u64,
    pub(crate) armed: bool,
    pub(crate) last: Option<NativeCopyoutDiagnostic>,
}

#[derive(Default)]
pub(super) struct NativeCopyoutProbe {
    state: Mutex<State>,
}

#[derive(Default)]
struct State {
    install_ioctl_count: u64,
    selected_ioctl_count: u64,
    efault_count: u64,
    armed: Option<Armed>,
    last: Option<NativeCopyoutDiagnostic>,
}

struct Armed {
    frame: [u8; INSTALL_FRAME_BYTES],
    output: InaccessibleOutput,
    after_fault: Option<AfterCopyoutFault>,
}

/// One owned mapping, never dereferenced by userspace and never transferred to
/// the kernel beyond a synchronous ioctl. The numeric address owns no Rust
/// reference and stays valid until this object's drop unmaps it.
struct InaccessibleOutput {
    address: usize,
    length: usize,
}

impl InaccessibleOutput {
    fn new() -> Result<Self, String> {
        // A whole page is sufficient for the unchanged original response
        // capacity. mmap supplies an aligned inaccessible region on both the
        // Linux host and the reviewed Asterinas native profile.
        let length = 4096;
        // SAFETY: no supplied address, backing file or alias is involved. The
        // mapping is PROT_NONE from creation and is never dereferenced here.
        let address = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                length,
                libc::PROT_NONE,
                libc::MAP_PRIVATE | libc::MAP_ANONYMOUS,
                -1,
                0,
            )
        };
        if address == libc::MAP_FAILED {
            return Err(format!(
                "preparing actual inaccessible HOS2 copyout: {}",
                std::io::Error::last_os_error()
            ));
        }
        Ok(Self {
            address: address as usize,
            length,
        })
    }
}

impl Drop for InaccessibleOutput {
    fn drop(&mut self) {
        // SAFETY: this is the exact live mapping allocated by new, with no
        // aliases retained or userspace accesses. It is unmapped exactly once.
        unsafe { libc::munmap(self.address as *mut libc::c_void, self.length) };
    }
}

impl NativeCopyoutProbe {
    pub(super) fn arm(
        &self,
        frame: &[u8],
        after_fault: Option<AfterCopyoutFault>,
    ) -> Result<(), String> {
        let frame: [u8; INSTALL_FRAME_BYTES] = frame
            .try_into()
            .map_err(|_| "native copyout qualification needs the complete Install frame")?;
        if &frame[..4] != b"HOS2" || u16::from_le_bytes(frame[8..10].try_into().unwrap()) != 3 {
            return Err("native copyout qualification accepts only original Install bytes".into());
        }
        // Allocate before arming and before the original FinalUse/effect-entry
        // barrier. A preparation failure leaves the original dispatch untouched.
        let output = InaccessibleOutput::new()?;
        let mut state = self
            .state
            .lock()
            .map_err(|_| "native copyout observation lock poisoned")?;
        if state.armed.is_some() {
            return Err("a native copyout qualification is already armed".into());
        }
        state.armed = Some(Armed {
            frame,
            output,
            after_fault,
        });
        Ok(())
    }

    pub(super) fn snapshot(&self) -> Result<NativeCopyoutSnapshot, String> {
        let state = self
            .state
            .lock()
            .map_err(|_| "native copyout observation lock poisoned")?;
        Ok(NativeCopyoutSnapshot {
            install_ioctl_count: state.install_ioctl_count,
            selected_ioctl_count: state.selected_ioctl_count,
            efault_count: state.efault_count,
            armed: state.armed.is_some(),
            last: state.last.clone(),
        })
    }

    pub(super) fn exchange(
        &self,
        file: &File,
        input: &[u8],
        output: &mut [u8],
    ) -> Result<(), String> {
        let install = input.get(8..10) == Some(&3_u16.to_le_bytes());
        let mut selected = {
            let mut state = self
                .state
                .lock()
                .map_err(|_| "native copyout observation lock poisoned")?;
            let matches = state
                .armed
                .as_ref()
                .is_some_and(|armed| armed.frame.as_slice() == input);
            if matches && output.len() != OUTPUT_CAPACITY {
                return Err("original HOS2 output capacity changed before qualification".into());
            }
            // These bounded counters describe calls through this retained
            // original descriptor. They never allocate a delivery sequence.
            if install {
                state.install_ioctl_count = state
                    .install_ioctl_count
                    .checked_add(1)
                    .ok_or("native Install observation count exhausted")?;
            }
            if matches {
                state.selected_ioctl_count = state
                    .selected_ioctl_count
                    .checked_add(1)
                    .ok_or("native copyout observation count exhausted")?;
                state.armed.take()
            } else {
                None
            }
        };
        let response_address = selected
            .as_ref()
            .map_or(output.as_mut_ptr() as u64, |armed| {
                armed.output.address as u64
            });
        let mut descriptor = [0_u8; 32];
        descriptor[..8].copy_from_slice(&(input.as_ptr() as u64).to_le_bytes());
        descriptor[8..16].copy_from_slice(&response_address.to_le_bytes());
        descriptor[16..20].copy_from_slice(&(input.len() as u32).to_le_bytes());
        descriptor[20..24].copy_from_slice(&(output.len() as u32).to_le_bytes());
        // SAFETY: input, the original output buffer, optional owned PROT_NONE
        // mapping and descriptor stay live throughout this one synchronous
        // ioctl. The kernel copies bytes and retains no userspace reference.
        let result =
            unsafe { libc::ioctl(file.as_raw_fd(), super::HOS2_IOCTL, descriptor.as_mut_ptr()) };
        // Capture errno immediately, before a mutex, allocation, unmap,
        // formatter or callback can perform another syscall and change it.
        let syscall_error = (result != 0).then(std::io::Error::last_os_error);
        if let Some(mut armed) = selected.take() {
            let errno = syscall_error
                .as_ref()
                .and_then(std::io::Error::raw_os_error);
            let actual_fault = result == -1 && errno == Some(libc::EFAULT);
            let observation = {
                let mut state = self
                    .state
                    .lock()
                    .map_err(|_| "native copyout observation lock poisoned after ioctl")?;
                if actual_fault {
                    state.efault_count = state
                        .efault_count
                        .checked_add(1)
                        .ok_or("native EFAULT observation count exhausted")?;
                }
                let observation = NativeCopyoutDiagnostic {
                    install_ioctl_count: state.install_ioctl_count,
                    selected_ioctl_count: state.selected_ioctl_count,
                    efault_count: state.efault_count,
                    request_sha256: Sha256::digest(input).into(),
                    request_bytes: input.len(),
                    response_capacity: output.len(),
                    syscall_return: result,
                    errno,
                };
                state.last = Some(observation.clone());
                observation
            };
            let callback = armed.after_fault.take();
            drop(armed);
            if actual_fault {
                // The caller may report this actual boundary to its existing
                // authenticated Root. No FinalUse frontier is reentered here:
                // its original state lock and HOS2 dispatch guard remain held.
                if let Some(callback) = callback {
                    callback(&observation).map_err(|reason| {
                        format!("actual HOS2 EFAULT; Root fault observation failed: {reason}")
                    })?;
                }
            } else if result == 0 {
                return Err("HOS2 unexpectedly accepted an inaccessible copyout mapping".into());
            }
        }
        if let Some(error) = syscall_error {
            // EINTR and EFAULT are never retried. The original outbox must
            // settle this D through its retained history owner.
            return Err(format!(
                "HOS2 ioctl did not return a complete result: {error}"
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "hos2_copyout_tests.rs"]
mod tests;
