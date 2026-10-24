//! Linux descriptor primitives for the single trusted-launch framing owner.

use super::root_notes_launch_wire::invalid;
use std::io;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;

pub(crate) fn require_connected_unix_datagram(descriptor: &OwnedFd) -> io::Result<()> {
    let mut kind: libc::c_int = 0;
    let mut kind_len = mem::size_of_val(&kind) as libc::socklen_t;
    // SAFETY: both output pointers are initialized and bounded for getsockopt.
    if unsafe { libc::getsockopt(descriptor.as_raw_fd(), libc::SOL_SOCKET, libc::SO_TYPE,
        (&mut kind as *mut libc::c_int).cast(), &mut kind_len) } < 0 {
        return Err(io::Error::last_os_error());
    }
    if kind != libc::SOCK_DGRAM || kind_len as usize != mem::size_of_val(&kind) {
        return Err(invalid());
    }
    // SAFETY: zeroed sockaddr_storage is valid writable syscall output.
    let mut address: libc::sockaddr_storage = unsafe { mem::zeroed() };
    let mut address_len = mem::size_of_val(&address) as libc::socklen_t;
    // SAFETY: the socket and full initialized output buffer remain live.
    if unsafe { libc::getpeername(descriptor.as_raw_fd(),
        (&mut address as *mut libc::sockaddr_storage).cast(), &mut address_len) } < 0 {
        return Err(io::Error::last_os_error());
    }
    if address.ss_family != libc::AF_UNIX as libc::sa_family_t {
        return Err(invalid());
    }
    Ok(())
}

pub(super) fn receive(stream: &UnixStream, bytes: &mut [u8]) -> io::Result<(usize, Vec<OwnedFd>)> {
    let mut control = [0usize; 16];
    let mut iov = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: all-zero msghdr has null optional pointers; each used pointer
    // below refers to an aligned, live buffer for this synchronous syscall.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut iov;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: buffers are writable for their declared bounds. CLOEXEC is set
    // atomically on every delivered descriptor, before any Rust ownership.
    let count = unsafe {
        libc::recvmsg(
            stream.as_raw_fd(),
            &mut message,
            libc::MSG_DONTWAIT | libc::MSG_CMSG_CLOEXEC,
        )
    };
    if count < 0 {
        return Err(io::Error::last_os_error());
    }
    let mut descriptors = Vec::new();
    let mut rejected = message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0;
    // SAFETY: recvmsg populated this kernel-validated, aligned ancillary buffer.
    // CMSG_NXTHDR remains within msg_controllen. Own all received rights before
    // returning any error so truncation/extra-rights paths cannot leak them.
    unsafe {
        let mut header = libc::CMSG_FIRSTHDR(&message);
        while !header.is_null() {
            let length = (*header).cmsg_len;
            let minimum = libc::CMSG_LEN(0) as usize;
            let offset = header as usize - control.as_ptr() as usize;
            if length < minimum || length > message.msg_controllen.saturating_sub(offset) {
                rejected = true;
                break;
            }
            if (*header).cmsg_level == libc::SOL_SOCKET && (*header).cmsg_type == libc::SCM_RIGHTS {
                let data_length = length - minimum;
                if !data_length.is_multiple_of(mem::size_of::<libc::c_int>()) {
                    rejected = true;
                }
                for index in 0..data_length / mem::size_of::<libc::c_int>() {
                    let fd = libc::CMSG_DATA(header)
                        .cast::<libc::c_int>()
                        .add(index)
                        .read_unaligned();
                    descriptors.push(OwnedFd::from_raw_fd(fd));
                }
            } else {
                rejected = true;
            }
            header = libc::CMSG_NXTHDR(&message, header);
        }
    }
    if rejected || count == 0 || descriptors.len() > 2 {
        return Err(invalid());
    }
    Ok((count as usize, descriptors))
}

pub(super) fn send(
    stream: &UnixStream,
    bytes: &[u8],
    descriptors: &[OwnedFd],
) -> io::Result<usize> {
    if descriptors.len() > 2 {
        return Err(invalid());
    }
    let mut control = [0usize; 16];
    let mut iov = libc::iovec {
        iov_base: bytes.as_ptr().cast_mut().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: zeroed optional fields are valid and all pointers below remain
    // live for the nonblocking syscall. sendmsg never mutates the input bytes.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut iov;
    message.msg_iovlen = 1;
    if !descriptors.is_empty() {
        let data_length = (descriptors.len() * mem::size_of::<libc::c_int>()) as u32;
        // SAFETY: aligned buffer exceeds CMSG_SPACE(two ints); only initialized
        // header/data bytes are passed, and every source fd stays borrowed.
        unsafe {
            message.msg_control = control.as_mut_ptr().cast();
            message.msg_controllen = libc::CMSG_SPACE(data_length) as usize;
            let header = libc::CMSG_FIRSTHDR(&message);
            (*header).cmsg_level = libc::SOL_SOCKET;
            (*header).cmsg_type = libc::SCM_RIGHTS;
            (*header).cmsg_len = libc::CMSG_LEN(data_length) as usize;
            for (index, descriptor) in descriptors.iter().enumerate() {
                libc::CMSG_DATA(header)
                    .cast::<libc::c_int>()
                    .add(index)
                    .write_unaligned(descriptor.as_raw_fd());
            }
        }
    }
    // SAFETY: valid msghdr and borrowed fd; no blocking or SIGPIPE delivery.
    let count = unsafe {
        libc::sendmsg(
            stream.as_raw_fd(),
            &message,
            libc::MSG_DONTWAIT | libc::MSG_NOSIGNAL,
        )
    };
    if count < 0 {
        return Err(io::Error::last_os_error());
    }
    if count == 0 {
        return Err(invalid());
    }
    Ok(count as usize)
}

pub(super) fn poll(
    peer: &OwnedFd,
    stream: &UnixStream,
    events: i16,
    timeout_ms: i32,
) -> io::Result<bool> {
    let mut fds = [
        libc::pollfd {
            fd: peer.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        },
        libc::pollfd {
            fd: stream.as_raw_fd(),
            events,
            revents: 0,
        },
    ];
    // SAFETY: two initialized pollfd entries, owned descriptors remain live.
    if unsafe { libc::poll(fds.as_mut_ptr(), fds.len() as libc::nfds_t, timeout_ms) } < 0 {
        return Err(io::Error::last_os_error());
    }
    if fds[0].revents != 0 || fds[1].revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
        return Err(invalid());
    }
    Ok(fds[1].revents & (events | libc::POLLHUP) != 0)
}
