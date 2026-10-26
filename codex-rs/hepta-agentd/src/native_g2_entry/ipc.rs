//! Bounded admission to the exact original process-bound channels.
use super::paths;
use super::supervisor;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

pub(super) fn listener(path: &Path, gid: u32) -> io::Result<UnixListener> {
    let listener = UnixListener::bind(path)?;
    paths::owner_socket(path, gid)?;
    listener.set_nonblocking(true)?;
    Ok(listener)
}

pub(super) fn accept(listener: &UnixListener, pid: u32) -> io::Result<UnixStream> {
    let end = Instant::now() + Duration::from_secs(2);
    loop {
        match listener.accept() {
            Ok((stream, _)) => {
                // SAFETY: getsockopt initializes this exact bounded Linux
                // peer credential record from the retained accepted socket.
                let mut peer: libc::ucred = unsafe { std::mem::zeroed() };
                let mut size = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
                if unsafe {
                    libc::getsockopt(
                        stream.as_raw_fd(),
                        libc::SOL_SOCKET,
                        libc::SO_PEERCRED,
                        (&mut peer as *mut libc::ucred).cast(),
                        &mut size,
                    )
                } != 0
                {
                    return Err(io::Error::last_os_error());
                }
                if size as usize != std::mem::size_of::<libc::ucred>() || peer.pid as u32 != pid {
                    return Err(io::Error::other(
                        "unexpected actual native process connection",
                    ));
                }
                return Ok(stream);
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock && Instant::now() < end => {
                std::thread::sleep(Duration::from_millis(2))
            }
            Err(error) => return Err(error),
        }
    }
}

pub(super) fn channel(
    listener: &UnixListener,
    pid: u32,
    uid: u32,
) -> Result<HostAuthorityPeerChannel, Box<dyn std::error::Error>> {
    Ok(HostAuthorityPeerChannel::from_stream(
        accept(listener, pid)?,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer { uid, pid },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(120),
            request_bound: 32768,
            response_bound: 32768,
        },
        supervisor::pin(pid)?,
    )?)
}

/// Wait for the original parent to SELECT this future pre-created child, or
/// prepare its sealed late descriptor. The original handoff's 200/500 ms
/// exchange still starts only once a packet exists; no owner API deadline is
/// extended. The actual Root pidfd must stay live throughout this finite wait.
pub(super) fn wait_selected(descriptor: &impl AsRawFd) -> io::Result<()> {
    let root = supervisor::pin(1)?;
    let end = Instant::now() + Duration::from_secs(110);
    loop {
        let mut fds = [
            libc::pollfd {
                fd: descriptor.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            },
            libc::pollfd {
                fd: root.as_raw_fd(),
                events: libc::POLLIN,
                revents: 0,
            },
        ];
        // SAFETY: poll receives the exact two retained live descriptors and a
        // short finite timeout; it cannot transfer or grant their authority.
        let count = unsafe { libc::poll(fds.as_mut_ptr(), 2, 100) };
        if count < 0 {
            return Err(io::Error::last_os_error());
        }
        if fds[1].revents != 0 || fds[0].revents & !libc::POLLIN != 0 {
            return Err(io::Error::other(
                "original Root lifetime/channel ended before selection",
            ));
        }
        if fds[0].revents == libc::POLLIN {
            return Ok(());
        }
        if Instant::now() >= end {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "future native role was not selected",
            ));
        }
    }
}
