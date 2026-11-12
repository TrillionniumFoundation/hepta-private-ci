//! Original five lanes for the explicit same-actor phase mode.
//! Every accepted channel keeps the startup Instant; the common stop gate
//! separately retains the original BOOTTIME limit and wakes blocked streams.

use super::*;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use std::sync::Arc;

impl HostAuthorityService {
    pub(crate) fn bind_original_same_actor_phase_issuer(
        &self,
        phase: &Arc<SameActorPhaseGate>,
    ) -> io::Result<()> {
        self.issuer.bind_original_same_actor_phase(phase)
    }

    pub(crate) fn serve_original_phase_lane_until(
        &self,
        lane: HostAuthorityLane,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), HostIssuerTransportError> {
        let _closing = CloseSameActorPhaseOnDrop::new(gate);
        gate.require_open().map_err(unavailable)?;
        let _stream_stop = gate.retain_original_stream(&stream).map_err(unavailable)?;
        let bound = match lane {
            HostAuthorityLane::Observation => 16 * 1024,
            HostAuthorityLane::Issuer => 64 * 1024,
            HostAuthorityLane::Checkpoint => 32 * 1024,
            HostAuthorityLane::DeviceConsumerFrontier
            | HostAuthorityLane::NotesConsumerFrontier => 16 * 1024,
        };
        policy.request_bound = bound;
        policy.response_bound = bound;
        if matches!(lane, HostAuthorityLane::Checkpoint)
            && let Some(checkpoint) = &self.checkpoint
        {
            checkpoint.validate_peer(policy.peer).map_err(unavailable)?;
        }
        let mut channel = HostAuthorityPeerChannel::from_stream_until(
            stream,
            policy,
            owner_pidfd,
            gate.deadline().instant(),
        )?;
        while channel.exchange(|bytes| {
            let _admission = gate.enter_original_lane().map_err(unavailable)?;
            let response = self.handle_original_same_actor_phase_lane(lane, bytes, gate)?;
            gate.require_open().map_err(unavailable)?;
            Ok(response)
        })? {
            // The framed ACK has completed. Instant-only transport checks
            // do not replace the phase's retained BOOTTIME boundary.
            gate.require_open().map_err(unavailable)?;
        }
        // These five owner lanes are required for the entire phase.
        // EOF is not a completion receipt and closes every participating lane.
        Err(HostIssuerTransportError::Closed)
    }
}

impl HostAuthorityService {
    fn handle_original_same_actor_phase_lane(
        &self,
        lane: HostAuthorityLane,
        bytes: &[u8],
        phase: &std::sync::Arc<crate::same_actor_q24_phase_gate::SameActorPhaseGate>,
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        phase.require_open().map_err(unavailable)?;
        self.check_logind_lifetime().map_err(unavailable)?;
        let result = match lane {
            HostAuthorityLane::Observation => self.observe(bytes),
            HostAuthorityLane::Issuer => self.issue(bytes),
            HostAuthorityLane::Checkpoint => self
                .writer
                .as_ref()
                .ok_or(HostIssuerTransportError::Unavailable)?
                .exchange_checkpoint_in_same_actor_phase(
                    &self.issuer,
                    &self.clock,
                    &self
                        .checkpoint
                        .as_ref()
                        .ok_or(HostIssuerTransportError::Unavailable)?
                        .backend,
                    bytes,
                    phase,
                ),
            HostAuthorityLane::DeviceConsumerFrontier
            | HostAuthorityLane::NotesConsumerFrontier => {
                let consumers = self
                    .consumers
                    .as_ref()
                    .ok_or(HostIssuerTransportError::Unavailable)?;
                let backend = if matches!(lane, HostAuthorityLane::DeviceConsumerFrontier) {
                    &consumers.device
                } else {
                    &consumers.notes
                };
                self.writer
                    .as_ref()
                    .ok_or(HostIssuerTransportError::Unavailable)?
                    .exchange_consumer_in_same_actor_phase(
                        &self.issuer,
                        &self.clock,
                        backend,
                        bytes,
                        phase,
                    )
            }
        };
        self.check_logind_lifetime().map_err(unavailable)?;
        phase.require_open().map_err(unavailable)?;
        result
    }
}

impl HostAuthorityService {
    pub(crate) fn serve_original_phase_lane_for_root_retirement(
        &self,
        lane: HostAuthorityLane,
        stream: (
            UnixStream,
            crate::same_actor_q24_phase_gate::SameActorPhaseStream,
        ),
        mut policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
        retirement: &Arc<crate::OriginalRootRetirementScope>,
    ) -> Result<crate::OriginalRootRetiredChannel, HostIssuerTransportError> {
        let gate = retirement.gate();
        let mut closing = CloseSameActorPhaseOnDrop::new(gate);
        gate.require_open().map_err(unavailable)?;
        let (stream, stream_stop) = stream;
        let bound = match lane {
            HostAuthorityLane::Observation => 16 * 1024,
            HostAuthorityLane::Issuer => 64 * 1024,
            HostAuthorityLane::Checkpoint => 32 * 1024,
            HostAuthorityLane::DeviceConsumerFrontier
            | HostAuthorityLane::NotesConsumerFrontier => 16 * 1024,
        };
        policy.request_bound = bound;
        policy.response_bound = bound;
        if matches!(lane, HostAuthorityLane::Checkpoint)
            && let Some(checkpoint) = &self.checkpoint
        {
            checkpoint.validate_peer(policy.peer).map_err(unavailable)?;
        }
        let mut channel = HostAuthorityPeerChannel::from_stream_until(
            stream,
            policy,
            owner_pidfd,
            gate.deadline().instant(),
        )?;
        let retirement_lane = retirement
            .register_original_lane(
                crate::OriginalRootRetirementPurpose::from_original_lane(lane),
                gate,
            )
            .map_err(unavailable)?;
        let mut retirement_admission = None;
        while channel.exchange(|bytes| {
            retirement_admission = Some(
                retirement_lane.enter_original_request().map_err(unavailable)?,
            );
            let _admission = gate.enter_original_lane().map_err(unavailable)?;
            let response = self.handle_original_same_actor_phase_lane(lane, bytes, gate)?;
            gate.require_open().map_err(unavailable)?;
            Ok(response)
        })? {
            // The framed ACK has completed. Instant-only transport checks
            // do not replace the phase's retained BOOTTIME boundary.
            gate.require_open().map_err(unavailable)?;
            drop(retirement_admission.take());
        }
        let retired = retirement_lane
            .accept_original_clean_eof(channel, stream_stop)
            .map_err(unavailable)?;
        closing.disarm();
        Ok(retired)
    }
}
