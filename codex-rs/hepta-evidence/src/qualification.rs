use std::collections::BTreeSet;
use std::collections::HashSet;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_state::SqliteConfig;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::AppendDisposition;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

pub const QUALIFICATION_EVIDENCE_SCHEMA_VERSION: u32 = 1;
pub const QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES: usize = 256 * 1024;
pub const QUALIFICATION_EVIDENCE_MAX_ASSET_REFS: usize = 64;
pub const QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES: usize = 256;
pub const QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS: usize = 512;
pub const QUALIFICATION_EVIDENCE_MAX_REQUIRED_ROLES: usize = 32;
pub const QUALIFICATION_EVIDENCE_MAX_ISSUER_ROLES: usize = 32;
pub const QUALIFICATION_EVIDENCE_ZERO_CHAIN: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";
const SECURITY_AUTHORITY_ROLE: &str = "security-authority";
const AUTHENTICATOR_ID: &str = "kernel.evidence.ed25519_policy.v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClaimClass {
    ExactSource,
    SyntheticMerge,
    Fixture,
    Hardware,
    ProviderEffect,
    Longitudinal,
    CandidateEvaluation,
    Conformance,
    AlgorithmFault,
    IndependentDecision,
    OperatorAcceptance,
    Revocation,
}

impl EvidenceClaimClass {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ExactSource => "exact_source",
            Self::SyntheticMerge => "synthetic_merge",
            Self::Fixture => "fixture",
            Self::Hardware => "hardware",
            Self::ProviderEffect => "provider_effect",
            Self::Longitudinal => "longitudinal",
            Self::CandidateEvaluation => "candidate_evaluation",
            Self::Conformance => "conformance",
            Self::AlgorithmFault => "algorithm_fault",
            Self::IndependentDecision => "independent_decision",
            Self::OperatorAcceptance => "operator_acceptance",
            Self::Revocation => "revocation",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceCandidate {
    pub candidate_id: String,
    pub source_commit: String,
    pub source_tree: String,
}

impl EvidenceCandidate {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        validate_text("candidate id", &self.candidate_id, 128)?;
        validate_git_identity("source commit", &self.source_commit)?;
        validate_git_identity("source tree", &self.source_tree)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceAssetReference {
    pub sha256: Sha256Digest,
    pub size_bytes: u64,
    pub media_type: String,
}

impl EvidenceAssetReference {
    fn validate(&self) -> Result<(), EvidenceError> {
        validate_sha256("asset", &self.sha256)?;
        validate_text("asset media type", &self.media_type, 128)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidenceEnvelope {
    pub schema_version: u32,
    pub receipt_id: String,
    pub candidate: EvidenceCandidate,
    pub claim_class: EvidenceClaimClass,
    pub issuer_role: String,
    pub payload_sha256: Sha256Digest,
    pub predecessor_receipt_id: Option<String>,
    pub revokes_receipt_id: Option<String>,
    pub revokes_issuer_key_sha256: Option<Sha256Digest>,
    pub observed_at_ms: u64,
    pub expires_at_ms: Option<u64>,
    pub asset_refs: Vec<EvidenceAssetReference>,
}

impl QualificationEvidenceEnvelope {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn validate(&self) -> Result<(), EvidenceError> {
        if self.schema_version != QUALIFICATION_EVIDENCE_SCHEMA_VERSION {
            return Err(invalid("qualification evidence schema version mismatch"));
        }
        validate_text("receipt id", &self.receipt_id, 128)?;
        self.candidate.validate()?;
        validate_text("issuer role", &self.issuer_role, 64)?;
        validate_sha256("payload", &self.payload_sha256)?;
        if let Some(value) = self.predecessor_receipt_id.as_deref() {
            validate_text("predecessor receipt id", value, 128)?;
            if value == self.receipt_id {
                return Err(invalid("qualification evidence cannot precede itself"));
            }
        }
        if let Some(value) = self.revokes_receipt_id.as_deref() {
            validate_text("revoked receipt id", value, 128)?;
            if value == self.receipt_id {
                return Err(invalid("qualification evidence cannot revoke itself"));
            }
        }
        if let Some(value) = self.revokes_issuer_key_sha256.as_ref() {
            validate_sha256("revoked issuer key", value)?;
        }
        if self.observed_at_ms > i64::MAX as u64 {
            return Err(invalid("observation time exceeds SQLite range"));
        }
        if let Some(expires_at_ms) = self.expires_at_ms {
            if expires_at_ms > i64::MAX as u64 || expires_at_ms <= self.observed_at_ms {
                return Err(invalid("qualification evidence expiry is invalid"));
            }
        }
        if self.asset_refs.len() > QUALIFICATION_EVIDENCE_MAX_ASSET_REFS {
            return Err(invalid("qualification evidence asset reference bound exceeded"));
        }
        for asset in &self.asset_refs {
            asset.validate()?;
        }
        match self.claim_class {
            EvidenceClaimClass::Revocation => {
                if self.issuer_role != SECURITY_AUTHORITY_ROLE {
                    return Err(invalid(
                        "qualification evidence revocation requires security-authority role",
                    ));
                }
                if self.predecessor_receipt_id.is_some() || self.expires_at_ms.is_some() {
                    return Err(invalid(
                        "qualification evidence revocations are permanent and cannot be corrections",
                    ));
                }
                if self.revokes_receipt_id.is_some() == self.revokes_issuer_key_sha256.is_some() {
                    return Err(invalid(
                        "qualification evidence revocation must target exactly one receipt or issuer key",
                    ));
                }
            }
            _ => {
                if self.revokes_receipt_id.is_some() || self.revokes_issuer_key_sha256.is_some() {
                    return Err(invalid(
                        "non-revocation qualification evidence cannot carry revocation targets",
                    ));
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceIssuerRegistration {
    pub principal_id: String,
    pub verifying_key_hex: String,
    pub roles: Vec<String>,
    pub not_before_ms: u64,
    pub expires_at_ms: u64,
}

impl EvidenceIssuerRegistration {
    fn validate(&self) -> Result<(), EvidenceError> {
        validate_text("issuer principal", &self.principal_id, 128)?;
        let _ = decode_hex::<32>(&self.verifying_key_hex, "issuer verifying key")?;
        validate_roles(&self.roles)?;
        if self.not_before_ms > i64::MAX as u64
            || self.expires_at_ms > i64::MAX as u64
            || self.not_before_ms >= self.expires_at_ms
        {
            return Err(invalid("issuer credential time window is invalid"));
        }
        Ok(())
    }

    pub fn signing_identity_digest(&self) -> Result<Sha256Digest, EvidenceError> {
        let key = decode_hex::<32>(&self.verifying_key_hex, "issuer verifying key")?;
        Ok(Sha256Digest::for_bytes(&key))
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceTrustPolicy {
    pub schema_version: u32,
    pub policy_id: String,
    pub revision: u64,
    pub registrations: Vec<EvidenceIssuerRegistration>,
    pub revoked_signing_identity_sha256: Vec<Sha256Digest>,
}

impl EvidenceTrustPolicy {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        if self.schema_version != 1 || self.revision == 0 {
            return Err(invalid("evidence trust policy schema or revision is invalid"));
        }
        validate_text("evidence trust policy id", &self.policy_id, 128)?;
        if self.registrations.is_empty() || self.registrations.len() > 256 {
            return Err(invalid("evidence trust policy registration bound is invalid"));
        }
        let mut identities = BTreeSet::new();
        for registration in &self.registrations {
            registration.validate()?;
            let identity = registration.signing_identity_digest()?;
            let key = (
                registration.principal_id.as_str(),
                identity.as_str().to_string(),
            );
            if !identities.insert(key) {
                return Err(invalid("duplicate evidence issuer registration"));
            }
        }
        let mut revoked = BTreeSet::new();
        for digest in &self.revoked_signing_identity_sha256 {
            validate_sha256("revoked signing identity", digest)?;
            if !revoked.insert(digest.as_str()) {
                return Err(invalid("duplicate revoked signing identity"));
            }
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, EvidenceError> {
        self.validate()?;
        Ok(Sha256Digest::for_bytes(&canonical_json(self)?))
    }

    pub fn registration(
        &self,
        principal_id: &str,
    ) -> Result<&EvidenceIssuerRegistration, EvidenceError> {
        self.validate()?;
        let mut matches = self
            .registrations
            .iter()
            .filter(|row| row.principal_id == principal_id);
        let Some(registration) = matches.next() else {
            return Err(invalid("evidence issuer principal is not registered"));
        };
        if matches.next().is_some() {
            return Err(invalid(
                "evidence issuer principal has multiple active registrations",
            ));
        }
        Ok(registration)
    }

    pub fn authenticate(
        &self,
        envelope: &QualificationEvidenceEnvelope,
        proof: &EvidenceIssuerProof,
    ) -> Result<AuthenticatedEvidenceIssuer, EvidenceError> {
        self.validate()?;
        envelope.validate()?;
        proof.validate()?;
        let registration = self.registration(&proof.principal_id)?;
        if registration.verifying_key_hex != proof.verifying_key_hex {
            return Err(invalid(
                "evidence issuer proof does not match the registered verifying key",
            ));
        }
        if !registration.roles.iter().any(|role| role == &envelope.issuer_role) {
            return Err(invalid("evidence issuer role is not registered"));
        }
        if proof.signed_at_ms < registration.not_before_ms
            || proof.signed_at_ms >= registration.expires_at_ms
            || proof.signed_at_ms > envelope.observed_at_ms
            || envelope.observed_at_ms >= registration.expires_at_ms
        {
            return Err(invalid(
                "evidence issuer proof is outside the credential validity window",
            ));
        }
        let key_bytes = decode_hex::<32>(&proof.verifying_key_hex, "issuer verifying key")?;
        let signing_identity_sha256 = Sha256Digest::for_bytes(&key_bytes);
        if self
            .revoked_signing_identity_sha256
            .iter()
            .any(|digest| digest == &signing_identity_sha256)
        {
            return Err(invalid("evidence issuer signing identity is revoked"));
        }
        let signature_bytes = decode_hex::<64>(&proof.signature_hex, "issuer signature")?;
        let verifying_key = VerifyingKey::from_bytes(&key_bytes)
            .map_err(|_| invalid("evidence issuer verifying key is invalid"))?;
        let signature = Signature::from_bytes(&signature_bytes);
        verifying_key
            .verify(&envelope.signing_bytes()?, &signature)
            .map_err(|_| invalid("qualification evidence signature verification failed"))?;
        Ok(AuthenticatedEvidenceIssuer {
            schema_version: 1,
            principal_id: proof.principal_id.clone(),
            verifying_key_hex: proof.verifying_key_hex.clone(),
            signature_hex: proof.signature_hex.clone(),
            signed_at_ms: proof.signed_at_ms,
            roles: registration.roles.clone(),
            credential_not_before_ms: registration.not_before_ms,
            credential_expires_at_ms: registration.expires_at_ms,
            signing_identity_sha256,
            signature_sha256: Sha256Digest::for_bytes(&signature_bytes),
            trust_policy_sha256: self.digest()?,
            trust_policy_id: self.policy_id.clone(),
            trust_policy_revision: self.revision,
            authenticator_id: AUTHENTICATOR_ID.to_string(),
        })
    }

    fn validate_authenticated(
        &self,
        envelope: &QualificationEvidenceEnvelope,
        issuer: &AuthenticatedEvidenceIssuer,
    ) -> Result<(), EvidenceError> {
        issuer.validate_for(envelope)?;
        let policy_digest = self.digest()?;
        if issuer.trust_policy_sha256 != policy_digest
            || issuer.trust_policy_id != self.policy_id
            || issuer.trust_policy_revision != self.revision
        {
            return Err(invalid(
                "authenticated issuer is not bound to the provisioned trust policy",
            ));
        }
        let registration = self.registration(&issuer.principal_id)?;
        if registration.verifying_key_hex != issuer.verifying_key_hex
            || registration.roles != issuer.roles
            || registration.not_before_ms != issuer.credential_not_before_ms
            || registration.expires_at_ms != issuer.credential_expires_at_ms
        {
            return Err(invalid(
                "authenticated issuer differs from the provisioned registration",
            ));
        }
        let identity = registration.signing_identity_digest()?;
        if identity != issuer.signing_identity_sha256
            || self
                .revoked_signing_identity_sha256
                .iter()
                .any(|digest| digest == &identity)
        {
            return Err(invalid(
                "authenticated issuer signing identity is not currently trusted",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceIssuerProof {
    pub principal_id: String,
    pub verifying_key_hex: String,
    pub signature_hex: String,
    pub signed_at_ms: u64,
}

impl EvidenceIssuerProof {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        validate_text("evidence issuer proof principal", &self.principal_id, 128)?;
        let _ = decode_hex::<32>(&self.verifying_key_hex, "issuer verifying key")?;
        let _ = decode_hex::<64>(&self.signature_hex, "issuer signature")?;
        if self.signed_at_ms > i64::MAX as u64 {
            return Err(invalid("evidence issuer proof time exceeds SQLite range"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthenticatedEvidenceIssuer {
    schema_version: u32,
    principal_id: String,
    verifying_key_hex: String,
    signature_hex: String,
    signed_at_ms: u64,
    roles: Vec<String>,
    credential_not_before_ms: u64,
    credential_expires_at_ms: u64,
    signing_identity_sha256: Sha256Digest,
    signature_sha256: Sha256Digest,
    trust_policy_sha256: Sha256Digest,
    trust_policy_id: String,
    trust_policy_revision: u64,
    authenticator_id: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AuthenticatedEvidenceIssuerWire {
    schema_version: u32,
    principal_id: String,
    verifying_key_hex: String,
    signature_hex: String,
    signed_at_ms: u64,
    roles: Vec<String>,
    credential_not_before_ms: u64,
    credential_expires_at_ms: u64,
    signing_identity_sha256: Sha256Digest,
    signature_sha256: Sha256Digest,
    trust_policy_sha256: Sha256Digest,
    trust_policy_id: String,
    trust_policy_revision: u64,
    authenticator_id: String,
}

impl AuthenticatedEvidenceIssuerWire {
    fn into_authenticated(self) -> AuthenticatedEvidenceIssuer {
        AuthenticatedEvidenceIssuer {
            schema_version: self.schema_version,
            principal_id: self.principal_id,
            verifying_key_hex: self.verifying_key_hex,
            signature_hex: self.signature_hex,
            signed_at_ms: self.signed_at_ms,
            roles: self.roles,
            credential_not_before_ms: self.credential_not_before_ms,
            credential_expires_at_ms: self.credential_expires_at_ms,
            signing_identity_sha256: self.signing_identity_sha256,
            signature_sha256: self.signature_sha256,
            trust_policy_sha256: self.trust_policy_sha256,
            trust_policy_id: self.trust_policy_id,
            trust_policy_revision: self.trust_policy_revision,
            authenticator_id: self.authenticator_id,
        }
    }
}

impl AuthenticatedEvidenceIssuer {
    pub fn principal_id(&self) -> &str {
        &self.principal_id
    }

    pub fn roles(&self) -> &[String] {
        &self.roles
    }

    pub fn signing_identity_sha256(&self) -> &Sha256Digest {
        &self.signing_identity_sha256
    }

    pub fn trust_policy_sha256(&self) -> &Sha256Digest {
        &self.trust_policy_sha256
    }

    pub fn credential_expires_at_ms(&self) -> u64 {
        self.credential_expires_at_ms
    }

    fn validate_for(
        &self,
        envelope: &QualificationEvidenceEnvelope,
    ) -> Result<(), EvidenceError> {
        if self.schema_version != 1 || self.authenticator_id != AUTHENTICATOR_ID {
            return Err(invalid("authenticated evidence issuer schema mismatch"));
        }
        validate_text("issuer principal", &self.principal_id, 128)?;
        validate_text("trust policy id", &self.trust_policy_id, 128)?;
        if self.trust_policy_revision == 0 {
            return Err(invalid("trust policy revision is invalid"));
        }
        validate_roles(&self.roles)?;
        validate_sha256("signing identity", &self.signing_identity_sha256)?;
        validate_sha256("signature", &self.signature_sha256)?;
        validate_sha256("trust policy", &self.trust_policy_sha256)?;
        if !self.roles.iter().any(|role| role == &envelope.issuer_role) {
            return Err(invalid(
                "authenticated evidence issuer does not carry the envelope role",
            ));
        }
        if self.credential_not_before_ms > self.signed_at_ms
            || self.signed_at_ms > envelope.observed_at_ms
            || envelope.observed_at_ms >= self.credential_expires_at_ms
            || self.credential_not_before_ms >= self.credential_expires_at_ms
        {
            return Err(invalid(
                "authenticated evidence issuer validity interval is inconsistent",
            ));
        }
        let key = decode_hex::<32>(&self.verifying_key_hex, "issuer verifying key")?;
        let signature_bytes = decode_hex::<64>(&self.signature_hex, "issuer signature")?;
        if Sha256Digest::for_bytes(&key) != self.signing_identity_sha256
            || Sha256Digest::for_bytes(&signature_bytes) != self.signature_sha256
        {
            return Err(invalid(
                "authenticated evidence issuer cryptographic digest mismatch",
            ));
        }
        let verifying_key = VerifyingKey::from_bytes(&key)
            .map_err(|_| invalid("authenticated issuer verifying key is invalid"))?;
        let signature = Signature::from_bytes(&signature_bytes);
        verifying_key
            .verify(&envelope.signing_bytes()?, &signature)
            .map_err(|_| invalid("stored qualification evidence signature is invalid"))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceReferenceState {
    Active,
    Expired,
    Revoked,
    Superseded,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceReference {
    pub seq: i64,
    pub receipt_id: String,
    pub claim_class: EvidenceClaimClass,
    pub issuer_role: String,
    pub issuer_principal_id: String,
    pub signing_identity_sha256: Sha256Digest,
    pub payload_sha256: Sha256Digest,
    pub state: EvidenceReferenceState,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceDispositionKind {
    Supported,
    Missing,
    Expired,
    Revoked,
    Conflicting,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceDisposition {
    pub kind: EvidenceDispositionKind,
    pub references: Vec<EvidenceReference>,
    pub missing_roles: Vec<String>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredQualificationEvidence {
    pub seq: i64,
    pub envelope: QualificationEvidenceEnvelope,
    pub issuer: AuthenticatedEvidenceIssuer,
    pub record_sha256: Sha256Digest,
    pub previous_chain_sha256: Sha256Digest,
    pub chain_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceCheckpoint {
    pub schema_version: u32,
    pub store_instance_id: Sha256Digest,
    pub receipt_count: u64,
    pub max_seq: u64,
    pub chain_head_sha256: Sha256Digest,
}

impl EvidenceCheckpoint {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        self.validate()?;
        canonical_json(self)
    }

    pub fn validate(&self) -> Result<(), EvidenceError> {
        if self.schema_version != 1 {
            return Err(invalid("evidence checkpoint schema version mismatch"));
        }
        validate_sha256("checkpoint store instance", &self.store_instance_id)?;
        validate_sha256("checkpoint chain head", &self.chain_head_sha256)?;
        if self.receipt_count == 0 {
            if self.max_seq != 0 || self.chain_head_sha256.as_str() != QUALIFICATION_EVIDENCE_ZERO_CHAIN
            {
                return Err(invalid("empty evidence checkpoint has a non-empty frontier"));
            }
        } else if self.max_seq == 0 {
            return Err(invalid("non-empty evidence checkpoint has a zero sequence"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IndependentDecision {
    Accept,
    Reject,
    Conditional,
    Abstain,
}

impl IndependentDecision {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Accept => "accept",
            Self::Reject => "reject",
            Self::Conditional => "conditional",
            Self::Abstain => "abstain",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IndependentDecisionReceiptV1 {
    pub decision_id: String,
    pub candidate_id: String,
    pub role: String,
    pub principal_id: String,
    pub signing_identity_digest: Sha256Digest,
    pub evidence_set_digest: Sha256Digest,
    pub decision: IndependentDecision,
    pub conditions: Vec<String>,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IndependentDecisionInput {
    pub decision_id: String,
    pub candidate: EvidenceCandidate,
    pub role: String,
    pub principal_id: String,
    pub evidence_set_digest: Sha256Digest,
    pub decision: IndependentDecision,
    pub conditions: Vec<String>,
    pub observed_at_ms: u64,
    pub expires_at_ms: u64,
    pub predecessor_receipt_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreparedIndependentDecision {
    pub receipt: IndependentDecisionReceiptV1,
    pub envelope: QualificationEvidenceEnvelope,
}

impl PreparedIndependentDecision {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        validate_prepared_independent_decision(self)?;
        canonical_json(self)
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        self.envelope.signing_bytes()
    }
}

#[derive(Clone, Copy)]
pub struct QualificationEvidence<'a> {
    store: &'a HeptaEvidenceStore,
}

impl HeptaEvidenceStore {
    pub fn qualification(&self) -> QualificationEvidence<'_> {
        QualificationEvidence { store: self }
    }

    /// Opens the durable store and rejects a database that is behind, replaced
    /// relative to, or divergent from an independently retained checkpoint.
    pub async fn open_with_checkpoint(
        sqlite: &SqliteConfig,
        checkpoint: &EvidenceCheckpoint,
    ) -> Result<Self, EvidenceError> {
        let store = Self::open(sqlite).await?;
        store
            .qualification()
            .verify_external_checkpoint(checkpoint)
            .await?;
        Ok(store)
    }

    /// Read-only counterpart of open_with_checkpoint.
    pub async fn open_existing_read_only_with_checkpoint(
        sqlite: &SqliteConfig,
        checkpoint: &EvidenceCheckpoint,
    ) -> Result<Self, EvidenceError> {
        let store = Self::open_existing_read_only(sqlite).await?;
        store
            .qualification()
            .verify_external_checkpoint(checkpoint)
            .await?;
        Ok(store)
    }
}

impl QualificationEvidence<'_> {
    pub async fn provision_trust_policy(
        &self,
        policy: &EvidenceTrustPolicy,
    ) -> Result<AppendDisposition, EvidenceError> {
        policy.validate()?;
        let policy_sha256 = policy.digest()?;
        let policy_bytes = canonical_json(policy)?;
        let policy_json = String::from_utf8(policy_bytes)
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let mut tx = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let evidence_count: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM qualification_evidence")
                .fetch_one(&mut *tx)
                .await
                .map_err(classify_sqlx_error)?;
        if evidence_count != 0 {
            return Err(invalid(
                "qualification trust policy must be provisioned before the first evidence receipt",
            ));
        }
        if let Some(row) = sqlx::query(
            "SELECT policy_id, revision, policy_sha256, policy_json
             FROM qualification_trust_policy WHERE slot = 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?
        {
            let existing_id: String = row.get("policy_id");
            let existing_revision: i64 = row.get("revision");
            let existing_digest: String = row.get("policy_sha256");
            let existing_json: String = row.get("policy_json");
            if existing_id == policy.policy_id
                && existing_revision == i64::try_from(policy.revision)
                    .map_err(|_| invalid("trust policy revision exceeds SQLite range"))?
                && existing_digest == policy_sha256.as_str()
                && existing_json == policy_json
            {
                tx.commit().await.map_err(classify_sqlx_error)?;
                return Ok(AppendDisposition::AlreadyPresent);
            }
            return Err(EvidenceError::IdempotencyConflict {
                record_id: "qualification_trust_policy".to_string(),
            });
        }
        sqlx::query(
            "INSERT INTO qualification_trust_policy
             (slot, policy_id, revision, policy_sha256, policy_json, provisioned_at_ms)
             VALUES (1, ?, ?, ?, ?, ?)",
        )
        .bind(&policy.policy_id)
        .bind(
            i64::try_from(policy.revision)
                .map_err(|_| invalid("trust policy revision exceeds SQLite range"))?,
        )
        .bind(policy_sha256.as_str())
        .bind(policy_json)
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(AppendDisposition::Inserted)
    }

    pub async fn append_receipt(
        &self,
        envelope: &QualificationEvidenceEnvelope,
        authenticated_issuer: &AuthenticatedEvidenceIssuer,
    ) -> Result<AppendDisposition, EvidenceError> {
        if envelope.claim_class == EvidenceClaimClass::IndependentDecision {
            return Err(invalid(
                "IndependentDecisionReceiptV1 must use append_prepared_independent_decision",
            ));
        }
        let mut tx = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let result = append_receipt_in_transaction(
            &mut tx,
            envelope,
            authenticated_issuer,
            false,
        )
        .await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(result)
    }

    pub fn authenticate_issuer(
        &self,
        policy: &EvidenceTrustPolicy,
        envelope: &QualificationEvidenceEnvelope,
        proof: &EvidenceIssuerProof,
    ) -> Result<AuthenticatedEvidenceIssuer, EvidenceError> {
        policy.authenticate(envelope, proof)
    }

    pub fn prepare_independent_decision(
        &self,
        input: IndependentDecisionInput,
        policy: &EvidenceTrustPolicy,
    ) -> Result<PreparedIndependentDecision, EvidenceError> {
        input.candidate.validate()?;
        validate_text("independent decision id", &input.decision_id, 128)?;
        validate_text("independent decision role", &input.role, 64)?;
        validate_text("independent decision principal", &input.principal_id, 128)?;
        validate_sha256("independent evidence set", &input.evidence_set_digest)?;
        if input.observed_at_ms > i64::MAX as u64
            || input.expires_at_ms > i64::MAX as u64
            || input.expires_at_ms <= input.observed_at_ms
        {
            return Err(invalid("independent decision validity interval is invalid"));
        }
        if input.conditions.len() > 64 {
            return Err(invalid("independent decision condition bound exceeded"));
        }
        for condition in &input.conditions {
            validate_text("independent decision condition", condition, 512)?;
        }
        if canonical_json(&input.conditions)?.len() > 32 * 1024 {
            return Err(invalid("independent decision conditions exceed 32 KiB"));
        }
        let registration = policy.registration(&input.principal_id)?;
        if !registration.roles.iter().any(|role| role == &input.role) {
            return Err(invalid(
                "independent decision principal is not registered for the requested role",
            ));
        }
        if input.observed_at_ms < registration.not_before_ms
            || input.observed_at_ms >= registration.expires_at_ms
            || input.expires_at_ms > registration.expires_at_ms
        {
            return Err(invalid(
                "independent decision exceeds issuer credential validity",
            ));
        }
        let signing_identity_digest = registration.signing_identity_digest()?;
        if policy
            .revoked_signing_identity_sha256
            .iter()
            .any(|digest| digest == &signing_identity_digest)
        {
            return Err(invalid(
                "independent decision issuer signing identity is revoked",
            ));
        }
        let receipt = IndependentDecisionReceiptV1 {
            decision_id: input.decision_id.clone(),
            candidate_id: input.candidate.candidate_id.clone(),
            role: input.role.clone(),
            principal_id: input.principal_id.clone(),
            signing_identity_digest,
            evidence_set_digest: input.evidence_set_digest,
            decision: input.decision,
            conditions: input.conditions,
            expires_unix_ms: input.expires_at_ms,
        };
        let payload = canonical_json(&receipt)?;
        let envelope = QualificationEvidenceEnvelope {
            schema_version: QUALIFICATION_EVIDENCE_SCHEMA_VERSION,
            receipt_id: input.decision_id,
            candidate: input.candidate,
            claim_class: EvidenceClaimClass::IndependentDecision,
            issuer_role: input.role,
            payload_sha256: Sha256Digest::for_bytes(&payload),
            predecessor_receipt_id: input.predecessor_receipt_id,
            revokes_receipt_id: None,
            revokes_issuer_key_sha256: None,
            observed_at_ms: input.observed_at_ms,
            expires_at_ms: Some(input.expires_at_ms),
            asset_refs: Vec::new(),
        };
        envelope.validate()?;
        Ok(PreparedIndependentDecision { receipt, envelope })
    }

    pub async fn append_prepared_independent_decision(
        &self,
        prepared: &PreparedIndependentDecision,
        policy: &EvidenceTrustPolicy,
        proof: &EvidenceIssuerProof,
    ) -> Result<AppendDisposition, EvidenceError> {
        validate_prepared_independent_decision(prepared)?;
        let issuer = policy.authenticate(&prepared.envelope, proof)?;
        if issuer.principal_id() != prepared.receipt.principal_id
            || issuer.signing_identity_sha256() != &prepared.receipt.signing_identity_digest
            || prepared.envelope.issuer_role != prepared.receipt.role
        {
            return Err(invalid(
                "independent decision issuer does not match the authenticated signer",
            ));
        }
        let payload = canonical_json(&prepared.receipt)?;
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let payload_sha256 = Sha256Digest::for_bytes(&payload);
        let mut tx = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let disposition = append_receipt_in_transaction(
            &mut tx,
            &prepared.envelope,
            &issuer,
            true,
        )
        .await?;
        let inserted = sqlx::query(
            "INSERT INTO independent_decision_receipts (
                decision_id, evidence_receipt_id, candidate_id, role, principal_id,
                signing_identity_sha256, evidence_set_sha256, decision,
                expires_at_ms, payload_json, payload_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(&prepared.receipt.decision_id)
        .bind(&prepared.envelope.receipt_id)
        .bind(&prepared.receipt.candidate_id)
        .bind(&prepared.receipt.role)
        .bind(&prepared.receipt.principal_id)
        .bind(prepared.receipt.signing_identity_digest.as_str())
        .bind(prepared.receipt.evidence_set_digest.as_str())
        .bind(prepared.receipt.decision.as_str())
        .bind(to_i64(prepared.receipt.expires_unix_ms, "decision expiry")?)
        .bind(&payload_json)
        .bind(payload_sha256.as_str())
        .bind(now_millis()?)
        .execute(&mut *tx)
        .await
        .map_err(classify_sqlx_error)?;
        if inserted.rows_affected() == 0 {
            let row = sqlx::query(
                "SELECT evidence_receipt_id, payload_json, payload_sha256
                 FROM independent_decision_receipts WHERE decision_id = ?",
            )
            .bind(&prepared.receipt.decision_id)
            .fetch_one(&mut *tx)
            .await
            .map_err(classify_sqlx_error)?;
            let existing_receipt: String = row.get("evidence_receipt_id");
            let existing_json: String = row.get("payload_json");
            let existing_digest: String = row.get("payload_sha256");
            if existing_receipt != prepared.envelope.receipt_id
                || existing_json != payload_json
                || existing_digest != payload_sha256.as_str()
            {
                return Err(EvidenceError::IdempotencyConflict {
                    record_id: prepared.receipt.decision_id.clone(),
                });
            }
        }
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(disposition)
    }

    pub async fn get_independent_decision(
        &self,
        decision_id: &str,
    ) -> Result<Option<IndependentDecisionReceiptV1>, EvidenceError> {
        validate_text("independent decision id", decision_id, 128)?;
        let row = sqlx::query(
            "SELECT payload_json, payload_sha256
             FROM independent_decision_receipts WHERE decision_id = ?",
        )
        .bind(decision_id)
        .fetch_optional(&self.store.pool)
        .await
        .map_err(classify_sqlx_error)?;
        row.map(|row| decode_independent_decision_projection(&row))
            .transpose()
    }

    pub async fn query_claim(
        &self,
        candidate: &EvidenceCandidate,
        claim_class: EvidenceClaimClass,
    ) -> Result<Vec<EvidenceReference>, EvidenceError> {
        let now = now_millis()?;
        self.query_claim_at(
            candidate,
            claim_class,
            u64::try_from(now).map_err(|_| invalid("system time is negative"))?,
        )
        .await
    }

    pub async fn query_claim_at(
        &self,
        candidate: &EvidenceCandidate,
        claim_class: EvidenceClaimClass,
        now_ms: u64,
    ) -> Result<Vec<EvidenceReference>, EvidenceError> {
        candidate.validate()?;
        let rows = load_candidate_claim_rows(&self.store.pool, candidate, claim_class).await?;
        classify_rows(&self.store.pool, candidate, rows, now_ms).await
    }

    pub async fn verify_chain(
        &self,
        candidate: &EvidenceCandidate,
        required_roles: &[String],
        now_ms: u64,
    ) -> Result<EvidenceDisposition, EvidenceError> {
        candidate.validate()?;
        if required_roles.is_empty() || required_roles.len() > QUALIFICATION_EVIDENCE_MAX_REQUIRED_ROLES
        {
            return Err(invalid("required evidence role bound is invalid"));
        }
        let mut role_set = BTreeSet::new();
        for role in required_roles {
            validate_text("required evidence role", role, 64)?;
            if !role_set.insert(role.as_str()) {
                return Err(invalid("duplicate required evidence role"));
            }
        }
        let (revoked_receipts, revoked_keys) =
            load_revocation_frontier(&self.store.pool, candidate).await?;
        let mut selected = Vec::new();
        let mut missing_roles = Vec::new();
        let mut expired_roles = Vec::new();
        let mut revoked_roles = Vec::new();
        let mut principals = BTreeSet::new();
        let mut signing_identities = BTreeSet::new();

        for role in required_roles {
            let rows = load_candidate_role_rows(&self.store.pool, candidate, role).await?;
            if rows.is_empty() {
                missing_roles.push(role.clone());
                continue;
            }
            let superseded = rows
                .iter()
                .filter_map(|row| row.envelope.predecessor_receipt_id.clone())
                .collect::<HashSet<_>>();
            let mut active = Vec::new();
            let mut saw_expired = false;
            let mut saw_revoked = false;
            for row in rows {
                let state = reference_state(
                    &row,
                    &revoked_receipts,
                    &revoked_keys,
                    &superseded,
                    now_ms,
                );
                match state {
                    EvidenceReferenceState::Active => active.push(row),
                    EvidenceReferenceState::Expired => saw_expired = true,
                    EvidenceReferenceState::Revoked | EvidenceReferenceState::Superseded => {
                        saw_revoked = true;
                    }
                }
            }
            if active.is_empty() {
                if saw_expired {
                    expired_roles.push(role.clone());
                } else if saw_revoked {
                    revoked_roles.push(role.clone());
                } else {
                    missing_roles.push(role.clone());
                }
                continue;
            }
            if independent_decisions_conflict(&active) {
                return Ok(EvidenceDisposition {
                    kind: EvidenceDispositionKind::Conflicting,
                    references: active
                        .iter()
                        .map(|row| evidence_reference(row, EvidenceReferenceState::Active))
                        .collect(),
                    missing_roles: Vec::new(),
                    reason: Some(format!(
                        "active independent decisions conflict for required role {role}"
                    )),
                });
            }
            active.sort_by_key(|row| row.seq);
            let chosen = active
                .last()
                .cloned()
                .ok_or_else(|| EvidenceError::Corrupt("active evidence disappeared".to_string()))?;
            verify_predecessor_chain(&self.store.pool, candidate, &chosen).await?;
            if !principals.insert(chosen.issuer.principal_id.clone())
                || !signing_identities
                    .insert(chosen.issuer.signing_identity_sha256.as_str().to_string())
            {
                return Ok(EvidenceDisposition {
                    kind: EvidenceDispositionKind::Conflicting,
                    references: vec![evidence_reference(
                        &chosen,
                        EvidenceReferenceState::Active,
                    )],
                    missing_roles: Vec::new(),
                    reason: Some(
                        "one principal/signing identity cannot satisfy multiple required independent roles"
                            .to_string(),
                    ),
                });
            }
            selected.push(evidence_reference(
                &chosen,
                EvidenceReferenceState::Active,
            ));
        }

        if !missing_roles.is_empty() {
            return Ok(EvidenceDisposition {
                kind: EvidenceDispositionKind::Missing,
                references: selected,
                missing_roles,
                reason: Some("one or more required evidence roles are missing".to_string()),
            });
        }
        if !revoked_roles.is_empty() {
            return Ok(EvidenceDisposition {
                kind: EvidenceDispositionKind::Revoked,
                references: selected,
                missing_roles: revoked_roles,
                reason: Some("one or more required evidence roles are revoked".to_string()),
            });
        }
        if !expired_roles.is_empty() {
            return Ok(EvidenceDisposition {
                kind: EvidenceDispositionKind::Expired,
                references: selected,
                missing_roles: expired_roles,
                reason: Some("one or more required evidence roles are expired".to_string()),
            });
        }
        Ok(EvidenceDisposition {
            kind: EvidenceDispositionKind::Supported,
            references: selected,
            missing_roles: Vec::new(),
            reason: None,
        })
    }

    pub async fn export_checkpoint(&self) -> Result<EvidenceCheckpoint, EvidenceError> {
        let store_instance_id = load_store_instance_id(&self.store.pool).await?;
        let receipt_count: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM qualification_evidence")
                .fetch_one(&self.store.pool)
                .await
                .map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT seq, chain_sha256 FROM qualification_evidence ORDER BY seq DESC LIMIT 1",
        )
        .fetch_optional(&self.store.pool)
        .await
        .map_err(classify_sqlx_error)?;
        let (max_seq, chain_head_sha256) = match row {
            Some(row) => {
                let seq: i64 = row.get("seq");
                let chain: String = row.get("chain_sha256");
                (
                    u64::try_from(seq)
                        .map_err(|_| EvidenceError::Corrupt("negative evidence sequence".into()))?,
                    parse_sha256("chain head", chain)?,
                )
            }
            None => (
                0,
                parse_sha256(
                    "zero chain",
                    QUALIFICATION_EVIDENCE_ZERO_CHAIN.to_string(),
                )?,
            ),
        };
        let checkpoint = EvidenceCheckpoint {
            schema_version: 1,
            store_instance_id,
            receipt_count: u64::try_from(receipt_count)
                .map_err(|_| EvidenceError::Corrupt("negative evidence count".into()))?,
            max_seq,
            chain_head_sha256,
        };
        checkpoint.validate()?;
        Ok(checkpoint)
    }

    pub async fn verify_external_checkpoint(
        &self,
        checkpoint: &EvidenceCheckpoint,
    ) -> Result<(), EvidenceError> {
        checkpoint.validate()?;
        let current = self.export_checkpoint().await?;
        if current.store_instance_id != checkpoint.store_instance_id {
            return Err(EvidenceError::Corrupt(
                "qualification evidence database replacement detected".to_string(),
            ));
        }
        if current.receipt_count < checkpoint.receipt_count || current.max_seq < checkpoint.max_seq {
            return Err(EvidenceError::Corrupt(
                "qualification evidence rollback detected".to_string(),
            ));
        }
        if checkpoint.max_seq == 0 {
            return Ok(());
        }
        let chain: Option<String> = sqlx::query_scalar(
            "SELECT chain_sha256 FROM qualification_evidence WHERE seq = ?",
        )
        .bind(to_i64(checkpoint.max_seq, "checkpoint sequence")?)
        .fetch_optional(&self.store.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if chain.as_deref() != Some(checkpoint.chain_head_sha256.as_str()) {
            return Err(EvidenceError::Corrupt(
                "qualification evidence checkpoint frontier diverged".to_string(),
            ));
        }
        Ok(())
    }
}

pub(crate) async fn ensure_qualification_store_identity(
    pool: &SqlitePool,
    path: &Path,
) -> Result<(), EvidenceError> {
    let existing: Option<String> =
        sqlx::query_scalar("SELECT store_instance_id FROM qualification_evidence_meta WHERE slot = 1")
            .fetch_optional(pool)
            .await
            .map_err(classify_sqlx_error)?;
    if existing.is_some() {
        return Ok(());
    }
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| EvidenceError::Unavailable(error.to_string()))?
        .as_nanos();
    let seed = format!("{}:{}:{}", path.display(), std::process::id(), nanos);
    let store_instance_id = Sha256Digest::for_bytes(seed.as_bytes());
    sqlx::query(
        "INSERT OR IGNORE INTO qualification_evidence_meta
         (slot, store_instance_id, created_at_ms) VALUES (1, ?, ?)",
    )
    .bind(store_instance_id.as_str())
    .bind(now_millis()?)
    .execute(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let stored: Option<String> =
        sqlx::query_scalar("SELECT store_instance_id FROM qualification_evidence_meta WHERE slot = 1")
            .fetch_optional(pool)
            .await
            .map_err(classify_sqlx_error)?;
    let Some(stored) = stored else {
        return Err(EvidenceError::Corrupt(
            "qualification evidence store identity was not established".to_string(),
        ));
    };
    let _ = parse_sha256("store instance", stored)?;
    Ok(())
}

pub(crate) async fn verify_qualification_evidence_rows(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let _ = load_store_instance_id(pool).await?;
    let provisioned_policy = load_trust_policy(pool).await?;
    let mut last_seq = 0_i64;
    let mut expected_previous = QUALIFICATION_EVIDENCE_ZERO_CHAIN.to_string();
    loop {
        let rows = sqlx::query(
            "SELECT seq, receipt_id, candidate_id, source_commit, source_tree, claim_class,
                    issuer_role, issuer_principal_id, signing_identity_sha256,
                    trust_policy_sha256, payload_sha256, predecessor_receipt_id,
                    revokes_receipt_id, revokes_issuer_key_sha256, observed_at_ms,
                    expires_at_ms, envelope_json, issuer_json, record_sha256,
                    previous_chain_sha256, chain_sha256
             FROM qualification_evidence WHERE seq > ? ORDER BY seq ASC LIMIT 256",
        )
        .bind(last_seq)
        .fetch_all(pool)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.is_empty() {
            break;
        }
        for row in rows {
            let stored = decode_stored_row(&row)?;
            let policy = provisioned_policy.as_ref().ok_or_else(|| {
                EvidenceError::Corrupt(
                    "qualification evidence exists without a provisioned trust policy".to_string(),
                )
            })?;
            policy
                .validate_authenticated(&stored.envelope, &stored.issuer)
                .map_err(|error| {
                    EvidenceError::Corrupt(format!(
                        "qualification evidence trust-policy verification failed: {error}"
                    ))
                })?;
            if stored.seq <= last_seq {
                return Err(EvidenceError::Corrupt(
                    "qualification evidence sequence is not strictly increasing".to_string(),
                ));
            }
            if stored.previous_chain_sha256.as_str() != expected_previous {
                return Err(EvidenceError::Corrupt(
                    "qualification evidence hash-chain predecessor mismatch".to_string(),
                ));
            }
            let expected_chain =
                chain_link_digest(&stored.previous_chain_sha256, &stored.record_sha256);
            if expected_chain != stored.chain_sha256 {
                return Err(EvidenceError::Corrupt(
                    "qualification evidence hash-chain digest mismatch".to_string(),
                ));
            }
            if stored.envelope.claim_class == EvidenceClaimClass::IndependentDecision {
                verify_independent_projection(pool, &stored).await?;
            }
            expected_previous = stored.chain_sha256.as_str().to_string();
            last_seq = stored.seq;
        }
    }
    let orphaned: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM independent_decision_receipts AS decisions
         LEFT JOIN qualification_evidence AS evidence
           ON evidence.receipt_id = decisions.evidence_receipt_id
         WHERE evidence.receipt_id IS NULL
            OR evidence.claim_class != 'independent_decision'",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if orphaned != 0 {
        return Err(EvidenceError::Corrupt(
            "independent decision projection is orphaned".to_string(),
        ));
    }
    Ok(())
}

async fn append_receipt_in_transaction(
    tx: &mut Transaction<'_, Sqlite>,
    envelope: &QualificationEvidenceEnvelope,
    issuer: &AuthenticatedEvidenceIssuer,
    allow_independent_decision: bool,
) -> Result<AppendDisposition, EvidenceError> {
    envelope.validate()?;
    issuer.validate_for(envelope)?;
    let provisioned_policy = load_trust_policy_in_transaction(tx)
        .await?
        .ok_or_else(|| invalid("qualification trust policy has not been provisioned"))?;
    provisioned_policy.validate_authenticated(envelope, issuer)?;
    if envelope.claim_class == EvidenceClaimClass::IndependentDecision && !allow_independent_decision
    {
        return Err(invalid(
            "IndependentDecisionReceiptV1 must use the typed append path",
        ));
    }
    let envelope_bytes = canonical_json(envelope)?;
    let issuer_bytes = canonical_json(issuer)?;
    let total_bytes = envelope_bytes
        .len()
        .checked_add(issuer_bytes.len())
        .ok_or_else(|| invalid("qualification evidence encoded size overflow"))?;
    if total_bytes > QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES {
        return Err(invalid("qualification evidence exceeds 256 KiB"));
    }
    let envelope_json = String::from_utf8(envelope_bytes)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let issuer_json = String::from_utf8(issuer_bytes)
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let record_sha256 = record_digest(envelope, issuer)?;

    if let Some(row) = sqlx::query(
        "SELECT envelope_json, issuer_json, record_sha256
         FROM qualification_evidence WHERE receipt_id = ?",
    )
    .bind(&envelope.receipt_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?
    {
        let existing_envelope: String = row.get("envelope_json");
        let existing_issuer: String = row.get("issuer_json");
        let existing_digest: String = row.get("record_sha256");
        if existing_envelope == envelope_json
            && existing_issuer == issuer_json
            && existing_digest == record_sha256.as_str()
        {
            return Ok(AppendDisposition::AlreadyPresent);
        }
        return Err(EvidenceError::IdempotencyConflict {
            record_id: envelope.receipt_id.clone(),
        });
    }

    if let Some(predecessor) = envelope.predecessor_receipt_id.as_deref() {
        let row = sqlx::query(
            "SELECT candidate_id, source_commit, source_tree, claim_class
             FROM qualification_evidence WHERE receipt_id = ?",
        )
        .bind(predecessor)
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or_else(|| invalid("qualification evidence predecessor is missing"))?;
        let candidate_id: String = row.get("candidate_id");
        let source_commit: String = row.get("source_commit");
        let source_tree: String = row.get("source_tree");
        let claim_class: String = row.get("claim_class");
        if candidate_id != envelope.candidate.candidate_id
            || source_commit != envelope.candidate.source_commit
            || source_tree != envelope.candidate.source_tree
            || claim_class != envelope.claim_class.as_str()
        {
            return Err(invalid(
                "qualification evidence predecessor belongs to a different candidate or claim class",
            ));
        }
    }

    if let Some(target) = envelope.revokes_receipt_id.as_deref() {
        let row = sqlx::query(
            "SELECT candidate_id, source_commit, source_tree
             FROM qualification_evidence WHERE receipt_id = ?",
        )
        .bind(target)
        .fetch_optional(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or_else(|| invalid("revoked qualification receipt is missing"))?;
        let candidate_id: String = row.get("candidate_id");
        let source_commit: String = row.get("source_commit");
        let source_tree: String = row.get("source_tree");
        if candidate_id != envelope.candidate.candidate_id
            || source_commit != envelope.candidate.source_commit
            || source_tree != envelope.candidate.source_tree
        {
            return Err(invalid(
                "qualification evidence cannot revoke a different candidate",
            ));
        }
    }

    let previous_chain: Option<String> = sqlx::query_scalar(
        "SELECT chain_sha256 FROM qualification_evidence ORDER BY seq DESC LIMIT 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    let previous_chain_sha256 = parse_sha256(
        "previous chain",
        previous_chain.unwrap_or_else(|| QUALIFICATION_EVIDENCE_ZERO_CHAIN.to_string()),
    )?;
    let chain_sha256 = chain_link_digest(&previous_chain_sha256, &record_sha256);

    sqlx::query(
        "INSERT INTO qualification_evidence (
            receipt_id, candidate_id, source_commit, source_tree, claim_class,
            issuer_role, issuer_principal_id, signing_identity_sha256,
            trust_policy_sha256, payload_sha256, predecessor_receipt_id,
            revokes_receipt_id, revokes_issuer_key_sha256, observed_at_ms,
            expires_at_ms, envelope_json, issuer_json, record_sha256,
            previous_chain_sha256, chain_sha256, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(&envelope.receipt_id)
    .bind(&envelope.candidate.candidate_id)
    .bind(&envelope.candidate.source_commit)
    .bind(&envelope.candidate.source_tree)
    .bind(envelope.claim_class.as_str())
    .bind(&envelope.issuer_role)
    .bind(&issuer.principal_id)
    .bind(issuer.signing_identity_sha256.as_str())
    .bind(issuer.trust_policy_sha256.as_str())
    .bind(envelope.payload_sha256.as_str())
    .bind(envelope.predecessor_receipt_id.as_deref())
    .bind(envelope.revokes_receipt_id.as_deref())
    .bind(
        envelope
            .revokes_issuer_key_sha256
            .as_ref()
            .map(Sha256Digest::as_str),
    )
    .bind(to_i64(envelope.observed_at_ms, "observation time")?)
    .bind(
        envelope
            .expires_at_ms
            .map(|value| to_i64(value, "evidence expiry"))
            .transpose()?,
    )
    .bind(envelope_json)
    .bind(issuer_json)
    .bind(record_sha256.as_str())
    .bind(previous_chain_sha256.as_str())
    .bind(chain_sha256.as_str())
    .bind(now_millis()?)
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;

    Ok(AppendDisposition::Inserted)
}

async fn load_candidate_claim_rows(
    pool: &SqlitePool,
    candidate: &EvidenceCandidate,
    claim_class: EvidenceClaimClass,
) -> Result<Vec<StoredQualificationEvidence>, EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, receipt_id, candidate_id, source_commit, source_tree, claim_class,
                issuer_role, issuer_principal_id, signing_identity_sha256,
                trust_policy_sha256, payload_sha256, predecessor_receipt_id,
                revokes_receipt_id, revokes_issuer_key_sha256, observed_at_ms,
                expires_at_ms, envelope_json, issuer_json, record_sha256,
                previous_chain_sha256, chain_sha256
         FROM qualification_evidence
         WHERE candidate_id = ? AND source_commit = ? AND source_tree = ? AND claim_class = ?
         ORDER BY seq ASC LIMIT ?",
    )
    .bind(&candidate.candidate_id)
    .bind(&candidate.source_commit)
    .bind(&candidate.source_tree)
    .bind(claim_class.as_str())
    .bind((QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS + 1) as i64)
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    decode_bounded_rows(rows)
}

async fn load_candidate_role_rows(
    pool: &SqlitePool,
    candidate: &EvidenceCandidate,
    role: &str,
) -> Result<Vec<StoredQualificationEvidence>, EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, receipt_id, candidate_id, source_commit, source_tree, claim_class,
                issuer_role, issuer_principal_id, signing_identity_sha256,
                trust_policy_sha256, payload_sha256, predecessor_receipt_id,
                revokes_receipt_id, revokes_issuer_key_sha256, observed_at_ms,
                expires_at_ms, envelope_json, issuer_json, record_sha256,
                previous_chain_sha256, chain_sha256
         FROM qualification_evidence
         WHERE candidate_id = ? AND source_commit = ? AND source_tree = ?
           AND issuer_role = ? AND claim_class != 'revocation'
         ORDER BY seq ASC LIMIT ?",
    )
    .bind(&candidate.candidate_id)
    .bind(&candidate.source_commit)
    .bind(&candidate.source_tree)
    .bind(role)
    .bind((QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS + 1) as i64)
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    decode_bounded_rows(rows)
}

fn decode_bounded_rows(
    rows: Vec<sqlx::sqlite::SqliteRow>,
) -> Result<Vec<StoredQualificationEvidence>, EvidenceError> {
    if rows.len() > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
        return Err(invalid("qualification evidence query result bound exceeded"));
    }
    rows.iter().map(decode_stored_row).collect()
}

async fn classify_rows(
    pool: &SqlitePool,
    candidate: &EvidenceCandidate,
    rows: Vec<StoredQualificationEvidence>,
    now_ms: u64,
) -> Result<Vec<EvidenceReference>, EvidenceError> {
    let (revoked_receipts, revoked_keys) = load_revocation_frontier(pool, candidate).await?;
    let superseded = rows
        .iter()
        .filter_map(|row| row.envelope.predecessor_receipt_id.clone())
        .collect::<HashSet<_>>();
    Ok(rows
        .iter()
        .map(|row| {
            let state =
                reference_state(row, &revoked_receipts, &revoked_keys, &superseded, now_ms);
            evidence_reference(row, state)
        })
        .collect())
}

async fn load_revocation_frontier(
    pool: &SqlitePool,
    candidate: &EvidenceCandidate,
) -> Result<(HashSet<String>, HashSet<String>), EvidenceError> {
    let rows = load_candidate_claim_rows(pool, candidate, EvidenceClaimClass::Revocation).await?;
    let mut receipts = HashSet::new();
    let mut keys = HashSet::new();
    for row in rows {
        if let Some(receipt) = row.envelope.revokes_receipt_id {
            receipts.insert(receipt);
        }
        if let Some(key) = row.envelope.revokes_issuer_key_sha256 {
            keys.insert(key.as_str().to_string());
        }
    }
    Ok((receipts, keys))
}

fn reference_state(
    row: &StoredQualificationEvidence,
    revoked_receipts: &HashSet<String>,
    revoked_keys: &HashSet<String>,
    superseded: &HashSet<String>,
    now_ms: u64,
) -> EvidenceReferenceState {
    if revoked_receipts.contains(&row.envelope.receipt_id)
        || revoked_keys.contains(row.issuer.signing_identity_sha256.as_str())
    {
        EvidenceReferenceState::Revoked
    } else if superseded.contains(&row.envelope.receipt_id) {
        EvidenceReferenceState::Superseded
    } else if row
        .envelope
        .expires_at_ms
        .is_some_and(|expiry| now_ms >= expiry)
        || now_ms >= row.issuer.credential_expires_at_ms
    {
        EvidenceReferenceState::Expired
    } else {
        EvidenceReferenceState::Active
    }
}

fn evidence_reference(
    row: &StoredQualificationEvidence,
    state: EvidenceReferenceState,
) -> EvidenceReference {
    EvidenceReference {
        seq: row.seq,
        receipt_id: row.envelope.receipt_id.clone(),
        claim_class: row.envelope.claim_class,
        issuer_role: row.envelope.issuer_role.clone(),
        issuer_principal_id: row.issuer.principal_id.clone(),
        signing_identity_sha256: row.issuer.signing_identity_sha256.clone(),
        payload_sha256: row.envelope.payload_sha256.clone(),
        state,
    }
}

fn independent_decisions_conflict(rows: &[StoredQualificationEvidence]) -> bool {
    let mut digests = BTreeSet::new();
    let mut saw_independent = false;
    for row in rows {
        if row.envelope.claim_class == EvidenceClaimClass::IndependentDecision {
            saw_independent = true;
            digests.insert(row.envelope.payload_sha256.as_str());
        }
    }
    saw_independent && digests.len() > 1
}

async fn verify_predecessor_chain(
    pool: &SqlitePool,
    candidate: &EvidenceCandidate,
    start: &StoredQualificationEvidence,
) -> Result<(), EvidenceError> {
    let mut current = start.envelope.predecessor_receipt_id.clone();
    let mut seen = HashSet::new();
    let mut edges = 0_usize;
    while let Some(receipt_id) = current {
        edges += 1;
        if edges > QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES {
            return Err(EvidenceError::Corrupt(
                "qualification evidence predecessor traversal exhausted".to_string(),
            ));
        }
        if !seen.insert(receipt_id.clone()) {
            return Err(EvidenceError::Corrupt(
                "qualification evidence predecessor cycle detected".to_string(),
            ));
        }
        let row = sqlx::query(
            "SELECT seq, receipt_id, candidate_id, source_commit, source_tree, claim_class,
                    issuer_role, issuer_principal_id, signing_identity_sha256,
                    trust_policy_sha256, payload_sha256, predecessor_receipt_id,
                    revokes_receipt_id, revokes_issuer_key_sha256, observed_at_ms,
                    expires_at_ms, envelope_json, issuer_json, record_sha256,
                    previous_chain_sha256, chain_sha256
             FROM qualification_evidence WHERE receipt_id = ?",
        )
        .bind(&receipt_id)
        .fetch_optional(pool)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or_else(|| {
            EvidenceError::Corrupt("qualification evidence predecessor is missing".to_string())
        })?;
        let stored = decode_stored_row(&row)?;
        if stored.envelope.candidate != *candidate
            || stored.envelope.claim_class != start.envelope.claim_class
        {
            return Err(EvidenceError::Corrupt(
                "qualification evidence predecessor crosses candidate or claim class".to_string(),
            ));
        }
        current = stored.envelope.predecessor_receipt_id;
    }
    Ok(())
}

fn validate_prepared_independent_decision(
    prepared: &PreparedIndependentDecision,
) -> Result<(), EvidenceError> {
    prepared.envelope.validate()?;
    if prepared.envelope.claim_class != EvidenceClaimClass::IndependentDecision
        || prepared.envelope.receipt_id != prepared.receipt.decision_id
        || prepared.envelope.candidate.candidate_id != prepared.receipt.candidate_id
        || prepared.envelope.issuer_role != prepared.receipt.role
        || prepared.envelope.expires_at_ms != Some(prepared.receipt.expires_unix_ms)
    {
        return Err(invalid(
            "prepared independent decision does not match its evidence envelope",
        ));
    }
    validate_text("independent decision id", &prepared.receipt.decision_id, 128)?;
    validate_text("independent decision candidate", &prepared.receipt.candidate_id, 128)?;
    validate_text("independent decision role", &prepared.receipt.role, 64)?;
    validate_text(
        "independent decision principal",
        &prepared.receipt.principal_id,
        128,
    )?;
    validate_sha256(
        "independent signing identity",
        &prepared.receipt.signing_identity_digest,
    )?;
    validate_sha256(
        "independent evidence set",
        &prepared.receipt.evidence_set_digest,
    )?;
    if canonical_json(&prepared.receipt.conditions)?.len() > 32 * 1024 {
        return Err(invalid("independent decision conditions exceed 32 KiB"));
    }
    let payload = canonical_json(&prepared.receipt)?;
    if Sha256Digest::for_bytes(&payload) != prepared.envelope.payload_sha256 {
        return Err(invalid(
            "prepared independent decision payload digest mismatch",
        ));
    }
    Ok(())
}

async fn verify_independent_projection(
    pool: &SqlitePool,
    evidence: &StoredQualificationEvidence,
) -> Result<(), EvidenceError> {
    let row = sqlx::query(
        "SELECT decision_id, evidence_receipt_id, candidate_id, role, principal_id,
                signing_identity_sha256, evidence_set_sha256, decision, expires_at_ms,
                payload_json, payload_sha256
         FROM independent_decision_receipts WHERE evidence_receipt_id = ?",
    )
    .bind(&evidence.envelope.receipt_id)
    .fetch_optional(pool)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or_else(|| {
        EvidenceError::Corrupt(
            "independent decision evidence is missing its typed projection".to_string(),
        )
    })?;
    let receipt = decode_independent_decision_projection(&row)?;
    let evidence_receipt_id: String = row.get("evidence_receipt_id");
    let candidate_id: String = row.get("candidate_id");
    let role: String = row.get("role");
    let principal_id: String = row.get("principal_id");
    let signing_identity: String = row.get("signing_identity_sha256");
    let evidence_set: String = row.get("evidence_set_sha256");
    let decision: String = row.get("decision");
    let expires_at_ms: i64 = row.get("expires_at_ms");
    if evidence_receipt_id != evidence.envelope.receipt_id
        || candidate_id != evidence.envelope.candidate.candidate_id
        || role != evidence.envelope.issuer_role
        || principal_id != evidence.issuer.principal_id
        || signing_identity != evidence.issuer.signing_identity_sha256.as_str()
        || evidence_set != receipt.evidence_set_digest.as_str()
        || decision != receipt.decision.as_str()
        || expires_at_ms
            != i64::try_from(receipt.expires_unix_ms)
                .map_err(|_| EvidenceError::Corrupt("decision expiry overflow".into()))?
        || receipt.decision_id != evidence.envelope.receipt_id
        || receipt.candidate_id != evidence.envelope.candidate.candidate_id
        || receipt.role != evidence.envelope.issuer_role
        || receipt.principal_id != evidence.issuer.principal_id
        || receipt.signing_identity_digest != evidence.issuer.signing_identity_sha256
        || receipt.expires_unix_ms != evidence.envelope.expires_at_ms.unwrap_or_default()
        || evidence.envelope.payload_sha256
            != Sha256Digest::for_bytes(&canonical_json(&receipt)?)
    {
        return Err(EvidenceError::Corrupt(
            "independent decision projection differs from authoritative evidence".to_string(),
        ));
    }
    Ok(())
}

fn decode_independent_decision_projection(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<IndependentDecisionReceiptV1, EvidenceError> {
    let payload_json: String = row.get("payload_json");
    let payload_sha256: String = row.get("payload_sha256");
    let receipt: IndependentDecisionReceiptV1 = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(format!("invalid independent decision JSON: {error}")))?;
    let canonical = canonical_json(&receipt)?;
    let canonical_json_text = String::from_utf8(canonical.clone())
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    if canonical_json_text != payload_json
        || Sha256Digest::for_bytes(&canonical).as_str() != payload_sha256
    {
        return Err(EvidenceError::Corrupt(
            "independent decision projection digest/canonicalization mismatch".to_string(),
        ));
    }
    Ok(receipt)
}

fn decode_stored_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<StoredQualificationEvidence, EvidenceError> {
    let envelope_json: String = row.get("envelope_json");
    let issuer_json: String = row.get("issuer_json");
    let envelope: QualificationEvidenceEnvelope = serde_json::from_str(&envelope_json)
        .map_err(|error| EvidenceError::Corrupt(format!("invalid qualification evidence JSON: {error}")))?;
    let issuer: AuthenticatedEvidenceIssuer = serde_json::from_str::<AuthenticatedEvidenceIssuerWire>(&issuer_json)
        .map_err(|error| EvidenceError::Corrupt(format!("invalid authenticated issuer JSON: {error}")))?
        .into_authenticated();
    envelope.validate()?;
    issuer.validate_for(&envelope)?;
    let canonical_envelope = String::from_utf8(canonical_json(&envelope)?)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    let canonical_issuer = String::from_utf8(canonical_json(&issuer)?)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    if canonical_envelope != envelope_json || canonical_issuer != issuer_json {
        return Err(EvidenceError::Corrupt(
            "qualification evidence stored JSON is not canonical".to_string(),
        ));
    }

    let seq: i64 = row.get("seq");
    let receipt_id: String = row.get("receipt_id");
    let candidate_id: String = row.get("candidate_id");
    let source_commit: String = row.get("source_commit");
    let source_tree: String = row.get("source_tree");
    let claim_class: String = row.get("claim_class");
    let issuer_role: String = row.get("issuer_role");
    let issuer_principal_id: String = row.get("issuer_principal_id");
    let signing_identity_sha256: String = row.get("signing_identity_sha256");
    let trust_policy_sha256: String = row.get("trust_policy_sha256");
    let payload_sha256: String = row.get("payload_sha256");
    let predecessor_receipt_id: Option<String> = row.get("predecessor_receipt_id");
    let revokes_receipt_id: Option<String> = row.get("revokes_receipt_id");
    let revokes_issuer_key_sha256: Option<String> = row.get("revokes_issuer_key_sha256");
    let observed_at_ms: i64 = row.get("observed_at_ms");
    let expires_at_ms: Option<i64> = row.get("expires_at_ms");
    if receipt_id != envelope.receipt_id
        || candidate_id != envelope.candidate.candidate_id
        || source_commit != envelope.candidate.source_commit
        || source_tree != envelope.candidate.source_tree
        || claim_class != envelope.claim_class.as_str()
        || issuer_role != envelope.issuer_role
        || issuer_principal_id != issuer.principal_id
        || signing_identity_sha256 != issuer.signing_identity_sha256.as_str()
        || trust_policy_sha256 != issuer.trust_policy_sha256.as_str()
        || payload_sha256 != envelope.payload_sha256.as_str()
        || predecessor_receipt_id != envelope.predecessor_receipt_id
        || revokes_receipt_id != envelope.revokes_receipt_id
        || revokes_issuer_key_sha256.as_deref()
            != envelope
                .revokes_issuer_key_sha256
                .as_ref()
                .map(Sha256Digest::as_str)
        || u64::try_from(observed_at_ms).ok() != Some(envelope.observed_at_ms)
        || expires_at_ms.and_then(|value| u64::try_from(value).ok()) != envelope.expires_at_ms
    {
        return Err(EvidenceError::Corrupt(
            "qualification evidence projection differs from canonical record".to_string(),
        ));
    }

    let record_sha256 = parse_sha256("record", row.get("record_sha256"))?;
    if record_sha256 != record_digest(&envelope, &issuer)? {
        return Err(EvidenceError::Corrupt(
            "qualification evidence record digest mismatch".to_string(),
        ));
    }
    Ok(StoredQualificationEvidence {
        seq,
        envelope,
        issuer,
        record_sha256,
        previous_chain_sha256: parse_sha256("previous chain", row.get("previous_chain_sha256"))?,
        chain_sha256: parse_sha256("chain", row.get("chain_sha256"))?,
    })
}

#[derive(Serialize)]
struct RecordDigest<'a> {
    envelope: &'a QualificationEvidenceEnvelope,
    issuer: &'a AuthenticatedEvidenceIssuer,
}

fn record_digest(
    envelope: &QualificationEvidenceEnvelope,
    issuer: &AuthenticatedEvidenceIssuer,
) -> Result<Sha256Digest, EvidenceError> {
    Ok(Sha256Digest::for_bytes(&canonical_json(&RecordDigest {
        envelope,
        issuer,
    })?))
}

fn chain_link_digest(previous: &Sha256Digest, record: &Sha256Digest) -> Sha256Digest {
    let mut bytes = Vec::with_capacity(129);
    bytes.extend_from_slice(previous.as_str().as_bytes());
    bytes.push(b':');
    bytes.extend_from_slice(record.as_str().as_bytes());
    Sha256Digest::for_bytes(&bytes)
}

async fn load_trust_policy(
    pool: &SqlitePool,
) -> Result<Option<EvidenceTrustPolicy>, EvidenceError> {
    let row = sqlx::query(
        "SELECT policy_id, revision, policy_sha256, policy_json
         FROM qualification_trust_policy WHERE slot = 1",
    )
    .fetch_optional(pool)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| decode_trust_policy_row(&row)).transpose()
}

async fn load_trust_policy_in_transaction(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<Option<EvidenceTrustPolicy>, EvidenceError> {
    let row = sqlx::query(
        "SELECT policy_id, revision, policy_sha256, policy_json
         FROM qualification_trust_policy WHERE slot = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    row.map(|row| decode_trust_policy_row(&row)).transpose()
}

fn decode_trust_policy_row(
    row: &sqlx::sqlite::SqliteRow,
) -> Result<EvidenceTrustPolicy, EvidenceError> {
    let policy_id: String = row.get("policy_id");
    let revision: i64 = row.get("revision");
    let policy_sha256: String = row.get("policy_sha256");
    let policy_json: String = row.get("policy_json");
    let policy: EvidenceTrustPolicy = serde_json::from_str(&policy_json)
        .map_err(|error| EvidenceError::Corrupt(format!("invalid trust policy JSON: {error}")))?;
    policy
        .validate()
        .map_err(|error| EvidenceError::Corrupt(format!("invalid trust policy: {error}")))?;
    let canonical = canonical_json(&policy)
        .map_err(|error| EvidenceError::Corrupt(format!("trust policy serialization failed: {error}")))?;
    let canonical_text =
        String::from_utf8(canonical.clone()).map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(&canonical);
    if policy_id != policy.policy_id
        || u64::try_from(revision).ok() != Some(policy.revision)
        || policy_sha256 != digest.as_str()
        || policy_json != canonical_text
    {
        return Err(EvidenceError::Corrupt(
            "provisioned qualification trust policy projection mismatch".to_string(),
        ));
    }
    Ok(policy)
}

async fn load_store_instance_id(pool: &SqlitePool) -> Result<Sha256Digest, EvidenceError> {
    let rows: Vec<String> =
        sqlx::query_scalar("SELECT store_instance_id FROM qualification_evidence_meta ORDER BY slot")
            .fetch_all(pool)
            .await
            .map_err(classify_sqlx_error)?;
    if rows.len() != 1 {
        return Err(EvidenceError::Corrupt(
            "qualification evidence store identity is missing or duplicated".to_string(),
        ));
    }
    parse_sha256("store instance", rows[0].clone())
}

fn validate_roles(roles: &[String]) -> Result<(), EvidenceError> {
    if roles.is_empty() || roles.len() > QUALIFICATION_EVIDENCE_MAX_ISSUER_ROLES {
        return Err(invalid("evidence issuer role bound is invalid"));
    }
    let mut seen = BTreeSet::new();
    for role in roles {
        validate_text("evidence issuer role", role, 64)?;
        if !seen.insert(role.as_str()) {
            return Err(invalid("duplicate evidence issuer role"));
        }
    }
    Ok(())
}

fn validate_text(label: &str, value: &str, max_bytes: usize) -> Result<(), EvidenceError> {
    if value.is_empty()
        || value.len() > max_bytes
        || value.trim() != value
        || value.as_bytes().contains(&0)
    {
        Err(invalid(format!("{label} is malformed")))
    } else {
        Ok(())
    }
}

fn validate_git_identity(label: &str, value: &str) -> Result<(), EvidenceError> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(format!(
            "{label} must be 40 or 64 lowercase hexadecimal characters"
        )));
    }
    Ok(())
}

fn validate_sha256(label: &str, digest: &Sha256Digest) -> Result<(), EvidenceError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|_| invalid(format!("{label} SHA-256 digest is malformed")))
}

fn parse_sha256(label: &str, value: String) -> Result<Sha256Digest, EvidenceError> {
    Sha256Digest::parse(value)
        .map_err(|_| EvidenceError::Corrupt(format!("{label} SHA-256 digest is malformed")))
}

fn decode_hex<const N: usize>(value: &str, label: &str) -> Result<[u8; N], EvidenceError> {
    if value.len() != N * 2 {
        return Err(invalid(format!("{label} has an invalid encoded length")));
    }
    let mut out = [0_u8; N];
    for (index, slot) in out.iter_mut().enumerate() {
        let start = index * 2;
        *slot = u8::from_str_radix(&value[start..start + 2], 16)
            .map_err(|_| invalid(format!("{label} is not lowercase hexadecimal")))?;
        if value.as_bytes()[start..start + 2]
            .iter()
            .any(|byte| byte.is_ascii_uppercase())
        {
            return Err(invalid(format!("{label} is not lowercase hexadecimal")));
        }
    }
    Ok(out)
}

fn to_i64(value: u64, label: &str) -> Result<i64, EvidenceError> {
    i64::try_from(value).map_err(|_| invalid(format!("{label} exceeds SQLite range")))
}

fn invalid(message: impl Into<String>) -> EvidenceError {
    EvidenceError::InvalidRecord(message.into())
}
