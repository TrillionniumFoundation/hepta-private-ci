//! Cryptographic admission for learning evidence. Trust configuration must come
//! from the host's authority store, never from the submitted evidence. A valid
//! signature authenticates an attestation; it does not prove its scientific
//! truth, independence of organizations, or permission to promote a candidate.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use crate::LearningAuthenticationProfile;
use crate::LearningSignature;
use crate::LearningVerificationKey;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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
    CreditAllocator,
    UnlearningAuthority,
    Selector,
}

impl LearningEvidenceRoleV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Generator => 0,
            Self::Observer => 1,
            Self::Evaluator => 2,
            Self::CreditAllocator => 3,
            Self::UnlearningAuthority => 4,
            Self::Selector => 5,
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
    pub verifying_key: LearningVerificationKey,
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
    pub signature: LearningSignature,
}

impl SignedLearningEvidenceV1 {
    /// Exact versioned application message; the signature itself is excluded.
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = self.signature.profile().learning_domain(
            b"hepta.learning-ledger.signed-evidence.v1",
            b"hepta.learning-ledger.signed-evidence.pq.v2",
        );
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
    activation_frontier: Option<frontier::EvidenceTrustFrontier>,
    authentication_profile: LearningAuthenticationProfile,
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
    /// Recheck retained distribution currentness and protected authority time
    /// before using an opaque role outside the original verification call.
    /// The supplied time is used only without a retained authority clock.
    pub fn validate_at(&self, supplied_now: u64) -> Result<u64, SignedEvidenceError> {
        let now = match &self.activation_frontier {
            Some(frontier) => frontier.verify_at(supplied_now)?,
            None => supplied_now,
        };
        if now < self.issued_at || self.authentication_profile.expired_at(now, self.expires_at) {
            return Err(SignedEvidenceError::ValidityWindow);
        }
        if self.revoked_at.is_some_and(|at| now >= at) {
            return Err(SignedEvidenceError::Revoked);
        }
        self.principal.validate(now)?;
        Ok(now)
    }

    #[must_use]
    pub const fn authentication_profile(&self) -> LearningAuthenticationProfile {
        self.authentication_profile
    }

    #[must_use]
    pub fn principal(&self) -> &AuthenticatedPrincipalV1 {
        &self.principal
    }

    pub(crate) fn principal_for_lifetime(&self) -> AuthenticatedPrincipalV1 {
        let mut principal = self.principal.clone();
        principal.authenticated_at = principal.authenticated_at.max(self.issued_at);
        principal.expires_at = principal.expires_at.min(match self.authentication_profile {
            LearningAuthenticationProfile::ClassicalV1 => self.expires_at,
            LearningAuthenticationProfile::MlDsa65V2 => self.expires_at.saturating_sub(1),
        });
        if let Some(at) = self.revoked_at {
            principal.expires_at = principal.expires_at.min(at.saturating_sub(1));
        }
        principal
    }
    #[must_use]
    pub fn role(&self) -> LearningEvidenceRoleV1 {
        self.role
    }
    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }
    #[must_use]
    pub fn controller_id(&self) -> &StableId {
        &self.controller_id
    }
    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }
    #[must_use]
    pub fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }
}

#[derive(Clone, Debug)]
pub struct LearningEvidenceVerifierV1 {
    scope_digest: Digest32,
    objective_digest: Digest32,
    authority_epoch: u64,
    trust_digest: Digest32,
    signers: BTreeMap<StableId, TrustedLearningSignerV1>,
    activation_window: Option<ActivationWindow>,
    activation_frontier: Option<frontier::EvidenceTrustFrontier>,
    authentication_profile: LearningAuthenticationProfile,
}

#[derive(Clone, Copy, Debug)]
struct ActivationWindow {
    verified_at: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
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
        let authentication_profile = trust.signers[0].verifying_key.profile();
        let mut signers = BTreeMap::new();
        for mut signer in trust.signers {
            signer
                .principal
                .validate(signer.principal.authenticated_at)?;
            if signer.principal.scope_digest != trust.scope_digest
                || signer.principal.authority_epoch != trust.authority_epoch
                || signer.principal.signing_key_digest != Digest32::of_bytes(&signer.verifying_key)
                || signer.roles.is_empty()
                || signer.roles.len() > 6
            {
                return Err(SignedEvidenceError::InvalidTrust);
            }
            signer
                .verifying_key
                .validate()
                .map_err(|_| SignedEvidenceError::InvalidKey)?;
            if signer.verifying_key.profile() != authentication_profile {
                return Err(SignedEvidenceError::InvalidTrust);
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
        let mut bytes = authentication_profile.learning_domain(
            b"hepta.learning-ledger.evidence-trust.v1",
            b"hepta.learning-ledger.evidence-trust.pq.v2",
        );
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
            activation_window: None,
            activation_frontier: None,
            authentication_profile,
        })
    }

    #[must_use]
    pub const fn authentication_profile(&self) -> LearningAuthenticationProfile {
        self.authentication_profile
    }

    pub(crate) fn bind_activation_window(
        &mut self,
        verified_at: u64,
        expires_at: u64,
        revoked_at: Option<u64>,
    ) {
        self.activation_window = Some(ActivationWindow {
            verified_at,
            expires_at,
            revoked_at,
        });
    }

    pub(crate) fn validate_active_at(&self, now: u64) -> Result<u64, SignedEvidenceError> {
        let now = match &self.activation_frontier {
            Some(frontier) => frontier.verify_at(now)?,
            None => now,
        };
        if let Some(window) = self.activation_window {
            if now < window.verified_at
                || self
                    .authentication_profile
                    .expired_at(now, window.expires_at)
            {
                return Err(SignedEvidenceError::ValidityWindow);
            }
            if window.revoked_at.is_some_and(|at| now >= at) {
                return Err(SignedEvidenceError::Revoked);
            }
        }
        Ok(now)
    }

    #[must_use]
    pub fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    pub fn verify(
        &self,
        expected_role: LearningEvidenceRoleV1,
        evidence: &SignedLearningEvidenceV1,
        payload: &[u8],
        now: u64,
    ) -> Result<VerifiedLearningEvidenceV1, SignedEvidenceError> {
        let now = self.validate_active_at(now)?;
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
            || self
                .authentication_profile
                .expired_at(now, evidence.expires_at)
            || evidence.issued_at > evidence.expires_at
            || evidence.issued_at < signer.principal.authenticated_at
            || evidence.expires_at > signer.principal.expires_at
        {
            return Err(SignedEvidenceError::ValidityWindow);
        }
        if Digest32::of_bytes(payload) != evidence.payload_digest {
            return Err(SignedEvidenceError::PayloadMismatch);
        }
        signer
            .verifying_key
            .verify(&evidence.signing_bytes(), &evidence.signature)
            .map_err(|_| SignedEvidenceError::InvalidSignature)?;
        let mut issued_at = evidence.issued_at;
        let mut expires_at = evidence.expires_at;
        let mut revoked_at = signer.revoked_at;
        if let Some(window) = self.activation_window {
            issued_at = issued_at.max(window.verified_at);
            expires_at = expires_at.min(window.expires_at);
            revoked_at = [revoked_at, window.revoked_at].into_iter().flatten().min();
        }
        Ok(VerifiedLearningEvidenceV1 {
            activation_frontier: self.activation_frontier.clone(),
            authentication_profile: self.authentication_profile,
            principal: signer.principal.clone(),
            controller_id: signer.controller_id.clone(),
            role: expected_role,
            trust_digest: self.trust_digest,
            objective_digest: self.objective_digest,
            payload_digest: evidence.payload_digest,
            issued_at,
            expires_at,
            revoked_at,
        })
    }
}

/// Require both distinct protocol roles and independently authenticated actors.
pub fn verify_signed_independent_roles_v1(
    left: &VerifiedLearningEvidenceV1,
    right: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<(), SignedEvidenceError> {
    if left.role == right.role {
        return Err(SignedEvidenceError::RoleMismatch);
    }
    verify_signed_actor_separation(left, right, now)
}

/// Verify that two already-authenticated evidence actors are independent in the
/// same trust/objective domain. This is role-agnostic and is used where a
/// protocol requires pairwise separation beyond generator-vs-observer.
pub fn verify_signed_actor_separation(
    left: &VerifiedLearningEvidenceV1,
    right: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<(), SignedEvidenceError> {
    if left.trust_digest != right.trust_digest || left.objective_digest != right.objective_digest {
        return Err(SignedEvidenceError::ContextMismatch);
    }
    let now = left.validate_at(now)?.max(right.validate_at(now)?);
    verify_independent_roles(&left.principal, &right.principal, now)?;
    if left.controller_id == right.controller_id {
        return Err(SignedEvidenceError::ControllerCollision);
    }
    Ok(())
}

pub fn verify_verified_role_separation(
    left: &VerifiedLearningEvidenceV1,
    right: &VerifiedLearningEvidenceV1,
    now: u64,
) -> Result<(), SignedEvidenceError> {
    verify_signed_actor_separation(left, right, now)
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
    verify_signed_actor_separation(generator, observer, now)
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
    TrustFrontier(codex_hepta_contracts::AuthorityTrustError),
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

#[path = "evidence_trust_frontier.rs"]
mod frontier;
