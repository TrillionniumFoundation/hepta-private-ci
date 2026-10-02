//! Parent-owned polling I/O. No reader/writer thread can outlive an operation.
use std::io;
#[cfg(unix)]
use std::io::Read as _;
use std::process::ChildStdin;
use std::process::ChildStdout;

pub(crate) fn prepare_reader(reader: &ChildStdout) -> io::Result<()> {
    #[cfg(unix)]
    {
        let flags = rustix::fs::fcntl_getfl(reader)?;
        rustix::fs::fcntl_setfl(reader, flags | rustix::fs::OFlags::NONBLOCK)?;
    }
    #[cfg(windows)]
    let _ = reader;
    Ok(())
}

pub(crate) fn prepare_writer(writer: &ChildStdin) -> io::Result<()> {
    #[cfg(unix)]
    {
        let flags = rustix::fs::fcntl_getfl(writer)?;
        rustix::fs::fcntl_setfl(writer, flags | rustix::fs::OFlags::NONBLOCK)?;
        Ok(())
    }
    #[cfg(windows)]
    hepta_native_platform::pipe::configure_writer(writer)
}

pub(crate) fn read_available(reader: &mut ChildStdout, bytes: &mut [u8]) -> io::Result<usize> {
    #[cfg(unix)]
    {
        reader.read(bytes)
    }
    #[cfg(windows)]
    hepta_native_platform::pipe::read_available(reader, bytes)
}

pub(crate) fn would_block(error: &io::Error) -> bool {
    error.kind() == io::ErrorKind::WouldBlock
        || error.kind() == io::ErrorKind::Interrupted
        || cfg!(windows) && error.raw_os_error() == Some(232)
}
