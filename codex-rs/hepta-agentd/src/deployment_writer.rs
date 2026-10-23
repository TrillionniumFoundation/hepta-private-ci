//! Root administrative writer registration in the canonical issuer's state.
//! Ordinary reads return a retained proof; they never mint a replacement grant.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::VerifiedUseAuthorityRefV1;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;
use codex_hepta_contracts::authority_lease::dispatch_authority_lease_with_witness;
use ed25519_dalek::Signature;

use crate::HostSignedWriterAuthorizationV1;
use crate::HostWriterAuthorizationClaimsV1;

/// Exact trusted launcher inputs. This is an administrative registration,
/// never a value accepted from an ordinary service request or audit witness.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostAuthorityWriterRegistration {
    pub registered_agent_id: AgentId,
    pub spawn_generation: u64,
    pub owner_epoch: u64,
    pub local_lease_id: String,
    pub local_lease_generation: u64,
    pub authority_lease: AuthorityLease,
}

impl HostAuthorityWriterRegistration {
    pub(crate) fn validate(&self) -> io::Result<()> {
        if self.spawn_generation == 0
            || self.owner_epoch == 0
            || self.local_lease_generation == 0
            || self.local_lease_id.is_empty()
            || self.local_lease_id.len() > 128
            || self.local_lease_id.as_bytes().contains(&0)
            || self.authority_lease.binding.principal_id != self.registered_agent_id.as_str()
            || self.authority_lease.binding.operation_class != "runtime.agentd.production_writer"
        {
            return Err(io::Error::other("invalid trusted writer registration"));
        }
        Ok(())
    }

    pub(crate) fn with_live<T>(
        &self,
        verifier: &AuthorityLeaseVerifier,
        dispatch: impl FnOnce(u64) -> io::Result<T>,
    ) -> io::Result<T> {
        self.validate()?;
        let lease = verifier
            .read_lease(&self.authority_lease.lease_id)
            .map_err(root::lease_error)?
            .ok_or_else(|| io::Error::other("writer lease missing"))?
            .lease;
        if lease != self.authority_lease {
            return Err(io::Error::other("writer lease changed"));
        }
        let token = verifier
            .verify_use(&lease.lease_id, lease.revision, &lease.binding)
            .map_err(root::lease_error)?;
        let (result, _) =
            dispatch_authority_lease_with_witness(verifier, token, &lease.binding, |witness| {
                match &witness.authority_ref {
                    // Metadata only. The original opaque token and owner fence,
                    // rather than the serializable witness, authorize this call.
                    VerifiedUseAuthorityRefV1::AuthorityLease(reference) => {
                        dispatch(reference.store_revision)
                    }
                    VerifiedUseAuthorityRefV1::FinalUse(_) => {
                        Err(io::Error::other("wrong original authority family"))
                    }
                }
            })
            .map_err(root::lease_error)?;
        result
    }
}

impl DeploymentFinalUseIssuer {
    /// The caller holds both original lease tokens through this local signing
    /// boundary. Check the exact retained proof under the same issuer lock as
    /// the original policy, durable sequence reservation and signature.
    pub(super) fn issue_registered_final_use(
        &self,
        binding: &FinalUseBinding,
        registration: &HostAuthorityWriterRegistration,
        proof: &HostSignedWriterAuthorizationV1,
        expiry: u64,
    ) -> io::Result<Option<SignedFinalUseGrant>> {
        self.issue_until_checked(
            binding,
            Some(registration.authority_lease.authority_epoch),
            expiry,
            |state| {
                if state.writer_authorization.as_ref() != Some(proof) {
                    return Err(io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        "registered writer proof changed",
                    ));
                }
                self.validate_writer_proof(state, registration, proof)
            },
        )
    }

    /// Explicit trusted-root registration, once per retained writer identity.
    /// It uses the original lease verifier and this issuer's shared durable
    /// sequence/key. A different registration is never implicitly substituted.
    pub fn register_writer_authorization(
        &self,
        registration: &HostAuthorityWriterRegistration,
        verifier: &AuthorityLeaseVerifier,
    ) -> io::Result<HostSignedWriterAuthorizationV1> {
        if self.lease.is_none() {
            return Err(io::Error::other("protected issuer required"));
        }
        registration.with_live(verifier, |_| {
            let _guard = self
                .request_lock
                .lock()
                .map_err(|_| io::Error::other("issuer fenced"))?;
            let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
            if let Some(proof) = &state.writer_authorization {
                self.validate_writer_proof(&state, registration, proof)?;
                return Ok(proof.clone());
            }
            let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
            validate_writer_time(registration, state.head.authority_epoch, now)?;
            self.retain_writer_authorization(&state, registration, now)
        })
    }

    fn retain_writer_authorization(
        &self,
        state: &IssuerState,
        registration: &HostAuthorityWriterRegistration,
        now: u64,
    ) -> io::Result<HostSignedWriterAuthorizationV1> {
        let mut reserved = state.clone();
        reserved.sequence = state
            .sequence
            .checked_add(1)
            .ok_or_else(|| io::Error::other("issuer counter exhausted"))?;
        let claims = HostWriterAuthorizationClaimsV1 {
            schema_version: 1,
            issuer_id: state.signer_id.clone(),
            sequence: reserved.sequence,
            registered_agent_id: registration.registered_agent_id.clone(),
            spawn_generation: registration.spawn_generation,
            owner_epoch: registration.owner_epoch,
            local_lease_id: registration.local_lease_id.clone(),
            local_lease_generation: registration.local_lease_generation,
            authority_lease: registration.authority_lease.clone(),
            authority_lease_sha256: Sha256Digest::for_bytes(&serde_json::to_vec(
                &registration.authority_lease,
            )?),
        };
        let bytes = claims.signing_bytes()?;
        self.store
            .compare_and_set(STATE_OWNER, state, &reserved)
            .map_err(io::Error::other)?;
        let proof = HostSignedWriterAuthorizationV1 {
            claims,
            signature_hex: self
                .key
                .sign(&bytes)
                .to_bytes()
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect(),
        };
        // I/O may outlive the lease. Never refund the reserved sequence.
        let after = self.clock.now_unix_ms().map_err(io::Error::other)?;
        if after < now {
            return Err(io::Error::other("writer clock regressed"));
        }
        validate_writer_time(registration, state.head.authority_epoch, after)?;
        let mut retained = reserved.clone();
        retained.writer_authorization = Some(proof.clone());
        self.store
            .compare_and_set(STATE_OWNER, &reserved, &retained)
            .map_err(io::Error::other)?;
        self.validate_writer_proof(&retained, registration, &proof)?;
        Ok(proof)
    }

    /// Open-only read for a trusted service registration. The caller retains
    /// the original verifier fence through its final clock/head observation.
    pub(crate) fn retained_writer_authorization(
        &self,
        registration: &HostAuthorityWriterRegistration,
    ) -> io::Result<HostSignedWriterAuthorizationV1> {
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let proof = state
            .writer_authorization
            .as_ref()
            .ok_or_else(|| io::Error::other("writer not provisioned"))?;
        self.validate_writer_proof(&state, registration, proof)?;
        Ok(proof.clone())
    }

    fn validate_writer_proof(
        &self,
        state: &IssuerState,
        registration: &HostAuthorityWriterRegistration,
        proof: &HostSignedWriterAuthorizationV1,
    ) -> io::Result<()> {
        self.validate_writer_proof_identity(state, registration, proof)?;
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        validate_writer_time(registration, state.head.authority_epoch, now)
    }
    // Authentication of a retired predecessor is deliberately independent of
    // temporal liveness. Its retirement is proved by the original registry.
    fn validate_writer_proof_identity(
        &self,
        state: &IssuerState,
        registration: &HostAuthorityWriterRegistration,
        proof: &HostSignedWriterAuthorizationV1,
    ) -> io::Result<()> {
        let claims = &proof.claims;
        registration.validate()?;
        if claims.schema_version != 1
            || claims.issuer_id != state.signer_id
            || claims.sequence == 0
            || claims.sequence > state.sequence
            || claims.registered_agent_id != registration.registered_agent_id
            || claims.spawn_generation != registration.spawn_generation
            || claims.owner_epoch != registration.owner_epoch
            || claims.local_lease_id != registration.local_lease_id
            || claims.local_lease_generation != registration.local_lease_generation
            || claims.authority_lease != registration.authority_lease
            || claims.authority_lease_sha256
                != Sha256Digest::for_bytes(&serde_json::to_vec(&registration.authority_lease)?)
        {
            return Err(io::Error::other("retained writer registration mismatch"));
        }
        if proof.signature_hex.len() != 128
            || !proof
                .signature_hex
                .bytes()
                .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err(io::Error::other("invalid retained signature"));
        }
        let mut signature = [0; 64];
        for (index, byte) in signature.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&proof.signature_hex[index * 2..index * 2 + 2], 16)
                .map_err(io::Error::other)?;
        }
        let signature = Signature::from_bytes(&signature);
        self.key
            .verifying_key()
            .verify_strict(&claims.signing_bytes()?, &signature)
            .map_err(io::Error::other)?;
        Ok(())
    }
}

pub(crate) fn validate_writer_time(
    registration: &HostAuthorityWriterRegistration,
    epoch: u64,
    now: u64,
) -> io::Result<()> {
    let lease = &registration.authority_lease;
    if lease.authority_epoch != epoch
        || now < lease.issued_at_unix_ms
        || now >= lease.expires_at_unix_ms
    {
        return Err(io::Error::other("writer lease expired or epoch changed"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "deployment_writer_tests.rs"]
mod tests;

#[path = "deployment_writer_rotate.rs"]
mod rotation;
