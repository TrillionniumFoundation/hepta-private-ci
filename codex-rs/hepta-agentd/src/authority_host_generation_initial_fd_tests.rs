//! Test-only transfer of original target files. These rights are material,
//! not the Root purpose or any permission to publish. Root consumes its writer
//! handles; the child must still use the original sealed production route.

use super::*;
use std::mem;

const FRAME: &[u8] = b"HEPTA_INITIAL_COMPONENT_ORIGINAL_TARGET_V1";

pub(super) fn send_target_files(
    socket: &UnixDatagram,
    journal: File,
    witness: File,
) -> anyhow::Result<()> {
    socket.set_write_timeout(Some(LIFETIME))?;
    let rights = [journal.as_raw_fd(), witness.as_raw_fd()];
    let mut vector = libc::iovec {
        iov_base: FRAME.as_ptr().cast_mut().cast(), iov_len: FRAME.len(),
    };
    let mut control = [0_usize; 32];
    // SAFETY: all aligned buffers are retained until this bounded send ends.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    // SAFETY: two fixed descriptors fit the aligned stack control buffer.
    message.msg_controllen = unsafe { libc::CMSG_SPACE(mem::size_of_val(&rights) as _) } as _;
    // SAFETY: initialized msghdr, bounded header and descriptor array.
    unsafe {
        let header = libc::CMSG_FIRSTHDR(&message);
        anyhow::ensure!(!header.is_null(), "component rights header");
        (*header).cmsg_level = libc::SOL_SOCKET;
        (*header).cmsg_type = libc::SCM_RIGHTS;
        (*header).cmsg_len = libc::CMSG_LEN(mem::size_of_val(&rights) as _) as _;
        std::ptr::copy_nonoverlapping(rights.as_ptr().cast::<u8>(),
            libc::CMSG_DATA(header), mem::size_of_val(&rights));
        let sent = libc::sendmsg(socket.as_raw_fd(), &message, libc::MSG_NOSIGNAL);
        anyhow::ensure!(sent == FRAME.len() as _, "{}", io::Error::last_os_error());
    }
    drop((journal, witness));
    Ok(())
}

pub(super) fn receive_target_files(socket: &UnixDatagram) -> anyhow::Result<(File, File)> {
    socket.set_read_timeout(Some(LIFETIME))?;
    let mut bytes = [0_u8; FRAME.len() + 1];
    let mut vector = libc::iovec {
        iov_base: bytes.as_mut_ptr().cast(), iov_len: bytes.len(),
    };
    let mut control = [0_usize; 32];
    // SAFETY: bounded aligned buffers and original inherited pair.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: atomically closes rights on exec and bounds all receive buffers.
    let received = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    anyhow::ensure!(received >= 0, "{}", io::Error::last_os_error());
    // SAFETY: existing owner parser takes every returned descriptor.
    let (mut rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    anyhow::ensure!(valid && message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) == 0
        && received as usize == FRAME.len() && &bytes[..FRAME.len()] == FRAME
        && rights.len() == 2, "exact original target rights");
    let witness = File::from(rights.pop().ok_or_else(|| anyhow::anyhow!("original witness"))?);
    let journal = File::from(rights.pop().ok_or_else(|| anyhow::anyhow!("original journal"))?);
    Ok((journal, witness))
}
