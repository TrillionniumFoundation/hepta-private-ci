//! Reference retirement proven by independent reads from the ORIGINAL owners.
//! UI JSON cannot construct this type or supply a successful outcome.
use super::*;
use crate::AuthBusTextState;
use crate::text_session::AgentdTextSession;
use crate::text_session::AgentdTextSessionConfig;
use codex_app_server_protocol::ThreadQueueReconcileOutcome;
use codex_app_server_protocol::TurnStatus;

pub(crate) struct VerifiedTextRetirement {
    original: AuthBusTextIngress,
    agent_id: codex_hepta_contracts::AgentId,
}

impl VerifiedTextRetirement {
    pub(crate) async fn read_original(
        route: AgentdTextSessionConfig,
        original: AuthBusTextIngress,
    ) -> io::Result<Self> {
        let agent_id = route.agent_id.clone();
        let session = AgentdTextSession::connect(route)
            .await
            .map_err(io::Error::other)?;
        let result = async {
            session
                .requests
                .lookup_signed(original.clone())
                .await
                .map_err(io::Error::other)?;
            let observed = session
                .requests
                .reconcile(&original.message_id)
                .await
                .map_err(io::Error::other)?;
            if observed.delivery.state != AuthBusTextState::QueueAccepted
                || observed.delivery.queue_receipt_digest.is_none()
            {
                return Err(io::Error::other(
                    "original AuthBus queue acknowledgement is not durable",
                ));
            }
            let terminal = match &observed.queue {
                ThreadQueueReconcileOutcome::Cancelled => true,
                ThreadQueueReconcileOutcome::Persisted { turn_id } => {
                    observed.turn.as_ref().is_some_and(|turn| {
                        &turn.id == turn_id && turn.status != TurnStatus::InProgress
                    })
                }
                _ => false,
            };
            if !terminal {
                return Err(io::Error::other("original Core outcome is not terminal"));
            }
            Ok(Self { original, agent_id })
        }
        .await;
        let _ = session.events.shutdown().await;
        result
    }
}

impl DeploymentFinalUseIssuer {
    pub(crate) fn retire_registered_text(
        &self,
        identity: &AgentdIdentity,
        request_id: &str,
        proof: VerifiedTextRetirement,
        registration: &HostAuthorityWriterRegistration,
        leases: &AuthorityLeaseVerifier,
        writer_proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> io::Result<()> {
        if self.lease.is_none()
            || registration.registered_agent_id != identity.agent_id
            || registration.spawn_generation != identity.spawn_generation
            || proof.agent_id != identity.agent_id
        {
            return Err(io::Error::other("protected registered writer required"));
        }
        registration.with_live(leases, |_| {
            if self.retained_writer_authorization(registration)? != *writer_proof {
                return Err(io::Error::other("retained writer proof changed"));
            }
            self.retire_verified_text(request_id, proof)
        })
    }

    fn retire_verified_text(
        &self,
        request_id: &str,
        proof: VerifiedTextRetirement,
    ) -> io::Result<()> {
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let number = intent_number(request_id)?;
        let retained = state
            .text_signatures
            .iter()
            .find(|entry| entry.request_id == request_id);
        if let Some(retained) = retained {
            if retained.agent_id != proof.agent_id.as_str()
                || envelope(&state.signer_id, retained, proof.original.body.clone())
                    != proof.original
                || retained.payload_sha256
                    != *Digest32::of_bytes(
                        &crate::authbus_ingress::payload(&proof.original.body)
                            .map_err(io::Error::other)?,
                    )
                    .as_array()
            {
                return Err(io::Error::other(
                    "retirement does not match original signature",
                ));
            }
        } else if number <= state.text_intent_sequence {
            return Ok(());
        } else {
            return Err(io::Error::other("text intent has not been reserved"));
        }
        let mut next = state.clone();
        next.text_signatures
            .retain(|entry| entry.request_id != request_id);
        // Neither signing sequence nor monotonic intent watermark goes back.
        // The original AuthBus/Core history is untouched; only this reference
        // slot is freed after THEIR independently read durable terminal state.
        self.store
            .compare_and_set(STATE_OWNER, &state, &next)
            .map_err(io::Error::other)
    }
}

#[cfg(test)]
#[path = "deployment_text_retirement_tests.rs"]
mod tests;
