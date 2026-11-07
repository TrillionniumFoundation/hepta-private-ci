//! Owned external PQ role signers. No role is inferred from another role's key.
use super::*;
use crate::signed_intent::SignedSupervisorIntent;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_fleet::ReleaseBinding;

pub struct H7PqProductionGrantSigner {
    role: PqRoleSigner,
    artifact_public_key_id: [u8; 32],
}

pub struct H7PqProductionRecoverySigner {
    role: PqRoleSigner,
}

struct PqRoleSigner {
    identity: ProductionAuthorityRoleV1,
    binding: PqAuthorityBinding,
    key: PqNativeSigningKey,
}

impl PqRoleSigner {
    fn new(
        identity: ProductionAuthorityRoleV1,
        policy_sha256: Sha256Digest,
        key: PqNativeSigningKey,
    ) -> Result<Self, ProductionAuthorityError> {
        let verifier = identity.verifier()?;
        if verifier.public_key_id() != key.public_key_id()
            || verifier.public_spki() != key.public_spki()
        {
            return Err(ProductionAuthorityError::SignerMismatch);
        }
        Ok(Self {
            binding: PqAuthorityBinding {
                policy_sha256,
                signer_public_key_id: identity.public_key_id,
            },
            identity,
            key,
        })
    }

    fn sign(&self, bytes: &[u8]) -> Result<String, ProductionAuthorityError> {
        self.key
            .sign_exact_message(bytes)
            .map(|signature| STANDARD.encode(signature))
            .map_err(|_| ProductionAuthorityError::SignatureInvalid)
    }
}

impl H7PqProductionGrantSigner {
    pub fn new(
        policy_bytes: &[u8],
        key: PqNativeSigningKey,
    ) -> Result<Self, ProductionAuthorityError> {
        let (policy, digest) = policy::decode_policy(policy_bytes)?;
        Ok(Self {
            role: PqRoleSigner::new(policy.grant, digest, key)?,
            artifact_public_key_id: policy.artifact.public_key_id,
        })
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "all original grant bindings remain explicit"
    )]
    pub fn sign(
        &self,
        agent_id: &AgentId,
        source_release: impl Into<String>,
        target_release: impl Into<String>,
        transition: H7H89ProductionTransition,
        h7_envelope: &H7SignedArtifactEnvelope,
        expected_control_revision: u64,
        expected_lifecycle_generation: u64,
        authority_epoch: u64,
        issued_at_unix_seconds: u64,
        expires_at_unix_seconds: u64,
    ) -> Result<H7H89ProductionGrant, ProductionAuthorityError> {
        if h7_envelope.signer_public_key_id != Some(self.artifact_public_key_id) {
            return Err(ProductionAuthorityError::H7Binding(
                "artifact must use its independent PQ policy role".to_string(),
            ));
        }
        let mut grant = unsigned::grant(
            &self.role.identity.signer_id,
            self.role.identity.signer_epoch,
            agent_id,
            source_release,
            target_release,
            transition,
            h7_envelope,
            expected_control_revision,
            expected_lifecycle_generation,
            authority_epoch,
            issued_at_unix_seconds,
            expires_at_unix_seconds,
        )?;
        grant.schema_version = 2;
        grant.namespace = pq_wire::GRANT_NAMESPACE.to_string();
        grant.pq_authority = Some(self.role.binding.clone());
        grant.grant_sha256 = grant.payload_digest();
        grant.signature_base64 = self.role.sign(&grant.signing_bytes())?;
        grant.validate_shape(h7_envelope)?;
        Ok(grant)
    }
}

#[path = "signed_authority_pq_recovery.rs"]
mod recovery;

#[path = "signed_authority_pq_retained.rs"]
mod retained;
