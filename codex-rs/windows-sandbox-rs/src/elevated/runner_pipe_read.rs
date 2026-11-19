use super::CANCEL_POLL;
use crate::ipc_framed::FramedMessage;
use anyhow::Result;
use std::fs::File;
use std::io;
use std::io::Read;
use std::os::windows::io::AsRawHandle;
use std::ptr;
use std::time::Instant;
use windows_sys::Win32::Foundation::ERROR_BROKEN_PIPE;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::Pipes::PeekNamedPipe;

/// The transport transfers its sole output reader after SpawnReady. No clone
/// reads from this pipe. Peek only bounds the next read to bytes already present;
/// the original decoder still owns framing, its size limit and JSON validation.
pub(super) fn read_frame(
    pipe: &mut File,
    deadline: Option<Instant>,
    cancelled: impl Fn() -> bool,
) -> Result<Option<FramedMessage>> {
    crate::ipc_framed::read_frame(InterruptiblePipe {
        pipe,
        deadline,
        cancelled,
    })
}

struct InterruptiblePipe<'a, F> {
    pipe: &'a mut File,
    deadline: Option<Instant>,
    cancelled: F,
}

impl<F: Fn() -> bool> InterruptiblePipe<'_, F> {
    fn check(&self) -> io::Result<()> {
        if (self.cancelled)() {
            // read_exact retries Interrupted, so cancellation must use a
            // terminal I/O error kind while preserving unknown process state.
            return Err(io::Error::other("runner output observation cancelled"));
        }
        if self.deadline.is_some_and(|end| Instant::now() >= end) {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "runner output was not completed within the original budget",
            ));
        }
        Ok(())
    }
}

impl<F: Fn() -> bool> Read for InterruptiblePipe<'_, F> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        if buffer.is_empty() {
            return Ok(0);
        }
        loop {
            self.check()?;
            let mut available = 0_u32;
            let ok = unsafe {
                PeekNamedPipe(
                    self.pipe.as_raw_handle() as HANDLE,
                    ptr::null_mut(),
                    0,
                    ptr::null_mut(),
                    &mut available,
                    ptr::null_mut(),
                )
            };
            if ok == 0 {
                let error = io::Error::last_os_error();
                self.check()?;
                return if error.raw_os_error() == Some(ERROR_BROKEN_PIPE as i32) {
                    Ok(0)
                } else {
                    Err(error)
                };
            }
            self.check()?;
            if available != 0 {
                let count = buffer.len().min(available as usize);
                let read = self.pipe.read(&mut buffer[..count]);
                self.check()?;
                return read;
            }
            let pause = self.deadline.map_or(CANCEL_POLL, |end| {
                CANCEL_POLL.min(end.saturating_duration_since(Instant::now()))
            });
            std::thread::sleep(pause);
        }
    }
}

#[cfg(test)]
#[path = "runner_pipe_read_tests.rs"]
mod tests;
