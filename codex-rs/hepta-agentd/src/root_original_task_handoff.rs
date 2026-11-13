//! Separate two-right purpose for the actual Root task service. The inherited
//! pair authenticates only the Root creator; the daemon opens both task streams
//! after credential drop and each original channel verifies SO_PEERCRED/pidfd.

use super::*;
use std::time::Instant;
use std::os::unix::net::UnixStream;
use codex_hepta_contracts::HostIssuerPeer;
use crate::root_original_task_descriptor::{Descriptor, require_before};

const TASK_FRAME: &[u8] = b"HEPTA_ROOT_ORIGINAL_TASK_HANDOFF_V1";

/// Consumed once by the ordinary launcher. There is no public descriptor,
/// raw-FD, Clone or deserialization path for manufacturing this offer.
pub struct RootOriginalTaskHandoffV1 {
    descriptor: Descriptor,
    root_pidfd: OwnedFd,
}

pub fn receive_root_original_task_handoff(
    socket: UnixDatagram, timeout: Duration,
) -> Result<RootOriginalTaskHandoffV1, AgentdError> {
    if rustix::process::getuid().as_raw() == 0 || rustix::process::geteuid().as_raw() == 0 {
        return Err(refused("original task receiver must already have dropped credentials"));
    }
    let root = root_pair(&socket, timeout)?;
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; TASK_FRAME.len() + 1];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec { iov_base: bytes.as_mut_ptr().cast(), iov_len: bytes.len() };
    // SAFETY: initialized below with bounded, live, aligned buffers.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg writes only the live buffers and gives rights CLOEXEC.
    let length = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if length < 0 { return Err(io::Error::last_os_error().into()); }
    // SAFETY: the same original parser owns every received descriptor.
    let (mut rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || rights.len() != 2 || length as usize != TASK_FRAME.len() || &bytes[..TASK_FRAME.len()] != TASK_FRAME
    { return Err(refused("exact original task marker and two ordered rights required")); }
    let root_pidfd = rights.pop().ok_or_else(|| refused("original Root pidfd missing"))?;
    let file = File::from(rights.pop().ok_or_else(|| refused("original task offer missing"))?);
    require_root_pin(&root_pidfd, root.pid as u32)?;
    let descriptor = crate::root_original_task_descriptor::read(&file, root.pid as u32)?;
    require_root_pin(&root_pidfd, root.pid as u32)?;
    require_before(descriptor.end)?;
    Ok(RootOriginalTaskHandoffV1 { descriptor, root_pidfd })
}

pub(crate) fn send_original_task_handoff(
    socket: UnixDatagram, descriptor: &File, root_pidfd: &OwnedFd, timeout: Duration,
) -> Result<(), AgentdError> {
    if rustix::process::getuid().as_raw() != 0 || rustix::process::geteuid().as_raw() != 0 {
        return Err(refused("actual Root task sender required"));
    }
    let root = root_pair(&socket, timeout)?;
    if root.pid as u32 != std::process::id() {
        return Err(refused("original task pair must belong to this same Root"));
    }
    validate_bootstrap(descriptor)?;
    require_root_pin(root_pidfd, std::process::id())?;
    send_packet(&socket, TASK_FRAME, &[descriptor.as_raw_fd(), root_pidfd.as_raw_fd()], timeout)
}

impl RootOriginalTaskHandoffV1 {
    pub(crate) async fn install(self, config: crate::AgentdConfig,
        original_root: &crate::AgentdRootProductionInputs) -> Result<crate::AgentdConfig, AgentdError>
    {
        let Self { descriptor, root_pidfd } = self;
        Descriptor::require_original_identity(&descriptor, config.identity())?;
        if original_root.bootstrap.root.pid != descriptor.root_pid
            || original_root.bootstrap.root.uid != 0
        { return Err(refused("task and writer handoffs must pin the same original Root")); }
        require_root_pin(&root_pidfd, descriptor.root_pid)?;
        crate::authority_host_runtime::validate_lane_paths(
            &[&descriptor.task_path, &descriptor.loan_path], descriptor.daemon_gid)?;
        let task_stream = connect(&descriptor.task_path, descriptor.end).await?;
        let loan_stream = connect(&descriptor.loan_path, descriptor.end).await?;
        Descriptor::require_original_identity(&descriptor, config.identity())?;
        require_root_pin(&root_pidfd, descriptor.root_pid)?;
        let lifetime = descriptor.end.checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero()).ok_or_else(|| refused("original task expired"))?;
        let inputs = crate::OriginalRootCircuitTaskDaemonInputsV1 {
            fence: descriptor.fence, registry: descriptor.registry, source: descriptor.source,
            task_stream, loan_stream,
            original_root: HostIssuerPeer { uid: 0, pid: descriptor.root_pid },
            original_root_task_pidfd: root_pidfd.try_clone()?, original_root_loan_pidfd: root_pidfd,
            session_nonce: descriptor.nonce, lifetime, queue_capacity: descriptor.capacity,
        };
        config.with_original_root_circuit_task_until(inputs, descriptor.end)
    }
}

async fn connect(path: &Path, end: Instant) -> Result<UnixStream, AgentdError> {
    require_before(end)?;
    let deadline = (Instant::now() + Duration::from_millis(500)).min(end);
    let stream = tokio::time::timeout_at(deadline.into(), tokio::net::UnixStream::connect(path))
        .await.map_err(|_| refused("original task connect deadline elapsed"))??;
    require_before(deadline)?;
    let stream = stream.into_std()?;
    stream.set_nonblocking(false)?;
    require_before(deadline)?;
    Ok(stream)
}
