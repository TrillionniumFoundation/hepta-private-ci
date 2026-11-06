//! Explicit grant, artifact and recovery roles authorized by one current M15
//! ProtocolConfiguration publication. Parsing a policy alone grants no authority.
use super::*;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SIGNATURE_BYTES;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SPKI_BYTES;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_memory::H7SignedArtifactError;
use std::sync::Arc;

pub const MAX_PRODUCTION_AUTHORITY_POLICY_BYTES: u64 = 16_384;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PqAuthorityBinding {
    pub policy_sha256: Sha256Digest,
    pub signer_public_key_id: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionAuthorityRoleV1 {
    pub signer_id: String,
    pub signer_epoch: u64,
    pub public_key_id: [u8; 32],
    pub public_spki_base64: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionAuthorityPolicyV1 {
    pub schema_version: u32,
    pub algorithm: String,
    pub grant: ProductionAuthorityRoleV1,
    pub artifact: ProductionAuthorityRoleV1,
    pub recovery: ProductionAuthorityRoleV1,
}

// A private, single-construction owner for all three validated role keys.
// These immutable verification inputs carry no current Fleet permission.
struct ValidatedPolicy {
    policy: ProductionAuthorityPolicyV1,
    policy_sha256: Sha256Digest,
    grant: PqNativeVerifier,
    artifact: PqNativeVerifier,
    recovery: PqNativeVerifier,
}

pub(super) fn decode_policy(
    bytes: &[u8],
) -> Result<(ProductionAuthorityPolicyV1, Sha256Digest), ProductionAuthorityError> {
    let validated = decode_policy_with_keys(bytes)?;
    Ok((validated.policy, validated.policy_sha256))
}

fn decode_policy_header(
    bytes: &[u8],
) -> Result<ProductionAuthorityPolicyV1, ProductionAuthorityError> {
    if bytes.is_empty() || bytes.len() as u64 > MAX_PRODUCTION_AUTHORITY_POLICY_BYTES {
        return Err(ProductionAuthorityError::Invalid(
            "production authority policy exceeds its bound".to_string(),
        ));
    }
    let policy: ProductionAuthorityPolicyV1 = serde_json::from_slice(bytes)
        .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?;
    if policy.schema_version != 1
        || policy.algorithm != "ml_dsa65_v2"
        || policy.grant.public_key_id == policy.artifact.public_key_id
        || policy.grant.public_key_id == policy.recovery.public_key_id
        || policy.artifact.public_key_id == policy.recovery.public_key_id
    {
        return Err(ProductionAuthorityError::Invalid(
            "three distinct explicit ML-DSA-65 authority roles are required".to_string(),
        ));
    }
    Ok(policy)
}

fn decode_policy_with_keys(bytes: &[u8]) -> Result<ValidatedPolicy, ProductionAuthorityError> {
    let policy = decode_policy_header(bytes)?;
    let grant = policy.grant.verifier()?;
    let artifact = policy.artifact.verifier()?;
    let recovery = policy.recovery.verifier()?;
    Ok(ValidatedPolicy {
        policy,
        policy_sha256: Sha256Digest::for_bytes(bytes),
        grant,
        artifact,
        recovery,
    })
}

impl ProductionAuthorityRoleV1 {
    pub(super) fn verifier(&self) -> Result<PqNativeVerifier, ProductionAuthorityError> {
        let spki = self.decode_spki()?;
        PqNativeVerifier::from_pinned_spki(&spki, self.public_key_id).map_err(|_| {
            ProductionAuthorityError::Invalid(
                "PQ authority key does not match its canonical pin".to_string(),
            )
        })
    }

    fn decode_spki(&self) -> Result<Vec<u8>, ProductionAuthorityError> {
        validate_identifier(&self.signer_id, "PQ authority signer id")?;
        if self.signer_epoch == 0
            || self.public_spki_base64.len() != ML_DSA_65_SPKI_BYTES.div_ceil(3) * 4
        {
            return Err(ProductionAuthorityError::Invalid(
                "PQ authority key or epoch is malformed".to_string(),
            ));
        }
        let spki = STANDARD
            .decode(&self.public_spki_base64)
            .map_err(|_| ProductionAuthorityError::SignatureMalformed)?;
        if STANDARD.encode(&spki) != self.public_spki_base64 {
            return Err(ProductionAuthorityError::SignatureMalformed);
        }
        Ok(spki)
    }
}

pub(super) struct PqVerificationKeys {
    pub(super) policy_sha256: Sha256Digest,
    policy_bytes: Vec<u8>,
    pub(super) grant: PqNativeVerifier,
    pub(super) recovery: PqNativeVerifier,
    recovery_id: String,
    recovery_epoch: u64,
}

#[derive(Clone)]
pub(super) enum AuthorityVerificationKeys {
    Classical(VerifyingKey),
    Pq(Arc<PqVerificationKeys>),
}

impl H7H89ProductionGrantVerifier {
    /// Structural validation only: no prepared key, signature result or current
    /// authority is returned. The signature path still constructs its verifier.
    pub(crate) fn validate_pq_policy_shape(
        bytes: &[u8],
    ) -> Result<Sha256Digest, ProductionAuthorityError> {
        let policy = decode_policy_header(bytes)?;
        for role in [&policy.grant, &policy.artifact, &policy.recovery] {
            let spki = role.decode_spki()?;
            if ml_dsa_65_key_id_from_spki(&spki).ok() != Some(role.public_key_id) {
                return Err(ProductionAuthorityError::Invalid(
                    "PQ authority key does not match its canonical pin".to_string(),
                ));
            }
        }
        // The role checks already enforce the artifact identifier and epoch.
        // Preserve Memory's additional rejection, after all three role keys.
        if policy.artifact.public_key_id == [0; 32] {
            return Err(ProductionAuthorityError::H7Binding(
                H7SignedArtifactError::Invalid(
                    "PQ artifact epoch or key ID is invalid".to_string(),
                )
                .to_string(),
            ));
        }
        Ok(Sha256Digest::for_bytes(bytes))
    }

    /// The raw policy bytes must separately be admitted by the current Fleet
    /// publication owner. This constructor never manufactures that admission.
    pub fn from_pq_policy_bytes(bytes: &[u8]) -> Result<Self, ProductionAuthorityError> {
        let ValidatedPolicy {
            policy,
            policy_sha256,
            grant,
            artifact,
            recovery,
        } = decode_policy_with_keys(bytes)?;
        let h7_verifier = H7ArtifactVerifier::from_pinned_spki(
            policy.artifact.signer_id.clone(),
            policy.artifact.signer_epoch,
            artifact.public_spki(),
            artifact.public_key_id(),
        )
        .map_err(|error| ProductionAuthorityError::H7Binding(error.to_string()))?;
        Ok(Self {
            signer_id: policy.grant.signer_id,
            signer_epoch: policy.grant.signer_epoch,
            keys: AuthorityVerificationKeys::Pq(Arc::new(PqVerificationKeys {
                policy_sha256,
                policy_bytes: bytes.to_vec(),
                grant,
                recovery,
                recovery_id: policy.recovery.signer_id,
                recovery_epoch: policy.recovery.signer_epoch,
            })),
            h7_verifier,
        })
    }

    pub fn read_pq_policy(path: &std::path::Path) -> Result<Self, ProductionAuthorityError> {
        let bytes =
            crate::bounded_regular_file::read_optional(path, MAX_PRODUCTION_AUTHORITY_POLICY_BYTES)
                .map_err(|error| ProductionAuthorityError::Invalid(error.to_string()))?
                .ok_or_else(|| {
                    ProductionAuthorityError::Invalid(
                        "production authority policy is missing".to_string(),
                    )
                })?;
        Self::from_pq_policy_bytes(&bytes)
    }

    pub(crate) fn policy_bytes(&self) -> Option<&[u8]> {
        match &self.keys {
            AuthorityVerificationKeys::Classical(_) => None,
            AuthorityVerificationKeys::Pq(keys) => Some(&keys.policy_bytes),
        }
    }

    pub fn policy_sha256(&self) -> Option<&Sha256Digest> {
        match &self.keys {
            AuthorityVerificationKeys::Classical(_) => None,
            AuthorityVerificationKeys::Pq(keys) => Some(&keys.policy_sha256),
        }
    }
}

impl AuthorityVerificationKeys {
    pub(super) fn recovery_identity<'a>(
        &'a self,
        legacy_id: &'a str,
        legacy_epoch: u64,
    ) -> (&'a str, u64) {
        match self {
            Self::Classical(_) => (legacy_id, legacy_epoch),
            Self::Pq(keys) => (&keys.recovery_id, keys.recovery_epoch),
        }
    }

    pub(super) fn verify_grant(
        &self,
        grant: &H7H89ProductionGrant,
    ) -> Result<(), ProductionAuthorityError> {
        self.verify(
            grant.pq_authority.as_ref(),
            &grant.signature_base64,
            &grant.signing_bytes(),
            AuthorityRole::Grant,
        )
    }

    pub(super) fn verify_recovery(
        &self,
        decision: &ProductionRecoveryDecision,
    ) -> Result<(), ProductionAuthorityError> {
        self.verify(
            decision.pq_authority.as_ref(),
            &decision.signature_base64,
            &decision.signing_bytes(),
            AuthorityRole::Recovery,
        )
    }

    fn verify(
        &self,
        binding: Option<&PqAuthorityBinding>,
        encoded: &str,
        message: &[u8],
        role: AuthorityRole,
    ) -> Result<(), ProductionAuthorityError> {
        let size = match self {
            Self::Classical(_) => 64,
            Self::Pq(_) => ML_DSA_65_SIGNATURE_BYTES,
        };
        if encoded.len() != size.div_ceil(3) * 4 {
            return Err(ProductionAuthorityError::SignatureMalformed);
        }
        let bytes = STANDARD
            .decode(encoded)
            .map_err(|_| ProductionAuthorityError::SignatureMalformed)?;
        if bytes.len() != size || STANDARD.encode(&bytes) != encoded {
            return Err(ProductionAuthorityError::SignatureMalformed);
        }
        match self {
            Self::Classical(key) => {
                if binding.is_some() {
                    return Err(ProductionAuthorityError::Boundary);
                }
                let signature = Signature::from_slice(&bytes)
                    .map_err(|_| ProductionAuthorityError::SignatureMalformed)?;
                key.verify(message, &signature)
                    .map_err(|_| ProductionAuthorityError::SignatureInvalid)
            }
            Self::Pq(keys) => {
                let key = match role {
                    AuthorityRole::Grant => &keys.grant,
                    AuthorityRole::Recovery => &keys.recovery,
                };
                let expected = PqAuthorityBinding {
                    policy_sha256: keys.policy_sha256.clone(),
                    signer_public_key_id: key.public_key_id(),
                };
                if binding != Some(&expected) {
                    return Err(ProductionAuthorityError::Boundary);
                }
                key.verify_exact_message(message, &bytes)
                    .map(|_| ())
                    .map_err(|_| ProductionAuthorityError::SignatureInvalid)
            }
        }
    }
}

enum AuthorityRole {
    Grant,
    Recovery,
}
