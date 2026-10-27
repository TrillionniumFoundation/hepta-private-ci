//! One private local pipe instance, with its real client checked before bytes.

use super::BoundChild;
use codex_utils_path::PrivateSecurityIdentity;
use std::fs::File;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::*;
use windows_sys::Win32::System::IO::*;
use windows_sys::Win32::System::Pipes::*;
use windows_sys::Win32::System::Threading::*;

pub(super) struct PrivatePipe {
    file: File,
    pub(super) name: String,
    security: PrivateSecurityIdentity,
    aborted: AtomicBool,
}

#[derive(Debug, Eq, PartialEq)]
pub(super) enum PipeDelivery {
    Consumed,
    CancelledBeforeClient,
}

pub(super) fn native_error(operation: &str) -> io::Error {
    let error = io::Error::last_os_error();
    io::Error::new(
        error.kind(),
        format!(
            "{operation}: {error}; raw_win32_error={:?}",
            error.raw_os_error()
        ),
    )
}

impl PrivatePipe {
    pub(super) fn create(descriptor: &[u8]) -> io::Result<Self> {
        let nonce = crate::ceremony::random_hex::<16>().map_err(io::Error::other)?;
        let name = format!(r"\\.\pipe\hepta-sshsig-{nonce}");
        let wide: Vec<u16> = name.encode_utf16().chain([0]).collect();
        let mut aligned = vec![0usize; descriptor.len().div_ceil(std::mem::size_of::<usize>())];
        unsafe {
            std::ptr::copy_nonoverlapping(
                descriptor.as_ptr(),
                aligned.as_mut_ptr().cast::<u8>(),
                descriptor.len(),
            )
        };
        let attributes = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: aligned.as_mut_ptr().cast(),
            bInheritHandle: 0,
        };
        let raw = unsafe {
            CreateNamedPipeW(
                wide.as_ptr(),
                PIPE_ACCESS_OUTBOUND | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                16384,
                0,
                0,
                &attributes,
            )
        };
        if raw == INVALID_HANDLE_VALUE {
            return Err(native_error(
                "CreateNamedPipeW(FIRST_INSTANCE,LOCAL_ONLY,max=1)",
            ));
        }
        let file = unsafe { File::from_raw_handle(raw as _) };
        let security = PrivateSecurityIdentity::inspect(&file)?;
        Ok(Self {
            file,
            name,
            security,
            aborted: AtomicBool::new(false),
        })
    }

    fn verify(&self) -> io::Result<()> {
        if PrivateSecurityIdentity::inspect(&self.file)? != self.security {
            return Err(io::Error::other("private verifier pipe owner/DACL changed"));
        }
        Ok(())
    }

    pub(super) fn send(
        &self,
        child: &BoundChild,
        bytes: &[u8],
        deadline: Instant,
    ) -> io::Result<PipeDelivery> {
        if self.aborted.load(Ordering::SeqCst) {
            return Ok(PipeDelivery::CancelledBeforeClient);
        }
        let mut connected = false;
        match self.send_inner(child, bytes, deadline, &mut connected) {
            Ok(()) => Ok(PipeDelivery::Consumed),
            Err(error)
                if !connected
                    && self.aborted.load(Ordering::SeqCst)
                    && error.raw_os_error() == Some(ERROR_OPERATION_ABORTED as i32) =>
            {
                Ok(PipeDelivery::CancelledBeforeClient)
            }
            Err(error) => Err(error),
        }
    }

    fn send_inner(
        &self,
        child: &BoundChild,
        bytes: &[u8],
        deadline: Instant,
        connected: &mut bool,
    ) -> io::Result<()> {
        self.verify()?;
        let mut pending = Pending::new(&self.file)?;
        let connection =
            unsafe { ConnectNamedPipe(self.file.as_raw_handle() as _, &mut *pending.overlapped) };
        if connection == 0 {
            match unsafe { GetLastError() } {
                ERROR_PIPE_CONNECTED => {}
                ERROR_OPERATION_ABORTED => {
                    return Err(io::Error::from_raw_os_error(ERROR_OPERATION_ABORTED as i32));
                }
                ERROR_IO_PENDING => {
                    pending.active = true;
                    pending.wait(deadline)?;
                }
                _ => return Err(native_error("ConnectNamedPipe")),
            }
        }
        *connected = true;
        let mut client_pid = 0;
        if unsafe { GetNamedPipeClientProcessId(self.file.as_raw_handle() as _, &mut client_pid) }
            == 0
        {
            return Err(native_error("GetNamedPipeClientProcessId"));
        }
        if client_pid != child.pid
            || unsafe { WaitForSingleObject(child.handle.as_raw_handle() as _, 0) } != WAIT_TIMEOUT
        {
            return Err(io::Error::other(
                "private verifier pipe client is not the retained live child",
            ));
        }
        self.verify()?;
        let mut written = 0;
        let mut pending = Pending::new(&self.file)?;
        let write = unsafe {
            WriteFile(
                self.file.as_raw_handle() as _,
                bytes.as_ptr(),
                bytes.len() as u32,
                &mut written,
                &mut *pending.overlapped,
            )
        };
        if write == 0 {
            if unsafe { GetLastError() } != ERROR_IO_PENDING {
                return Err(native_error("WriteFile(original verifier bytes)"));
            }
            pending.active = true;
            written = pending.wait(deadline)?;
        }
        if written as usize != bytes.len() {
            return Err(io::Error::other("partial native verifier pipe write"));
        }
        // The parent retains this same File and disconnects on child exit/kill.
        // Flush waits for the real client to consume the bytes; only then does
        // disconnect deliver EOF. Closing early can discard unread pipe data.
        if unsafe { FlushFileBuffers(self.file.as_raw_handle() as _) } == 0 {
            return Err(native_error("FlushFileBuffers(verifier pipe)"));
        }
        self.verify()?;
        let disconnect_error =
            if unsafe { DisconnectNamedPipe(self.file.as_raw_handle() as _) } == 0 {
                let code = unsafe { GetLastError() };
                // After exact write and successful flush, this known client may
                // already have closed. No unread bytes are being discarded here.
                if code != ERROR_PIPE_NOT_CONNECTED {
                    return Err(native_error("DisconnectNamedPipe(deliver EOF)"));
                }
                Some(code)
            } else {
                None
            };
        #[cfg(test)]
        eprintln!(
            "HEPTA_WIN_SSHSIG_PIPE client_pid={client_pid} bytes={} private_dacl_sha256={} disconnect_error={disconnect_error:?}",
            bytes.len(),
            crate::durable::sha256(self.security.descriptor_bytes())
        );
        #[cfg(not(test))]
        let _ = disconnect_error;
        Ok(())
    }

    pub(super) fn abort(&self) {
        self.aborted.store(true, Ordering::SeqCst);
        // Same HANDLE as each worker's outstanding overlapped operation. Workers
        // retain their buffers until cancellation completion before joining.
        unsafe {
            CancelIoEx(self.file.as_raw_handle() as _, std::ptr::null());
            DisconnectNamedPipe(self.file.as_raw_handle() as _);
        }
    }
}

struct Pending<'a> {
    file: &'a File,
    _event: OwnedHandle,
    overlapped: Box<OVERLAPPED>,
    active: bool,
}

impl<'a> Pending<'a> {
    fn new(file: &'a File) -> io::Result<Self> {
        let raw = unsafe { CreateEventW(std::ptr::null(), 1, 0, std::ptr::null()) };
        if raw == 0 {
            return Err(native_error("CreateEventW(verifier IO)"));
        }
        let event = unsafe { OwnedHandle::from_raw_handle(raw as _) };
        let mut overlapped: Box<OVERLAPPED> = Box::new(unsafe { std::mem::zeroed() });
        overlapped.hEvent = raw;
        Ok(Self {
            file,
            _event: event,
            overlapped,
            active: false,
        })
    }

    fn wait(&mut self, deadline: Instant) -> io::Result<u32> {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let millis = u32::try_from(remaining.as_millis())
            .unwrap_or(u32::MAX - 1)
            .max(1);
        match unsafe { WaitForSingleObject(self.overlapped.hEvent, millis) } {
            WAIT_OBJECT_0 => {}
            WAIT_TIMEOUT => {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "native verifier pipe IO deadline",
                ));
            }
            _ => return Err(native_error("WaitForSingleObject(verifier IO)")),
        }
        let mut transferred = 0;
        let completed = unsafe {
            GetOverlappedResult(
                self.file.as_raw_handle() as _,
                &*self.overlapped,
                &mut transferred,
                0,
            )
        };
        if completed == 0 {
            let code = unsafe { GetLastError() };
            if code != ERROR_IO_INCOMPLETE {
                self.active = false;
            }
            if code == ERROR_OPERATION_ABORTED {
                return Err(io::Error::from_raw_os_error(code as i32));
            }
            return Err(native_error("GetOverlappedResult(verifier IO)"));
        }
        self.active = false;
        Ok(transferred)
    }
}

impl Drop for Pending<'_> {
    fn drop(&mut self) {
        if self.active {
            unsafe {
                CancelIoEx(self.file.as_raw_handle() as _, &*self.overlapped);
                let mut transferred = 0;
                GetOverlappedResult(
                    self.file.as_raw_handle() as _,
                    &*self.overlapped,
                    &mut transferred,
                    1,
                );
            }
        }
    }
}
