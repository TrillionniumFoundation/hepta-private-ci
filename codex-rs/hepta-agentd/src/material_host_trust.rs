//! Authenticate the complete immutable distribution selected by the protected
//! supervisor. A signer list or child-reported digest cannot select the root.

use std::fs::File;
use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_ledger::{ActivatedLearningTrustV1, AuthenticatedPrincipalV1,
    LearningEvidenceRoleV1, LearningEvidenceTrustV1, LearningTrustDistributionV1,
    LearningTrustRootV1, SignedLearningEvidenceV1, SignedLearningTrustDistributionV1,
    TrustedLearningSignerV1, activate_learning_trust};
use codex_hepta_types::StableId;
use serde::Deserialize;
use crate::AgentdError;
use super::{config::{digest, id}, files, invalid};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TrustPin {
    root_id: String, root_digest: String, distribution_id: String,
    distribution_digest: String, generation: u64, evidence_trust_digest: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RootFile {
    schema_version: u32, purpose: String, root_id: String, scope_digest: String,
    verifying_key: [u8; 32], valid_from: u64, expires_at: u64, revoked_at: Option<u64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DistributionFile {
    schema_version: u32, purpose: String, distribution_id: String, generation: u64,
    effective_at: u64, root_id: String, issued_at: u64, expires_at: u64, signature: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustFile {
    schema_version: u32, purpose: String, scope_digest: String, objective_digest: String,
    authority_epoch: u64, signers: Vec<Signer>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Signer {
    principal: Principal, controller_id: String, verifying_key: [u8; 32],
    roles: Vec<Role>, revoked_at: Option<u64>,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Principal {
    principal_id: String, credential_chain_digest: String, signing_key_digest: String,
    scope_digest: String, authority_epoch: u64, authenticated_at: u64, expires_at: u64,
}
impl Principal {
    pub(super) fn original(&self) -> Result<AuthenticatedPrincipalV1, AgentdError> {
        Ok(AuthenticatedPrincipalV1 { principal_id: id(&self.principal_id)?,
            credential_chain_digest: digest(&self.credential_chain_digest)?,
            signing_key_digest: digest(&self.signing_key_digest)?, scope_digest: digest(&self.scope_digest)?,
            authority_epoch: self.authority_epoch, authenticated_at: self.authenticated_at, expires_at: self.expires_at })
    }
}
#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Role { Generator, Observer, Evaluator, CreditAllocator, UnlearningAuthority, Selector }
impl Role {
    fn original(self) -> LearningEvidenceRoleV1 {
        match self { Self::Generator => LearningEvidenceRoleV1::Generator,
            Self::Observer => LearningEvidenceRoleV1::Observer, Self::Evaluator => LearningEvidenceRoleV1::Evaluator,
            Self::CreditAllocator => LearningEvidenceRoleV1::CreditAllocator,
            Self::UnlearningAuthority => LearningEvidenceRoleV1::UnlearningAuthority,
            Self::Selector => LearningEvidenceRoleV1::Selector }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Evidence {
    evidence_id: String, principal_id: String, role: Role, trust_digest: String,
    scope_digest: String, objective_digest: String, authority_epoch: u64,
    issued_at: u64, expires_at: u64, payload_digest: String, signature: String,
}
impl Evidence {
    pub(super) fn original(&self) -> Result<SignedLearningEvidenceV1, AgentdError> {
        Ok(SignedLearningEvidenceV1 { evidence_id: id(&self.evidence_id)?, principal_id: id(&self.principal_id)?,
            role: self.role.original(), trust_digest: digest(&self.trust_digest)?, scope_digest: digest(&self.scope_digest)?,
            objective_digest: digest(&self.objective_digest)?, authority_epoch: self.authority_epoch,
            issued_at: self.issued_at, expires_at: self.expires_at, payload_digest: digest(&self.payload_digest)?,
            signature: signature(&self.signature)? })
    }
}

pub(super) struct OriginalMaterialTrust {
    root: LearningTrustRootV1,
    signed: SignedLearningTrustDistributionV1,
    activated: ActivatedLearningTrustV1,
}

impl OriginalMaterialTrust {
    pub(super) fn read(evidence: &File, root: &File, distribution: &File, pin: &TrustPin, at: u64)
        -> Result<Self, AgentdError>
    {
        let data: TrustFile = files::read_root(evidence)?;
        let root: RootFile = files::read_root(root)?;
        let distribution: DistributionFile = files::read_root(distribution)?;
        if data.schema_version != 3 || data.purpose != "hepta.host-resident-learning.trusted-evidence.v3"
            || data.signers.is_empty() || data.signers.len() > 64
            || root.schema_version != 1 || root.purpose != "hepta.root.learning-trust-root.v1"
            || distribution.schema_version != 1
            || distribution.purpose != "hepta.root.original-learning-trust-distribution.v1"
        { return Err(invalid("original Material root-signed trust profile differs")); }
        let signers = data.signers.into_iter().map(|s| {
            if s.roles.is_empty() || s.roles.len() > 6 { return Err(invalid("invalid original role list")); }
            Ok(TrustedLearningSignerV1 { principal: s.principal.original()?, controller_id: id(&s.controller_id)?,
                verifying_key: s.verifying_key, roles: s.roles.into_iter().map(Role::original).collect(), revoked_at: s.revoked_at })
        }).collect::<Result<Vec<_>, AgentdError>>()?;
        let root = LearningTrustRootV1 { root_id: id(&root.root_id)?, scope_digest: digest(&root.scope_digest)?,
            verifying_key: root.verifying_key, valid_from: root.valid_from, expires_at: root.expires_at, revoked_at: root.revoked_at };
        let signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 { distribution_id: id(&distribution.distribution_id)?,
                generation: distribution.generation, effective_at: distribution.effective_at,
                trust: LearningEvidenceTrustV1 { scope_digest: digest(&data.scope_digest)?, objective_digest: digest(&data.objective_digest)?,
                    authority_epoch: data.authority_epoch, signers } },
            root_id: id(&distribution.root_id)?, issued_at: distribution.issued_at,
            expires_at: distribution.expires_at, signature: signature(&distribution.signature)?,
        };
        // Authentication of the exact current statement explicitly selected by
        // the Root supervisor, not a successor rotation or a child-selected key.
        let activated = activate_learning_trust(&root, signed.clone(), None, at).map_err(invalid)?;
        if activated.root_id() != &id(&pin.root_id)? || activated.root_digest() != digest(&pin.root_digest)?
            || activated.distribution_id() != &id(&pin.distribution_id)?
            || activated.distribution_digest() != digest(&pin.distribution_digest)?
            || activated.generation() != pin.generation || activated.verifier().trust_digest() != digest(&pin.evidence_trust_digest)?
        { return Err(invalid("original activated trust differs from the protected full pin")); }
        Ok(Self { root, signed, activated })
    }

    pub(super) fn require_window(&self, at: u64) -> Result<(), AgentdError> {
        let value = activate_learning_trust(&self.root, self.signed.clone(), None, at).map_err(invalid)?;
        if value.root_id() != self.activated.root_id() || value.root_digest() != self.activated.root_digest()
            || value.distribution_id() != self.activated.distribution_id()
            || value.distribution_digest() != self.activated.distribution_digest()
            || value.generation() != self.activated.generation()
            || value.verifier().trust_digest() != self.activated.verifier().trust_digest()
        { return Err(invalid("retained original distribution changed")); }
        Ok(())
    }
    pub(super) fn activation(&self) -> ActivatedLearningTrustV1 { self.activated.clone() }
    pub(super) fn signer(&self, actor: &StableId, role: LearningEvidenceRoleV1, at: u64)
        -> Result<TrustedLearningSignerV1, AgentdError>
    {
        let signer = self.signed.distribution.trust.signers.iter()
            .find(|s| &s.principal.principal_id == actor).ok_or_else(|| invalid("original actor is not enrolled"))?;
        self.activated.verifier().require_signer_binding(role, signer, at).map_err(invalid)?;
        Ok(signer.clone())
    }
}

fn signature(text: &str) -> Result<[u8; 64], AgentdError> {
    let bytes = decode(text, 64)?;
    bytes.try_into().map_err(|_| invalid("original signature width differs"))
}
pub(super) fn decode(text: &str, maximum: usize) -> Result<Vec<u8>, AgentdError> {
    if text.len() > maximum.saturating_mul(4).div_ceil(3).saturating_add(4) {
        return Err(invalid("original encoded value exceeds its bound"));
    }
    let bytes = STANDARD_NO_PAD.decode(text).map_err(invalid)?;
    if bytes.len() > maximum || STANDARD_NO_PAD.encode(&bytes) != text {
        return Err(invalid("original encoded value is noncanonical or oversized"));
    }
    Ok(bytes)
}
