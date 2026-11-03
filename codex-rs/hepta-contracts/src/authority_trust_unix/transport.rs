//! One bounded connection, with OS peer identity and absolute-deadline I/O.
#[cfg(target_os = "linux")]
pub(super) use linux::exchange;

#[cfg(not(target_os = "linux"))]
pub(super) fn exchange(
    _config: &super::UnixPqTrustEndpointConfig,
    _request: &[u8],
    _deadline: std::time::Instant,
) -> Result<Vec<u8>, crate::AuthorityTrustError> {
    Err(crate::AuthorityTrustError::Unavailable)
}

#[cfg(target_os = "linux")]
mod linux {
    use super::super::MAX_RESPONSE_BYTES;
    use super::super::UnixPqTrustEndpointConfig;
    use crate::AuthorityTrustError;
    use rustix::event::PollFd;
    use rustix::event::PollFlags;
    use rustix::event::Timespec;
    use rustix::event::poll;
    use rustix::net::AddressFamily;
    use rustix::net::SocketAddrUnix;
    use rustix::net::SocketFlags;
    use rustix::net::SocketType;
    use rustix::net::{self};
    use std::io::Read;
    use std::io::Write;
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::net::UnixStream;
    use std::time::Instant;

    pub(crate) fn exchange(
        config: &UnixPqTrustEndpointConfig,
        request: &[u8],
        deadline: Instant,
    ) -> Result<Vec<u8>, AuthorityTrustError> {
        let meta = std::fs::symlink_metadata(&config.socket_path)
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        let parent = config
            .socket_path
            .parent()
            .ok_or(AuthorityTrustError::Invalid)?;
        let parent_meta =
            std::fs::symlink_metadata(parent).map_err(|_| AuthorityTrustError::Unavailable)?;
        if !meta.file_type().is_socket()
            || meta.uid() != config.peer_uid
            || meta.mode() & 0o007 != 0
            || !parent_meta.is_dir()
            || parent_meta.mode() & 0o022 != 0
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let fd = net::socket_with(
            AddressFamily::UNIX,
            SocketType::STREAM,
            SocketFlags::CLOEXEC | SocketFlags::NONBLOCK,
            /*protocol*/ None,
        )
        .map_err(|_| AuthorityTrustError::Unavailable)?;
        let address =
            SocketAddrUnix::new(&config.socket_path).map_err(|_| AuthorityTrustError::Invalid)?;
        match net::connect(&fd, &address) {
            Ok(()) => (),
            Err(rustix::io::Errno::INPROGRESS) => wait(&fd, PollFlags::OUT, deadline)?,
            Err(_) => return Err(AuthorityTrustError::Unavailable),
        }
        net::sockopt::socket_error(&fd)
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if net::sockopt::socket_peercred(&fd)
            .map_err(|_| AuthorityTrustError::Unavailable)?
            .uid
            .as_raw()
            != config.peer_uid
        {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut stream = UnixStream::from(fd);
        let mut wire = (request.len() as u32).to_be_bytes().to_vec();
        wire.extend(request);
        let mut left = wire.as_slice();
        while !left.is_empty() {
            wait(&stream, PollFlags::OUT, deadline)?;
            match stream.write(left) {
                Ok(0) => return Err(AuthorityTrustError::Unavailable),
                Ok(n) => left = &left[n..],
                Err(e)
                    if matches!(
                        e.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                    ) => {}
                Err(_) => return Err(AuthorityTrustError::Unavailable),
            }
        }
        let mut length = [0; 4];
        read(&mut stream, &mut length, deadline)?;
        let length = u32::from_be_bytes(length) as usize;
        if length == 0 || length > MAX_RESPONSE_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut response = vec![0; length];
        read(&mut stream, &mut response, deadline)?;
        Ok(response)
    }
    fn wait(
        fd: &impl std::os::fd::AsFd,
        events: PollFlags,
        deadline: Instant,
    ) -> Result<(), AuthorityTrustError> {
        loop {
            let remaining = deadline
                .checked_duration_since(Instant::now())
                .filter(|v| !v.is_zero())
                .ok_or(AuthorityTrustError::Unavailable)?;
            let timeout =
                Timespec::try_from(remaining).map_err(|_| AuthorityTrustError::Invalid)?;
            let mut fds = [PollFd::new(fd, events)];
            match poll(&mut fds, Some(&timeout)) {
                Ok(0) => return Err(AuthorityTrustError::Unavailable),
                Ok(_) => {
                    if fds[0]
                        .revents()
                        .intersects(PollFlags::ERR | PollFlags::NVAL)
                    {
                        return Err(AuthorityTrustError::Unavailable);
                    }
                    return Ok(());
                }
                Err(rustix::io::Errno::INTR) => (),
                Err(_) => return Err(AuthorityTrustError::Unavailable),
            }
        }
    }
    fn read(
        stream: &mut UnixStream,
        mut out: &mut [u8],
        deadline: Instant,
    ) -> Result<(), AuthorityTrustError> {
        while !out.is_empty() {
            wait(stream, PollFlags::IN, deadline)?;
            match stream.read(out) {
                Ok(0) => return Err(AuthorityTrustError::Unavailable),
                Ok(n) => out = &mut out[n..],
                Err(e)
                    if matches!(
                        e.kind(),
                        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                    ) => {}
                Err(_) => return Err(AuthorityTrustError::Unavailable),
            }
        }
        Ok(())
    }
}
