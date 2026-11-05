//! Unit-test observations only; no descriptor or child ownership is retained.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::sync::Weak;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use tokio::io::unix::AsyncFd;

pub(super) enum ReaderEvent<'a> {
    WaitingForRead,
    ReadStarted,
    ReadResult(&'a io::Result<usize>),
    Sending,
    Discarded(usize),
    Eof,
    Failed(&'a io::Error),
}

pub(crate) struct PtyIoDiagnostics {
    fd: Weak<AsyncFd<File>>,
    read_calls: AtomicU64,
    read_bytes: AtomicU64,
    discarded_bytes: AtomicU64,
    last_read: AtomicU64,
    terminal_error: AtomicU64,
    wait_state: AtomicU8,
}

impl PtyIoDiagnostics {
    pub(crate) fn new(fd: Weak<AsyncFd<File>>) -> Self {
        Self {
            fd,
            read_calls: AtomicU64::default(),
            read_bytes: AtomicU64::default(),
            discarded_bytes: AtomicU64::default(),
            last_read: AtomicU64::default(),
            terminal_error: AtomicU64::default(),
            wait_state: AtomicU8::default(),
        }
    }

    pub(super) fn observe(&self, event: ReaderEvent<'_>) {
        match event {
            ReaderEvent::WaitingForRead => self.wait_state.store(/*val*/ 1, Ordering::Relaxed),
            ReaderEvent::ReadStarted => {
                self.wait_state.store(/*val*/ 2, Ordering::Relaxed);
                self.read_calls.fetch_add(/*val*/ 1, Ordering::Relaxed);
            }
            ReaderEvent::ReadResult(result) => {
                let encoded = match result {
                    Ok(count) => {
                        self.read_bytes.fetch_add(*count as u64, Ordering::Relaxed);
                        // Reads use an 8 KiB buffer, so the count fits below the tag.
                        (1_u64 << 32) | *count as u64
                    }
                    Err(error) => {
                        if error.kind() == io::ErrorKind::WouldBlock {
                            self.wait_state.store(/*val*/ 1, Ordering::Relaxed);
                        }
                        encode_error(error)
                    }
                };
                self.last_read.store(encoded, Ordering::Relaxed);
            }
            ReaderEvent::Sending => self.wait_state.store(/*val*/ 3, Ordering::Relaxed),
            ReaderEvent::Discarded(count) => {
                self.discarded_bytes.fetch_add(count as u64, Ordering::Relaxed);
            }
            ReaderEvent::Eof => self.wait_state.store(/*val*/ 4, Ordering::Relaxed),
            ReaderEvent::Failed(error) => {
                self.terminal_error
                    .store(encode_error(error), Ordering::Relaxed);
                self.wait_state.store(/*val*/ 5, Ordering::Relaxed);
            }
        }
    }

    pub(crate) fn snapshot(&self) -> String {
        // These independent observations do not form an atomic protocol state.
        let wait_state = match self.wait_state.load(Ordering::Relaxed) {
            0 => "not_started",
            1 => "waiting_for_read",
            2 => "in_read",
            3 => "sending",
            4 => "eof",
            5 => "read_error",
            _ => "unknown",
        };
        let descriptor = match self.fd.upgrade() {
            Some(fd) => {
                // The temporary strong reference pins this exact AsyncFd only
                // during the two non-consuming queries. No raw FD is cached.
                let raw_fd = fd.get_ref().as_raw_fd();
                // SAFETY: AsyncFd owns this unchanged open descriptor.
                let flags = unsafe { libc::fcntl(raw_fd, libc::F_GETFL) };
                let flags = if flags == -1 {
                    Err(io::Error::last_os_error().raw_os_error())
                } else {
                    Ok(flags)
                };
                let mut queued_bytes: libc::c_int = 0;
                // SAFETY: queued_bytes is a valid output buffer for FIONREAD.
                let rc = unsafe { libc::ioctl(raw_fd, libc::FIONREAD, &mut queued_bytes) };
                let queued_bytes = if rc == -1 {
                    Err(io::Error::last_os_error().raw_os_error())
                } else {
                    Ok(queued_bytes)
                };
                format!("flags={flags:?} queued_bytes={queued_bytes:?}")
            }
            None => "descriptor_released".to_string(),
        };
        format!(
            "state={wait_state} read_calls={} read_bytes={} discarded_bytes={} last_read={} terminal_error={} {descriptor}",
            self.read_calls.load(Ordering::Relaxed),
            self.read_bytes.load(Ordering::Relaxed),
            self.discarded_bytes.load(Ordering::Relaxed),
            describe_result(self.last_read.load(Ordering::Relaxed)),
            describe_result(self.terminal_error.load(Ordering::Relaxed)),
        )
    }
}

fn encode_error(error: &io::Error) -> u64 {
    match error.raw_os_error() {
        Some(errno) => (2_u64 << 32) | u64::from(errno as u32),
        None => 3_u64 << 32,
    }
}

fn describe_result(encoded: u64) -> String {
    match encoded >> 32 {
        0 => "none".to_string(),
        1 => format!("ok({})", encoded as u32),
        2 => format!("errno({})", encoded as u32 as i32),
        3 => "error_without_os_errno".to_string(),
        _ => "unknown".to_string(),
    }
}
