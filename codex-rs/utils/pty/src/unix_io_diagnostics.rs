//! Unit-test observations only; no descriptor or child ownership is retained.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::sync::Weak;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::AtomicU64;
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

pub(super) enum WriterEvent<'a> {
    WaitingForMessage,
    MessageReceived(usize),
    WaitingForWrite,
    Written(usize),
    Interrupted(&'a io::Error),
    Failed(&'a io::Error),
    MessageComplete,
    QueueClosed,
    Termios { canonical: bool, eof: libc::cc_t },
    TermiosFailed(&'a io::Error),
    EofStarted,
    EofResult(&'a io::Result<()>),
    EofDisabled,
    NoEofRequested,
    Finished,
}

pub(crate) struct PtyIoDiagnostics {
    fd: Weak<AsyncFd<File>>,
    read_calls: AtomicU64,
    read_bytes: AtomicU64,
    discarded_bytes: AtomicU64,
    last_read: AtomicU64,
    terminal_error: AtomicU64,
    wait_state: AtomicU8,
    writer_messages: AtomicU64,
    writer_requested_bytes: AtomicU64,
    writer_completed_messages: AtomicU64,
    written_bytes: AtomicU64,
    write_waits: AtomicU64,
    last_write: AtomicU64,
    last_write_bytes: AtomicU64,
    writer_error: AtomicU64,
    writer_state: AtomicU8,
    termios: AtomicU64,
    eof_state: AtomicU8,
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
            writer_messages: AtomicU64::default(),
            writer_requested_bytes: AtomicU64::default(),
            writer_completed_messages: AtomicU64::default(),
            written_bytes: AtomicU64::default(),
            write_waits: AtomicU64::default(),
            last_write: AtomicU64::default(),
            last_write_bytes: AtomicU64::default(),
            writer_error: AtomicU64::default(),
            writer_state: AtomicU8::default(),
            termios: AtomicU64::default(),
            eof_state: AtomicU8::default(),
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
                self.discarded_bytes
                    .fetch_add(count as u64, Ordering::Relaxed);
            }
            ReaderEvent::Eof => self.wait_state.store(/*val*/ 4, Ordering::Relaxed),
            ReaderEvent::Failed(error) => {
                self.terminal_error
                    .store(encode_error(error), Ordering::Relaxed);
                self.wait_state.store(/*val*/ 5, Ordering::Relaxed);
            }
        }
    }

    pub(super) fn observe_writer(&self, event: WriterEvent<'_>) {
        match event {
            WriterEvent::WaitingForMessage => {
                self.writer_state.store(/*val*/ 1, Ordering::Relaxed);
            }
            WriterEvent::MessageReceived(count) => {
                self.writer_messages.fetch_add(/*val*/ 1, Ordering::Relaxed);
                self.writer_requested_bytes
                    .fetch_add(count as u64, Ordering::Relaxed);
                self.writer_state.store(/*val*/ 2, Ordering::Relaxed);
            }
            WriterEvent::WaitingForWrite => {
                // Counts awaited async writes, not individual write syscalls.
                self.write_waits.fetch_add(/*val*/ 1, Ordering::Relaxed);
                self.writer_state.store(/*val*/ 3, Ordering::Relaxed);
            }
            WriterEvent::Written(count) => {
                // Includes the final newline and VEOF when they are written.
                self.written_bytes
                    .fetch_add(count as u64, Ordering::Relaxed);
                self.last_write_bytes.store(count as u64, Ordering::Relaxed);
                self.last_write.store(1_u64 << 32, Ordering::Relaxed);
            }
            WriterEvent::Interrupted(error) => {
                self.last_write
                    .store(encode_error(error), Ordering::Relaxed);
            }
            WriterEvent::Failed(error) => {
                self.last_write
                    .store(encode_error(error), Ordering::Relaxed);
                self.writer_error
                    .store(encode_error(error), Ordering::Relaxed);
                self.writer_state.store(/*val*/ 7, Ordering::Relaxed);
            }
            WriterEvent::MessageComplete => {
                self.writer_completed_messages
                    .fetch_add(/*val*/ 1, Ordering::Relaxed);
                self.writer_state.store(/*val*/ 4, Ordering::Relaxed);
            }
            WriterEvent::QueueClosed => {
                self.writer_state.store(/*val*/ 5, Ordering::Relaxed);
            }
            WriterEvent::Termios { canonical, eof } => {
                self.termios.store(
                    (1_u64 << 32) | (u64::from(canonical) << 8) | u64::from(eof),
                    Ordering::Relaxed,
                );
            }
            WriterEvent::TermiosFailed(error) => {
                self.termios.store(encode_error(error), Ordering::Relaxed);
                self.eof_state.store(/*val*/ 5, Ordering::Relaxed);
            }
            WriterEvent::EofStarted => self.eof_state.store(/*val*/ 1, Ordering::Relaxed),
            WriterEvent::EofResult(result) => {
                let state = if result.is_ok() { 2 } else { 3 };
                self.eof_state.store(state, Ordering::Relaxed);
            }
            WriterEvent::EofDisabled => self.eof_state.store(/*val*/ 4, Ordering::Relaxed),
            WriterEvent::NoEofRequested => self.eof_state.store(/*val*/ 6, Ordering::Relaxed),
            WriterEvent::Finished => self.writer_state.store(/*val*/ 6, Ordering::Relaxed),
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
        let writer_state = match self.writer_state.load(Ordering::Relaxed) {
            0 => "not_started",
            1 => "waiting_for_message",
            2 => "message_received",
            3 => "waiting_for_write",
            4 => "message_complete",
            5 => "queue_closed",
            6 => "finished",
            7 => "write_error",
            _ => "unknown",
        };
        let eof_state = match self.eof_state.load(Ordering::Relaxed) {
            0 => "not_attempted",
            1 => "writing",
            2 => "written",
            3 => "write_error",
            4 => "veof_disabled",
            5 => "termios_error",
            6 => "not_requested",
            _ => "unknown",
        };
        let termios = self.termios.load(Ordering::Relaxed);
        let termios = if termios >> 32 == 1 {
            format!("icanon={} veof={}", (termios >> 8) & 1, termios & 255)
        } else {
            describe_result(termios)
        };
        let last_write = self.last_write.load(Ordering::Relaxed);
        let last_write = if last_write >> 32 == 1 {
            format!("ok({})", self.last_write_bytes.load(Ordering::Relaxed))
        } else {
            describe_result(last_write)
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
            "state={wait_state} read_calls={} read_bytes={} discarded_bytes={} last_read={} terminal_error={} {descriptor} writer_state={writer_state} writer_messages={} writer_requested_bytes={} writer_completed_messages={} written_bytes={} write_waits={} last_write={last_write} writer_error={} termios=({termios}) eof_state={eof_state}",
            self.read_calls.load(Ordering::Relaxed),
            self.read_bytes.load(Ordering::Relaxed),
            self.discarded_bytes.load(Ordering::Relaxed),
            describe_result(self.last_read.load(Ordering::Relaxed)),
            describe_result(self.terminal_error.load(Ordering::Relaxed)),
            self.writer_messages.load(Ordering::Relaxed),
            self.writer_requested_bytes.load(Ordering::Relaxed),
            self.writer_completed_messages.load(Ordering::Relaxed),
            self.written_bytes.load(Ordering::Relaxed),
            self.write_waits.load(Ordering::Relaxed),
            describe_result(self.writer_error.load(Ordering::Relaxed)),
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
