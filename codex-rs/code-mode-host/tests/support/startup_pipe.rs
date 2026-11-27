//! One OS read after a failed startup, only on a verified nonblocking duplicate.
//!
//! The fixture exclusively borrows its captured stderr and has no concurrent
//! flag-changing alias. This is not an atomic guarantee against unrelated users
//! of the same open file description. Never change flags or wait for readiness.

use std::fs::File;
use std::io;
use std::io::Read;
use std::os::fd::AsFd;
use std::os::fd::AsRawFd;

pub(super) fn observe(stderr: &mut impl AsFd) -> String {
    let duplicate = match stderr.as_fd().try_clone_to_owned() {
        Ok(duplicate) => duplicate,
        Err(error) => {
            return format!(
                "os_read_not_attempted duplicate_error(kind={:?}, os={:?})",
                error.kind(),
                error.raw_os_error(),
            );
        }
    };
    // F_GETFL queries the exact descriptor used below. It never changes the
    // shared open-file status flags; the owned duplicate closes on every return.
    let flags = unsafe { libc::fcntl(duplicate.as_raw_fd(), libc::F_GETFL) };
    if flags == -1 {
        let error = io::Error::last_os_error();
        return format!(
            "os_read_not_attempted flags_error(kind={:?}, os={:?})",
            error.kind(),
            error.raw_os_error(),
        );
    }
    if flags & libc::O_NONBLOCK == 0 {
        return format!("os_read_not_attempted nonblocking=false flags=0x{flags:x}");
    }

    let mut file = File::from(duplicate);
    let mut buffer = [0_u8; 4096];
    // File::read issues one OS read. In particular, do not use read_exact,
    // read_to_end, a Tokio future, or an EINTR retry here.
    match file.read(&mut buffer) {
        Ok(0) => format!("os_eof nonblocking=true flags=0x{flags:x}"),
        Ok(bytes) => {
            // Bound displayed bytes independently of read size. Debug escaping
            // and lossy UTF-8 conversion cannot expand this prefix beyond 6146
            // bytes; the whole returned observation remains below 8192 bytes.
            let prefix_bytes = bytes.min(1024);
            let prefix = String::from_utf8_lossy(&buffer[..prefix_bytes]);
            let prefix_truncated = prefix_bytes < bytes;
            format!(
                "os_single_read_bytes={bytes} nonblocking=true flags=0x{flags:x} capacity=4096 prefix_bytes={prefix_bytes} prefix_truncated={prefix_truncated} prefix={prefix:?}"
            )
        }
        Err(error) if error.kind() == io::ErrorKind::WouldBlock => format!(
            "os_would_block nonblocking=true flags=0x{flags:x} kind={:?} os={:?}",
            error.kind(),
            error.raw_os_error(),
        ),
        Err(error) => format!(
            "os_read_error nonblocking=true flags=0x{flags:x} kind={:?} os={:?}",
            error.kind(),
            error.raw_os_error(),
        ),
    }
}
