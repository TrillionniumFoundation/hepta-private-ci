use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::IndependentDecisionReceiptV1;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
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
pub const QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES: usize = 262_144;
pub const QUALIFICATION_EVIDENCE_MAX_ASSETS: usize = 64;
pub const QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES: usize = 256;
pub const QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS: usize = 512;
const QUALIFICATION_EVIDENCE_MAX_VERIFY_ROWS: usize = 4096;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClaimClassV1 {
    SourceExecution,
    MergeExecution,
    Fixture,
    Hardware,
    ProviderEffect,
    Longitudinal,
    IndependentReview,
    OperatorAcceptance,
    TrustRoot,
    Promotion,
    Release,
}

impl EvidenceClaimClassV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SourceExecution => "source_execution",
            Self::MergeExecution => "merge_execution",
            Self::Fixture => "fixture",
            Self::Hardware => "hardware",
            Self::ProviderEffect => "provider_effect",
            Self::Longitudinal => "longitudinal",
            Self::IndependentReview => "independent_review",
            Self::OperatorAcceptance => "operator_acceptance",
            Self::TrustRoot => "trust_root",
            Self::Promotion => "promotion",
            Self::Release => "release",
        }
    }

    fn parse(value: &str) -> Result<Self, EvidenceError> {
        match value {
            "source_execution" => Ok(Self::SourceExecution),
            "merge_execution" => Ok(Self::MergeExecution),
            "fixture" => Ok(Self::Fixture),
            "hardware" => Ok(Self::Hardware),
            "provider_effect" => Ok(Self::ProviderEffect),
            "longitudinal" => Ok(Self::Longitudinal),
            "independent_review" => Ok(Self::IndependentReview),
            "operator_acceptance" => Ok(Self::OperatorAcceptance),
            "trust_root" => Ok(Self::TrustRoot),
            "promotion" => Ok(Self::Promotion),
            "release" => Ok(Self::Release),
            _ => Err(EvidenceError::Corrupt(format!(
                "unknown qualification evidence claim class {value}"
            ))),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceIssuerRoleV1 {
    Generator,
    CiExecutor,
    IndependentEvaluator,
    ArchitectureReviewer,
    SecurityReviewer,
    Operator,
    Provider,
    TerminalObserver,
    ReleaseAuthority,
}

impl EvidenceIssuerRoleV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Generator => "generator",
            Self::CiExecutor => "ci_executor",
            Self::IndependentEvaluator => "independent_evaluator",
            Self::ArchitectureReviewer => "architecture_reviewer",
            Self::SecurityReviewer => "security_reviewer",
            Self::Operator => "operator",
            Self::Provider => "provider",
            Self::TerminalObserver => "terminal_observer",
            Self::ReleaseAuthority => "release_authority",
        }
    }

    fn parse(value: &str) -> Result<Self, EvidenceError> {
        match value {
            "generator" => Ok(Self::Generator),
            "ci_executor" => Ok(Self::CiExecutor),
            "independent_evaluator" => Ok(Self::IndependentEvaluator),
            "architecture_reviewer" => Ok(Self::ArchitectureReviewer),
            "security_reviewer" => Ok(Self::SecurityReviewer),
            "operator" => Ok(Self::Operator),
            "provider" => Ok(Self::Provider),
            "terminal_observer" => Ok(Self::TerminalObserver),
            "release_authority" => Ok(Self::ReleaseAuthority),
            _ => Err(EvidenceError::Corrupt(format!(
                "unknown qualification evidence issuer role {value}"
            ))),
        }
    }

    fn is_independent_decision_role(self) -> bool {
        matches!(
            self,
            Self::IndependentEvaluator | Self::ArchitectureReviewer | Self::SecurityReviewer
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceCandidateV1 {
    pub candidate_id: String,
    pub source_commit: String,
    pub source_tree: String,
}

impl EvidenceCandidateV1 {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        validate_id(&self.candidate_id, "candidate id")?;
        validate_git_oid(&self.source_commit, "candidate source commit")?;
        validate_git_oid(&self.source_tree, "candidate source tree")?;
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct EvidenceId(String);

impl EvidenceId {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceAssetRefV1 {
    pub content_sha256: Sha256Digest,
    pub byte_len: u64,
    pub media_type: String,
}

impl EvidenceAssetRefV1 {
    fn validate(&self) -> Result<(), EvidenceError> {
        if self.media_type.is_empty()
            || self.media_type.len() > 128
            || !self
                .media_type
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._+-/".contains(&byte))
        {
            return invalid("evidence asset media type is invalid");
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidenceEnvelopeV1 {
    pub schema_version: u32,
    pub receipt_id: String,
    pub candidate: EvidenceCandidateV1,
    pub claim_class: EvidenceClaimClassV1,
    pub issuer_role: EvidenceIssuerRoleV1,
    pub issuer_principal: String,
    pub issuer_key_id: String,
    pub payload_sha256: Sha256Digest,
    pub predecessor_receipt_id: Option<String>,
    pub observed_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub revokes_receipt_id: Option<String>,
    pub assets: Vec<EvidenceAssetRefV1>,
}

impl QualificationEvidenceEnvelopeV1 {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        if self.schema_version != QUALIFICATION_EVIDENCE_SCHEMA_VERSION {
            return invalid("qualification evidence schema version is unsupported");
        }
        if self.claim_class == EvidenceClaimClassV1::IndependentReview
            && !self.issuer_role.is_independent_decision_role()
        {
            return invalid("independent review evidence requires an independent issuer role");
        }
        validate_id(&self.receipt_id, "qualification receipt id")?;
        self.candidate.validate()?;
        validate_id(&self.issuer_principal, "issuer principal")?;
        validate_id(&self.issuer_key_id, "issuer key id")?;
        if self.observed_unix_ms == 0 || self.expires_unix_ms <= self.observed_unix_ms {
            return invalid("qualification evidence validity window is invalid");
        }
        if self.assets.len() > QUALIFICATION_EVIDENCE_MAX_ASSETS {
            return invalid("qualification evidence references too many assets");
        }
        for asset in &self.assets {
            asset.validate()?;
        }
        if let Some(predecessor) = self.predecessor_receipt_id.as_deref() {
            validate_id(predecessor, "predecessor receipt id")?;
            if predecessor == self.receipt_id {
                return invalid("qualification evidence cannot precede itself");
            }
        }
        if let Some(revoked) = self.revokes_receipt_id.as_deref() {
            validate_id(revoked, "revoked receipt id")?;
            if revoked == self.receipt_id {
                return invalid("qualification evidence cannot revoke itself");
            }
        }
        let encoded = canonical_json(self)?;
        if encoded.len() > QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES {
            return invalid("qualification evidence exceeds the receipt size bound");
        }
        Ok(())
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        self.validate()?;
        let mut bytes = b"hepta.kernel.evidence.qualification-receipt.v1\0".to_vec();
        bytes.extend(canonical_json(self)?);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SignedQualificationEvidenceEnvelopeV1 {
    pub envelope: QualificationEvidenceEnvelopeV1,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceIssuerCertificateV1 {
    pub schema_version: u32,
    pub root_id: String,
    pub principal_id: String,
    pub key_id: String,
    pub role: EvidenceIssuerRoleV1,
    pub verifying_key: [u8; 32],
    pub not_before_unix_ms: u64,
    pub expires_unix_ms: u64,
}

impl EvidenceIssuerCertificateV1 {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        if self.schema_version != 1 {
            return invalid("issuer certificate schema version is unsupported");
        }
        validate_id(&self.root_id, "issuer certificate root id")?;
        validate_id(&self.principal_id, "issuer certificate principal id")?;
        validate_id(&self.key_id, "issuer certificate key id")?;
        if self.verifying_key == [0; 32]
            || self.not_before_unix_ms == 0
            || self.expires_unix_ms <= self.not_before_unix_ms
        {
            return invalid("issuer certificate validity is invalid");
        }
        Ok(())
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        self.validate()?;
        let mut bytes = b"hepta.kernel.evidence.issuer-certificate.v1\0".to_vec();
        bytes.extend(canonical_json(self)?);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SignedEvidenceIssuerCertificateV1 {
    pub certificate: EvidenceIssuerCertificateV1,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceIssuerRevocationsV1 {
    pub root_id: String,
    pub revision: u64,
    pub revoked_key_ids: BTreeSet<String>,
}

impl EvidenceIssuerRevocationsV1 {
    fn validate(&self) -> Result<(), EvidenceError> {
        validate_id(&self.root_id, "issuer revocation root id")?;
        if self.revision == 0 || self.revoked_key_ids.len() > 16_384 {
            return invalid("issuer revocation head is invalid");
        }
        for key_id in &self.revoked_key_ids {
            validate_id(key_id, "revoked issuer key id")?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct EvidenceIssuerAuthorityV1 {
    root: EvidenceTrustRootV1,
    revocations: EvidenceIssuerRevocationsV1,
}

impl EvidenceIssuerAuthorityV1 {
    pub fn new(
        root: EvidenceTrustRootV1,
        revocations: EvidenceIssuerRevocationsV1,
    ) -> Result<Self, EvidenceError> {
        revocations.validate()?;
        if revocations.root_id != root.root_id() {
            return invalid("issuer authority revocation head is bound to a different trust root");
        }
        Ok(Self { root, revocations })
    }

    pub fn root_id(&self) -> &str {
        self.root.root_id()
    }

    pub fn revision(&self) -> u64 {
        self.revocations.revision
    }

    pub fn authenticate(
        &self,
        signed: SignedEvidenceIssuerCertificateV1,
        now_unix_ms: u64,
    ) -> Result<AuthenticatedEvidenceIssuerV1, EvidenceError> {
        authenticate_evidence_issuer(&self.root, &self.revocations, signed, now_unix_ms)
    }

    fn verify_certificate_signature(
        &self,
        signed: &SignedEvidenceIssuerCertificateV1,
    ) -> Result<(), EvidenceError> {
        signed.certificate.validate()?;
        if signed.certificate.root_id != self.root.root_id {
            return invalid("stored issuer certificate is bound to a different trust root");
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| invalid_error("stored issuer certificate signature is malformed"))?;
        self.root
            .verifying_key
            .verify_strict(&signed.certificate.signing_bytes()?, &signature)
            .map_err(|_| invalid_error("stored issuer certificate signature is invalid"))?;
        let verifying_key = VerifyingKey::from_bytes(&signed.certificate.verifying_key)
            .map_err(|_| invalid_error("stored issuer certificate verifying key is invalid"))?;
        if verifying_key.is_weak() {
            return invalid("stored issuer certificate verifying key is weak");
        }
        Ok(())
    }

    fn extend_revoked_keys(&self, keys: &mut BTreeSet<(String, String)>) {
        for key_id in &self.revocations.revoked_key_ids {
            keys.insert((self.root.root_id.clone(), key_id.clone()));
        }
    }

    fn is_key_revoked(&self, root_id: &str, key_id: &str) -> bool {
        root_id == self.root.root_id && self.revocations.revoked_key_ids.contains(key_id)
    }
}

#[derive(Clone)]
pub struct EvidenceTrustRootV1 {
    root_id: String,
    verifying_key: VerifyingKey,
}

impl std::fmt::Debug for EvidenceTrustRootV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("EvidenceTrustRootV1")
            .field("root_id", &self.root_id)
            .field("verifying_key", &"[PINNED]")
            .finish()
    }
}

impl EvidenceTrustRootV1 {
    pub fn new(root_id: String, verifying_key: [u8; 32]) -> Result<Self, EvidenceError> {
        validate_id(&root_id, "evidence trust root id")?;
        let verifying_key = VerifyingKey::from_bytes(&verifying_key)
            .map_err(|_| invalid_error("invalid trust root"))?;
        if verifying_key.is_weak() {
            return invalid("evidence trust root is weak");
        }
        Ok(Self {
            root_id,
            verifying_key,
        })
    }

    pub fn root_id(&self) -> &str {
        &self.root_id
    }
}

#[derive(Clone)]
pub struct AuthenticatedEvidenceIssuerV1 {
    signed_certificate: SignedEvidenceIssuerCertificateV1,
    verifying_key: VerifyingKey,
}

impl std::fmt::Debug for AuthenticatedEvidenceIssuerV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("AuthenticatedEvidenceIssuerV1")
            .field("principal_id", &self.principal_id())
            .field("key_id", &self.key_id())
            .field("role", &self.role())
            .field("verifying_key", &"[AUTHENTICATED]")
            .finish()
    }
}

impl AuthenticatedEvidenceIssuerV1 {
    pub fn principal_id(&self) -> &str {
        &self.signed_certificate.certificate.principal_id
    }

    pub fn key_id(&self) -> &str {
        &self.signed_certificate.certificate.key_id
    }

    pub fn root_id(&self) -> &str {
        &self.signed_certificate.certificate.root_id
    }

    pub fn role(&self) -> EvidenceIssuerRoleV1 {
        self.signed_certificate.certificate.role
    }

    pub fn expires_unix_ms(&self) -> u64 {
        self.signed_certificate.certificate.expires_unix_ms
    }

    pub fn signing_identity_digest(&self) -> Sha256Digest {
        Sha256Digest::for_bytes(self.verifying_key.as_bytes())
    }
}

pub fn authenticate_evidence_issuer(
    root: &EvidenceTrustRootV1,
    revocations: &EvidenceIssuerRevocationsV1,
    signed: SignedEvidenceIssuerCertificateV1,
    now_unix_ms: u64,
) -> Result<AuthenticatedEvidenceIssuerV1, EvidenceError> {
    signed.certificate.validate()?;
    revocations.validate()?;
    if signed.certificate.root_id != root.root_id || revocations.root_id != root.root_id {
        return invalid("issuer certificate trust root binding is invalid");
    }
    if revocations
        .revoked_key_ids
        .contains(&signed.certificate.key_id)
    {
        return invalid("issuer certificate key is revoked");
    }
    if now_unix_ms < signed.certificate.not_before_unix_ms
        || now_unix_ms >= signed.certificate.expires_unix_ms
    {
        return invalid("issuer certificate is not live");
    }
    let signature = Signature::from_slice(&signed.signature)
        .map_err(|_| invalid_error("issuer certificate signature is malformed"))?;
    root.verifying_key
        .verify_strict(&signed.certificate.signing_bytes()?, &signature)
        .map_err(|_| invalid_error("issuer certificate signature is invalid"))?;
    let verifying_key = VerifyingKey::from_bytes(&signed.certificate.verifying_key)
        .map_err(|_| invalid_error("issuer certificate verifying key is invalid"))?;
    if verifying_key.is_weak() {
        return invalid("issuer certificate verifying key is weak");
    }
    Ok(AuthenticatedEvidenceIssuerV1 {
        signed_certificate: signed,
        verifying_key,
    })
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceIssuerKeyRevocationV1 {
    pub schema_version: u32,
    pub revocation_id: String,
    pub root_id: String,
    pub key_id: String,
    pub observed_unix_ms: u64,
    pub reason_code: String,
}

impl EvidenceIssuerKeyRevocationV1 {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        if self.schema_version != 1 {
            return invalid("issuer key revocation schema version is unsupported");
        }
        validate_id(&self.revocation_id, "issuer key revocation id")?;
        validate_id(&self.root_id, "issuer key revocation root id")?;
        validate_id(&self.key_id, "issuer key revocation key id")?;
        if self.observed_unix_ms == 0
            || self.reason_code.is_empty()
            || self.reason_code.len() > 128
            || !self.reason_code.bytes().all(|byte| {
                byte.is_ascii_lowercase() || byte.is_ascii_digit() || b"._-".contains(&byte)
            })
        {
            return invalid("issuer key revocation reason or time is invalid");
        }
        Ok(())
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        self.validate()?;
        let mut bytes = b"hepta.kernel.evidence.issuer-key-revocation.v1\0".to_vec();
        bytes.extend(canonical_json(self)?);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SignedEvidenceIssuerKeyRevocationV1 {
    pub revocation: EvidenceIssuerKeyRevocationV1,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EvidenceReferenceV1 {
    pub receipt_id: String,
    pub claim_class: EvidenceClaimClassV1,
    pub issuer_role: EvidenceIssuerRoleV1,
    pub issuer_principal: String,
    pub payload_sha256: Sha256Digest,
    pub observed_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EvidenceDispositionV1 {
    Supported {
        receipts: Vec<EvidenceReferenceV1>,
    },
    Missing {
        roles: Vec<EvidenceIssuerRoleV1>,
    },
    Expired {
        receipt_ids: Vec<String>,
    },
    Conflicting {
        receipt_ids: Vec<String>,
        reason_code: String,
    },
}

#[derive(Clone)]
struct LoadedQualificationReceipt {
    seq: i64,
    issuer_root_id: String,
    envelope: QualificationEvidenceEnvelopeV1,
}

impl HeptaEvidenceStore {
    /// Target kernel.evidence append contract. The authenticated issuer is a
    /// host-created value whose certificate has already been checked against a
    /// pinned trust root and current revocation head.
    pub async fn append_receipt(
        &self,
        signed: &SignedQualificationEvidenceEnvelopeV1,
        issuer: &AuthenticatedEvidenceIssuerV1,
    ) -> Result<EvidenceId, EvidenceError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        append_qualification_receipt_in_transaction(&mut transaction, signed, issuer).await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(EvidenceId(signed.envelope.receipt_id.clone()))
    }

    pub async fn append_independent_decision_receipt(
        &self,
        signed: &SignedQualificationEvidenceEnvelopeV1,
        issuer: &AuthenticatedEvidenceIssuerV1,
        decision: &IndependentDecisionReceiptV1,
    ) -> Result<AppendDisposition, EvidenceError> {
        decision
            .validate()
            .map_err(|error| EvidenceError::InvalidRecord(error.to_string()))?;
        validate_independent_decision_binding(signed, issuer, decision)?;
        let decision_payload = decision
            .canonical_bytes()
            .map_err(EvidenceError::Serialization)?;
        let decision_digest = Sha256Digest::for_bytes(&decision_payload);
        if decision_digest != signed.envelope.payload_sha256 {
            return invalid(
                "independent decision payload digest does not bind the evidence envelope",
            );
        }

        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let receipt_disposition =
            append_qualification_receipt_in_transaction(&mut transaction, signed, issuer).await?;
        let payload_json = String::from_utf8(decision_payload)
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let conditions_json = serde_json::to_string(&decision.conditions)
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        sqlx::query(
            "INSERT INTO independent_decision_receipts (
                decision_id, receipt_id, candidate_id, role, principal_id,
                signing_identity_digest, evidence_set_digest, decision,
                conditions_json, expires_unix_ms, payload_json, payload_sha256
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(&decision.decision_id)
        .bind(&signed.envelope.receipt_id)
        .bind(&decision.candidate_id)
        .bind(&decision.role)
        .bind(&decision.principal_id)
        .bind(decision.signing_identity_digest.as_str())
        .bind(decision.evidence_set_digest.as_str())
        .bind(&decision.decision)
        .bind(&conditions_json)
        .bind(to_i64(
            decision.expires_unix_ms,
            "independent decision expiry",
        )?)
        .bind(&payload_json)
        .bind(decision_digest.as_str())
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        verify_independent_decision_in_transaction(
            &mut transaction,
            decision,
            &signed.envelope.receipt_id,
            &payload_json,
            decision_digest.as_str(),
        )
        .await?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(receipt_disposition)
    }

    pub async fn append_issuer_key_revocation(
        &self,
        signed: &SignedEvidenceIssuerKeyRevocationV1,
        authority: &AuthenticatedEvidenceIssuerV1,
    ) -> Result<AppendDisposition, EvidenceError> {
        signed.revocation.validate()?;
        if authority.role() != EvidenceIssuerRoleV1::SecurityReviewer
            || signed.revocation.root_id != authority.root_id()
        {
            return invalid("issuer key revocation requires the matching security reviewer root");
        }
        if signed.revocation.observed_unix_ms >= authority.expires_unix_ms() {
            return invalid("issuer key revocation is outside the authority certificate window");
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| invalid_error("issuer key revocation signature is malformed"))?;
        authority
            .verifying_key
            .verify_strict(&signed.revocation.signing_bytes()?, &signature)
            .map_err(|_| invalid_error("issuer key revocation signature is invalid"))?;
        let payload = canonical_json(&signed.revocation)?;
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let payload_sha256 = Sha256Digest::for_bytes(&payload);
        let authority_key = authority.verifying_key.as_bytes().to_vec();
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let insert = sqlx::query(
            "INSERT INTO qualification_issuer_key_revocations (
                revocation_id, root_id, key_id, observed_unix_ms, reason_code,
                authority_principal, authority_key_id, authority_role,
                authority_verifying_key, payload_json, payload_sha256, signature,
                recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(&signed.revocation.revocation_id)
        .bind(&signed.revocation.root_id)
        .bind(&signed.revocation.key_id)
        .bind(to_i64(
            signed.revocation.observed_unix_ms,
            "issuer key revocation observation",
        )?)
        .bind(&signed.revocation.reason_code)
        .bind(authority.principal_id())
        .bind(authority.key_id())
        .bind(authority.role().as_str())
        .bind(authority_key)
        .bind(&payload_json)
        .bind(payload_sha256.as_str())
        .bind(&signed.signature)
        .bind(now_millis()?)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let row = sqlx::query(
            "SELECT root_id, key_id, payload_json, payload_sha256, signature
             FROM qualification_issuer_key_revocations WHERE revocation_id = ?",
        )
        .bind(&signed.revocation.revocation_id)
        .fetch_one(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        let same = row
            .try_get::<String, _>("root_id")
            .map_err(classify_sqlx_error)?
            == signed.revocation.root_id
            && row
                .try_get::<String, _>("key_id")
                .map_err(classify_sqlx_error)?
                == signed.revocation.key_id
            && row
                .try_get::<String, _>("payload_json")
                .map_err(classify_sqlx_error)?
                == payload_json
            && row
                .try_get::<String, _>("payload_sha256")
                .map_err(classify_sqlx_error)?
                == payload_sha256.as_str()
            && row
                .try_get::<Vec<u8>, _>("signature")
                .map_err(classify_sqlx_error)?
                == signed.signature;
        if !same {
            return Err(EvidenceError::IdempotencyConflict {
                record_id: signed.revocation.revocation_id.clone(),
            });
        }
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(if insert.rows_affected() == 1 {
            AppendDisposition::Inserted
        } else {
            AppendDisposition::AlreadyPresent
        })
    }

    pub async fn verify_qualification_trust(
        &self,
        authority: &EvidenceIssuerAuthorityV1,
    ) -> Result<(), EvidenceError> {
        verify_qualification_evidence_rows(&self.pool).await?;
        let rows = sqlx::query(
            "SELECT DISTINCT issuer_certificate_json, issuer_certificate_signature
             FROM qualification_evidence
             ORDER BY issuer_certificate_sha256",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        for row in rows {
            let certificate_json: String = row
                .try_get("issuer_certificate_json")
                .map_err(classify_sqlx_error)?;
            let certificate: EvidenceIssuerCertificateV1 =
                serde_json::from_str(&certificate_json).map_err(|error| {
                    EvidenceError::Corrupt(format!(
                        "stored qualification issuer certificate failed to decode: {error}"
                    ))
                })?;
            let signature: Vec<u8> = row
                .try_get("issuer_certificate_signature")
                .map_err(classify_sqlx_error)?;
            authority
                .verify_certificate_signature(&SignedEvidenceIssuerCertificateV1 {
                    certificate,
                    signature,
                })
                .map_err(|error| {
                    EvidenceError::Corrupt(format!(
                        "stored qualification issuer certificate is not trusted: {error}"
                    ))
                })?;
        }
        Ok(())
    }

    pub async fn query_claim_with_authority(
        &self,
        candidate: &EvidenceCandidateV1,
        claim_class: EvidenceClaimClassV1,
        authority: &EvidenceIssuerAuthorityV1,
    ) -> Result<Vec<EvidenceReferenceV1>, EvidenceError> {
        self.verify_qualification_trust(authority).await?;
        candidate.validate()?;
        let rows = sqlx::query(
            "SELECT q.receipt_id, q.claim_class, q.issuer_role, q.issuer_principal,
                    q.issuer_root_id, q.issuer_key_id, q.payload_sha256,
                    q.observed_unix_ms, q.expires_unix_ms,
                    EXISTS(
                        SELECT 1 FROM qualification_evidence r
                        WHERE r.revokes_receipt_id = q.receipt_id
                    ) AS revoked
             FROM qualification_evidence q
             WHERE q.candidate_id = ? AND q.source_commit = ? AND q.source_tree = ?
               AND q.claim_class = ?
             ORDER BY q.seq DESC
             LIMIT 513",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(claim_class.as_str())
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.len() > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
            return invalid("qualification claim query exceeds the bounded result limit");
        }
        rows.into_iter()
            .map(|row| {
                let root_id: String = row
                    .try_get("issuer_root_id")
                    .map_err(classify_sqlx_error)?;
                let key_id: String = row.try_get("issuer_key_id").map_err(classify_sqlx_error)?;
                let mut reference = reference_from_row(row)?;
                if authority.is_key_revoked(&root_id, &key_id) {
                    reference.revoked = true;
                }
                Ok(reference)
            })
            .collect()
    }

    pub async fn query_claim(
        &self,
        candidate: &EvidenceCandidateV1,
        claim_class: EvidenceClaimClassV1,
    ) -> Result<Vec<EvidenceReferenceV1>, EvidenceError> {
        candidate.validate()?;
        verify_qualification_evidence_rows(&self.pool).await?;
        let rows = sqlx::query(
            "SELECT q.receipt_id, q.claim_class, q.issuer_role, q.issuer_principal,
                    q.payload_sha256, q.observed_unix_ms, q.expires_unix_ms,
                    EXISTS(
                        SELECT 1 FROM qualification_evidence r
                        WHERE r.revokes_receipt_id = q.receipt_id
                    ) AS revoked
             FROM qualification_evidence q
             WHERE q.candidate_id = ? AND q.source_commit = ? AND q.source_tree = ?
               AND q.claim_class = ?
             ORDER BY q.seq DESC
             LIMIT 513",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(claim_class.as_str())
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.len() > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
            return invalid("qualification claim query exceeds the bounded result limit");
        }
        rows.into_iter().map(reference_from_row).collect()
    }

    pub async fn verify_chain(
        &self,
        candidate: &EvidenceCandidateV1,
        required_roles: &[EvidenceIssuerRoleV1],
        now_unix_ms: u64,
    ) -> Result<EvidenceDispositionV1, EvidenceError> {
        self.verify_chain_inner(candidate, required_roles, now_unix_ms, None)
            .await
    }

    pub async fn verify_chain_with_authority(
        &self,
        candidate: &EvidenceCandidateV1,
        required_roles: &[EvidenceIssuerRoleV1],
        now_unix_ms: u64,
        authority: &EvidenceIssuerAuthorityV1,
    ) -> Result<EvidenceDispositionV1, EvidenceError> {
        self.verify_qualification_trust(authority).await?;
        self.verify_chain_inner(candidate, required_roles, now_unix_ms, Some(authority))
            .await
    }

    async fn verify_chain_inner(
        &self,
        candidate: &EvidenceCandidateV1,
        required_roles: &[EvidenceIssuerRoleV1],
        now_unix_ms: u64,
        authority: Option<&EvidenceIssuerAuthorityV1>,
    ) -> Result<EvidenceDispositionV1, EvidenceError> {
        candidate.validate()?;
        if required_roles.is_empty() || required_roles.len() > 32 || now_unix_ms == 0 {
            return invalid("qualification chain verification request is invalid");
        }
        let unique_roles = required_roles.iter().copied().collect::<BTreeSet<_>>();
        if unique_roles.len() != required_roles.len() {
            return invalid("qualification chain required roles contain duplicates");
        }
        if authority.is_none() {
            verify_qualification_evidence_rows(&self.pool).await?;
        }
        let rows = sqlx::query(
            "SELECT seq, issuer_root_id, envelope_json
             FROM qualification_evidence
             WHERE candidate_id = ? AND source_commit = ? AND source_tree = ?
             ORDER BY seq ASC
             LIMIT 4097",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.len() > QUALIFICATION_EVIDENCE_MAX_VERIFY_ROWS {
            return invalid("qualification candidate has too many receipts to verify");
        }
        let mut receipts = Vec::with_capacity(rows.len());
        for row in rows {
            let envelope_json: String =
                row.try_get("envelope_json").map_err(classify_sqlx_error)?;
            let envelope: QualificationEvidenceEnvelopeV1 = serde_json::from_str(&envelope_json)
                .map_err(|error| {
                    EvidenceError::Corrupt(format!(
                        "qualification evidence envelope failed to decode: {error}"
                    ))
                })?;
            receipts.push(LoadedQualificationReceipt {
                seq: row.try_get("seq").map_err(classify_sqlx_error)?,
                issuer_root_id: row.try_get("issuer_root_id").map_err(classify_sqlx_error)?,
                envelope,
            });
        }
        let by_id = receipts
            .iter()
            .map(|receipt| (receipt.envelope.receipt_id.as_str(), receipt))
            .collect::<BTreeMap<_, _>>();
        let revoked_receipts = receipts
            .iter()
            .filter_map(|receipt| receipt.envelope.revokes_receipt_id.as_deref())
            .collect::<BTreeSet<_>>();
        let mut revoked_keys = load_revoked_keys(&self.pool, now_unix_ms).await?;
        if let Some(authority) = authority {
            authority.extend_revoked_keys(&mut revoked_keys);
        }

        let mut missing = Vec::new();
        let mut expired = Vec::new();
        let mut chosen = Vec::new();
        for role in required_roles {
            let role_receipts = receipts
                .iter()
                .filter(|receipt| receipt.envelope.issuer_role == *role)
                .collect::<Vec<_>>();
            let live = role_receipts
                .iter()
                .copied()
                .filter(|receipt| {
                    !revoked_receipts.contains(receipt.envelope.receipt_id.as_str())
                        && !revoked_keys.contains(&(
                            receipt.issuer_root_id.clone(),
                            receipt.envelope.issuer_key_id.clone(),
                        ))
                        && receipt.envelope.observed_unix_ms <= now_unix_ms
                        && now_unix_ms < receipt.envelope.expires_unix_ms
                })
                .collect::<Vec<_>>();
            if live.is_empty() {
                let mut role_expired = role_receipts
                    .iter()
                    .filter(|receipt| receipt.envelope.expires_unix_ms <= now_unix_ms)
                    .map(|receipt| receipt.envelope.receipt_id.clone())
                    .collect::<Vec<_>>();
                if role_expired.is_empty() {
                    missing.push(*role);
                } else {
                    expired.append(&mut role_expired);
                }
                continue;
            }
            let payloads = live
                .iter()
                .map(|receipt| receipt.envelope.payload_sha256.as_str())
                .collect::<BTreeSet<_>>();
            if payloads.len() > 1 {
                return Ok(EvidenceDispositionV1::Conflicting {
                    receipt_ids: live
                        .iter()
                        .map(|receipt| receipt.envelope.receipt_id.clone())
                        .collect(),
                    reason_code: "same_role_conflicting_payloads".to_string(),
                });
            }
            let receipt = live
                .into_iter()
                .max_by_key(|receipt| receipt.seq)
                .expect("live evidence is non-empty");
            verify_predecessor_chain(
                receipt,
                &by_id,
                &revoked_receipts,
                &revoked_keys,
                now_unix_ms,
            )?;
            chosen.push(receipt);
        }

        if !expired.is_empty() {
            expired.sort();
            expired.dedup();
            return Ok(EvidenceDispositionV1::Expired {
                receipt_ids: expired,
            });
        }
        if !missing.is_empty() {
            return Ok(EvidenceDispositionV1::Missing { roles: missing });
        }

        let mut principals = BTreeSet::new();
        let mut keys = BTreeSet::new();
        for receipt in &chosen {
            if !principals.insert(receipt.envelope.issuer_principal.as_str()) {
                return Ok(EvidenceDispositionV1::Conflicting {
                    receipt_ids: chosen
                        .iter()
                        .map(|item| item.envelope.receipt_id.clone())
                        .collect(),
                    reason_code: "independent_roles_share_principal".to_string(),
                });
            }
            if !keys.insert(receipt.envelope.issuer_key_id.as_str()) {
                return Ok(EvidenceDispositionV1::Conflicting {
                    receipt_ids: chosen
                        .iter()
                        .map(|item| item.envelope.receipt_id.clone())
                        .collect(),
                    reason_code: "independent_roles_share_signing_key".to_string(),
                });
            }
        }
        let mut references = Vec::with_capacity(chosen.len());
        for receipt in chosen {
            references.push(EvidenceReferenceV1 {
                receipt_id: receipt.envelope.receipt_id.clone(),
                claim_class: receipt.envelope.claim_class,
                issuer_role: receipt.envelope.issuer_role,
                issuer_principal: receipt.envelope.issuer_principal.clone(),
                payload_sha256: receipt.envelope.payload_sha256.clone(),
                observed_unix_ms: receipt.envelope.observed_unix_ms,
                expires_unix_ms: receipt.envelope.expires_unix_ms,
                revoked: false,
            });
        }
        Ok(EvidenceDispositionV1::Supported {
            receipts: references,
        })
    }
}

async fn append_qualification_receipt_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    signed: &SignedQualificationEvidenceEnvelopeV1,
    issuer: &AuthenticatedEvidenceIssuerV1,
) -> Result<AppendDisposition, EvidenceError> {
    signed.envelope.validate()?;
    if signed.envelope.issuer_role != issuer.role()
        || signed.envelope.issuer_principal != issuer.principal_id()
        || signed.envelope.issuer_key_id != issuer.key_id()
        || signed.envelope.observed_unix_ms
            < issuer.signed_certificate.certificate.not_before_unix_ms
        || signed.envelope.expires_unix_ms > issuer.expires_unix_ms()
    {
        return invalid("qualification evidence issuer binding is invalid");
    }
    let persisted_revocation: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM qualification_issuer_key_revocations
         WHERE root_id = ? AND key_id = ? AND observed_unix_ms <= ?",
    )
    .bind(issuer.root_id())
    .bind(issuer.key_id())
    .bind(to_i64(
        signed.envelope.observed_unix_ms,
        "qualification evidence observation",
    )?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    if persisted_revocation != 0 {
        return invalid("qualification evidence issuer key is durably revoked");
    }

    let signature = Signature::from_slice(&signed.signature)
        .map_err(|_| invalid_error("qualification evidence signature is malformed"))?;
    issuer
        .verifying_key
        .verify_strict(&signed.envelope.signing_bytes()?, &signature)
        .map_err(|_| invalid_error("qualification evidence signature is invalid"))?;

    verify_optional_receipt_binding(
        transaction,
        signed.envelope.predecessor_receipt_id.as_deref(),
        &signed.envelope.candidate,
        "predecessor",
    )
    .await?;
    verify_optional_receipt_binding(
        transaction,
        signed.envelope.revokes_receipt_id.as_deref(),
        &signed.envelope.candidate,
        "revocation target",
    )
    .await?;

    let envelope_bytes = canonical_json(&signed.envelope)?;
    let envelope_json = String::from_utf8(envelope_bytes.clone())
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let envelope_sha256 = Sha256Digest::for_bytes(&envelope_bytes);
    let certificate_bytes = canonical_json(&issuer.signed_certificate.certificate)?;
    let certificate_json = String::from_utf8(certificate_bytes.clone())
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
    let certificate_sha256 = Sha256Digest::for_bytes(&certificate_bytes);
    let insert = sqlx::query(
        "INSERT INTO qualification_evidence (
            receipt_id, candidate_id, source_commit, source_tree, claim_class,
            issuer_role, issuer_principal, issuer_key_id, issuer_root_id,
            issuer_verifying_key, issuer_certificate_json, issuer_certificate_sha256,
            issuer_certificate_signature, payload_sha256, predecessor_receipt_id,
            observed_unix_ms, expires_unix_ms, revokes_receipt_id, envelope_json,
            envelope_sha256, signature, recorded_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT DO NOTHING",
    )
    .bind(&signed.envelope.receipt_id)
    .bind(&signed.envelope.candidate.candidate_id)
    .bind(&signed.envelope.candidate.source_commit)
    .bind(&signed.envelope.candidate.source_tree)
    .bind(signed.envelope.claim_class.as_str())
    .bind(signed.envelope.issuer_role.as_str())
    .bind(&signed.envelope.issuer_principal)
    .bind(&signed.envelope.issuer_key_id)
    .bind(issuer.root_id())
    .bind(issuer.verifying_key.as_bytes().to_vec())
    .bind(&certificate_json)
    .bind(certificate_sha256.as_str())
    .bind(&issuer.signed_certificate.signature)
    .bind(signed.envelope.payload_sha256.as_str())
    .bind(signed.envelope.predecessor_receipt_id.as_deref())
    .bind(to_i64(
        signed.envelope.observed_unix_ms,
        "qualification evidence observation",
    )?)
    .bind(to_i64(
        signed.envelope.expires_unix_ms,
        "qualification evidence expiry",
    )?)
    .bind(signed.envelope.revokes_receipt_id.as_deref())
    .bind(&envelope_json)
    .bind(envelope_sha256.as_str())
    .bind(&signed.signature)
    .bind(now_millis()?)
    .execute(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;

    let row = sqlx::query(
        "SELECT issuer_root_id, issuer_verifying_key, issuer_certificate_sha256,
                payload_sha256, envelope_json, envelope_sha256, signature
         FROM qualification_evidence WHERE receipt_id = ?",
    )
    .bind(&signed.envelope.receipt_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let same = row
        .try_get::<String, _>("issuer_root_id")
        .map_err(classify_sqlx_error)?
        == issuer.root_id()
        && row
            .try_get::<Vec<u8>, _>("issuer_verifying_key")
            .map_err(classify_sqlx_error)?
            == issuer.verifying_key.as_bytes()
        && row
            .try_get::<String, _>("issuer_certificate_sha256")
            .map_err(classify_sqlx_error)?
            == certificate_sha256.as_str()
        && row
            .try_get::<String, _>("payload_sha256")
            .map_err(classify_sqlx_error)?
            == signed.envelope.payload_sha256.as_str()
        && row
            .try_get::<String, _>("envelope_json")
            .map_err(classify_sqlx_error)?
            == envelope_json
        && row
            .try_get::<String, _>("envelope_sha256")
            .map_err(classify_sqlx_error)?
            == envelope_sha256.as_str()
        && row
            .try_get::<Vec<u8>, _>("signature")
            .map_err(classify_sqlx_error)?
            == signed.signature;
    if !same {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: signed.envelope.receipt_id.clone(),
        });
    }
    Ok(if insert.rows_affected() == 1 {
        AppendDisposition::Inserted
    } else {
        AppendDisposition::AlreadyPresent
    })
}

async fn verify_optional_receipt_binding(
    transaction: &mut Transaction<'_, Sqlite>,
    receipt_id: Option<&str>,
    candidate: &EvidenceCandidateV1,
    label: &str,
) -> Result<(), EvidenceError> {
    let Some(receipt_id) = receipt_id else {
        return Ok(());
    };
    let row = sqlx::query(
        "SELECT candidate_id, source_commit, source_tree
         FROM qualification_evidence WHERE receipt_id = ?",
    )
    .bind(receipt_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?
    .ok_or_else(|| EvidenceError::InvalidRecord(format!("{label} receipt does not exist")))?;
    if row
        .try_get::<String, _>("candidate_id")
        .map_err(classify_sqlx_error)?
        != candidate.candidate_id
        || row
            .try_get::<String, _>("source_commit")
            .map_err(classify_sqlx_error)?
            != candidate.source_commit
        || row
            .try_get::<String, _>("source_tree")
            .map_err(classify_sqlx_error)?
            != candidate.source_tree
    {
        return invalid(&format!(
            "{label} receipt belongs to a different exact candidate"
        ));
    }
    Ok(())
}

fn validate_independent_decision_binding(
    signed: &SignedQualificationEvidenceEnvelopeV1,
    issuer: &AuthenticatedEvidenceIssuerV1,
    decision: &IndependentDecisionReceiptV1,
) -> Result<(), EvidenceError> {
    if signed.envelope.claim_class != EvidenceClaimClassV1::IndependentReview
        || !issuer.role().is_independent_decision_role()
        || decision.candidate_id != signed.envelope.candidate.candidate_id
        || decision.role != issuer.role().as_str()
        || decision.principal_id != issuer.principal_id()
        || decision.signing_identity_digest != issuer.signing_identity_digest()
        || decision.expires_unix_ms > signed.envelope.expires_unix_ms
    {
        return invalid("independent decision does not bind the authenticated evidence issuer");
    }
    Ok(())
}

async fn verify_independent_decision_in_transaction(
    transaction: &mut Transaction<'_, Sqlite>,
    decision: &IndependentDecisionReceiptV1,
    receipt_id: &str,
    payload_json: &str,
    payload_sha256: &str,
) -> Result<(), EvidenceError> {
    let row = sqlx::query(
        "SELECT receipt_id, payload_json, payload_sha256
         FROM independent_decision_receipts WHERE decision_id = ?",
    )
    .bind(&decision.decision_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    let same = row
        .try_get::<String, _>("receipt_id")
        .map_err(classify_sqlx_error)?
        == receipt_id
        && row
            .try_get::<String, _>("payload_json")
            .map_err(classify_sqlx_error)?
            == payload_json
        && row
            .try_get::<String, _>("payload_sha256")
            .map_err(classify_sqlx_error)?
            == payload_sha256;
    if !same {
        return Err(EvidenceError::IdempotencyConflict {
            record_id: decision.decision_id.clone(),
        });
    }
    Ok(())
}

fn verify_predecessor_chain(
    start: &LoadedQualificationReceipt,
    by_id: &BTreeMap<&str, &LoadedQualificationReceipt>,
    revoked_receipts: &BTreeSet<&str>,
    revoked_keys: &BTreeSet<(String, String)>,
    now_unix_ms: u64,
) -> Result<(), EvidenceError> {
    let mut current = start;
    let mut visited = BTreeSet::new();
    for _ in 0..=QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES {
        if !visited.insert(current.envelope.receipt_id.as_str()) {
            return Err(EvidenceError::Corrupt(
                "qualification evidence predecessor chain contains a cycle".to_string(),
            ));
        }
        if revoked_receipts.contains(current.envelope.receipt_id.as_str())
            || revoked_keys.contains(&(
                current.issuer_root_id.clone(),
                current.envelope.issuer_key_id.clone(),
            ))
        {
            return Err(EvidenceError::InvalidRecord(
                "qualification evidence predecessor chain contains revoked evidence".to_string(),
            ));
        }
        if current.envelope.observed_unix_ms > now_unix_ms
            || current.envelope.expires_unix_ms <= now_unix_ms
        {
            return Err(EvidenceError::InvalidRecord(
                "qualification evidence predecessor chain contains stale evidence".to_string(),
            ));
        }
        let Some(predecessor) = current.envelope.predecessor_receipt_id.as_deref() else {
            return Ok(());
        };
        current = by_id.get(predecessor).copied().ok_or_else(|| {
            EvidenceError::Corrupt(
                "qualification evidence predecessor is missing from the exact candidate"
                    .to_string(),
            )
        })?;
    }
    Err(EvidenceError::InvalidRecord(
        "qualification evidence predecessor traversal exceeded the bounded edge limit".to_string(),
    ))
}

async fn load_revoked_keys(
    pool: &SqlitePool,
    now_unix_ms: u64,
) -> Result<BTreeSet<(String, String)>, EvidenceError> {
    let rows = sqlx::query(
        "SELECT root_id, key_id
         FROM qualification_issuer_key_revocations
         WHERE observed_unix_ms <= ?",
    )
    .bind(to_i64(now_unix_ms, "qualification verification time")?)
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    rows.into_iter()
        .map(|row| {
            Ok((
                row.try_get("root_id").map_err(classify_sqlx_error)?,
                row.try_get("key_id").map_err(classify_sqlx_error)?,
            ))
        })
        .collect()
}

fn reference_from_row(row: sqlx::sqlite::SqliteRow) -> Result<EvidenceReferenceV1, EvidenceError> {
    let claim_class = EvidenceClaimClassV1::parse(
        &row.try_get::<String, _>("claim_class")
            .map_err(classify_sqlx_error)?,
    )?;
    let issuer_role = EvidenceIssuerRoleV1::parse(
        &row.try_get::<String, _>("issuer_role")
            .map_err(classify_sqlx_error)?,
    )?;
    Ok(EvidenceReferenceV1 {
        receipt_id: row.try_get("receipt_id").map_err(classify_sqlx_error)?,
        claim_class,
        issuer_role,
        issuer_principal: row
            .try_get("issuer_principal")
            .map_err(classify_sqlx_error)?,
        payload_sha256: Sha256Digest::parse(
            row.try_get::<String, _>("payload_sha256")
                .map_err(classify_sqlx_error)?,
        )
        .map_err(EvidenceError::Corrupt)?,
        observed_unix_ms: from_i64(
            row.try_get("observed_unix_ms")
                .map_err(classify_sqlx_error)?,
            "qualification evidence observation",
        )?,
        expires_unix_ms: from_i64(
            row.try_get("expires_unix_ms")
                .map_err(classify_sqlx_error)?,
            "qualification evidence expiry",
        )?,
        revoked: row
            .try_get::<i64, _>("revoked")
            .map_err(classify_sqlx_error)?
            != 0,
    })
}

pub(crate) async fn verify_qualification_evidence_rows(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let rows = sqlx::query(
        "SELECT receipt_id, candidate_id, source_commit, source_tree, claim_class,
                issuer_role, issuer_principal, issuer_key_id, issuer_root_id,
                issuer_verifying_key, issuer_certificate_json, issuer_certificate_sha256,
                issuer_certificate_signature, payload_sha256, predecessor_receipt_id,
                observed_unix_ms, expires_unix_ms, revokes_receipt_id, envelope_json,
                envelope_sha256, signature
         FROM qualification_evidence ORDER BY seq ASC",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in rows {
        verify_qualification_row(&row)?;
    }

    let invalid_link_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM qualification_evidence AS current
         LEFT JOIN qualification_evidence AS predecessor
           ON predecessor.receipt_id = current.predecessor_receipt_id
         LEFT JOIN qualification_evidence AS revoked
           ON revoked.receipt_id = current.revokes_receipt_id
         WHERE (
             current.predecessor_receipt_id IS NOT NULL
             AND (
                 predecessor.receipt_id IS NULL
                 OR predecessor.candidate_id != current.candidate_id
                 OR predecessor.source_commit != current.source_commit
                 OR predecessor.source_tree != current.source_tree
             )
         )
         OR (
             current.revokes_receipt_id IS NOT NULL
             AND (
                 revoked.receipt_id IS NULL
                 OR revoked.candidate_id != current.candidate_id
                 OR revoked.source_commit != current.source_commit
                 OR revoked.source_tree != current.source_tree
             )
         )",
    )
    .fetch_one(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if invalid_link_count != 0 {
        return Err(EvidenceError::Corrupt(
            "qualification evidence contains a missing or cross-candidate stored link".to_string(),
        ));
    }

    let decisions = sqlx::query(
        "SELECT decision_id, receipt_id, candidate_id, role, principal_id,
                signing_identity_digest, evidence_set_digest, decision,
                conditions_json, expires_unix_ms, payload_json, payload_sha256
         FROM independent_decision_receipts ORDER BY decision_id",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in decisions {
        verify_independent_decision_row(pool, &row).await?;
    }

    let revocations = sqlx::query(
        "SELECT revocation_id, root_id, key_id, observed_unix_ms, reason_code,
                authority_principal, authority_key_id, authority_role,
                authority_verifying_key, payload_json, payload_sha256, signature
         FROM qualification_issuer_key_revocations ORDER BY revocation_id",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    for row in revocations {
        verify_revocation_row(&row)?;
    }
    Ok(())
}

fn verify_qualification_row(row: &sqlx::sqlite::SqliteRow) -> Result<(), EvidenceError> {
    let envelope_json: String = row.try_get("envelope_json").map_err(classify_sqlx_error)?;
    let envelope: QualificationEvidenceEnvelopeV1 =
        serde_json::from_str(&envelope_json).map_err(|error| {
            EvidenceError::Corrupt(format!(
                "qualification evidence envelope failed to decode: {error}"
            ))
        })?;
    envelope.validate().map_err(|error| {
        EvidenceError::Corrupt(format!(
            "qualification evidence envelope is invalid: {error}"
        ))
    })?;
    let canonical = canonical_json(&envelope)?;
    let canonical_json_text = String::from_utf8(canonical.clone())
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    let envelope_sha256 = Sha256Digest::for_bytes(&canonical);
    if canonical_json_text != envelope_json
        || row
            .try_get::<String, _>("receipt_id")
            .map_err(classify_sqlx_error)?
            != envelope.receipt_id
        || row
            .try_get::<String, _>("candidate_id")
            .map_err(classify_sqlx_error)?
            != envelope.candidate.candidate_id
        || row
            .try_get::<String, _>("source_commit")
            .map_err(classify_sqlx_error)?
            != envelope.candidate.source_commit
        || row
            .try_get::<String, _>("source_tree")
            .map_err(classify_sqlx_error)?
            != envelope.candidate.source_tree
        || row
            .try_get::<String, _>("claim_class")
            .map_err(classify_sqlx_error)?
            != envelope.claim_class.as_str()
        || row
            .try_get::<String, _>("issuer_role")
            .map_err(classify_sqlx_error)?
            != envelope.issuer_role.as_str()
        || row
            .try_get::<String, _>("issuer_principal")
            .map_err(classify_sqlx_error)?
            != envelope.issuer_principal
        || row
            .try_get::<String, _>("issuer_key_id")
            .map_err(classify_sqlx_error)?
            != envelope.issuer_key_id
        || row
            .try_get::<String, _>("payload_sha256")
            .map_err(classify_sqlx_error)?
            != envelope.payload_sha256.as_str()
        || row
            .try_get::<Option<String>, _>("predecessor_receipt_id")
            .map_err(classify_sqlx_error)?
            != envelope.predecessor_receipt_id
        || from_i64(
            row.try_get("observed_unix_ms")
                .map_err(classify_sqlx_error)?,
            "qualification evidence observation",
        )? != envelope.observed_unix_ms
        || from_i64(
            row.try_get("expires_unix_ms")
                .map_err(classify_sqlx_error)?,
            "qualification evidence expiry",
        )? != envelope.expires_unix_ms
        || row
            .try_get::<Option<String>, _>("revokes_receipt_id")
            .map_err(classify_sqlx_error)?
            != envelope.revokes_receipt_id
        || row
            .try_get::<String, _>("envelope_sha256")
            .map_err(classify_sqlx_error)?
            != envelope_sha256.as_str()
    {
        return Err(EvidenceError::Corrupt(
            "qualification evidence row projection does not match canonical envelope".to_string(),
        ));
    }

    let certificate_json: String = row
        .try_get("issuer_certificate_json")
        .map_err(classify_sqlx_error)?;
    let certificate: EvidenceIssuerCertificateV1 = serde_json::from_str(&certificate_json)
        .map_err(|error| {
            EvidenceError::Corrupt(format!("issuer certificate failed to decode: {error}"))
        })?;
    certificate.validate().map_err(|error| {
        EvidenceError::Corrupt(format!("issuer certificate is invalid: {error}"))
    })?;
    let certificate_canonical = canonical_json(&certificate)?;
    let certificate_text = String::from_utf8(certificate_canonical.clone())
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    let certificate_sha256 = Sha256Digest::for_bytes(&certificate_canonical);
    if certificate_text != certificate_json
        || certificate.root_id
            != row
                .try_get::<String, _>("issuer_root_id")
                .map_err(classify_sqlx_error)?
        || certificate.principal_id != envelope.issuer_principal
        || certificate.key_id != envelope.issuer_key_id
        || certificate.role != envelope.issuer_role
        || certificate.expires_unix_ms < envelope.expires_unix_ms
        || certificate_sha256.as_str()
            != row
                .try_get::<String, _>("issuer_certificate_sha256")
                .map_err(classify_sqlx_error)?
        || certificate.verifying_key.as_slice()
            != row
                .try_get::<Vec<u8>, _>("issuer_verifying_key")
                .map_err(classify_sqlx_error)?
                .as_slice()
        || row
            .try_get::<Vec<u8>, _>("issuer_certificate_signature")
            .map_err(classify_sqlx_error)?
            .len()
            != 64
    {
        return Err(EvidenceError::Corrupt(
            "qualification evidence issuer certificate projection is invalid".to_string(),
        ));
    }
    let key = VerifyingKey::from_bytes(&certificate.verifying_key).map_err(|_| {
        EvidenceError::Corrupt("qualification evidence issuer key is invalid".to_string())
    })?;
    if key.is_weak() {
        return Err(EvidenceError::Corrupt(
            "qualification evidence issuer key is weak".to_string(),
        ));
    }
    let signature_bytes: Vec<u8> = row.try_get("signature").map_err(classify_sqlx_error)?;
    let signature = Signature::from_slice(&signature_bytes).map_err(|_| {
        EvidenceError::Corrupt("qualification evidence signature is malformed".to_string())
    })?;
    key.verify_strict(&envelope.signing_bytes()?, &signature)
        .map_err(|_| {
            EvidenceError::Corrupt("qualification evidence signature is invalid".to_string())
        })?;
    Ok(())
}

async fn verify_independent_decision_row(
    pool: &SqlitePool,
    row: &sqlx::sqlite::SqliteRow,
) -> Result<(), EvidenceError> {
    let payload_json: String = row.try_get("payload_json").map_err(classify_sqlx_error)?;
    let decision: IndependentDecisionReceiptV1 =
        serde_json::from_str(&payload_json).map_err(|error| {
            EvidenceError::Corrupt(format!("independent decision failed to decode: {error}"))
        })?;
    decision.validate().map_err(|error| {
        EvidenceError::Corrupt(format!("independent decision is invalid: {error}"))
    })?;
    let canonical = decision
        .canonical_bytes()
        .map_err(EvidenceError::Serialization)?;
    let canonical_text = String::from_utf8(canonical.clone())
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(&canonical);
    let receipt_id: String = row.try_get("receipt_id").map_err(classify_sqlx_error)?;
    let conditions_json = serde_json::to_string(&decision.conditions)
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    if canonical_text != payload_json
        || conditions_json
            != row
                .try_get::<String, _>("conditions_json")
                .map_err(classify_sqlx_error)?
        || decision.decision_id
            != row
                .try_get::<String, _>("decision_id")
                .map_err(classify_sqlx_error)?
        || decision.candidate_id
            != row
                .try_get::<String, _>("candidate_id")
                .map_err(classify_sqlx_error)?
        || decision.role
            != row
                .try_get::<String, _>("role")
                .map_err(classify_sqlx_error)?
        || decision.principal_id
            != row
                .try_get::<String, _>("principal_id")
                .map_err(classify_sqlx_error)?
        || decision.signing_identity_digest.as_str()
            != row
                .try_get::<String, _>("signing_identity_digest")
                .map_err(classify_sqlx_error)?
        || decision.evidence_set_digest.as_str()
            != row
                .try_get::<String, _>("evidence_set_digest")
                .map_err(classify_sqlx_error)?
        || decision.decision
            != row
                .try_get::<String, _>("decision")
                .map_err(classify_sqlx_error)?
        || to_i64(decision.expires_unix_ms, "independent decision expiry")?
            != row
                .try_get::<i64, _>("expires_unix_ms")
                .map_err(classify_sqlx_error)?
        || digest.as_str()
            != row
                .try_get::<String, _>("payload_sha256")
                .map_err(classify_sqlx_error)?
    {
        return Err(EvidenceError::Corrupt(
            "independent decision row projection is invalid".to_string(),
        ));
    }
    let envelope_json: String =
        sqlx::query_scalar("SELECT envelope_json FROM qualification_evidence WHERE receipt_id = ?")
            .bind(&receipt_id)
            .fetch_one(pool)
            .await
            .map_err(classify_sqlx_error)?;
    let envelope: QualificationEvidenceEnvelopeV1 =
        serde_json::from_str(&envelope_json).map_err(|error| {
            EvidenceError::Corrupt(format!(
                "independent decision evidence envelope failed to decode: {error}"
            ))
        })?;
    if envelope.claim_class != EvidenceClaimClassV1::IndependentReview
        || envelope.candidate.candidate_id != decision.candidate_id
        || envelope.issuer_role.as_str() != decision.role
        || envelope.issuer_principal != decision.principal_id
        || envelope.payload_sha256 != digest
    {
        return Err(EvidenceError::Corrupt(
            "independent decision is not bound to its qualification evidence receipt".to_string(),
        ));
    }
    Ok(())
}

fn verify_revocation_row(row: &sqlx::sqlite::SqliteRow) -> Result<(), EvidenceError> {
    let payload_json: String = row.try_get("payload_json").map_err(classify_sqlx_error)?;
    let revocation: EvidenceIssuerKeyRevocationV1 =
        serde_json::from_str(&payload_json).map_err(|error| {
            EvidenceError::Corrupt(format!("issuer key revocation failed to decode: {error}"))
        })?;
    revocation.validate().map_err(|error| {
        EvidenceError::Corrupt(format!("issuer key revocation is invalid: {error}"))
    })?;
    let canonical = canonical_json(&revocation)?;
    let canonical_text = String::from_utf8(canonical.clone())
        .map_err(|error| EvidenceError::Corrupt(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(&canonical);
    if canonical_text != payload_json
        || revocation.revocation_id
            != row
                .try_get::<String, _>("revocation_id")
                .map_err(classify_sqlx_error)?
        || revocation.root_id
            != row
                .try_get::<String, _>("root_id")
                .map_err(classify_sqlx_error)?
        || revocation.key_id
            != row
                .try_get::<String, _>("key_id")
                .map_err(classify_sqlx_error)?
        || to_i64(
            revocation.observed_unix_ms,
            "issuer key revocation observation",
        )? != row
            .try_get::<i64, _>("observed_unix_ms")
            .map_err(classify_sqlx_error)?
        || revocation.reason_code
            != row
                .try_get::<String, _>("reason_code")
                .map_err(classify_sqlx_error)?
        || row
            .try_get::<String, _>("authority_role")
            .map_err(classify_sqlx_error)?
            != EvidenceIssuerRoleV1::SecurityReviewer.as_str()
        || digest.as_str()
            != row
                .try_get::<String, _>("payload_sha256")
                .map_err(classify_sqlx_error)?
    {
        return Err(EvidenceError::Corrupt(
            "issuer key revocation row projection is invalid".to_string(),
        ));
    }
    let key_bytes: Vec<u8> = row
        .try_get("authority_verifying_key")
        .map_err(classify_sqlx_error)?;
    let key_array: [u8; 32] = key_bytes.try_into().map_err(|_| {
        EvidenceError::Corrupt("issuer key revocation authority key has invalid length".to_string())
    })?;
    let key = VerifyingKey::from_bytes(&key_array).map_err(|_| {
        EvidenceError::Corrupt("issuer key revocation authority key is invalid".to_string())
    })?;
    let signature_bytes: Vec<u8> = row.try_get("signature").map_err(classify_sqlx_error)?;
    let signature = Signature::from_slice(&signature_bytes).map_err(|_| {
        EvidenceError::Corrupt("issuer key revocation signature is malformed".to_string())
    })?;
    key.verify_strict(&revocation.signing_bytes()?, &signature)
        .map_err(|_| {
            EvidenceError::Corrupt("issuer key revocation signature is invalid".to_string())
        })
}

fn validate_id(value: &str, label: &str) -> Result<(), EvidenceError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._-:/".contains(&byte))
    {
        return invalid(&format!("{label} is not a bounded identifier"));
    }
    Ok(())
}

fn validate_git_oid(value: &str, label: &str) -> Result<(), EvidenceError> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return invalid(&format!("{label} is not a canonical Git object id"));
    }
    Ok(())
}

fn to_i64(value: u64, label: &str) -> Result<i64, EvidenceError> {
    i64::try_from(value)
        .map_err(|_| EvidenceError::InvalidRecord(format!("{label} does not fit SQLite INTEGER")))
}

fn from_i64(value: i64, label: &str) -> Result<u64, EvidenceError> {
    u64::try_from(value).map_err(|_| EvidenceError::Corrupt(format!("{label} is negative")))
}

fn invalid<T>(message: &str) -> Result<T, EvidenceError> {
    Err(invalid_error(message))
}

fn invalid_error(message: &str) -> EvidenceError {
    EvidenceError::InvalidRecord(message.to_string())
}
