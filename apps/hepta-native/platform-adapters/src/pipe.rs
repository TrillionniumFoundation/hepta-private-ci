//! Nonblocking operations on exclusively owned parent ends of anonymous pipes.
//! No other thread or process may read the parent reader concurrently. The child
//! inherits only the opposite end. OS scheduling and kernel calls are not a
//! real-time guarantee; these operations never wait for descendant-held EOF.
use std::io;
use std::io::Read;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle as _;
use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::Pipes::PIPE_NOWAIT;
use windows::Win32::System::Pipes::PeekNamedPipe;
use windows::Win32::System::Pipes::SetNamedPipeHandleState;

/// Put an owned anonymous-pipe writer in nonblocking mode before polling writes.
pub fn configure_writer(writer: &impl AsHandle) -> io::Result<()> {
    let handle = HANDLE(writer.as_handle().as_raw_handle());
    // SAFETY: The borrowed pipe handle remains live. PIPE_NOWAIT is supported
    // for CreatePipe anonymous handles with the writer's GENERIC_WRITE access.
    unsafe { SetNamedPipeHandleState(handle, Some(&PIPE_NOWAIT), None, None) }
        .map_err(|error| io::Error::from_raw_os_error(error.code().0 & 0xffff))
}

/// Read only currently available bytes from an exclusively owned parent reader.
/// Empty-but-open is WouldBlock, while a broken pipe is EOF.
pub fn read_available(reader: &mut (impl Read + AsHandle), bytes: &mut [u8]) -> io::Result<usize> {
    let handle = HANDLE(reader.as_handle().as_raw_handle());
    let mut available = 0_u32;
    // SAFETY: The handle is live and this owner performs no concurrent I/O on it.
    // Only the available count is requested; its output pointer is valid.
    if let Err(error) = unsafe { PeekNamedPipe(handle, None, 0, None, Some(&mut available), None) }
    {
        let code = error.code().0 & 0xffff;
        return if code == 109 {
            Ok(0)
        } else {
            Err(io::Error::from_raw_os_error(code))
        };
    }
    if available == 0 {
        return Err(io::ErrorKind::WouldBlock.into());
    }
    let length = bytes.len().min(available as usize);
    reader.read(&mut bytes[..length])
}

#[cfg(test)]
#[path = "pipe_tests.rs"]
mod tests;
