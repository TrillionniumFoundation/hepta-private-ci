//! Bounded reads of exact signatures in the original Root issuer record.
use super::*;

impl DeploymentFinalUseIssuer {
    pub(crate) fn retained_text_page(
        &self,
        identity: &AgentdIdentity,
        namespace: &str,
        thread_id: &str,
        after: u64,
        through: u64,
    ) -> io::Result<Option<(String, AuthBusTextIngress)>> {
        self.text_route_available(identity, thread_id)?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        if after > through || through > state.text_intent_sequence {
            return Err(io::Error::other("invalid original text recovery range"));
        }
        let prefix = format!("{namespace}:");
        let mut found: Option<(u64, &RetainedTextSignature)> = None;
        for retained in &state.text_signatures {
            if retained.agent_id != identity.agent_id.as_str()
                || !retained.request_id.starts_with(&prefix)
            {
                continue;
            }
            let number = intent_number(&retained.request_id)?;
            if number <= after || number > through {
                continue;
            }
            let body = retained.body.as_ref().ok_or_else(|| {
                io::Error::other("legacy original text reference requires its retained input")
            })?;
            if body.thread_id != thread_id
                || body.spawn_generation != retained.spawn_generation
                || body.spawn_generation > identity.spawn_generation
                || retained.payload_sha256
                    != *Digest32::of_bytes(
                        &crate::authbus_ingress::payload(body).map_err(io::Error::other)?,
                    )
                    .as_array()
            {
                return Err(io::Error::other("original text recovery identity mismatch"));
            }
            if found.as_ref().is_none_or(|(prior, _)| number < *prior) {
                found = Some((number, retained));
            }
        }
        Ok(found.map(|(_, retained)| {
            (
                retained.request_id.clone(),
                envelope(
                    &state.signer_id,
                    retained,
                    retained
                        .body
                        .as_ref()
                        .expect("validated original body")
                        .clone(),
                ),
            )
        }))
    }
}

#[cfg(test)]
#[path = "deployment_text_recovery_tests.rs"]
mod tests;
