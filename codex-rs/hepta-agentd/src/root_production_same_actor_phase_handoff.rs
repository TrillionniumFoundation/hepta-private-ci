//! One original Root phase purpose. All descriptors retain their actual
//! original custody; no pathname, public JSON, or fresh writer is substituted.
//! The new packets are separate from every default V1 handoff.

use super::*;
use std::sync::Arc;
use std::time::Instant;

use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

const START_FRAME: &[u8] = b"HEPTA_ROOT_SAME_ACTOR_PHASE_START_V1";
const SCOPED_FRAME: &[u8] = b"HEPTA_ROOT_SAME_ACTOR_PHASE_SCOPED_V1";

pub struct RootSameActorPhaseOfferV1 {
    pub(crate) bootstrap: File,
    pub(crate) gate: Arc<SameActorPhaseGate>,
    pub(crate) closing: CloseSameActorPhaseOnDrop,
}

pub(crate) struct RootSameActorScopedOfferV1 {
    pub(crate) bootstrap: File,
    pub(crate) learning: File,
    pub(crate) model: crate::RootQ24ModelFactoryOfferV1,
    pub(crate) publication: crate::RootGenerationPublicationOfferV1,
}

pub(crate) struct OriginalSameActorPhaseHandoff {
    pub(crate) bootstrap: File,
    pub(crate) root_pidfd: OwnedFd,
    pub(crate) root_pid: u32,
    pub(crate) initial: RootGenerationInitialHandoffV1,
}

pub(crate) struct OriginalSameActorScopedHandoff {
    pub(crate) bootstrap: File,
    pub(crate) root_pid: u32,
    pub(crate) learning: RootLearningHandoffV1,
    pub(crate) model: RootQ24ModelFactoryHandoffV1,
    pub(crate) publication: RootGenerationPublicationHandoffV1,
}

/// Consume the two original sealed offers on one Root-created pair. This
/// only delivers phase and Initial routing; the original five-lane bootstrap
/// and actual writer handoff remain separately authenticated originals.
pub fn send_root_same_actor_phase_handoff(
    socket: UnixDatagram,
    offer: RootSameActorPhaseOfferV1,
    initial: crate::RootGenerationInitialOfferV1,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    let RootSameActorPhaseOfferV1 { bootstrap, gate, mut closing } = offer;
    let budget = bounded_timeout(timeout, gate.deadline().instant())?;
    gate.require_open()?;
    let _stop = gate.retain_original_datagram(&socket)?;
    require_original_sender(&socket, root_pidfd, budget)?;
    validate_bootstrap(&bootstrap)?;
    validate_bootstrap(&initial.bootstrap)?;
    send_packet(
        &socket, START_FRAME,
        &[bootstrap.as_raw_fd(), root_pidfd.as_raw_fd(), initial.bootstrap.as_raw_fd()],
        bounded_timeout(timeout, gate.deadline().instant())?,
    )?;
    gate.require_open()?;
    closing.disarm();
    Ok(())
}

/// The same original Root retains the publication enrollment capability. The
/// actual Model writable rights move once in this packet, including on error.
pub fn send_root_same_actor_scoped_handoff(
    socket: UnixDatagram,
    enrolled: crate::RootSameActorScopedEnrollmentV1,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<crate::RootSameActorPublicationEnrollmentCapabilityV1, AgentdError> {
    let crate::RootSameActorScopedEnrollmentV1 {
        offer, publication, gate, mut closing,
    } = enrolled;
    gate.require_open()?;
    let _stop = gate.retain_original_datagram(&socket)?;
    require_original_sender(
        &socket, root_pidfd, bounded_timeout(timeout, gate.deadline().instant())?,
    )?;
    validate_bootstrap(&offer.bootstrap)?;
    validate_bootstrap(&offer.learning)?;
    validate_bootstrap(&offer.model.bootstrap)?;
    validate_bootstrap(&offer.publication.bootstrap)?;
    send_packet(
        &socket, SCOPED_FRAME,
        &[
            offer.bootstrap.as_raw_fd(), root_pidfd.as_raw_fd(),
            offer.learning.as_raw_fd(), offer.model.bootstrap.as_raw_fd(),
            offer.model.journal.as_raw_fd(), offer.model.witness.as_raw_fd(),
            offer.publication.bootstrap.as_raw_fd(),
        ],
        bounded_timeout(timeout, gate.deadline().instant())?,
    )?;
    gate.require_open()?;
    closing.disarm();
    Ok(publication)
}

pub(crate) fn receive_original_phase_start(
    socket: UnixDatagram,
    timeout: Duration,
    original_receiver_end: Instant,
) -> Result<OriginalSameActorPhaseHandoff, AgentdError> {
    let peer = root_pair(&socket, bounded_timeout(timeout, original_receiver_end)?)?;
    let mut rights = receive_phase_packet(
        &socket, START_FRAME, 3, bounded_timeout(timeout, original_receiver_end)?,
    )?;
    let initial = File::from(rights.pop().ok_or_else(|| refused("phase Initial offer missing"))?);
    let root_pidfd = rights.pop().ok_or_else(|| refused("phase Root pin missing"))?;
    let bootstrap = File::from(rights.pop().ok_or_else(|| refused("phase descriptor missing"))?);
    validate_bootstrap(&bootstrap)?;
    validate_bootstrap(&initial)?;
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    bounded_timeout(timeout, original_receiver_end)?;
    let initial = RootGenerationInitialHandoffV1 {
        bootstrap: initial,
        root_pidfd: root_pidfd.try_clone()?,
        root_pid: peer.pid as u32,
    };
    Ok(OriginalSameActorPhaseHandoff {
        bootstrap, root_pidfd, root_pid: peer.pid as u32, initial,
    })
}

pub(crate) fn receive_original_scoped_phase(
    socket: UnixDatagram,
    timeout: Duration,
    gate: &Arc<SameActorPhaseGate>,
) -> Result<OriginalSameActorScopedHandoff, AgentdError> {
    let mut closing = CloseSameActorPhaseOnDrop::new(gate);
    gate.require_open()?;
    let _stop = gate.retain_original_datagram(&socket)?;
    let peer = root_pair(&socket, bounded_timeout(timeout, gate.deadline().instant())?)?;
    let mut rights = receive_phase_packet(
        &socket, SCOPED_FRAME, 7, bounded_timeout(timeout, gate.deadline().instant())?,
    )?;
    let publication = File::from(rights.pop().ok_or_else(|| refused("phase publication offer missing"))?);
    let witness = File::from(rights.pop().ok_or_else(|| refused("phase Model witness missing"))?);
    let journal = File::from(rights.pop().ok_or_else(|| refused("phase Model journal missing"))?);
    let model = File::from(rights.pop().ok_or_else(|| refused("phase Model offer missing"))?);
    let learning = File::from(rights.pop().ok_or_else(|| refused("phase Learning offer missing"))?);
    let root_pidfd = rights.pop().ok_or_else(|| refused("phase original Root pin missing"))?;
    let bootstrap = File::from(rights.pop().ok_or_else(|| refused("phase scoped descriptor missing"))?);
    for sealed in [&bootstrap, &learning, &model, &publication] {
        validate_bootstrap(sealed)?;
    }
    require_root_pin(&root_pidfd, peer.pid as u32)?;
    let result = OriginalSameActorScopedHandoff {
        bootstrap,
        root_pid: peer.pid as u32,
        learning: RootLearningHandoffV1 {
            bootstrap: learning, root_pidfd: root_pidfd.try_clone()?, root_pid: peer.pid as u32,
        },
        model: RootQ24ModelFactoryHandoffV1 {
            bootstrap: model, root_pidfd: root_pidfd.try_clone()?, root_pid: peer.pid as u32,
            journal, witness,
        },
        publication: RootGenerationPublicationHandoffV1 {
            bootstrap: publication, root_pidfd, root_pid: peer.pid as u32,
        },
    };
    gate.require_open()?;
    closing.disarm();
    Ok(result)
}

fn require_original_sender(
    socket: &UnixDatagram,
    root_pidfd: &OwnedFd,
    timeout: Duration,
) -> Result<(), AgentdError> {
    // SAFETY: both calls only read this process's actual kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("same-actor phase sender requires actual Root"));
    }
    if root_pair(socket, timeout)?.pid as u32 != std::process::id() {
        return Err(refused("same-actor phase pair belongs to another Root"));
    }
    require_root_pin(root_pidfd, std::process::id())
}

fn bounded_timeout(timeout: Duration, end: Instant) -> Result<Duration, AgentdError> {
    if timeout.is_zero() || timeout > Duration::from_secs(30) {
        return Err(refused("bounded original phase handoff timeout required"));
    }
    end.checked_duration_since(Instant::now())
        .filter(|left| !left.is_zero())
        .map(|left| left.min(timeout))
        .ok_or_else(|| refused("original phase handoff end elapsed"))
}

fn receive_phase_packet(
    socket: &UnixDatagram,
    frame: &[u8],
    count: usize,
    timeout: Duration,
) -> Result<Vec<OwnedFd>, AgentdError> {
    if frame.len() > 127 || !(1..=8).contains(&count) {
        return Err(refused("original phase packet bound differs"));
    }
    socket.set_nonblocking(false)?;
    socket.set_read_timeout(Some(timeout))?;
    let mut bytes = [0_u8; 128];
    let mut control = [0_usize; 32];
    let mut vector = libc::iovec { iov_base: bytes.as_mut_ptr().cast(), iov_len: frame.len() + 1 };
    // SAFETY: every pointer is initialized below to a bounded live buffer.
    let mut message: libc::msghdr = unsafe { mem::zeroed() };
    message.msg_iov = &mut vector;
    message.msg_iovlen = 1;
    message.msg_control = control.as_mut_ptr().cast();
    message.msg_controllen = mem::size_of_val(&control);
    // SAFETY: recvmsg writes only the retained bounded buffers and marks all
    // received rights CLOEXEC atomically.
    let size = unsafe { libc::recvmsg(socket.as_raw_fd(), &mut message, libc::MSG_CMSG_CLOEXEC) };
    if size < 0 { return Err(io::Error::last_os_error().into()); }
    // SAFETY: the original ancillary parser immediately owns every returned
    // descriptor; the completed aligned message remains live here.
    let (rights, valid) = unsafe { crate::notes_bootstrap::received_descriptors(&message) };
    if !valid || message.msg_flags & (libc::MSG_TRUNC | libc::MSG_CTRUNC) != 0
        || rights.len() != count || size as usize != frame.len()
        || &bytes[..frame.len()] != frame
    {
        return Err(refused("exact original phase marker and ordered rights required"));
    }
    Ok(rights)
}
