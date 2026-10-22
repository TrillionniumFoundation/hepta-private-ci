//! Bind owner-local socket authority to the kernel's connected process identity.

use std::io;
use std::io::ErrorKind;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::io::RawSocket;
use std::ptr;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_FAILED;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::Networking::WinSock::SIO_AF_UNIX_GETPEERPID;
use windows_sys::Win32::Networking::WinSock::SOCKET_ERROR;
use windows_sys::Win32::Networking::WinSock::WSAGetLastError;
use windows_sys::Win32::Networking::WinSock::WSAIoctl;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::EqualSid;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::SECURITY_MAX_SID_SIZE;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::OpenProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

pub(super) fn ensure_current_user_peer(socket: RawSocket) -> io::Result<()> {
    let peer_pid = connected_process_id(socket)?;
    // Keep the process object open while resolving its token and rechecking
    // the socket. Never treat an unqueryable or exited process as the owner.
    let process = unsafe {
        OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SYNCHRONIZE,
            /*binherithandle*/ 0,
            peer_pid,
        )
    };
    if process.is_null() {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: OpenProcess returned an owned, non-null handle.
    let process = unsafe { OwnedHandle::from_raw_handle(process) };
    ensure_running(&process)?;
    let peer = UserSid::from_process(process.as_raw_handle())?;
    // GetCurrentProcess returns a pseudo-handle, which must not be closed.
    let owner = UserSid::from_process(unsafe { GetCurrentProcess() })?;
    if connected_process_id(socket)? != peer_pid {
        return Err(io::Error::new(
            ErrorKind::PermissionDenied,
            "Unix socket peer process changed during owner verification",
        ));
    }
    ensure_running(&process)?;
    peer.ensure_owner(&owner)
}

fn connected_process_id(socket: RawSocket) -> io::Result<u32> {
    let mut pid = 0_u32;
    let mut bytes_returned = 0_u32;
    let result = unsafe {
        WSAIoctl(
            socket as _,
            SIO_AF_UNIX_GETPEERPID,
            ptr::null(),
            /*cbinbuffer*/ 0,
            ptr::from_mut(&mut pid).cast(),
            size_of::<u32>() as u32,
            &mut bytes_returned,
            ptr::null_mut(),
            /*lpcompletionroutine*/ None,
        )
    };
    if result == SOCKET_ERROR {
        return Err(io::Error::from_raw_os_error(unsafe { WSAGetLastError() }));
    }
    // Some Windows versions return the PID but leave bytes_returned at zero:
    // https://github.com/microsoft/WSL/issues/4676. Success plus a nonzero PID
    // is still required, followed by live-process and token-owner checks.
    if pid == 0 || ![0, size_of::<u32>() as u32].contains(&bytes_returned) {
        return Err(io::Error::new(
            ErrorKind::PermissionDenied,
            "Unix socket did not identify a connected peer process",
        ));
    }
    Ok(pid)
}

fn ensure_running(process: &OwnedHandle) -> io::Result<()> {
    match unsafe {
        WaitForSingleObject(process.as_raw_handle(), /*dwmilliseconds*/ 0)
    } {
        WAIT_TIMEOUT => Ok(()),
        WAIT_FAILED => Err(io::Error::last_os_error()),
        _ => Err(io::Error::new(
            ErrorKind::PermissionDenied,
            "Unix socket peer process is no longer running",
        )),
    }
}

// TOKEN_USER includes a pointer into its output buffer. Resolve and copy it
// before moving the buffer; both buffers are aligned and strictly bounded.
#[repr(C)]
struct TokenUserBuffer {
    user: TOKEN_USER,
    sid: [u32; SECURITY_MAX_SID_SIZE as usize / size_of::<u32>()],
}

struct UserSid([u32; SECURITY_MAX_SID_SIZE as usize / size_of::<u32>()]);

impl UserSid {
    fn from_process(process: HANDLE) -> io::Result<Self> {
        let mut token = ptr::null_mut();
        if unsafe { OpenProcessToken(process, TOKEN_QUERY, &mut token) } == 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: OpenProcessToken succeeded and transferred a token handle.
        let token = unsafe { OwnedHandle::from_raw_handle(token) };
        // SAFETY: the buffer contains only integers and a nullable raw pointer.
        let mut buffer: TokenUserBuffer = unsafe { std::mem::zeroed() };
        let mut returned = 0;
        if unsafe {
            GetTokenInformation(
                token.as_raw_handle(),
                TokenUser,
                ptr::from_mut(&mut buffer).cast(),
                size_of::<TokenUserBuffer>() as u32,
                &mut returned,
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let sid = buffer.user.User.Sid;
        let start = ptr::from_ref(&buffer) as usize;
        let sid_offset = (sid as usize).checked_sub(start);
        // Bound even the maximum SID before asking Win32 to inspect its header.
        if !(size_of::<TOKEN_USER>()..=size_of::<TokenUserBuffer>()).contains(&(returned as usize))
            || !sid_offset.is_some_and(|offset| {
                offset >= size_of::<TOKEN_USER>()
                    && offset <= size_of::<TokenUserBuffer>() - SECURITY_MAX_SID_SIZE as usize
            })
            || unsafe { IsValidSid(sid) } == 0
        {
            return Err(io::Error::new(
                ErrorKind::InvalidData,
                "process token returned an invalid owner SID",
            ));
        }
        let length = unsafe { GetLengthSid(sid) } as usize;
        if sid_offset
            .and_then(|offset| offset.checked_add(length))
            .is_none_or(|end| end > returned as usize)
        {
            return Err(io::Error::new(
                ErrorKind::InvalidData,
                "process token owner SID exceeds its returned buffer",
            ));
        }
        let mut result = Self([0; SECURITY_MAX_SID_SIZE as usize / size_of::<u32>()]);
        if unsafe { CopySid(SECURITY_MAX_SID_SIZE, result.0.as_mut_ptr().cast(), sid) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(result)
    }

    fn ensure_owner(&self, owner: &Self) -> io::Result<()> {
        if unsafe {
            EqualSid(
                self.0.as_ptr().cast_mut().cast(),
                owner.0.as_ptr().cast_mut().cast(),
            )
        } != 0
        {
            Ok(())
        } else {
            Err(io::Error::new(
                ErrorKind::PermissionDenied,
                "Unix socket peer is not owned by the current user",
            ))
        }
    }
}

#[cfg(test)]
#[path = "windows_peer_tests.rs"]
mod tests;
