//! Explicit one-shot retirement and join for the original same-actor A.
//! The Root-only profile is an authorization input. Peer JSON cannot select
//! another profile, file, owner, namespace or deadline.

use std::io;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use serde::Deserialize;
use serde::Serialize;

use crate::HostAuthorityLearningProfileV1;
use crate::authority_host_service::HostAuthorityService;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

const UNUSED: u8 = 0;
const RETIRE_ACCEPTED: u8 = 1;
const JOIN_ACCEPTED: u8 = 2;
const PURPOSE: &str = "hepta.same-actor-q24-phase.join.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseJoinRequest {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) sequence: u8,
    pub(crate) phase: String,
    pub(crate) profile: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseJoinResponse {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) sequence: u8,
    pub(crate) phase: String,
    pub(crate) profile: String,
}

/// This shared state belongs to one original Root phase. It is never decoded
/// from a descriptor and cannot be reset after an accepted or failed exchange.
pub(crate) struct OriginalInitialRetirement {
    state: AtomicU8,
    gate: Arc<SameActorPhaseGate>,
    phase: String,
}

pub(crate) struct OriginalPhaseJoined {
    phase: String,
    profile: String,
}

impl OriginalInitialRetirement {
    pub(crate) fn new(gate: &Arc<SameActorPhaseGate>, phase: &str) -> Self {
        Self { state: AtomicU8::new(UNUSED), gate: Arc::clone(gate), phase: phase.into() }
    }

    /// Initial EOF transfers only the held owner; it does not grant a phase.
    /// A separate completed join and the real durable Claim are still required.
    pub(crate) fn require_expected_eof(
        &self,
        gate: &Arc<SameActorPhaseGate>,
    ) -> io::Result<()> {
        gate.require_open()?;
        if !Arc::ptr_eq(gate, &self.gate)
            || !matches!(self.state.load(Ordering::Acquire), RETIRE_ACCEPTED | JOIN_ACCEPTED)
        {
            return Err(io::Error::other("original Initial retired without an accepted intent"));
        }
        Ok(())
    }
}

impl OriginalPhaseJoined {
    pub(crate) fn require_original_profile(
        &self,
        phase: &str,
        profile: &HostAuthorityLearningProfileV1,
        retirement: &OriginalInitialRetirement,
        gate: &Arc<SameActorPhaseGate>,
    ) -> io::Result<()> {
        gate.require_open()?;
        if self.phase != phase
            || retirement.phase != phase
            || !Arc::ptr_eq(gate, &retirement.gate)
            || self.profile != serde_json::to_string(profile).map_err(io::Error::other)?
            || retirement.state.load(Ordering::Acquire) != JOIN_ACCEPTED
        {
            return Err(io::Error::other("original completed phase join differs"));
        }
        Ok(())
    }
}

/// Called only by the same Root worker after it receives the trusted host's
/// one-shot typed profile. This returns no writable rights and creates no
/// namespace. Failure keeps the common close guard armed.
pub(crate) fn accept_original_phase_join(
    service: &HostAuthorityService,
    config: &crate::HostAuthorityServiceConfig,
    registration: &crate::HostAuthorityRegistration,
    owner: &OwnedFd,
    stream: UnixStream,
    policy: HostAuthorityPeerPolicy,
    phase: &str,
    profile: &HostAuthorityLearningProfileV1,
    retirement: &OriginalInitialRetirement,
    gate: &Arc<SameActorPhaseGate>,
) -> io::Result<OriginalPhaseJoined> {
    let mut closing = CloseSameActorPhaseOnDrop::new(gate);
    let _stream_stop = gate.retain_original_stream(&stream)?;
    if retirement.phase != phase || !Arc::ptr_eq(gate, &retirement.gate) {
        return Err(io::Error::other("original phase retirement belongs to another gate"));
    }
    let exact_profile = serde_json::to_string(profile).map_err(io::Error::other)?;
    let mut channel = HostAuthorityPeerChannel::from_stream_until(
        stream, policy, owner.try_clone()?, gate.deadline().instant(),
    ).map_err(io::Error::other)?;
    for sequence in [1_u8, 2_u8] {
        let received = channel.exchange(|bytes| {
            let _admission = gate.enter_original_lane().map_err(unavailable)?;
            service.with_learning_profile(config, registration, owner, profile, |initial, _proof| {
                profile.require_cell_scope(&initial)?;
                let request: PhaseJoinRequest =
                    serde_json::from_slice(bytes).map_err(io::Error::other)?;
                if request.schema != 1
                    || request.purpose != PURPOSE
                    || request.sequence != sequence
                    || request.phase != phase
                    || request.profile != exact_profile
                {
                    return Err(io::Error::other("original phase intent and host profile differ"));
                }
                let (before, after) = if sequence == 1 {
                    (UNUSED, RETIRE_ACCEPTED)
                } else {
                    (RETIRE_ACCEPTED, JOIN_ACCEPTED)
                };
                retirement.state.compare_exchange(
                    before, after, Ordering::AcqRel, Ordering::Acquire,
                ).map_err(|_| io::Error::other("original phase intent was already consumed"))?;
                let reply = PhaseJoinResponse {
                    schema: 1,
                    purpose: PURPOSE.into(),
                    sequence,
                    phase: phase.into(),
                    profile: exact_profile.clone(),
                };
                let raw = serde_json::to_vec(&reply).map_err(io::Error::other)?;
                if raw.len() > 16 * 1024 {
                    return Err(io::Error::other("original phase reply bound"));
                }
                gate.require_open()?;
                Ok(raw)
            }).map_err(unavailable)
        }).map_err(io::Error::other)?;
        if !received {
            return Err(io::Error::other("original phase peer closed before the join"));
        }
        // Successful framing is not enough across suspend or a concurrent
        // phase close. This check follows each actual ACK write.
        gate.require_open()?;
    }
    let joined = OriginalPhaseJoined { phase: phase.into(), profile: exact_profile };
    joined.require_original_profile(phase, profile, retirement, gate)?;
    closing.disarm();
    Ok(joined)
}

fn unavailable(_: io::Error) -> codex_hepta_contracts::HostIssuerTransportError {
    codex_hepta_contracts::HostIssuerTransportError::Unavailable
}
