//! Receive and authenticate the complete original transport before reading a
//! late protected profile. This held frame cannot produce role streams until
//! the independently loaded full profile passes the original validator.

use super::*;

pub(crate) struct OriginalRootCandidateStageTransportV1 {
    packet: Packet,
    descriptors: Vec<OwnedFd>,
    sender: OwnedFd,
}

pub(crate) fn receive_original_candidate_stage_transport(
    socket: UnixDatagram, timeout: Duration,
) -> Result<OriginalRootCandidateStageTransportV1, AgentdError> {
    require_root()?;
    let root = super::super::root_pair(&socket, timeout)?;
    let (bytes, mut descriptors) = wire::receive(&socket, timeout)?;
    let sender = descriptors.remove(0);
    super::super::require_root_pin(&sender, root.pid as u32)?;
    let packet: Packet = serde_json::from_slice(&bytes)?;
    if packet.purpose != PURPOSE || packet.recipient.pid != std::process::id()
        || packet.lanes.len() != ROLES.len()
    { return Err(refused("original late transport purpose, recipient and ten roles required")); }
    require_process(&packet.recipient)?;
    let now = wire::monotonic_ns()?;
    for (index, lane) in packet.lanes.iter().enumerate() {
        if lane.role != ROLES[index] { return Err(refused("original late transport role order differs")); }
        let lifetime = lane.end_ns.checked_sub(now).ok_or_else(|| refused("expired original role"))?;
        require_timing(index, lane.timeout_ns, lifetime)?;
    }
    super::super::require_root_pin(&sender, root.pid as u32)?;
    Ok(OriginalRootCandidateStageTransportV1 { packet, descriptors, sender })
}

impl OriginalRootCandidateStageTransportV1 {
    pub(crate) fn bind_original_profile(self, profile: &RootResidentLearningProfileV3)
        -> Result<RootCandidateStageHandoffV1, AgentdError>
    {
        require_root()?;
        crate::root_observation_stream::check_lifetime(&self.sender)
            .map_err(|_| refused("original handoff Root exited"))?;
        // No self-comparison, parsed claim or mere readability can satisfy this
        // independent full profile check. Failure closes every retained right.
        validate_packet(&self.packet, profile.binding())?;
        Ok(RootCandidateStageHandoffV1 {
            packet: self.packet, descriptors: self.descriptors, sender: self.sender,
        })
    }
}
