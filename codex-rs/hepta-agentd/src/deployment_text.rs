//! A closed text operation in the existing issuer's key/policy/counter/store.
//! Retained signature identities are not a conversation or effect journal.

use super::*;
use crate::AgentdIdentity;
use crate::AuthBusTextBody;
use crate::AuthBusTextIngress;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;
use codex_hepta_types::Digest32;

const MAX_TEXT_SIGNATURES: usize = 32;

#[path = "deployment_text_retirement.rs"]
mod retirement;
pub(crate) use retirement::VerifiedTextRetirement;
#[path = "deployment_text_recovery.rs"]
mod recovery;
#[path = "deployment_text_unsigned.rs"]
mod unsigned;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TextIssuerOperation {
    Sign,
    Lookup,
}

#[derive(Clone, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(super) struct RetainedTextSignature {
    request_id: String,
    agent_id: String,
    spawn_generation: u64,
    payload_sha256: [u8; 32],
    key_epoch: u64,
    sequence: u64,
    expires_at_ms: u64,
    signature_hex: String,
    // Atomic with the original signature/counter, so a restarted UI can only
    // recover the exact retained input. Legacy hash-only entries are never
    // reconstructed from guessed text or re-signed.
    #[serde(default)]
    body: Option<AuthBusTextBody>,
}

impl DeploymentFinalUseIssuer {
    pub(crate) fn next_text_intent(&self) -> io::Result<u64> {
        self.store
            .load(STATE_OWNER)
            .map_err(io::Error::other)?
            .text_intent_sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("text intent sequence exhausted"))
    }

    pub(crate) fn text_reference_retired(&self, request_id: &str) -> io::Result<bool> {
        let number = intent_number(request_id)?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        Ok(number <= state.text_intent_sequence
            && !state
                .text_signatures
                .iter()
                .any(|retained| intent_number(&retained.request_id).ok() == Some(number)))
    }
    /// Read-only readiness against the same installed policy. This reserves no
    /// sequence and cannot create a signature or initialize missing state.
    pub(crate) fn text_route_available(
        &self,
        identity: &AgentdIdentity,
        thread: &str,
    ) -> io::Result<()> {
        let destination = Self::text_destination(thread)?;
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
        Ok(())
    }

    /// Exact existing-thread policy destination, installed by the root owner.
    /// Neither the requesting host nor the UI can add this route through RPC.
    pub fn text_destination(thread_id: &str) -> io::Result<String> {
        if thread_id.is_empty()
            || thread_id.len() > 96
            || !thread_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
        {
            return Err(io::Error::other("invalid text thread identity"));
        }
        Ok(format!("hepta.authbus.text:{thread_id}"))
    }

    /// Same canonical AuthBus routing scope used by the receiver. This helper
    /// calculates registration data and confers no authority.
    pub fn text_scope(agent_id: &codex_hepta_contracts::AgentId) -> [u8; 32] {
        *crate::authbus_ingress::scope(agent_id).as_array()
    }

    /// Existing independently operated issuer entry. Sign is idempotent for a
    /// retained exact request; Lookup never advances the original sequence.
    pub fn text(
        &self,
        identity: &AgentdIdentity,
        request_id: &str,
        body: AuthBusTextBody,
        operation: TextIssuerOperation,
    ) -> io::Result<AuthBusTextIngress> {
        // A protected issuer may only be entered through its registered writer.
        if self.lease.is_some() {
            return Err(io::Error::other("registered writer entry required"));
        }
        self.text_until(identity, request_id, body, operation, None)
    }

    pub(crate) fn registered_writer_text(
        &self,
        identity: &AgentdIdentity,
        request_id: &str,
        body: AuthBusTextBody,
        operation: TextIssuerOperation,
        registration: &HostAuthorityWriterRegistration,
        leases: &AuthorityLeaseVerifier,
        proof: &crate::HostSignedWriterAuthorizationV1,
    ) -> io::Result<AuthBusTextIngress> {
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
            self.text_until(
                identity,
                request_id,
                body,
                operation,
                Some(&registration.authority_lease),
            )
        })
    }

    fn text_until(
        &self,
        identity: &AgentdIdentity,
        request_id: &str,
        mut body: AuthBusTextBody,
        operation: TextIssuerOperation,
        lease: Option<&AuthorityLease>,
    ) -> io::Result<AuthBusTextIngress> {
        if request_id.is_empty()
            || request_id.len() > 192
            || !request_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
        {
            return Err(io::Error::other("invalid text request identity"));
        }
        let intent_sequence = intent_number(request_id)?;
        crate::authbus_ingress::payload(&body).map_err(io::Error::other)?;
        let destination = Self::text_destination(&body.thread_id)?;
        let _guard = self
            .request_lock
            .lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let policy = state
            .policies
            .iter()
            .find(|policy| {
                policy.subject_id == identity.agent_id.as_str()
                    && policy.destination_id == destination
                    && policy.scope_sha256 == Self::text_scope(&identity.agent_id)
            })
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "text route is not installed",
                )
            })?;
        if !(1..=300_000).contains(&policy.lifetime_ms) {
            return Err(io::Error::other("invalid text lifetime"));
        }
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        if lease.is_some_and(|lease| {
            lease.authority_epoch != state.head.authority_epoch
                || now < lease.issued_at_unix_ms
                || now >= lease.expires_at_unix_ms
        }) {
            return Err(io::Error::other("text writer lease is not live"));
        }
        if let Some(retained) = state
            .text_signatures
            .iter()
            .find(|retained| retained.request_id == request_id)
        {
            // A new process may look up the exact old generation's signature,
            // but cannot change the owner, thread, text or reserved identity.
            body.spawn_generation = retained.spawn_generation;
            let bytes = crate::authbus_ingress::payload(&body).map_err(io::Error::other)?;
            if retained.agent_id != identity.agent_id.as_str()
                || retained.payload_sha256 != *Digest32::of_bytes(&bytes).as_array()
            {
                return Err(io::Error::other("text request identity conflict"));
            }
            return Ok(envelope(&state.signer_id, retained, body));
        }
        if operation == TextIssuerOperation::Lookup {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "original text signature not retained",
            ));
        }
        // A missing past number is permanently closed, regardless of the
        // requested prefix/body. Retirement cannot enable a replacement send.
        if intent_sequence <= state.text_intent_sequence {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "text intent is retired or already reserved",
            ));
        }
        if body.spawn_generation != identity.spawn_generation
            || state.text_signatures.len() >= MAX_TEXT_SIGNATURES
        {
            return Err(io::Error::other(
                "text generation or retained capacity unavailable",
            ));
        }
        let bytes = crate::authbus_ingress::payload(&body).map_err(io::Error::other)?;
        let mut next = state.clone();
        next.text_intent_sequence = intent_sequence;
        next.sequence = next
            .sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("issuer counter exhausted"))?;
        let mut retained = RetainedTextSignature {
            request_id: request_id.into(),
            agent_id: identity.agent_id.to_string(),
            spawn_generation: body.spawn_generation,
            payload_sha256: *Digest32::of_bytes(&bytes).as_array(),
            key_epoch: state.head.authority_epoch,
            sequence: next.sequence,
            expires_at_ms: now
                .checked_add(policy.lifetime_ms)
                .ok_or_else(|| io::Error::other("text expiry overflow"))?
                .min(lease.map_or(u64::MAX, |lease| lease.expires_at_unix_ms)),
            signature_hex: "0".repeat(128),
            body: Some(body.clone()),
        };
        next.text_signatures.push(retained.clone());
        // Exact total encoded record budget, checked BEFORE signing or CAS.
        // 32 is an entry cap, not a promise of 32 maximum-sized text inputs.
        self.store.validate_record(STATE_OWNER, &next)?;
        let unsigned = envelope(&state.signer_id, &retained, body.clone());
        let claims =
            crate::authbus_text_claims(&identity.agent_id, &unsigned).map_err(io::Error::other)?;
        retained.signature_hex = self
            .key
            .sign(&claims.signing_bytes())
            .to_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        let signed = envelope(&state.signer_id, &retained, body);
        *next
            .text_signatures
            .last_mut()
            .expect("reserved original reference") = retained;
        // The exact signature and shared sequence commit in the SAME original
        // issuer CAS. A lost response reopens this record without new signing.
        self.store
            .compare_and_set(STATE_OWNER, &state, &next)
            .map_err(io::Error::other)?;
        let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
        if after < now || after >= signed.expires_at_ms {
            return Err(io::Error::other("text expired during signing"));
        }
        Ok(signed)
    }
}

fn intent_number(request_id: &str) -> io::Result<u64> {
    let suffix = request_id
        .rsplit_once(':')
        .map(|(_, suffix)| suffix)
        .ok_or_else(|| io::Error::other("text intent requires a monotonic numeric suffix"))?;
    let number = suffix.parse::<u64>().map_err(io::Error::other)?;
    if number == 0 || number.to_string() != suffix {
        return Err(io::Error::other("invalid text intent sequence"));
    }
    Ok(number)
}

fn envelope(
    signer: &str,
    retained: &RetainedTextSignature,
    body: AuthBusTextBody,
) -> AuthBusTextIngress {
    AuthBusTextIngress {
        issuer_id: signer.into(),
        key_epoch: retained.key_epoch,
        message_id: format!("{signer}:text:{}:{}", retained.key_epoch, retained.sequence),
        sequence: retained.sequence,
        expires_at_ms: retained.expires_at_ms,
        signature_hex: retained.signature_hex.clone(),
        body,
    }
}

#[cfg(test)]
#[path = "deployment_text_tests.rs"]
mod tests;
