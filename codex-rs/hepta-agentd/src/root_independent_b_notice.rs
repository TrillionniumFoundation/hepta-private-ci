//! One-shot DATA notifications between original B frames. These sockets do
//! not carry a request, authority, receipt, key or new lifetime. Both ends are
//! consumed once; EOF, cancellation and the original end are fail-closed.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Write;
use std::net::Shutdown;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

pub(crate) const BOUND: usize = 16_384;
const MAGIC: &[u8; 8] = b"HEPBN001";

pub(crate) struct OriginalBNoticeWriter {
    stream: UnixStream,
}

impl OriginalBNoticeWriter {
    pub(crate) fn pair() -> io::Result<(Self, File)> {
        let (writer, reader) = UnixStream::pair()?;
        writer.shutdown(Shutdown::Read)?;
        reader.shutdown(Shutdown::Write)?;
        writer.set_nonblocking(true)?;
        reader.set_nonblocking(true)?;
        Ok((Self { stream: writer }, File::from(OwnedFd::from(reader))))
    }

    pub(crate) fn send(
        mut self,
        bytes: &[u8],
        end: Instant,
        mut require_original: impl FnMut() -> io::Result<()>,
    ) -> io::Result<()> {
        if bytes.is_empty() || bytes.len() > BOUND {
            return Err(io::Error::other("bounded original B notification required"));
        }
        let mut image = Vec::with_capacity(12 + bytes.len());
        image.extend_from_slice(MAGIC);
        image.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
        image.extend_from_slice(bytes);
        let mut written = 0;
        while written < image.len() {
            require_live(end, &mut require_original)?;
            match self.stream.write(&image[written..]) {
                Ok(0) => return Err(io::Error::other("original B notification write closed")),
                Ok(count) => written += count,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => pause(end)?,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(error) => return Err(error),
            }
        }
        require_live(end, &mut require_original)?;
        self.stream.shutdown(Shutdown::Write)
    }
}

pub(crate) fn require_original_notice_reader(file: &File, root_pid: u32) -> io::Result<()> {
    if !file.metadata()?.file_type().is_socket() || root_pid == 0 {
        return Err(io::Error::other(
            "original Root B notification socket required",
        ));
    }
    let mut credentials = libc::ucred {
        pid: 0,
        uid: 0,
        gid: 0,
    };
    let mut size = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    // SAFETY: getsockopt writes one bounded live ucred and its initialized size.
    if unsafe {
        libc::getsockopt(
            file.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            (&raw mut credentials).cast(),
            &raw mut size,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    if size as usize != std::mem::size_of::<libc::ucred>()
        || credentials.uid != 0
        || credentials.pid <= 0
        || credentials.pid as u32 != root_pid
    {
        return Err(io::Error::other(
            "original B notification Root peer differs",
        ));
    }
    Ok(())
}

pub(crate) fn receive_original_notice(
    file: File,
    root_pid: u32,
    end: Instant,
    require_original: impl FnMut() -> io::Result<()>,
) -> io::Result<Vec<u8>> {
    require_original_notice_reader(&file, root_pid)?;
    receive_stream(UnixStream::from(OwnedFd::from(file)), end, require_original)
}

fn receive_stream(
    mut stream: UnixStream,
    end: Instant,
    mut require_original: impl FnMut() -> io::Result<()>,
) -> io::Result<Vec<u8>> {
    stream.set_nonblocking(true)?;
    let mut image = Vec::new();
    let mut expected = None;
    loop {
        require_live(end, &mut require_original)?;
        let mut chunk = [0_u8; 1024];
        match stream.read(&mut chunk) {
            Ok(0) => {
                if expected != Some(image.len()) {
                    return Err(io::Error::other(
                        "original B notification ended before its cut",
                    ));
                }
                require_live(end, &mut require_original)?;
                return Ok(image.split_off(12));
            }
            Ok(count) => {
                image.extend_from_slice(&chunk[..count]);
                if image.len() > BOUND + 12 {
                    return Err(io::Error::other(
                        "original B notification exceeds its bound",
                    ));
                }
                if image.len() >= 12 {
                    if &image[..8] != MAGIC {
                        return Err(io::Error::other("original B notification framing differs"));
                    }
                    let length =
                        u32::from_le_bytes(image[8..12].try_into().map_err(io::Error::other)?)
                            as usize;
                    if length == 0 || length > BOUND || image.len() > length + 12 {
                        return Err(io::Error::other("original B notification length differs"));
                    }
                    expected = Some(length + 12);
                }
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => pause(end)?,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
        }
    }
}

fn require_live(
    end: Instant,
    require_original: &mut impl FnMut() -> io::Result<()>,
) -> io::Result<()> {
    require_original()?;
    if Instant::now() >= end {
        return Err(io::Error::other("original B notification end elapsed"));
    }
    Ok(())
}

fn pause(end: Instant) -> io::Result<()> {
    let remaining = end
        .checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .ok_or_else(|| io::Error::other("original B notification end elapsed"))?;
    std::thread::sleep(remaining.min(Duration::from_millis(5)));
    Ok(())
}

#[cfg(test)]
#[path = "root_independent_b_notice_tests.rs"]
mod tests;
