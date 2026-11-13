//! A separate, one-shot transfer of already connected original role channels.
//! Public wire metadata carries no material, verifier, result, signer or grant.

use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdRootAuthorityPeer;
use crate::LearningIterationEvidencePeerV1;
use crate::OriginalCellQ24CandidateStageStreamsV1;
use crate::OriginalCellQ24NoUpdatePeerStreamV1 as PeerStream;
use crate::OriginalCellQ24NoUpdateStageStreamsV1;
use crate::OriginalCellQ24NoUpdateTaskStreamV1 as TaskStream;
use crate::RootResidentLearningProfileV3;

#[path = "root_candidate_stage_handoff_wire.rs"]
mod wire;

#[path = "root_candidate_stage_transport.rs"]
mod late_transport;
pub(crate) use late_transport::{OriginalRootCandidateStageTransportV1, receive_original_candidate_stage_transport};

const PURPOSE: &str = "hepta.original-root-candidate-stage-handoff.v1";
const ROLES: [&str; 10] = [
    "experience",
    "dataset",
    "trainer",
    "selector",
    "version",
    "next_use",
    "completion",
    "candidate_material",
    "evaluator",
    "model",
];

#[derive(Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Process {
    pid: u32,
    boot_id: String,
    process_start_ticks: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Lane {
    role: String,
    uid: u32,
    process: Process,
    timeout_ns: u64,
    end_ns: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Packet {
    purpose: String,
    profile: String,
    recipient: Process,
    lanes: Vec<Lane>,
}

/// No public constructor, deserializer, role getter or retry path. Admission
/// consumes all rights against an independently supplied original Root profile.
pub struct RootCandidateStageHandoffV1 {
    packet: Packet,
    descriptors: Vec<OwnedFd>,
    sender: OwnedFd,
}

enum Input {
    Peer(PeerStream),
    Task(TaskStream),
}

/// The original host transfers existing endpoints for the actual resident
/// process. Passing an FD cannot retarget its established SO_PEERCRED peer.
/// Every endpoint and the private handoff socket are consumed even on error.
pub fn send_root_candidate_stage_handoff(
    socket: UnixDatagram,
    root_pidfd: &OwnedFd,
    recipient: AgentdRootAuthorityPeer,
    recipient_pidfd: &OwnedFd,
    profile: &RootResidentLearningProfileV3,
    streams: OriginalCellQ24CandidateStageStreamsV1,
    timeout: Duration,
) -> Result<(), AgentdError> {
    require_root()?;
    let root = super::root_pair(&socket, timeout)?;
    if root.pid as u32 != std::process::id() {
        return Err(refused("same original Root pair required"));
    }
    super::require_root_pin(root_pidfd, std::process::id())?;
    super::require_root_pin(recipient_pidfd, recipient.pid)?;
    let recipient = Process {
        pid: recipient.pid,
        boot_id: recipient.boot_id,
        process_start_ticks: recipient.process_start_ticks,
    };
    require_process(&recipient)?;
    let OriginalCellQ24CandidateStageStreamsV1 {
        common,
        candidate_material,
        evaluator,
        model,
    } = streams;
    let OriginalCellQ24NoUpdateStageStreamsV1 {
        experience,
        dataset,
        trainer,
        selector,
        version,
        next_use,
        completion,
    } = common;
    let inputs = [
        Input::Peer(experience),
        Input::Peer(dataset),
        Input::Peer(trainer),
        Input::Peer(selector),
        Input::Task(version),
        Input::Peer(next_use),
        Input::Task(completion),
        Input::Peer(candidate_material),
        Input::Peer(evaluator),
        Input::Peer(model),
    ];
    let now = wire::monotonic_ns()?;
    let mut lanes = Vec::with_capacity(ROLES.len());
    let mut owned = Vec::with_capacity(ROLES.len());
    let mut sockets = std::collections::BTreeSet::new();
    for (index, input) in inputs.into_iter().enumerate() {
        let (stream, pidfd, uid, process, command_timeout, lifetime) = match input {
            Input::Peer(input) => {
                if Some(&input.peer.actor_id) != actor(profile, index)? {
                    return Err(refused("original role actor differs"));
                }
                (
                    input.stream,
                    input.original_owner_pidfd,
                    input.peer.uid,
                    Process {
                        pid: input.peer.pid,
                        boot_id: input.peer.boot_id,
                        process_start_ticks: input.peer.process_start_ticks,
                    },
                    input.timeout,
                    input.lifetime,
                )
            }
            Input::Task(input) => (
                input.stream,
                input.original_task_pidfd,
                input.uid,
                Process {
                    pid: input.peer.pid,
                    boot_id: input.peer.boot_id,
                    process_start_ticks: input.peer.process_start_ticks,
                },
                input.timeout,
                input.lifetime,
            ),
        };
        let timeout_ns =
            u64::try_from(command_timeout.as_nanos()).map_err(|_| refused("timeout overflow"))?;
        let lifetime_ns =
            u64::try_from(lifetime.as_nanos()).map_err(|_| refused("lifetime overflow"))?;
        require_timing(index, timeout_ns, lifetime_ns)?;
        crate::notes_bootstrap::require_socket(stream.as_raw_fd(), libc::SOCK_STREAM)?;
        if !sockets.insert(wire::socket_identity(stream.as_raw_fd())?) {
            return Err(refused("role purposes require distinct original streams"));
        }
        let end_ns = now
            .checked_add(lifetime_ns)
            .ok_or_else(|| refused("deadline overflow"))?;
        lanes.push(Lane {
            role: ROLES[index].into(),
            uid,
            process,
            timeout_ns,
            end_ns,
        });
        owned.push((stream, pidfd));
    }
    let packet = Packet {
        purpose: PURPOSE.into(),
        profile: profile.binding().to_string(),
        recipient,
        lanes,
    };
    let bytes = serde_json::to_vec(&packet)?;
    let mut descriptors = vec![root_pidfd.as_raw_fd()];
    for (stream, pidfd) in &owned {
        descriptors.extend([stream.as_raw_fd(), pidfd.as_raw_fd()]);
    }
    wire::send(&socket, &bytes, &descriptors, timeout)
}

/// Receive only original connected capabilities. Material, loaded-model and
/// evaluation trust are supplied separately to the consuming Root service.
pub fn receive_root_candidate_stage_handoff(
    socket: UnixDatagram,
    profile: &RootResidentLearningProfileV3,
    timeout: Duration,
) -> Result<RootCandidateStageHandoffV1, AgentdError> {
    require_root()?;
    let root = super::root_pair(&socket, timeout)?;
    let (bytes, mut descriptors) = wire::receive(&socket, timeout)?;
    let sender = descriptors.remove(0);
    super::require_root_pin(&sender, root.pid as u32)?;
    let packet: Packet = serde_json::from_slice(&bytes)?;
    validate_packet(&packet, profile.binding())?;
    Ok(RootCandidateStageHandoffV1 {
        packet,
        descriptors,
        sender,
    })
}

impl RootCandidateStageHandoffV1 {
    pub(crate) fn into_original_streams(
        self,
        profile: &RootResidentLearningProfileV3,
    ) -> Result<(OriginalCellQ24CandidateStageStreamsV1, Instant), AgentdError> {
        require_root()?;
        validate_packet(&self.packet, profile.binding())?;
        crate::root_observation_stream::check_lifetime(&self.sender)
            .map_err(|_| refused("original handoff Root exited"))?;
        // Sample Instant first: conversion can only shorten the original end.
        let local = Instant::now();
        let now = wire::monotonic_ns()?;
        let minimum = self
            .packet
            .lanes
            .iter()
            .map(|lane| lane.end_ns)
            .min()
            .ok_or_else(|| refused("missing role deadline"))?;
        let remaining = minimum
            .checked_sub(now)
            .filter(|ns| *ns > 0)
            .ok_or_else(|| refused("original role deadline elapsed"))?;
        let end = local
            .checked_add(Duration::from_nanos(remaining))
            .ok_or_else(|| refused("deadline overflow"))?;
        let mut descriptors = self.descriptors.into_iter();
        let mut inputs = Vec::with_capacity(ROLES.len());
        for (index, lane) in self.packet.lanes.into_iter().enumerate() {
            let stream = descriptors
                .next()
                .ok_or_else(|| refused("missing role stream"))?;
            let pidfd = descriptors
                .next()
                .ok_or_else(|| refused("missing original role pidfd"))?;
            crate::notes_bootstrap::require_socket(stream.as_raw_fd(), libc::SOCK_STREAM)?;
            let lifetime_ns = lane
                .end_ns
                .checked_sub(now)
                .ok_or_else(|| refused("expired original role"))?;
            require_timing(index, lane.timeout_ns, lifetime_ns)?;
            let peer = AgentdRootAuthorityPeer {
                pid: lane.process.pid,
                boot_id: lane.process.boot_id,
                process_start_ticks: lane.process.process_start_ticks,
            };
            let stream = UnixStream::from(stream);
            let timeout = Duration::from_nanos(lane.timeout_ns);
            let lifetime = Duration::from_nanos(lifetime_ns);
            inputs.push(match actor(profile, index)? {
                Some(actor_id) => Input::Peer(PeerStream {
                    stream,
                    peer: LearningIterationEvidencePeerV1 {
                        pid: peer.pid,
                        uid: lane.uid,
                        boot_id: peer.boot_id,
                        process_start_ticks: peer.process_start_ticks,
                        actor_id: actor_id.clone(),
                    },
                    original_owner_pidfd: pidfd,
                    timeout,
                    lifetime,
                }),
                None => Input::Task(TaskStream {
                    stream,
                    peer,
                    uid: lane.uid,
                    original_task_pidfd: pidfd,
                    timeout,
                    lifetime,
                }),
            });
        }
        let [
            Input::Peer(experience),
            Input::Peer(dataset),
            Input::Peer(trainer),
            Input::Peer(selector),
            Input::Task(version),
            Input::Peer(next_use),
            Input::Task(completion),
            Input::Peer(candidate_material),
            Input::Peer(evaluator),
            Input::Peer(model),
        ]: [Input; 10] = inputs
            .try_into()
            .map_err(|_| refused("exact original roles required"))?
        else {
            return Err(refused("original role purposes differ"));
        };
        Ok((
            OriginalCellQ24CandidateStageStreamsV1 {
                common: OriginalCellQ24NoUpdateStageStreamsV1 {
                    experience,
                    dataset,
                    trainer,
                    selector,
                    version,
                    next_use,
                    completion,
                },
                candidate_material,
                evaluator,
                model,
            },
            end,
        ))
    }
}

fn actor(
    profile: &RootResidentLearningProfileV3,
    index: usize,
) -> Result<Option<&StableId>, AgentdError> {
    let owners = &profile.initial().owners;
    Ok(match index {
        0 => Some(&owners.experience),
        1 => Some(&owners.dataset),
        2 | 7 => Some(&owners.trainer),
        3 => Some(&owners.selector),
        5 => Some(&owners.next_use_observer),
        8 => Some(&owners.evaluator),
        9 => Some(&owners.proposal),
        4 | 6 => None,
        _ => return Err(refused("unknown original role")),
    })
}

fn validate_packet(packet: &Packet, binding: Digest32) -> Result<(), AgentdError> {
    if packet.purpose != PURPOSE
        || packet.profile != binding.to_string()
        || packet.recipient.pid != std::process::id()
        || packet.lanes.len() != ROLES.len()
    {
        return Err(refused(
            "original purpose, profile, recipient and ten roles required",
        ));
    }
    require_process(&packet.recipient)?;
    let now = wire::monotonic_ns()?;
    for (index, lane) in packet.lanes.iter().enumerate() {
        if lane.role != ROLES[index] {
            return Err(refused("original role order differs"));
        }
        let lifetime = lane
            .end_ns
            .checked_sub(now)
            .ok_or_else(|| refused("expired original role"))?;
        require_timing(index, lane.timeout_ns, lifetime)?;
    }
    Ok(())
}

fn require_timing(index: usize, timeout: u64, lifetime: u64) -> Result<(), AgentdError> {
    let limit = if index == 6 {
        500_000_000
    } else {
        30_000_000_000
    };
    if timeout == 0 || timeout > limit || lifetime == 0 || lifetime > 300_000_000_000 {
        return Err(refused("original role timing exceeds its bound"));
    }
    Ok(())
}

fn require_process(peer: &Process) -> Result<(), AgentdError> {
    use std::io::Read;
    if peer.pid == 0 || peer.pid > i32::MAX as u32 || peer.process_start_ticks == 0 {
        return Err(refused("original recipient identity is invalid"));
    }
    let mut boot = String::new();
    std::fs::File::open("/proc/sys/kernel/random/boot_id")?
        .take(129)
        .read_to_string(&mut boot)?;
    let mut stat = String::new();
    std::fs::File::open(format!("/proc/{}/stat", peer.pid))?
        .take(8193)
        .read_to_string(&mut stat)?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok());
    if boot.len() > 128
        || boot.trim() != peer.boot_id
        || stat.len() > 8192
        || start != Some(peer.process_start_ticks)
    {
        return Err(refused("original recipient process differs"));
    }
    Ok(())
}

fn require_root() -> Result<(), AgentdError> {
    // SAFETY: these calls only inspect this process's kernel credentials.
    if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
        return Err(refused("actual Root resident required"));
    }
    Ok(())
}

fn refused(message: &str) -> AgentdError {
    AgentdError::Protocol(format!("original Root candidate handoff: {message}"))
}

#[cfg(test)]
#[path = "root_candidate_stage_handoff_tests.rs"]
mod tests;
