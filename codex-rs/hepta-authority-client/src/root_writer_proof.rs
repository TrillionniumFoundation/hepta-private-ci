//! A retained root signature, converted only after strict verification. The
//! original writer's `from_verified_parts` is a shape check, never our verifier.

use codex_hepta_authority_types::ProductionAuthorityLease;
use codex_hepta_authority_types::ProductionAuthorityToken;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::HOST_AUTHORITY_OBSERVATION_V2;
use crate::HostAuthorityObservationResponseV2;
use crate::HostSignedWriterAuthorizationV1;

/// Trusted launch configuration for exactly one root registration. In
/// particular, `authority_lease` comes from that registration, not the UI or
/// the unverified proof. The key is the original canonical issuer public key.
#[derive(Clone)]
pub struct AgentdRootWriterTrust {
    pub issuer_id: String,
    pub verifying_key: [u8; 32],
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub owner_epoch: u64,
    pub local_lease_id: String,
    pub local_lease_generation: u64,
    pub authority_lease: AuthorityLease,
}

/// Opaque evidence from the original strict signature and registration checks.
/// Callers must independently pin the trust input. Verification alone proves no
/// process lifetime, clock freshness, current revocations or execution grant;
/// only the actual retained RootSession installs a live writer verifier.
pub struct VerifiedRootWriterProof {
    proof: HostSignedWriterAuthorizationV1,
    authority: ProductionAuthorityLease,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum AgentdRootAuthorityError {
    #[error("protected root authority configuration or proof was refused")]
    Refused,
    #[error("protected root authority observation is unavailable or fenced")]
    Unavailable,
}

impl VerifiedRootWriterProof {
    pub fn verify(
        proof: HostSignedWriterAuthorizationV1,
        trust: &AgentdRootWriterTrust,
    ) -> Result<Self, AgentdRootAuthorityError> {
        let claims = &proof.claims;
        let lease = &claims.authority_lease;
        trust
            .authority_lease
            .validate()
            .map_err(|_| AgentdRootAuthorityError::Refused)?;
        let canonical_lease =
            serde_json::to_vec(lease).map_err(|_| AgentdRootAuthorityError::Refused)?;
        if !identifier(&trust.issuer_id)
            || !identifier(&trust.local_lease_id)
            || trust.spawn_generation == 0
            || trust.owner_epoch == 0
            || trust.local_lease_generation == 0
            || claims.schema_version != 1
            || claims.sequence == 0
            || claims.issuer_id != trust.issuer_id
            || claims.registered_agent_id != trust.agent_id
            || claims.spawn_generation != trust.spawn_generation
            || claims.owner_epoch != trust.owner_epoch
            || claims.local_lease_id != trust.local_lease_id
            || claims.local_lease_generation != trust.local_lease_generation
            || *lease != trust.authority_lease
            || lease.binding.principal_id != trust.agent_id.as_str()
            || lease.binding.operation_class != "runtime.agentd.production_writer"
            || claims.authority_lease_sha256 != Sha256Digest::for_bytes(&canonical_lease)
            || proof.signature_hex.len() != 128
            || !proof
                .signature_hex
                .bytes()
                .all(|value| matches!(value, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let key = VerifyingKey::from_bytes(&trust.verifying_key)
            .map_err(|_| AgentdRootAuthorityError::Refused)?;
        if key.is_weak() {
            return Err(AgentdRootAuthorityError::Refused);
        }
        let mut signature_bytes = [0; 64];
        for (index, output) in signature_bytes.iter_mut().enumerate() {
            *output = u8::from_str_radix(&proof.signature_hex[index * 2..index * 2 + 2], 16)
                .map_err(|_| AgentdRootAuthorityError::Refused)?;
        }
        key.verify_strict(
            &claims
                .signing_bytes()
                .map_err(|_| AgentdRootAuthorityError::Refused)?,
            &Signature::from_bytes(&signature_bytes),
        )
        .map_err(|_| AgentdRootAuthorityError::Refused)?;
        // Hash the entire signed proof; never substitute the unsigned claims
        // hash or a FinalUse nonce. The token is the already verified ASCII
        // signature spelling, not arbitrary local entropy or a hash seed.
        let authority = ProductionAuthorityLease::from_verified_parts(
            trust.agent_id.clone(),
            proof
                .sha256()
                .map_err(|_| AgentdRootAuthorityError::Refused)?,
            lease.authority_epoch,
            trust.owner_epoch,
            lease.expires_at_unix_ms / 1000,
            ProductionAuthorityToken::from_verified_bytes(proof.signature_hex.as_bytes().to_vec())
                .map_err(|_| AgentdRootAuthorityError::Refused)?,
        )
        .map_err(|_| AgentdRootAuthorityError::Refused)?;
        Ok(Self { proof, authority })
    }

    pub fn authority(&self) -> &ProductionAuthorityLease {
        &self.authority
    }

    /// Static identity/proof binding. Clock, global revision and revocation
    /// freshness are checked separately by the protected observation cache.
    pub(crate) fn matches_observation(
        &self,
        value: &HostAuthorityObservationResponseV2,
    ) -> Result<(), AgentdRootAuthorityError> {
        let claims = &self.proof.claims;
        let writer = &value.writer;
        if value.schema_version != 2
            || value.operation != HOST_AUTHORITY_OBSERVATION_V2
            || value.registered_agent_id != claims.registered_agent_id
            || value.spawn_generation != claims.spawn_generation
            || value.authority_epoch != claims.authority_lease.authority_epoch
            || value.revocations.authority_epoch != value.authority_epoch
            || writer.authority_lease != claims.authority_lease
            || writer.authority_lease_sha256 != claims.authority_lease_sha256
            || writer.owner_epoch != claims.owner_epoch
            || writer.local_lease_id != claims.local_lease_id
            || writer.local_lease_generation != claims.local_lease_generation
            || writer.writer_authorization_sha256 != self.authority.grant_digest
            || writer.store_revision < claims.authority_lease.revision
            || value.observed_unix_ms < claims.authority_lease.issued_at_unix_ms
            || value.observed_unix_ms
                >= self
                    .authority
                    .lease_expires_at_unix_seconds
                    .saturating_mul(1000)
        {
            return Err(AgentdRootAuthorityError::Refused);
        }
        Ok(())
    }
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}

#[cfg(test)]
#[path = "root_writer_proof_tests.rs"]
pub(crate) mod tests;
