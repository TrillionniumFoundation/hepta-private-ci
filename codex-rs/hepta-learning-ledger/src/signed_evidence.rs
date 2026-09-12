//! Cryptographic admission for learning evidence. Trust configuration must come
//! from the host's authority store, never from the submitted evidence. A valid
//! signature authenticates an attestation; it does not prove its scientific
//! truth, independence of organizations, or permission to promote a candidate.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

use crate::AuthenticatedPrincipalV1;
use crate::CausalV2Error;
use crate::verify_independent_roles;

const MAX_SIGNERS: usize = 64;
const MAX_PAYLOAD_BYTES: usize = 1_048_576;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum LearningEvidenceRoleV1 {
    Generator,
    Observer,
    Evaluator,
}

impl LearningEvidenceRoleV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Generator => 0,
            Self::Observer => 1,
            Self::Evaluator => 2,
        }
    }
}

/// Host-authorized key and role assignment. `controller_id` identifies the
/// controlling authority across credentials; changing keys does not establish
/// independent evaluation. The host remains responsible for this mapping.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedLearningSignerV1 {
    pub principal: AuthenticatedPrincipalV1,
    pub controller_id: StableId,
    pub verifying_key: [u8; 32],
    pub roles: Vec<LearningEvidenceRoleV1>,
    pub revoked_at: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningEvidenceTrustV1 {
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
    pub signers: Vec<TrustedLearningSignerV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedLearningEvidenceV1 {
    pub evidence_id: StableId,
    pub principal_id: StableId,
    pub role: LearningEvidenceRoleV1,
    pub trust_digest: Digest32,
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub payload_digest: Digest32,
    pub signature: [u8; 64],
}

impl SignedLearningEvidenceV1 {
    /// Canonical bytes signed with Ed25519; the signature itself is excluded.
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-ledger.signed-evidence.v1".to_vec();
        push_id(&mut bytes, &self.evidence_id);
        push_id(&mut bytes, &self.principal_id);
        bytes.push(self.role.tag());
        for digest in [self.trust_digest, self.scope_digest, self.objective_digest] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [self.authority_epoch, self.issued_at, self.expires_at] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes
    }
}

/// Only `LearningEvidenceVerifierV1` can construct this value. It is valid for
/// the verifier's immutable trust snapshot and the admitted payload, not an
/// unbounded authorization token. Reverify after rotation or revocation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedLearningEvidenceV1 {
    principal: AuthenticatedPrincipalV1,
    controller_id: StableId,
    role: LearningEvidenceRoleV1,
    trust_digest: Digest32,
    objective_digest: Digest32,
    payload_digest: Digest32,
    issued_at: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}

impl VerifiedLearningEvidenceV1 {
    #[must_use]
    pub fn principal(&self) -> &AuthenticatedPrincipalV1 {
        &self.principal
    }
    #[must_use]
    pub fn role(&self) -> LearningEvidenceRoleV1 {
        self.role
    }
    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }
}

#[derive(Clone, Debug)]
pub struct LearningEvidenceVerifierV1 {
    scope_digest: Digest32,
    objective_digest: Digest32,
    authority_epoch: u64,
    trust_digest: Digest32,
    signers: BTreeMap<StableId, TrustedLearningSignerV1>,
}

impl LearningEvidenceVerifierV1 {
    /// Constructs a verifier from host-owned trust state. Remote evidence must
    /// not be allowed to choose this state or replace the verifier's epoch.
    pub fn new(trust: LearningEvidenceTrustV1) -> Result<Self, SignedEvidenceError> {
        if trust.scope_digest == Digest32::ZERO
            || trust.objective_digest == Digest32::ZERO
            || trust.authority_epoch == 0
            || trust.signers.is_empty()
            || trust.signers.len() > MAX_SIGNERS
        {
            return Err(SignedEvidenceError::InvalidTrust);
        }
        let mut signers = BTreeMap::new();
        for mut signer in trust.signers {
            signer
                .principal
                .validate(signer.principal.authenticated_at)?;
            if signer.principal.scope_digest != trust.scope_digest
                || signer.principal.authority_epoch != trust.authority_epoch
                || signer.principal.signing_key_digest != Digest32::of_bytes(&signer.verifying_key)
                || signer.roles.is_empty()
                || signer.roles.len() > 3
            {
                return Err(SignedEvidenceError::InvalidTrust);
            }
            let key = VerifyingKey::from_bytes(&signer.verifying_key)
                .map_err(|_| SignedEvidenceError::InvalidKey)?;
            if key.is_weak() {
                return Err(SignedEvidenceError::InvalidKey);
            }
            signer.roles.sort();
            if signer.roles.windows(2).any(|pair| pair[0] == pair[1]) {
                return Err(SignedEvidenceError::InvalidTrust);
            }
            if signers
                .insert(signer.principal.principal_id.clone(), signer)
                .is_some()
            {
                return Err(SignedEvidenceError::InvalidTrust);
            }
        }
        let mut bytes = b"hepta.learning-ledger.evidence-trust.v1".to_vec();
        bytes.extend_from_slice(trust.scope_digest.as_array());
        bytes.extend_from_slice(trust.objective_digest.as_array());
        bytes.extend_from_slice(&trust.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&(signers.len() as u64).to_be_bytes());
        for signer in signers.values() {
            push_id(&mut bytes, &signer.principal.principal_id);
            push_id(&mut bytes, &signer.controller_id);
            bytes.extend_from_slice(signer.principal.credential_chain_digest.as_array());
            bytes.extend_from_slice(&signer.verifying_key);
            bytes.extend_from_slice(&signer.principal.authenticated_at.to_be_bytes());
            bytes.extend_from_slice(&signer.principal.expires_at.to_be_bytes());
            bytes.extend_from_slice(&(signer.roles.len() as u64).to_be_bytes());
            for role in &signer.roles {
                bytes.push(role.tag());
            }
            match signer.revoked_at {
                Some(at) => {
                    bytes.push(1);
                    bytes.extend_from_slice(&at.to_be_bytes());
                }
                None => bytes.push(0),
            }
        }
        Ok(Self {
            scope_digest: trust.scope_digest,
            objective_digest: trust.objective_digest,
            authority_epoch: trust.authority_epoch,
            trust_digest: Digest32::of_bytes(&bytes),
            signers,
        })
    }

    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    pub fn verify(
        &self,
        expected_role: LearningEvidenceRoleV1,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<VerifiedLearningEvidenceV1, SignedEvidenceError> {
        if payload.len() > MAX_PAYLOAD_BYTES {
            return Err(SignedEvidenceError::PayloadLimit);
        }
        if evidence.role != expected_role {
            return Err(SignedEvidenceError::RoleMismatch);
        }
        if evidence.trust_digest != self.trust_digest
            || evidence.scope_digest != self.scope_digest
            || evidence.objective_digest != self.objective_digest
            || evidence.authority_epoch != self.authority_epoch
        {
            return Err(SignedEvidenceError::ContextMismatch);
        }
        let signer = self
            .signers
            .get(&evidence.principal_id)
            .ok_or(SignedEvidenceError::UnknownSigner)?;
        signer.principal.validate(now)?;
        if signer.revoked_at.is_some_and(|at| now >= at) {
            return Err(SignedEvidenceError::Revoked);
        }
        if !signer.roles.contains(&expected_role) {
            return Err(SignedEvidenceError::RoleMismatch);
        }
        if evidence.issued_at > now
            || now > evidence.expires_at
            || evidence.issued_at > evidence.expires_at
            || evidence.issued_at < signer.principal.authenticated_at
            || evidence.expires_at > signer.principal.expires_at
        {
            return Err(SignedEvidenceError::ValidityWindow);
        }
        if Digest32::of_bytes(payload) != evidence.payload_digest {
            return Err(SignedEvidenceError::PayloadMismatch);
        }
        VerifyingKey::from_bytes(&signer.verifying_key)
            .map_err(|_| SignedEvidenceError::InvalidKey)?
            .verify_strict(
                &evidence.signing_bytes(),
                &Signature::from_bytes(&evidence.signature),
            )
            .map_err(|_| SignedEvidenceError::InvalidSignature)?;
        Ok(VerifiedLearningEvidenceV1 {
            principal: signer.principal.clone(),
            controller_id: signer.controller_id.clone(),
            role: expected_role,
            trust_digest: self.trust_digest,
            objective_digest: self.objective_digest,
            payload_digest: evidence.payload_digest,
            issued_at: evidence.issued_at,
            expires_at: evidence.expires_at,
            revoked_at: signer.revoked_at,
        })
    }
}

pub fn verify_signed_role_separation(
    generator: &VerifiedLearningEvidenceV1,
    observer: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<(), SignedEvidenceError> {
    if generator.role != LearningEvidenceRoleV1::Generator
        || observer.role == LearningEvidenceRoleV1::Generator
    {
        return Err(SignedEvidenceError::RoleMismatch);
    }
    if generator.trust_digest != observer.trust_digest
        || generator.objective_digest != observer.objective_digest
    {
        return Err(SignedEvidenceError::ContextMismatch);
    }
    for evidence in [generator, observer] {
        if now < evidence.issued_at || now > evidence.expires_at {
            return Err(SignedEvidenceError::ValidityWindow);
        }
        if evidence.revoked_at.is_some_and(|at| now >= at) {
            return Err(SignedEvidenceError::Revoked);
        }
    }
    verify_independent_roles(&generator.principal, &observer.principal, now)?;
    if generator.controller_id == observer.controller_id {
        return Err(SignedEvidenceError::ControllerCollision);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SignedEvidenceError {
    Principal(CausalV2Error),
    InvalidTrust,
    InvalidKey,
    UnknownSigner,
    ContextMismatch,
    RoleMismatch,
    ValidityWindow,
    Revoked,
    PayloadLimit,
    PayloadMismatch,
    InvalidSignature,
    ControllerCollision,
}

impl fmt::Display for SignedEvidenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SignedEvidenceError {}
impl From<CausalV2Error> for SignedEvidenceError {
    fn from(value: CausalV2Error) -> Self {
        Self::Principal(value)
    }
}

#[cfg(test)]
#[path = "signed_evidence_tests.rs"]
mod tests;
