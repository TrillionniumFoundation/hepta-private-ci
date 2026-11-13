//! Root creates each product datagram in its own eventual service process.
//! The parent control socket transfers only original descriptors and never
//! carries a product bootstrap, authority decision or successful phase result.

use std::io;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::fd::RawFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::process::CommandExt;
use std::process::Command;
use std::time::Instant;

use crate::ordinary_q24_process_child_tests::OriginalChild;
use crate::ordinary_q24_process_child_tests::OriginalChildDescriptors;

const MAX_PAIRS: usize = 8;
const RIGHTS_FRAME: &[u8] = b"OQ_ROOT_PAIRS_1";

pub(super) fn spawn_with_original_pairs<T: Send>(
    command: &mut Command,
    root_slots: &[RawFd],
    own_pidfd_slot: RawFd,
    end: Instant,
    start_original_children: impl FnOnce(Vec<UnixDatagram>) -> anyhow::Result<(T, OwnedFd)> + Send,
) -> anyhow::Result<(OriginalChild, T)> {
    anyhow::ensure!(
        !root_slots.is_empty() && root_slots.len() <= MAX_PAIRS,
        "bounded original Root pairs required"
    );
    let mut slots = [-1; MAX_PAIRS];
    for (index, slot) in root_slots.iter().enumerate() {
        anyhow::ensure!(
            *slot >= 3 && *slot != own_pidfd_slot && !slots[..index].contains(slot),
            "distinct reserved original Root descriptor required"
        );
        slots[index] = *slot;
    }
    let count = root_slots.len();
    let (parent, child) = UnixDatagram::pair()?;
    let control = child.as_raw_fd();
    let absolute_end = crate::root_independent_b_source_protocol::seal_original_end(end)?;
    // SAFETY: all child storage is fixed stack data, arranged before fork.
    // Only socketpair/dup2/close/sendmsg/recvmsg/poll/clock_gettime and integer
    // operations occur before exec. No allocator, lock, environment, parsing,
    // filesystem loader or Rust thread/runtime is used in the child closure.
    unsafe {
        command.pre_exec(move || child_original_pairs(control, slots, count, absolute_end));
    }
    let outcome = std::thread::scope(|scope| {
        let prepared = scope.spawn(move || -> anyhow::Result<T> {
            let result = (|| {
                let received = receive_rights(&parent, RIGHTS_FRAME, count, end)?;
                start_original_children(received.into_iter().map(UnixDatagram::from).collect())
            })();
            match result {
                Ok((value, owner)) => {
                    require_end(end)?;
                    send_rights(&parent, b"1", &[owner.as_raw_fd()])?;
                    Ok(value)
                }
                Err(error) => {
                    let _ = parent.send(b"0");
                    Err(error)
                }
            }
        });
        let root = OriginalChild::spawn(
            command,
            OriginalChildDescriptors {
                inherited: root_slots.to_vec(),
                own_pidfd_slot: Some(own_pidfd_slot),
            },
        );
        drop(child);
        let prepared = prepared
            .join()
            .map_err(|_| anyhow::anyhow!("original child preparation panicked"))?;
        Ok::<_, anyhow::Error>((root?, prepared?))
    })?;
    require_end(end)?;
    Ok(outcome)
}

fn require_end(end: Instant) -> io::Result<()> {
    if Instant::now() >= end {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "original launch deadline",
        ));
    }
    Ok(())
}

fn receive_rights(
    socket: &UnixDatagram,
    expected: &[u8],
    count: usize,
    end: Instant,
) -> anyhow::Result<Vec<OwnedFd>> {
    require_end(end)?;
    socket.set_read_timeout(Some(end.duration_since(Instant::now())))?;
    let mut bytes = [0; 64];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: initialized, aligned bounded storage lives through recvmsg.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: kernel writes only the bounded live buffers above.
    let size = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    anyhow::ensure!(size >= 0, "{}", io::Error::last_os_error());
    // SAFETY: parser takes ownership of every actual received descriptor.
    let (rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    anyhow::ensure!(
        valid
            && message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) == 0
            && size as usize == expected.len()
            && &bytes[..size as usize] == expected
            && rights.len() == count,
        "original Root descriptor packet differs"
    );
    require_end(end)?;
    Ok(rights)
}

fn send_rights(socket: &UnixDatagram, bytes: &[u8], rights: &[RawFd]) -> io::Result<()> {
    // SAFETY: the parent is not between fork and exec. This also uses only
    // fixed stack buffers; all supplied original descriptors remain owned.
    unsafe { send_raw(socket.as_raw_fd(), bytes, rights) }
}

unsafe fn send_raw(socket: RawFd, bytes: &[u8], rights: &[RawFd]) -> io::Result<()> {
    let mut control = [0_usize; 16];
    let mut vector = libc::iovec {
        iov_base: bytes.as_ptr().cast_mut().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: zero is the specified empty msghdr representation.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    // SAFETY: callers pass at most MAX_PAIRS descriptors, fitting control.
    message.msg_controllen = unsafe { libc::CMSG_SPACE(mem::size_of_val(rights) as u32) as usize };
    // SAFETY: control is aligned and sized for this exact single rights cmsg.
    unsafe {
        let header = libc::CMSG_FIRSTHDR(&message);
        (*header).cmsg_level = libc::SOL_SOCKET;
        (*header).cmsg_type = libc::SCM_RIGHTS;
        (*header).cmsg_len = libc::CMSG_LEN(mem::size_of_val(rights) as u32) as usize;
        std::ptr::copy_nonoverlapping(
            rights.as_ptr(),
            libc::CMSG_DATA(header).cast(),
            rights.len(),
        );
        if libc::sendmsg(socket, &message, libc::MSG_NOSIGNAL | libc::MSG_DONTWAIT)
            != bytes.len() as isize
        {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}

// This entire function runs between fork and exec. Keep every error as an
// allocation-free OS error; do not add formatted diagnostics here.
fn child_original_pairs(
    control: RawFd,
    slots: [RawFd; MAX_PAIRS],
    count: usize,
    end: u64,
) -> io::Result<()> {
    let mut receivers = [-1; MAX_PAIRS];
    for index in 0..count {
        let mut pair = [-1; 2];
        // SAFETY: two stack integers receive the newly created original pair.
        unsafe {
            if libc::socketpair(
                libc::AF_UNIX,
                libc::SOCK_DGRAM | libc::SOCK_CLOEXEC,
                0,
                pair.as_mut_ptr(),
            ) != 0
            {
                return Err(io::Error::last_os_error());
            }
            if libc::dup2(pair[0], slots[index]) < 0 {
                return Err(io::Error::last_os_error());
            }
            libc::close(pair[0]);
        }
        receivers[index] = pair[1];
    }
    // SAFETY: each receiver is the original peer endpoint created above.
    unsafe {
        send_raw(control, RIGHTS_FRAME, &receivers[..count])?;
    }
    for receiver in &receivers[..count] {
        // SAFETY: this child closes only its copies after successful transfer.
        unsafe {
            libc::close(*receiver);
        }
    }
    child_poll(control, end)?;
    let mut bytes = [0_u8; 1];
    let mut ancillary = [0_usize; 8];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: fixed stack storage remains live through this one recvmsg.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = ancillary.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&ancillary);
    // SAFETY: one actual daemon pidfd is received and duped to stdin for the
    // production --owner-pidfd-stdin entry. No PID is serialized into a pin.
    unsafe {
        let size = libc::recvmsg(
            control,
            &mut message,
            libc::MSG_CMSG_CLOEXEC | libc::MSG_DONTWAIT,
        );
        if size != 1
            || bytes[0] != b'1'
            || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        {
            return Err(io::Error::from_raw_os_error(libc::ECANCELED));
        }
        let header = libc::CMSG_FIRSTHDR(&message);
        if header.is_null()
            || (*header).cmsg_level != libc::SOL_SOCKET
            || (*header).cmsg_type != libc::SCM_RIGHTS
            || (*header).cmsg_len != libc::CMSG_LEN(mem::size_of::<RawFd>() as u32) as usize
            || !libc::CMSG_NXTHDR(&message, header).is_null()
        {
            return Err(io::Error::from_raw_os_error(libc::EPROTO));
        }
        let owner = std::ptr::read_unaligned(libc::CMSG_DATA(header).cast::<RawFd>());
        if libc::dup2(owner, libc::STDIN_FILENO) < 0 {
            return Err(io::Error::last_os_error());
        }
        libc::close(owner);
        libc::close(control);
    }
    child_remaining(end)?;
    Ok(())
}

fn child_remaining(end: u64) -> io::Result<i32> {
    let mut now = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    // SAFETY: the kernel writes one initialized live timespec.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut now) } != 0 {
        return Err(io::Error::last_os_error());
    }
    if now.tv_sec < 0 || now.tv_nsec < 0 || now.tv_nsec >= 1_000_000_000 {
        return Err(io::Error::from_raw_os_error(libc::EINVAL));
    }
    let now = (now.tv_sec as u64)
        .saturating_mul(1_000_000_000)
        .saturating_add(now.tv_nsec as u64);
    if now >= end || end - now > 300_000_000_000 {
        return Err(io::Error::from_raw_os_error(libc::ETIMEDOUT));
    }
    Ok(((end - now).div_ceil(1_000_000)) as i32)
}

fn child_poll(fd: RawFd, end: u64) -> io::Result<()> {
    loop {
        let mut poll = libc::pollfd {
            fd,
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: poll observes the one actual control descriptor in place.
        let ready = unsafe { libc::poll(&mut poll, 1, child_remaining(end)?) };
        if ready > 0 && poll.revents & libc::POLLIN != 0 {
            return Ok(());
        }
        if ready < 0 && io::Error::last_os_error().raw_os_error() == Some(libc::EINTR) {
            continue;
        }
        return Err(io::Error::from_raw_os_error(libc::ETIMEDOUT));
    }
}

#[test]
fn ordinary_root_child_pair_preserves_the_actual_creator_through_exec() -> anyhow::Result<()> {
    let end = Instant::now() + std::time::Duration::from_secs(5);
    let slot = tempfile::tempfile()?;
    let own = tempfile::tempfile()?;
    let mut command = Command::new("/bin/sleep");
    command.arg("0.2");
    let (root, (owner, pair)) = spawn_with_original_pairs(
        &mut command,
        &[slot.as_raw_fd()],
        own.as_raw_fd(),
        end,
        |mut pairs| {
            let pair = pairs
                .pop()
                .ok_or_else(|| anyhow::anyhow!("actual peer absent"))?;
            let owner = OriginalChild::spawn(
                Command::new("/bin/sleep").arg("0.2"),
                OriginalChildDescriptors::default(),
            )?;
            let pin = owner.original_pidfd()?;
            Ok(((owner, pair), pin))
        },
    )?;
    let mut peer = libc::ucred {
        pid: 0,
        uid: u32::MAX,
        gid: u32::MAX,
    };
    let mut size = mem::size_of_val(&peer) as libc::socklen_t;
    // SAFETY: getsockopt observes the original kernel creator of this pair.
    anyhow::ensure!(
        unsafe {
            libc::getsockopt(
                pair.as_raw_fd(),
                libc::SOL_SOCKET,
                libc::SO_PEERCRED,
                (&mut peer as *mut libc::ucred).cast(),
                &mut size,
            )
        } == 0,
        "{}",
        io::Error::last_os_error()
    );
    pretty_assertions::assert_eq!(peer.pid as u32, root.lifetime().pid);
    anyhow::ensure!(
        peer.pid as u32 != std::process::id(),
        "parent did not create product pair"
    );
    root.wait_success_until(end)?.require_dead()?;
    owner.wait_success_until(end)?.require_dead()
}

#[test]
fn ordinary_root_child_pair_refuses_failed_original_owner_preparation() -> anyhow::Result<()> {
    let end = Instant::now() + std::time::Duration::from_secs(5);
    let slot = tempfile::tempfile()?;
    let own = tempfile::tempfile()?;
    let result = spawn_with_original_pairs::<()>(
        Command::new("/bin/sleep").arg("1"),
        &[slot.as_raw_fd()],
        own.as_raw_fd(),
        end,
        |_| anyhow::bail!("original child setup refused"),
    );
    assert!(result.is_err());
    Ok(())
}
