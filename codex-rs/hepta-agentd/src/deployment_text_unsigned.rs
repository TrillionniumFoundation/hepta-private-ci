//! Close an unissued intent in the SAME issuer watermark and signing fence.
//! A retained signature is returned unchanged and is never retired here.
use super::*;
use crate::text_session::TextUnsignedClosure;

impl DeploymentFinalUseIssuer {
    pub(crate) fn registered_writer_close_unsigned_text(
        &self,
        identity: &AgentdIdentity,
        namespace: &str,
        request_id: &str,
        body: AuthBusTextBody,
        registration: &HostAuthorityWriterRegistration,
        leases: &AuthorityLeaseVerifier,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> io::Result<TextUnsignedClosure> {
        if self.lease.is_none()
            || registration.registered_agent_id != identity.agent_id
            || registration.spawn_generation != identity.spawn_generation
        {
            return Err(io::Error::other("protected registered writer required"));
        }
        registration.with_live(leases, |_| {
            if self.retained_writer_authorization(registration)? != *proof {
                return Err(io::Error::other("retained writer proof changed"));
            }
            self.close_unsigned_text_until(
                identity,
                namespace,
                request_id,
                body,
                Some(&registration.authority_lease),
            )
        })
    }

    pub(super) fn close_unsigned_text_until(
        &self,
        identity: &AgentdIdentity,
        namespace: &str,
        request_id: &str,
        mut body: AuthBusTextBody,
        lease: Option<&AuthorityLease>,
    ) -> io::Result<TextUnsignedClosure> {
        let number = intent_number(request_id)?;
        if request_id.len() > 192
            || !request_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
            || request_id != format!("{namespace}:{number}")
            || body.spawn_generation != identity.spawn_generation
        {
            return Err(io::Error::other("unsigned closure identity mismatch"));
        }
        let payload_sha256 =
            *Digest32::of_bytes(&crate::authbus_ingress::payload(&body).map_err(io::Error::other)?)
                .as_array();
        let destination = Self::text_destination(&body.thread_id)?;
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        if !state.policies.iter().any(|policy| {
            policy.subject_id == identity.agent_id.as_str()
                && policy.destination_id == destination
                && policy.scope_sha256 == Self::text_scope(&identity.agent_id)
                && (1..=300_000).contains(&policy.lifetime_ms)
        }) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "text route is not installed",
            ));
        }
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        if lease.is_some_and(|lease| {
            lease.authority_epoch != state.head.authority_epoch
                || now < lease.issued_at_unix_ms
                || now >= lease.expires_at_unix_ms
        }) {
            return Err(io::Error::other("text writer lease is not live"));
        }
        if let Some(original) = state
            .text_signatures
            .iter()
            .find(|entry| entry.request_id == request_id)
        {
            // A new current process may recover an old signature, but never
            // replace it with a current-generation signature or auto-dispatch it.
            body.spawn_generation = original.spawn_generation;
            if original.agent_id != identity.agent_id.as_str()
                || original.spawn_generation > identity.spawn_generation
                || original.payload_sha256
                    != *Digest32::of_bytes(
                        &crate::authbus_ingress::payload(&body).map_err(io::Error::other)?,
                    )
                    .as_array()
            {
                return Err(io::Error::other("text request identity conflict"));
            }
            return Ok(TextUnsignedClosure::Retained {
                envelope: envelope(&state.signer_id, original, body),
            });
        }
        let through_sequence = state.text_intent_sequence.max(number);
        if through_sequence != state.text_intent_sequence {
            let mut next = state.clone();
            next.text_intent_sequence = through_sequence;
            self.store.validate_record(STATE_OWNER, &next)?;
            // Signing holds this same lock and CAS. Once this commits, even a
            // delayed first Sign after owner restart cannot issue this number.
            self.store
                .compare_and_set(STATE_OWNER, &state, &next)
                .map_err(io::Error::other)?;
        }
        Ok(TextUnsignedClosure::Closed {
            through_sequence,
            payload_sha256,
        })
    }
}

#[cfg(test)]
#[path = "deployment_text_unsigned_tests.rs"]
mod tests;
