//! Kernel descriptor controls for the failure-only stderr observer.
#![cfg(unix)]

#[path = "support/startup_pipe.rs"]
mod startup_pipe;

use std::io;
use std::io::Read;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixStream;

use pretty_assertions::assert_eq;

fn status_flags(stream: &UnixStream) -> io::Result<i32> {
    let flags = unsafe { libc::fcntl(stream.as_raw_fd(), libc::F_GETFL) };
    if flags == -1 {
        return Err(io::Error::last_os_error());
    }
    Ok(flags)
}

#[test]
fn blocking_descriptor_is_refused_without_consuming_bytes() -> io::Result<()> {
    let (mut reader, mut writer) = UnixStream::pair()?;
    writer.write_all(b"retained")?;
    let before = status_flags(&reader)?;
    let observed = startup_pipe::observe(&mut reader);
    assert_eq!(
        observed,
        format!("os_read_not_attempted nonblocking=false flags=0x{before:x}")
    );
    assert_eq!(status_flags(&reader)?, before);
    // Only this fresh control changes its own flags after observation. This
    // prevents an erroneous earlier consumption from hanging the assertion.
    reader.set_nonblocking(/*nonblocking*/ true)?;
    let mut retained = [0_u8; 8];
    reader.read_exact(&mut retained)?;
    assert_eq!(&retained, b"retained");
    Ok(())
}

#[test]
fn nonblocking_empty_and_closed_peer_are_distinct() -> io::Result<()> {
    let (mut reader, writer) = UnixStream::pair()?;
    reader.set_nonblocking(/*nonblocking*/ true)?;
    let before = status_flags(&reader)?;
    let empty = startup_pipe::observe(&mut reader);
    assert!(empty.starts_with("os_would_block nonblocking=true "));
    assert!(empty.contains("kind=WouldBlock"));
    assert_eq!(status_flags(&reader)?, before);
    drop(writer);
    assert_eq!(
        startup_pipe::observe(&mut reader),
        format!("os_eof nonblocking=true flags=0x{before:x}")
    );
    assert_eq!(status_flags(&reader)?, before);
    Ok(())
}

#[test]
fn single_read_keeps_remainder_and_bounds_display() -> io::Result<()> {
    let (mut reader, mut writer) = UnixStream::pair()?;
    reader.set_nonblocking(/*nonblocking*/ true)?;
    writer.set_nonblocking(/*nonblocking*/ true)?;
    let before = status_flags(&reader)?;
    writer.write_all(&[0x1b; 4097])?;
    let observed = startup_pipe::observe(&mut reader);
    let bytes = observed
        .strip_prefix("os_single_read_bytes=")
        .and_then(|tail| tail.split_once(' '))
        .and_then(|(count, _)| count.parse::<usize>().ok())
        .ok_or_else(|| io::Error::other("single-read byte count missing or invalid"))?;
    assert!((1..=4096).contains(&bytes));
    let prefix_bytes = bytes.min(1024);
    let prefix_truncated = prefix_bytes < bytes;
    assert!(observed.contains(&format!(
        "prefix_bytes={prefix_bytes} prefix_truncated={prefix_truncated}"
    )));
    assert!(observed.len() < 8192);
    assert_eq!(status_flags(&reader)?, before);
    let mut remainder = vec![0_u8; 4097 - bytes];
    reader.read_exact(&mut remainder)?;
    assert_eq!(remainder, vec![0x1b; 4097 - bytes]);
    Ok(())
}
