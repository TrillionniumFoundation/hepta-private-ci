//! Human provenance in the SAME original issuer signature CAS. A generic text
//! signature or a matching public namespace cannot manufacture this provenance.
use super::*;
use crate::text_session::AgentdTextSessionConfig;

#[derive(Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct TextHumanBinding {
    pub(crate) principal_id: String,
    pub(crate) session_id: String,
    pub(crate) permission_revision: u64,
    pub(crate) expires_at_ms: u64,
    pub(crate) route: AgentdTextSessionConfig,
}

pub(crate) struct RootHumanTextRequest<'a> {
    pub(crate) request_id: &'a str,
    pub(crate) body: AuthBusTextBody,
    pub(crate) operation: TextIssuerOperation,
    pub(crate) human: &'a TextHumanBinding,
}

impl DeploymentFinalUseIssuer {
    pub(crate) fn registered_writer_human_text(
        &self,
        identity: &AgentdIdentity,
        request: RootHumanTextRequest<'_>,
        registration: &HostAuthorityWriterRegistration,
        leases: &AuthorityLeaseVerifier,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> io::Result<AuthBusTextIngress> {
        if self.lease.is_none()
            || registration.registered_agent_id != identity.agent_id
            || registration.spawn_generation != identity.spawn_generation
        {
            return Err(io::Error::other(
                "protected registered human writer required",
            ));
        }
        self.with_issuer_writer_readback(registration, leases, |parent| {
            if self.retained_writer_authorization(registration)? != *proof {
                return Err(io::Error::other("retained human writer proof changed"));
            }
            self.text_until_checked(
                identity,
                request.request_id,
                request.body,
                request.operation,
                TextIssueAuthority {
                    lease: Some(&registration.authority_lease),
                    human: Some(request.human),
                    parent: Some(parent),
                },
            )
        })
    }

    pub(crate) fn verify_retained_human_text(
        &self,
        identity: &AgentdIdentity,
        ingress: &AuthBusTextIngress,
        human: &TextHumanBinding,
        namespace: &str,
    ) -> io::Result<()> {
        self.text_route_available(identity, &human.route.thread_id)?;
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        state
            .verify_retained_human_text_at(identity, ingress, human, namespace, now)
            .map(|_| ())
    }
}

impl IssuerState {
    /// Inspect the same original state while its caller owns the request lock.
    /// This pure predicate neither opens the Registry nor returns a read permit.
    /// Its result is only the earliest retained human/signature expiry.
    pub(in crate::deployment_issuer) fn verify_retained_human_text_at(
        &self,
        identity: &AgentdIdentity,
        ingress: &AuthBusTextIngress,
        human: &TextHumanBinding,
        namespace: &str,
        now: u64,
    ) -> io::Result<u64> {
        let destination = DeploymentFinalUseIssuer::text_destination(&human.route.thread_id)?;
        self.require_text_route(identity, &destination)?;
        let retained = self
            .text_signatures
            .iter()
            .find(|retained| {
                retained.agent_id == identity.agent_id.as_str()
                    && retained.sequence == ingress.sequence
                    && retained.key_epoch == ingress.key_epoch
            })
            .ok_or_else(|| io::Error::other("original human signature is not retained"))?;
        let body = retained
            .body
            .as_ref()
            .ok_or_else(|| io::Error::other("legacy text has no retained input"))?;
        if retained.human_binding.as_ref() != Some(human)
            || !retained.request_id.starts_with(&format!("{namespace}:"))
            || body.thread_id != human.route.thread_id
            || body.spawn_generation != identity.spawn_generation
            || retained.payload_sha256
                != *Digest32::of_bytes(
                    &crate::authbus_ingress::payload(body).map_err(io::Error::other)?,
                )
                .as_array()
            || now >= human.expires_at_ms
            || now >= retained.expires_at_ms
            || serde_json::to_value(envelope(&self.signer_id, retained, body.clone()))
                .map_err(io::Error::other)?
                != serde_json::to_value(ingress).map_err(io::Error::other)?
        {
            return Err(io::Error::other(
                "original text was not authenticated by this live human session",
            ));
        }
        Ok(human.expires_at_ms.min(retained.expires_at_ms))
    }
}

#[cfg(test)]
#[path = "deployment_text_human_tests.rs"]
mod tests;
