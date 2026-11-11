//! Consume the real Session's first staged message on Root's inherited pair.
//! The original two effect/recovery descriptors remain in Session until Agentd
//! activates the exact reservation after its original owner has recovered.

use std::fs::File;
use std::io;
use std::io::Read;
use std::mem;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_memory::NotesTargetIdentity;
use serde::Deserialize;
use serde::Serialize;

const RESERVED_BOUND: usize = 1024;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StartupRelease {
    pub(super) target: NotesTargetIdentity,
    pub(super) nonce: String,
}

#[derive(Serialize)]
pub(super) struct SessionBirth {
    uid: u32,
    pid: u32,
    boot_id: String,
    process_start_ticks: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Reserved {
    schema_version: u16,
    action: Action,
    target: NotesTargetIdentity,
    destination_id: String,
    nonce: String,
}

#[derive(Deserialize)]
enum Action {
    #[serde(rename = "notes_target_reserved")]
    NotesTargetReserved,
}

pub(super) fn receive(
    socket: UnixDatagram,
    pidfd: &OwnedFd,
    uid: u32,
    gid: u32,
    end: Instant,
) -> io::Result<(StartupRelease, SessionBirth)> {
    let timeout = remaining(end)?;
    // SO_PEERCRED identifies the trusted pair creator; SCM_CREDENTIALS below
    // identifies the actual Session that sent this particular reservation.
    let creator =
        crate::root_production_handoff::root_pair(&socket, timeout).map_err(io::Error::other)?;
    // SAFETY: geteuid reads this process's actual credential.
    if unsafe { libc::geteuid() } != 0
        || creator.pid as u32 != std::process::id()
        || uid == 0
        || gid == 0
    {
        return Err(io::Error::other(
            "Notes reservation requires its same actual Root creator",
        ));
    }
    let descriptor = pidfd.as_raw_fd();
    if std::fs::read_link(format!("/proc/self/fd/{descriptor}"))? != Path::new("anon_inode:[pidfd]")
    {
        return Err(io::Error::other(
            "Notes reservation requires the retained actual Session pidfd",
        ));
    }
    let info = bounded_text(&format!("/proc/self/fdinfo/{descriptor}"), 4096)?;
    let pid = info
        .lines()
        .find_map(|line| line.strip_prefix("Pid:")?.trim().parse::<u32>().ok())
        .filter(|pid| *pid > 0 && *pid <= i32::MAX as u32)
        .ok_or_else(|| io::Error::other("Notes Session pidfd no longer names a live process"))?;
    crate::authority_host_runtime::owner_alive(pidfd, end)?;
    crate::authority_host_runtime::verify_process_credentials(pid, uid, gid)?;
    let boot_id = bounded_text("/proc/sys/kernel/random/boot_id", 128)?
        .trim()
        .to_owned();
    let stat = bounded_text(&format!("/proc/{pid}/stat"), 8192)?;
    let process_start_ticks = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("Notes Session birth is unavailable"))?;
    socket.set_nonblocking(false)?;
    let release = receive_packet_before(
        &socket,
        libc::ucred {
            pid: pid as i32,
            uid,
            gid,
        },
        end,
    )?;
    crate::authority_host_runtime::owner_alive(pidfd, end)?;
    crate::authority_host_runtime::verify_process_credentials(pid, uid, gid)?;
    // Agentd already holds a duplicate of this same endpoint. Remove the
    // metadata credential option before it uses the original two-right parser.
    set_passcred(&socket, 0)?;
    Ok((
        release,
        SessionBirth {
            uid,
            pid,
            boot_id,
            process_start_ticks,
        },
    ))
}

pub(super) fn remaining(end: Instant) -> io::Result<Duration> {
    let remaining = end
        .checked_duration_since(Instant::now())
        .filter(|duration| !duration.is_zero() && *duration <= Duration::from_secs(30))
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::TimedOut,
                "original Notes startup episode elapsed or exceeds 30 seconds",
            )
        })?;
    Ok(remaining)
}

fn receive_packet_before(
    socket: &UnixDatagram,
    expected: libc::ucred,
    end: Instant,
) -> io::Result<StartupRelease> {
    socket.set_read_timeout(Some(remaining(end)?))?;
    let release = receive_packet(socket, expected)?;
    remaining(end)?;
    Ok(release)
}

fn receive_packet(socket: &UnixDatagram, expected: libc::ucred) -> io::Result<StartupRelease> {
    let mut enabled: libc::c_int = 0;
    let mut length = mem::size_of_val(&enabled) as libc::socklen_t;
    // SAFETY: the live socket and correctly sized initialized option buffer are
    // retained. Root must enable this before Session is allowed to send.
    if unsafe {
        libc::getsockopt(
            socket.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PASSCRED,
            std::ptr::from_mut(&mut enabled).cast(),
            &mut length,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    if length as usize != mem::size_of_val(&enabled) || enabled != 1 {
        return Err(io::Error::other(
            "Root must enable SO_PASSCRED before Session startup",
        ));
    }
    let mut bytes = [0_u8; RESERVED_BOUND + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(),
        iov_len: bytes.len(),
    };
    // SAFETY: all message pointers below reference live bounded aligned buffers.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg borrows the exact live buffers and gives any received
    // descriptors CLOEXEC, including descriptors on a rejected message.
    let count = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if count < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: adopt all rights with the existing parser for unconditional close
    // on refusal. Its boolean rejects credentials by design; this message has
    // a different strict contract and validates its sole credential below.
    let (rights, _) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !rights.is_empty()
        || count == 0
        || count as usize > RESERVED_BOUND
        || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
    {
        return Err(io::Error::other(
            "Notes Reserved must contain bounded metadata without rights",
        ));
    }
    // SAFETY: recvmsg initialized this bounded ancillary chain; only a complete
    // single ucred message is accepted before reading its payload.
    let header = unsafe { libc::CMSG_FIRSTHDR(&message) };
    if header.is_null() {
        return Err(io::Error::other("actual Session sender credential missing"));
    }
    let credential = unsafe {
        if (*header).cmsg_level != libc::SOL_SOCKET
            || (*header).cmsg_type != libc::SCM_CREDENTIALS
            || (*header).cmsg_len != libc::CMSG_LEN(mem::size_of::<libc::ucred>() as u32) as usize
            || (*header).cmsg_len > message.msg_controllen
            || !libc::CMSG_NXTHDR(&message, header).is_null()
        {
            return Err(io::Error::other(
                "Notes Reserved requires one exact kernel credential",
            ));
        }
        libc::CMSG_DATA(header)
            .cast::<libc::ucred>()
            .read_unaligned()
    };
    if credential.pid != expected.pid
        || credential.uid != expected.uid
        || credential.gid != expected.gid
    {
        return Err(io::Error::other(
            "Notes Reserved sender differs from the held actual Session",
        ));
    }
    let value: Reserved =
        serde_json::from_slice(&bytes[..count as usize]).map_err(io::Error::other)?;
    value.target.validate().map_err(io::Error::other)?;
    if value.schema_version != 1
        || !matches!(value.action, Action::NotesTargetReserved)
        || value.target.task_id != 1
        || value.destination_id != value.target.destination_id()
        || value.nonce.len() != 32
        || !value
            .nonce
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        || value.nonce.bytes().all(|byte| byte == b'0')
    {
        return Err(io::Error::other(
            "Notes Reserved target or one-time nonce differs",
        ));
    }
    Ok(StartupRelease {
        target: value.target,
        nonce: value.nonce,
    })
}

fn set_passcred(socket: &UnixDatagram, enabled: libc::c_int) -> io::Result<()> {
    // SAFETY: setsockopt borrows one integer and the live private socket only.
    if unsafe {
        libc::setsockopt(
            socket.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PASSCRED,
            std::ptr::from_ref(&enabled).cast(),
            mem::size_of_val(&enabled) as libc::socklen_t,
        )
    } != 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn bounded_text(path: &str, bound: u64) -> io::Result<String> {
    let mut text = String::new();
    File::open(path)?
        .take(bound + 1)
        .read_to_string(&mut text)?;
    if text.len() as u64 > bound {
        return Err(io::Error::other("Notes Session metadata exceeds bound"));
    }
    Ok(text)
}

#[cfg(test)]
#[path = "root_notes_reservation_tests.rs"]
mod tests;
