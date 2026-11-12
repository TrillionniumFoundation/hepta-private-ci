//! The actual Root retirement request, after local owners have really joined.
//! This private capability authorizes purpose-stream retirement only. It does
//! not prove Root process exit or permit any authority/business operation.

use std::sync::Arc;

use codex_hepta_contracts::HostAuthorityPeerChannel;

use super::OriginalDeploymentClient;
use super::owner_error;
use super::refused;
use super::uncertain;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::circuit_task::OriginalCircuitNaturalJoin;
use crate::production_launcher::OriginalSameActorRuntimeStopped;
use crate::root_authority_session::OriginalRootSessionPaused;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningJoined;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementAcknowledgement;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementRequest;
use crate::same_actor_q24_root_retirement_protocol::OriginalRootRetirementStage;
use crate::same_actor_q24_root_retirement_protocol::RETIREMENT_PURPOSE;

#[path = "same_actor_q24_deployment_root_exit.rs"]
mod root_exit;
pub(crate) use root_exit::OriginalRootWorkersJoined;
pub(crate) use root_exit::OriginalRootProcessExited;

/// Only the actual exchange below can construct this non-Clone, non-serde
/// owner. The same progress channel, original Root pidfd, required-stream
/// guard, exact context and original absolute deadline remain inside it.
/// The four joined/paused owners are borrowed synchronously and stay held by
/// the actual outer owner; this method never replaces them with data.
pub(crate) struct OriginalRootRetirementIntent {
    // The original sender's guard transfers here before the channel. Every
    // failure/cancelled owner drop closes the common Gate before releasing it.
    _closing: crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop,
    client: OriginalDeploymentClient,
    request: OriginalRootRetirementRequest,
    acknowledgement: OriginalRootRetirementAcknowledgement,
    intent_digest: String,
}

impl OriginalDeploymentClient {
    /// This synchronous operation runs on the retained actual outer owner.
    /// There is no await holding references to the non-Sync owner bundles.
    /// A lost ACK consumes this client and closes the same phase; it is never
    /// treated as absence of the Root effect, nor made available for retry.
    pub(in super::super) fn authorize_original_root_retirement(
        mut self,
        stopped: &OriginalSameActorRuntimeStopped,
        learning: &OriginalSameActorLearningJoined,
        natural: &OriginalCircuitNaturalJoin,
        session: &OriginalRootSessionPaused,
    ) -> Result<OriginalRootRetirementIntent, AgentdError> {
        let closing = self.required.failure_scope();
        let identity = self.context.identity().clone();
        let gate = Arc::clone(self.context.gate());
        stopped.require_original_origin(&identity, &gate)?;
        learning.require_original_phase(&identity, &gate)?;
        natural.require_original_phase(&identity, &gate)?;
        session.require_original_origin(&identity, &gate)?;
        self.required.require_open()?;
        HostAuthorityPeerChannel::check_peer_lifetime(&self.channel).map_err(owner_error)?;
        if self.next.is_some() {
            return Err(refused("actual deployment registrations are incomplete"));
        }
        let current = self.current_registration.take()
            .ok_or_else(|| refused("actual Current registration acknowledgement is unavailable"))?;
        let request = OriginalRootRetirementRequest {
            schema_version: 1,
            purpose: RETIREMENT_PURPOSE.into(),
            binding: self.binding.clone(),
            sequence: 1,
            stage: OriginalRootRetirementStage::AuthorizeRootRetirement,
            current_registration: current.registration,
            current_request: current.request,
            original_intent: None,
        };
        let bytes = request.encode_original()?;
        let intent_digest = request.digest()?;
        self.required.require_open()?;
        HostAuthorityPeerChannel::check_peer_lifetime(&self.channel).map_err(owner_error)?;
        // The original channel captures its single 500 ms request deadline
        // here, after all local pause/join checks. No new session end is made.
        let response = HostAuthorityPeerChannel::request(&mut self.channel, &bytes)
            .map_err(uncertain)?;
        let acknowledgement = (|| {
            let acknowledgement = OriginalRootRetirementAcknowledgement::decode_original(
                &response, &request, &intent_digest,
            )?;
            HostAuthorityPeerChannel::check_peer_lifetime(&self.channel).map_err(owner_error)?;
            self.required.require_open()?;
            // Ordinary Current is intentionally fenced by the real Session
            // pause. These sealed origins validate their retained owners and
            // same Gate, without seeking fresh authority after retirement.
            stopped.require_original_origin(&identity, &gate)?;
            learning.require_original_phase(&identity, &gate)?;
            natural.require_original_phase(&identity, &gate)?;
            session.require_original_origin(&identity, &gate)?;
            self.required.require_open()?;
            Ok::<_, AgentdError>(acknowledgement)
        })().map_err(uncertain)?;
        let intent = OriginalRootRetirementIntent {
            _closing: closing,
            client: self,
            request,
            acknowledgement,
            intent_digest,
        };
        OriginalRootRetirementIntent::require_original_origin(&intent, &identity, &gate)?;
        Ok(intent)
    }
}

impl OriginalRootRetirementIntent {
    /// A close-only owner of a real channel may compare the exact Gate; the
    /// identity remains the one held by this actual acknowledged client.
    pub(crate) fn require_original_gate(
        &self, gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        self.require_original_origin(self.client.context.identity(), gate)
    }

    /// A same-origin permission for already-quiesced owners to release their
    /// actual Root-purpose streams. This is not an admission to Current,
    /// another business operation, a renewed deadline, or a completion proof.
    pub(crate) fn require_original_origin(
        &self,
        identity: &AgentdIdentity,
        gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        let checked = (|| {
            if self.client.context.identity() != identity
                || !Arc::ptr_eq(self.client.context.gate(), gate)
            {
                return Err(refused("actual Root retirement origin differs"));
            }
            self.acknowledgement.require_original_request(&self.request, &self.intent_digest)?;
            self.client.required.require_open()?;
            HostAuthorityPeerChannel::check_peer_lifetime(&self.client.channel)
                .map_err(owner_error)?;
            self.client.required.require_open()?;
            Ok::<(), AgentdError>(())
        })();
        if checked.is_err() {
            self.client.context.gate().close();
        }
        checked
    }
}
