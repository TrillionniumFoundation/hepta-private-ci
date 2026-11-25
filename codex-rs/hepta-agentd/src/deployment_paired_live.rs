//! Current human inspection inside the original four-record boundary.
//! The result remains read-only metadata. There is no material or grant entry.
use super::*;
use crate::authority_host_service::OriginalHumanLifetime;

pub(super) enum PairedRootInspection<'a> {
    RegistrationOnly,
    OriginalHuman {
        identity: &'a AgentdIdentity,
        ingress: &'a AuthBusTextIngress,
        held: &'a OriginalHumanLifetime<'a>,
    },
}

impl PairedRootInspection<'_> {
    /// This call runs only while the original Registry and issuer request locks
    /// are held. It must never invoke the complete human verifier or await.
    pub(super) fn verify(
        &self,
        owner: &RegisteredRootPaired,
        state: &IssuerState,
        entered_now: u64,
    ) -> io::Result<u64> {
        let Self::OriginalHuman {
            identity,
            ingress,
            held,
        } = self
        else {
            return Ok(entered_now);
        };
        let registration = &owner.registration;
        let original = &registration.request.original;
        let human = held.binding();
        if identity.agent_id != owner.writer.registered_agent_id
            || identity.spawn_generation != owner.writer.spawn_generation
            || human.route != registration.original_route
            || human.principal_id != registration.preparation.principal_id
            || human.permission_revision != registration.permission_revision
            || human.expires_at_ms != registration.human_expires_at_ms
            || ingress.body.text != original.usage.consent_text(original.study)
        {
            return Err(denied("paired original human scope changed"));
        }
        let message = codex_hepta_authbus::SignedMessage {
            claims: crate::authbus_text_claims(&identity.agent_id, ingress)
                .map_err(io::Error::other)?,
            signature: crate::authbus_trust::hex_bytes(&ingress.signature_hex)
                .map_err(io::Error::other)?,
        };
        if message.delivery_id() != original.delivery_id {
            return Err(denied("paired original signed delivery changed"));
        }
        let expires_at_ms = state.verify_retained_human_text_at(
            identity,
            ingress,
            &human,
            &held.namespace(),
            entered_now,
        )?;
        held.recheck_original_human_lifetime(&human)?;
        let now = owner.issuer.clock.now_unix_ms().map_err(io::Error::other)?;
        if now < entered_now || now >= expires_at_ms {
            return Err(denied(
                "paired original human expired during retained readback",
            ));
        }
        Ok(now)
    }
}
