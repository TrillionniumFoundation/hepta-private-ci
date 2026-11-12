//! Actual Root worker acknowledgement, peer EOF, and held-pidfd exit.
//! None of these facts is reconstructed from JSON, a count, Current refusal,
//! or a generic Runtime return. Daemon OS exit still needs its real parent.

use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use tokio::io::unix::AsyncFd;

use super::*;
use crate::production_launcher::OriginalRuntimeRootPurposesRetired;
use crate::root_authority_session::OriginalRootSessionObservationRetired;
use crate::same_actor_q24_deployment::OriginalDeploymentRetained;
use crate::same_actor_q24_phase_gate::RequiredSameActorPhaseChannel;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningPurposesRetired;

/// Constructed only by the real second retirement exchange after three
/// concrete retired-owner bundles were checked. Intent is first: cancellation
/// closes common fault custody before releasing the actual final peer.
pub(crate) struct OriginalRootWorkersJoined {
    intent: OriginalRootRetirementIntent,
    request: OriginalRootRetirementRequest,
    acknowledgement: OriginalRootRetirementAcknowledgement,
}

/// Only a successful kernel observation on the same pre-held Root pidfd can
/// construct this value, after the complete ACK2 and actual final-peer EOF.
/// It permits cleanup of this phase's already-joined owners, never authority
/// use or a new request. It does not retain Context or claim daemon OS exit.
pub(crate) struct OriginalRootProcessExited {
    identity: AgentdIdentity,
    gate: Arc<SameActorPhaseGate>,
    root: AsyncFd<OwnedFd>,
}

impl OriginalRootRetirementIntent {
    /// Synchronous on the actual outer owner, with no borrowed non-Sync
    /// resources crossing an await. The original single-frame 500 ms budget
    /// is captured by request(), after all actual purpose-close proofs.
    pub(crate) fn observe_original_root_workers_joined(
        self,
        runtime: &OriginalRuntimeRootPurposesRetired,
        learning: &OriginalSameActorLearningPurposesRetired,
        session: &OriginalRootSessionObservationRetired,
        coordinator: &OriginalDeploymentRetained,
    ) -> Result<OriginalRootWorkersJoined, AgentdError> {
        let mut intent = self;
        let identity = intent.client.context.identity().clone();
        let gate = Arc::clone(intent.client.context.gate());
        intent.require_original_origin(&identity, &gate)?;
        runtime.require_original_origin(&identity, &gate)?;
        learning.require_original_phase(&identity, &gate)?;
        session.require_original_origin(&identity, &gate)?;
        coordinator.require_original_origin(&identity, &gate)?;
        let request = OriginalRootRetirementRequest {
            schema_version: 1,
            purpose: RETIREMENT_PURPOSE.into(),
            binding: intent.request.binding.clone(),
            sequence: 2,
            stage: OriginalRootRetirementStage::ObserveRootWorkersJoined,
            current_registration: intent.request.current_registration.clone(),
            current_request: intent.request.current_request.clone(),
            original_intent: Some(intent.intent_digest.clone()),
        };
        let bytes = request.encode_original()?;
        intent.require_original_origin(&identity, &gate)?;
        let response = HostAuthorityPeerChannel::request(&mut intent.client.channel, &bytes)
            .map_err(uncertain)?;
        let acknowledgement = (|| {
            let acknowledgement = OriginalRootRetirementAcknowledgement::decode_original(
                &response, &request, &intent.intent_digest,
            )?;
            // Root still holds its real joined owners and process until the
            // final peer EOF below. Preserve every original postcheck.
            HostAuthorityPeerChannel::check_peer_lifetime(&intent.client.channel)
                .map_err(owner_error)?;
            intent.require_original_origin(&identity, &gate)?;
            runtime.require_original_origin(&identity, &gate)?;
            learning.require_original_phase(&identity, &gate)?;
            session.require_original_origin(&identity, &gate)?;
            coordinator.require_original_origin(&identity, &gate)?;
            gate.require_open()?;
            Ok::<_, AgentdError>(acknowledgement)
        })().map_err(uncertain)?;
        Ok(OriginalRootWorkersJoined { intent, request, acknowledgement })
    }
}

impl OriginalRootWorkersJoined {
    /// Used only by the exact required-channel shutdown implementation.
    /// Comparing the real field address prevents this ACK2 from closing any
    /// different channel, even another purpose under the same Gate.
    pub(crate) fn require_original_final_peer(
        &self, channel: &RequiredSameActorPhaseChannel,
    ) -> Result<(), AgentdError> {
        if !std::ptr::eq(channel, &self.intent.client.required) {
            self.intent.client.context.gate().close();
            return Err(refused("actual final retirement peer differs"));
        }
        self.acknowledgement.require_original_request(
            &self.request, &self.intent.intent_digest,
        )?;
        OriginalRootRetirementIntent::require_original_origin(
            &self.intent, self.intent.client.context.identity(), self.intent.client.context.gate(),
        )
    }

    /// The same ACK2 owner is retained before this future's first poll.
    /// One successful shutdown closes the exact socket and all its aliases;
    /// only then do we observe actual Root process exit on its original pidfd.
    pub(crate) fn wait_original_root_process_exit(
        self,
    ) -> impl std::future::Future<Output = Result<OriginalRootProcessExited, AgentdError>> + Send + 'static {
        let joined = self;
        async move {
            let joined = joined;
            let identity = joined.intent.client.context.identity().clone();
            let gate = Arc::clone(joined.intent.client.context.gate());
            joined.require_original_final_peer(&joined.intent.client.required)?;
            let root_pidfd = joined.intent.client.root_exit_pidfd.try_clone()?;
            // SAFETY: this AsyncFd exclusively owns a clone of the exact
            // pidfd verified at the original Root channel construction.
            // No raw ownership or alternate PID lookup is introduced.
            let root = unsafe {
                AsyncFd::register_with_interest(root_pidfd, tokio::io::Interest::READABLE)
            }?;
            RequiredSameActorPhaseChannel::shutdown_original_after_root_workers_joined(
                &joined.intent.client.required, &joined,
            )?;
            loop {
                let remaining = gate.require_open()?;
                if original_pidfd_has_exited(root.get_ref())? {
                    gate.require_open()?;
                    let exited = OriginalRootProcessExited {
                        identity, gate: Arc::clone(&gate), root,
                    };
                    // Expected final cleanup begins only AFTER the actual
                    // kernel exit proof. All fault guards remain armed;
                    // their common close can now release no live Root work.
                    drop(joined);
                    return Ok(exited);
                }
                tokio::select! {
                    _ = gate.cancelled() => {
                        return Err(refused("original Root exit observation was cancelled"));
                    }
                    ready = root.readable() => {
                        let mut ready = ready?;
                        // Readiness itself is not the proof; the next single
                        // poll verifies the same retained pidfd's kernel flags.
                        ready.clear_ready();
                    }
                    _ = tokio::time::sleep(remaining.min(Duration::from_millis(5))) => {}
                }
            }
        }
    }
}

impl OriginalRootProcessExited {
    /// Cleanup-only provenance. Gate was intentionally closed after the
    /// proven exit; this method cannot refresh Current or reopen a purpose.
    pub(crate) fn require_original_cleanup_origin(
        &self, identity: &AgentdIdentity, gate: &Arc<SameActorPhaseGate>,
    ) -> Result<(), AgentdError> {
        if &self.identity != identity || !Arc::ptr_eq(&self.gate, gate)
            || !original_pidfd_has_exited(self.root.get_ref())?
        {
            self.gate.close();
            return Err(refused("actual Root-exit cleanup origin differs"));
        }
        Ok(())
    }
}

fn original_pidfd_has_exited(fd: &OwnedFd) -> Result<bool, AgentdError> {
    let mut pollfd = libc::pollfd {
        fd: fd.as_raw_fd(), events: libc::POLLIN, revents: 0,
    };
    // SAFETY: one initialized pollfd points to this still-owned, already
    // verified pidfd. This is a nonblocking kernel exit observation, not an
    // authority call and not a reinterpretation of Current/PeerGone errors.
    let observed = unsafe { libc::poll(&mut pollfd, 1, 0) };
    if observed < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    if observed == 0 {
        return Ok(false);
    }
    if pollfd.revents & (libc::POLLERR | libc::POLLNVAL) != 0
        || pollfd.revents & libc::POLLIN == 0
    {
        return Err(refused("original Root pidfd reported invalid exit readiness"));
    }
    Ok(true)
}
