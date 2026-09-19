use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::authbus_store::advance_replay;
use crate::canonical::canonical_json;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

pub const QUALIFICATION_EVIDENCE_SCHEMA_VERSION: u32 = 1;
pub const QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES: usize = 256 * 1024;
pub const QUALIFICATION_EVIDENCE_MAX_ASSETS: usize = 64;
pub const QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES: usize = 256;
pub const QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS: usize = 512;
const MAX_INDEPENDENT_CONDITIONS: usize = 64;
const MAX_INDEPENDENT_CONDITIONS_BYTES: usize = 32 * 1024;

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct EvidenceId(String);

impl EvidenceId {
    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        StableId::new(value.clone()).map_err(|error| error.to_string())?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for EvidenceId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        Self::parse(String::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}

impl fmt::Display for EvidenceId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceCandidateV1 {
    pub candidate_id: String,
    pub source_commit: String,
    pub source_tree: String,
}

impl EvidenceCandidateV1 {
    pub fn validate(&self) -> Result<(), String> {
        StableId::new(self.candidate_id.clone()).map_err(|error| error.to_string())?;
        validate_git_identity(&self.source_commit, "source commit")?;
        validate_git_identity(&self.source_tree, "source tree")
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClaimClassV1 {
    ExactSource,
    SyntheticMerge,
    MandatoryTests,
    Fixture,
    Hardware,
    Causal,
    Longitudinal,
    SecurityResource,
    ProviderEffect,
    IndependentDecision,
    Conformance,
    AlgorithmFault,
    Runtime,
    Outbox,
    Reconciliation,
    Unlearning,
    OperatorAcceptance,
    RegistrySnapshot,
}

impl EvidenceClaimClassV1 {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ExactSource => "exact_source",
            Self::SyntheticMerge => "synthetic_merge",
            Self::MandatoryTests => "mandatory_tests",
            Self::Fixture => "fixture",
            Self::Hardware => "hardware",
            Self::Causal => "causal",
            Self::Longitudinal => "longitudinal",
            Self::SecurityResource => "security_resource",
            Self::ProviderEffect => "provider_effect",
            Self::IndependentDecision => "independent_decision",
            Self::Conformance => "conformance",
            Self::AlgorithmFault => "algorithm_fault",
            Self::Runtime => "runtime",
            Self::Outbox => "outbox",
            Self::Reconciliation => "reconciliation",
            Self::Unlearning => "unlearning",
            Self::OperatorAcceptance => "operator_acceptance",
            Self::RegistrySnapshot => "registry_snapshot",
        }
    }

    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "exact_source" => Ok(Self::ExactSource),
            "synthetic_merge" => Ok(Self::SyntheticMerge),
            "mandatory_tests" => Ok(Self::MandatoryTests),
            "fixture" => Ok(Self::Fixture),
            "hardware" => Ok(Self::Hardware),
            "causal" => Ok(Self::Causal),
            "longitudinal" => Ok(Self::Longitudinal),
            "security_resource" => Ok(Self::SecurityResource),
            "provider_effect" => Ok(Self::ProviderEffect),
            "independent_decision" => Ok(Self::IndependentDecision),
            "conformance" => Ok(Self::Conformance),
            "algorithm_fault" => Ok(Self::AlgorithmFault),
            "runtime" => Ok(Self::Runtime),
            "outbox" => Ok(Self::Outbox),
            "reconciliation" => Ok(Self::Reconciliation),
            "unlearning" => Ok(Self::Unlearning),
            "operator_acceptance" => Ok(Self::OperatorAcceptance),
            "registry_snapshot" => Ok(Self::RegistrySnapshot),
            _ => Err("unknown qualification evidence claim class".to_string()),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceReceiptKindV1 {
    Evidence,
    Correction,
    Revocation,
}

impl EvidenceReceiptKindV1 {
    fn as_str(self) -> &'static str {
        match self {
            Self::Evidence => "evidence",
            Self::Correction => "correction",
            Self::Revocation => "revocation",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceIssuerRoleV1 {
    Generator,
    Evaluator,
    Reviewer,
    Architecture,
    Durability,
    Learning,
    Security,
    Operator,
    Documentation,
    TerminalObserver,
    ProductWriter,
    Selector,
    Loader,
}

impl EvidenceIssuerRoleV1 {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Generator => "generator",
            Self::Evaluator => "evaluator",
            Self::Reviewer => "reviewer",
            Self::Architecture => "architecture",
            Self::Durability => "durability",
            Self::Learning => "learning",
            Self::Security => "security",
            Self::Operator => "operator",
            Self::Documentation => "documentation",
            Self::TerminalObserver => "terminal_observer",
            Self::ProductWriter => "product_writer",
            Self::Selector => "selector",
            Self::Loader => "loader",
        }
    }

    pub fn parse(value: &str) -> Result<Self, String> {
        match value {
            "generator" => Ok(Self::Generator),
            "evaluator" => Ok(Self::Evaluator),
            "reviewer" => Ok(Self::Reviewer),
            "architecture" => Ok(Self::Architecture),
            "durability" => Ok(Self::Durability),
            "learning" => Ok(Self::Learning),
            "security" => Ok(Self::Security),
            "operator" => Ok(Self::Operator),
            "documentation" => Ok(Self::Documentation),
            "terminal_observer" => Ok(Self::TerminalObserver),
            "product_writer" => Ok(Self::ProductWriter),
            "selector" => Ok(Self::Selector),
            "loader" => Ok(Self::Loader),
            _ => Err("unknown qualification evidence issuer role".to_string()),
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QualificationEvidenceEnvelopeV1 {
    pub schema_version: u32,
    pub evidence_id: EvidenceId,
    pub candidate: EvidenceCandidateV1,
    pub claim_class: EvidenceClaimClassV1,
    pub receipt_kind: EvidenceReceiptKindV1,
    pub issuer_role: EvidenceIssuerRoleV1,
    pub payload: Value,
    pub predecessor_evidence_id: Option<EvidenceId>,
    pub target_evidence_id: Option<EvidenceId>,
    pub observed_unix_ms: u64,
    pub expires_unix_ms: Option<u64>,
    pub asset_digests: Vec<Sha256Digest>,
}

impl QualificationEvidenceEnvelopeV1 {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != QUALIFICATION_EVIDENCE_SCHEMA_VERSION {
            return Err("unsupported qualification evidence schema version".to_string());
        }
        self.candidate.validate()?;
        if self.asset_digests.len() > QUALIFICATION_EVIDENCE_MAX_ASSETS {
            return Err("qualification evidence references more than 64 assets".to_string());
        }
        if let Some(expires) = self.expires_unix_ms
            && expires <= self.observed_unix_ms
        {
            return Err("qualification evidence expiry must follow observation".to_string());
        }
        match self.receipt_kind {
            EvidenceReceiptKindV1::Evidence => {
                if self.predecessor_evidence_id.is_some() || self.target_evidence_id.is_some() {
                    return Err(
                        "base evidence cannot name predecessor or revocation/correction target"
                            .to_string(),
                    );
                }
            }
            EvidenceReceiptKindV1::Correction | EvidenceReceiptKindV1::Revocation => {
                if self.predecessor_evidence_id.is_none() || self.target_evidence_id.is_none() {
                    return Err(
                        "correction/revocation requires predecessor and target evidence"
                            .to_string(),
                    );
                }
                if self.predecessor_evidence_id.as_ref() == Some(&self.evidence_id)
                    || self.target_evidence_id.as_ref() == Some(&self.evidence_id)
                {
                    return Err("qualification evidence cannot reference itself".to_string());
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IndependentDecisionRoleV1 {
    Architecture,
    Durability,
    Learning,
    Security,
    Operator,
    Documentation,
}

impl IndependentDecisionRoleV1 {
    fn evidence_role(self) -> EvidenceIssuerRoleV1 {
        match self {
            Self::Architecture => EvidenceIssuerRoleV1::Architecture,
            Self::Durability => EvidenceIssuerRoleV1::Durability,
            Self::Learning => EvidenceIssuerRoleV1::Learning,
            Self::Security => EvidenceIssuerRoleV1::Security,
            Self::Operator => EvidenceIssuerRoleV1::Operator,
            Self::Documentation => EvidenceIssuerRoleV1::Documentation,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum IndependentDecisionV1 {
    Accept,
    Reject,
    Abstain,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IndependentDecisionReceiptV1 {
    pub decision_id: String,
    pub candidate_id: String,
    pub role: IndependentDecisionRoleV1,
    pub principal_id: String,
    pub signing_identity_digest: Sha256Digest,
    pub evidence_set_digest: Sha256Digest,
    pub decision: IndependentDecisionV1,
    pub conditions: Vec<String>,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VerifyChainRequestV1 {
    pub candidate: EvidenceCandidateV1,
    pub claim_class: EvidenceClaimClassV1,
    pub required_roles: Vec<EvidenceIssuerRoleV1>,
    pub now_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceReferenceV1 {
    pub evidence_id: EvidenceId,
    pub claim_class: EvidenceClaimClassV1,
    pub receipt_kind: EvidenceReceiptKindV1,
    pub issuer_role: EvidenceIssuerRoleV1,
    pub issuer_principal_id: String,
    pub payload_sha256: Sha256Digest,
    pub envelope_sha256: Sha256Digest,
    pub predecessor_evidence_id: Option<EvidenceId>,
    pub target_evidence_id: Option<EvidenceId>,
    pub observed_unix_ms: u64,
    pub expires_unix_ms: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum EvidenceDispositionV1 {
    Supported { evidence: Vec<EvidenceReferenceV1> },
    Missing,
    Expired { evidence: Vec<EvidenceReferenceV1> },
    Conflicting {
        evidence: Vec<EvidenceReferenceV1>,
        reason: String,
    },
}

#[derive(Clone, Debug)]
struct StoredQualificationEvidence {
    seq: i64,
    envelope: QualificationEvidenceEnvelopeV1,
    issuer_principal_id: String,
    issuer_key_epoch: u64,
    issuer_signing_identity_sha256: Sha256Digest,
    auth_message_id: String,
    auth_sequence: u64,
    auth_expires_at_ms: u64,
    payload_sha256: Sha256Digest,
    envelope_sha256: Sha256Digest,
}

impl StoredQualificationEvidence {
    fn reference(&self) -> EvidenceReferenceV1 {
        EvidenceReferenceV1 {
            evidence_id: self.envelope.evidence_id.clone(),
            claim_class: self.envelope.claim_class,
            receipt_kind: self.envelope.receipt_kind,
            issuer_role: self.envelope.issuer_role,
            issuer_principal_id: self.issuer_principal_id.clone(),
            payload_sha256: self.payload_sha256.clone(),
            envelope_sha256: self.envelope_sha256.clone(),
            predecessor_evidence_id: self.envelope.predecessor_evidence_id.clone(),
            target_evidence_id: self.envelope.target_evidence_id.clone(),
            observed_unix_ms: self.envelope.observed_unix_ms,
            expires_unix_ms: self.envelope.expires_unix_ms,
        }
    }
}

#[derive(Clone, Copy)]
pub struct QualificationEvidenceStore<'a> {
    store: &'a HeptaEvidenceStore,
}

impl HeptaEvidenceStore {
    pub fn qualification(&self) -> QualificationEvidenceStore<'_> {
        QualificationEvidenceStore { store: self }
    }
}

impl QualificationEvidenceStore<'_> {
    /// Append one exact-candidate qualification receipt from an AuthBus-authenticated
    /// issuer. Signature verification, durable replay fencing and the evidence insert
    /// share one BEGIN IMMEDIATE transaction. Exact retries of the same signed receipt
    /// are idempotent; reused evidence identities with changed semantics conflict.
    pub async fn append_receipt(
        &self,
        issuer: &IssuerRegistration,
        message: &SignedMessage,
        envelope: &QualificationEvidenceEnvelopeV1,
    ) -> Result<EvidenceId, EvidenceError> {
        envelope.validate().map_err(EvidenceError::InvalidRecord)?;
        let envelope_bytes = qualification_envelope_bytes(envelope)?;
        let payload_bytes = canonical_json(&envelope.payload)?;
        let payload_sha256 = Sha256Digest::for_bytes(&payload_bytes);
        let envelope_sha256 = Sha256Digest::for_bytes(&envelope_bytes);
        let signing_identity_sha256 = Sha256Digest::for_bytes(issuer.verifying_key.as_bytes());
        let expected_scope = qualification_append_scope_digest();
        let expected_subject = qualification_subject(&envelope.candidate, envelope.issuer_role)?;

        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let now = u64::try_from(now_millis()?)
            .map_err(|_| EvidenceError::Unavailable("clock predates Unix epoch".into()))?;
        let authenticated = message
            .authenticate(
                issuer,
                expected_scope,
                Digest32::of_bytes(&envelope_bytes),
                now,
            )
            .map_err(|error| {
                EvidenceError::InvalidRecord(format!(
                    "qualification issuer authentication failed: {error}"
                ))
            })?;
        if authenticated.claims().subject_id != expected_subject {
            return Err(EvidenceError::InvalidRecord(
                "qualification issuer subject does not bind candidate and role".to_string(),
            ));
        }
        if envelope.observed_unix_ms > now {
            return Err(EvidenceError::InvalidRecord(
                "qualification evidence observation is in the future".to_string(),
            ));
        }
        if envelope.expires_unix_ms.is_some_and(|expires| expires <= now) {
            return Err(EvidenceError::InvalidRecord(
                "qualification evidence is already expired".to_string(),
            ));
        }
        validate_independent_decision(
            envelope,
            issuer,
            message,
            &signing_identity_sha256,
            now,
        )?;

        if let Some(existing) =
            load_evidence_by_id(&mut transaction, envelope.evidence_id.as_str()).await?
        {
            if existing.envelope == *envelope
                && existing.issuer_principal_id == issuer.issuer_id.as_str()
                && existing.issuer_key_epoch == issuer.key_epoch.get()
                && existing.issuer_signing_identity_sha256 == signing_identity_sha256
                && existing.auth_message_id == message.claims.message_id.as_str()
                && existing.auth_sequence == message.claims.sequence
                && existing.auth_expires_at_ms == message.claims.expires_at_ms
                && existing.payload_sha256 == payload_sha256
                && existing.envelope_sha256 == envelope_sha256
            {
                transaction.commit().await.map_err(classify_sqlx_error)?;
                return Ok(envelope.evidence_id.clone());
            }
            return Err(EvidenceError::IdempotencyConflict {
                record_id: envelope.evidence_id.to_string(),
            });
        }

        validate_lineage_references(&mut transaction, envelope).await?;
        advance_replay(&mut transaction, &authenticated)
            .await
            .map_err(|error| {
                EvidenceError::InvalidRecord(format!(
                    "qualification issuer replay admission failed: {error}"
                ))
            })?;

        let envelope_json = String::from_utf8(envelope_bytes)
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        sqlx::query(
            "INSERT INTO qualification_evidence (
                evidence_id, schema_version, candidate_id, source_commit, source_tree,
                claim_class, receipt_kind, issuer_role, issuer_principal_id,
                issuer_key_epoch, issuer_signing_identity_sha256, auth_message_id,
                auth_sequence, auth_expires_at_ms, payload_sha256, envelope_sha256,
                predecessor_evidence_id, target_evidence_id, observed_at_ms, expires_at_ms,
                asset_count, envelope_json, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(envelope.evidence_id.as_str())
        .bind(i64::from(envelope.schema_version))
        .bind(&envelope.candidate.candidate_id)
        .bind(&envelope.candidate.source_commit)
        .bind(&envelope.candidate.source_tree)
        .bind(envelope.claim_class.as_str())
        .bind(envelope.receipt_kind.as_str())
        .bind(envelope.issuer_role.as_str())
        .bind(issuer.issuer_id.as_str())
        .bind(issuer.key_epoch.get().to_be_bytes().to_vec())
        .bind(signing_identity_sha256.as_str())
        .bind(message.claims.message_id.as_str())
        .bind(message.claims.sequence.to_be_bytes().to_vec())
        .bind(message.claims.expires_at_ms.to_be_bytes().to_vec())
        .bind(payload_sha256.as_str())
        .bind(envelope_sha256.as_str())
        .bind(
            envelope
                .predecessor_evidence_id
                .as_ref()
                .map(EvidenceId::as_str),
        )
        .bind(
            envelope
                .target_evidence_id
                .as_ref()
                .map(EvidenceId::as_str),
        )
        .bind(envelope.observed_unix_ms.to_be_bytes().to_vec())
        .bind(
            envelope
                .expires_unix_ms
                .map(u64::to_be_bytes)
                .map(|bytes| bytes.to_vec()),
        )
        .bind(
            i64::try_from(envelope.asset_digests.len())
                .map_err(|_| EvidenceError::InvalidRecord("asset count overflow".into()))?,
        )
        .bind(envelope_json)
        .bind(now_millis()?)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(envelope.evidence_id.clone())
    }

    pub async fn query_claim(
        &self,
        candidate: &EvidenceCandidateV1,
        claim_class: EvidenceClaimClassV1,
    ) -> Result<Vec<EvidenceReferenceV1>, EvidenceError> {
        candidate.validate().map_err(EvidenceError::InvalidRecord)?;
        let rows = load_claim_rows(&self.store.pool, candidate, claim_class).await?;
        Ok(rows.into_iter().map(|row| row.reference()).collect())
    }

    pub async fn verify_chain(
        &self,
        request: &VerifyChainRequestV1,
    ) -> Result<EvidenceDispositionV1, EvidenceError> {
        request
            .candidate
            .validate()
            .map_err(EvidenceError::InvalidRecord)?;
        if request.required_roles.len() > 32 {
            return Err(EvidenceError::InvalidRecord(
                "qualification verification requires at most 32 roles".to_string(),
            ));
        }
        let unique_roles = request.required_roles.iter().copied().collect::<BTreeSet<_>>();
        if unique_roles.len() != request.required_roles.len() {
            return Err(EvidenceError::InvalidRecord(
                "qualification verification contains duplicate required roles".to_string(),
            ));
        }

        let rows = load_claim_rows(&self.store.pool, &request.candidate, request.claim_class).await?;
        if rows.is_empty() {
            return Ok(EvidenceDispositionV1::Missing);
        }
        verify_rows_integrity(&rows)?;

        let mut corrected = BTreeSet::new();
        let mut revoked = BTreeSet::new();
        for row in &rows {
            match row.envelope.receipt_kind {
                EvidenceReceiptKindV1::Correction => {
                    if let Some(target) = row.envelope.target_evidence_id.as_ref() {
                        corrected.insert(target.clone());
                    }
                }
                EvidenceReceiptKindV1::Revocation => {
                    if let Some(target) = row.envelope.target_evidence_id.as_ref() {
                        revoked.insert(target.clone());
                    }
                }
                EvidenceReceiptKindV1::Evidence => {}
            }
        }

        let mut active = Vec::new();
        let mut expired = Vec::new();
        for row in rows {
            if row.envelope.receipt_kind == EvidenceReceiptKindV1::Revocation
                || corrected.contains(&row.envelope.evidence_id)
                || revoked.contains(&row.envelope.evidence_id)
            {
                continue;
            }
            if row
                .envelope
                .expires_unix_ms
                .is_some_and(|expires| expires <= request.now_unix_ms)
            {
                expired.push(row.reference());
                continue;
            }
            if row.envelope.claim_class == EvidenceClaimClassV1::IndependentDecision {
                let receipt: IndependentDecisionReceiptV1 =
                    serde_json::from_value(row.envelope.payload.clone()).map_err(|error| {
                        EvidenceError::Corrupt(format!(
                            "independent decision payload is invalid: {error}"
                        ))
                    })?;
                match receipt.decision {
                    IndependentDecisionV1::Reject => {
                        return Ok(EvidenceDispositionV1::Conflicting {
                            evidence: vec![row.reference()],
                            reason: "independent decision rejected the claim".to_string(),
                        });
                    }
                    IndependentDecisionV1::Abstain => continue,
                    IndependentDecisionV1::Accept => {}
                }
            }
            active.push(row);
        }

        if active.is_empty() {
            return if expired.is_empty() {
                Ok(EvidenceDispositionV1::Missing)
            } else {
                Ok(EvidenceDispositionV1::Expired { evidence: expired })
            };
        }

        for role in &request.required_roles {
            if !active.iter().any(|row| row.envelope.issuer_role == *role) {
                return Ok(EvidenceDispositionV1::Missing);
            }
        }
        if !roles_have_distinct_principals(&request.required_roles, &active) {
            return Ok(EvidenceDispositionV1::Conflicting {
                evidence: active.iter().map(StoredQualificationEvidence::reference).collect(),
                reason: "required independent roles cannot be assigned to distinct authenticated principals"
                    .to_string(),
            });
        }

        Ok(EvidenceDispositionV1::Supported {
            evidence: active
                .iter()
                .map(StoredQualificationEvidence::reference)
                .collect(),
        })
    }
}

pub fn qualification_envelope_bytes(
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<Vec<u8>, EvidenceError> {
    envelope.validate().map_err(EvidenceError::InvalidRecord)?;
    let bytes = canonical_json(envelope)?;
    if bytes.len() > QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES {
        return Err(EvidenceError::InvalidRecord(
            "qualification evidence exceeds 256 KiB".to_string(),
        ));
    }
    Ok(bytes)
}

pub fn qualification_append_scope_digest() -> Digest32 {
    Digest32::of_bytes(b"hepta:kernel.evidence:qualification-append:v1")
}

pub fn qualification_subject(
    candidate: &EvidenceCandidateV1,
    role: EvidenceIssuerRoleV1,
) -> Result<StableId, EvidenceError> {
    candidate.validate().map_err(EvidenceError::InvalidRecord)?;
    let mut bytes = b"hepta:kernel.evidence:qualification-subject:v1\0".to_vec();
    push_part(&mut bytes, candidate.candidate_id.as_bytes());
    push_part(&mut bytes, candidate.source_commit.as_bytes());
    push_part(&mut bytes, candidate.source_tree.as_bytes());
    push_part(&mut bytes, role.as_str().as_bytes());
    let digest = Sha256Digest::for_bytes(&bytes);
    StableId::new(format!("kernel.evidence:{}", digest.as_str()))
        .map_err(|error| EvidenceError::InvalidRecord(error.to_string()))
}

pub fn evidence_set_digest(
    evidence: &[EvidenceReferenceV1],
) -> Result<Sha256Digest, EvidenceError> {
    let mut ordered = evidence.to_vec();
    ordered.sort_by(|left, right| {
        left.evidence_id
            .cmp(&right.evidence_id)
            .then(left.envelope_sha256.as_str().cmp(right.envelope_sha256.as_str()))
    });
    Ok(Sha256Digest::for_bytes(&canonical_json(&ordered)?))
}

pub(crate) async fn verify_qualification_evidence_rows(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, evidence_id, schema_version, candidate_id, source_commit, source_tree,
                claim_class, receipt_kind, issuer_role, issuer_principal_id, issuer_key_epoch,
                issuer_signing_identity_sha256, auth_message_id, auth_sequence,
                auth_expires_at_ms, payload_sha256, envelope_sha256,
                predecessor_evidence_id, target_evidence_id, observed_at_ms, expires_at_ms,
                asset_count, envelope_json
         FROM qualification_evidence ORDER BY seq ASC",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() > 1_000_000 {
        return Err(EvidenceError::Corrupt(
            "qualification evidence exceeds startup integrity scan bound".to_string(),
        ));
    }
    let mut decoded = Vec::with_capacity(rows.len());
    for row in rows {
        decoded.push(decode_row(&row)?);
    }
    verify_rows_integrity(&decoded)
}

async fn validate_lineage_references(
    transaction: &mut Transaction<'_, Sqlite>,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<(), EvidenceError> {
    for (label, reference) in [
        ("predecessor", envelope.predecessor_evidence_id.as_ref()),
        ("target", envelope.target_evidence_id.as_ref()),
    ] {
        let Some(reference) = reference else {
            continue;
        };
        let row = load_evidence_by_id(transaction, reference.as_str())
            .await?
            .ok_or_else(|| {
                EvidenceError::InvalidRecord(format!(
                    "qualification {label} evidence does not exist"
                ))
            })?;
        if row.envelope.candidate != envelope.candidate
            || row.envelope.claim_class != envelope.claim_class
        {
            return Err(EvidenceError::InvalidRecord(format!(
                "qualification {label} evidence belongs to another candidate or claim class"
            )));
        }
    }
    Ok(())
}

fn validate_independent_decision(
    envelope: &QualificationEvidenceEnvelopeV1,
    issuer: &IssuerRegistration,
    message: &SignedMessage,
    signing_identity_sha256: &Sha256Digest,
    now: u64,
) -> Result<(), EvidenceError> {
    if envelope.claim_class != EvidenceClaimClassV1::IndependentDecision {
        return Ok(());
    }
    if envelope.receipt_kind == EvidenceReceiptKindV1::Revocation {
        return Ok(());
    }
    let receipt: IndependentDecisionReceiptV1 =
        serde_json::from_value(envelope.payload.clone()).map_err(|error| {
            EvidenceError::InvalidRecord(format!(
                "independent decision payload does not match IndependentDecisionReceiptV1: {error}"
            ))
        })?;
    if receipt.decision_id != envelope.evidence_id.as_str()
        || receipt.candidate_id != envelope.candidate.candidate_id
        || receipt.role.evidence_role() != envelope.issuer_role
        || receipt.principal_id != issuer.issuer_id.as_str()
        || receipt.signing_identity_digest != *signing_identity_sha256
        || envelope.expires_unix_ms != Some(receipt.expires_unix_ms)
        || receipt.expires_unix_ms <= now
        || receipt.expires_unix_ms > message.claims.expires_at_ms
    {
        return Err(EvidenceError::InvalidRecord(
            "independent decision identity, role, candidate or expiry is not bound to authenticated admission"
                .to_string(),
        ));
    }
    if receipt.conditions.len() > MAX_INDEPENDENT_CONDITIONS
        || receipt
            .conditions
            .iter()
            .any(|condition| condition.is_empty() || condition.len() > 4096)
        || receipt.conditions.iter().map(String::len).sum::<usize>()
            > MAX_INDEPENDENT_CONDITIONS_BYTES
    {
        return Err(EvidenceError::InvalidRecord(
            "independent decision conditions exceed registered bounds".to_string(),
        ));
    }
    Ok(())
}

async fn load_claim_rows(
    pool: &SqlitePool,
    candidate: &EvidenceCandidateV1,
    claim_class: EvidenceClaimClassV1,
) -> Result<Vec<StoredQualificationEvidence>, EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, evidence_id, schema_version, candidate_id, source_commit, source_tree,
                claim_class, receipt_kind, issuer_role, issuer_principal_id, issuer_key_epoch,
                issuer_signing_identity_sha256, auth_message_id, auth_sequence,
                auth_expires_at_ms, payload_sha256, envelope_sha256,
                predecessor_evidence_id, target_evidence_id, observed_at_ms, expires_at_ms,
                asset_count, envelope_json
         FROM qualification_evidence
         WHERE candidate_id = ? AND source_commit = ? AND source_tree = ? AND claim_class = ?
         ORDER BY seq ASC LIMIT ?",
    )
    .bind(&candidate.candidate_id)
    .bind(&candidate.source_commit)
    .bind(&candidate.source_tree)
    .bind(claim_class.as_str())
    .bind(
        i64::try_from(QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS + 1)
            .map_err(|_| EvidenceError::InvalidRecord("query bound overflow".into()))?,
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    if rows.len() > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
        return Err(EvidenceError::InvalidRecord(
            "qualification claim query exceeds 512 references".to_string(),
        ));
    }
    rows.iter().map(decode_row).collect()
}

async fn load_evidence_by_id(
    transaction: &mut Transaction<'_, Sqlite>,
    evidence_id: &str,
) -> Result<Option<StoredQualificationEvidence>, EvidenceError> {
    let row = sqlx::query(
        "SELECT seq, evidence_id, schema_version, candidate_id, source_commit, source_tree,
                claim_class, receipt_kind, issuer_role, issuer_principal_id, issuer_key_epoch,
                issuer_signing_identity_sha256, auth_message_id, auth_sequence,
                auth_expires_at_ms, payload_sha256, envelope_sha256,
                predecessor_evidence_id, target_evidence_id, observed_at_ms, expires_at_ms,
                asset_count, envelope_json
         FROM qualification_evidence WHERE evidence_id = ?",
    )
    .bind(evidence_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(classify_sqlx_error)?;
    row.as_ref().map(decode_row).transpose()
}

fn decode_row(row: &SqliteRow) -> Result<StoredQualificationEvidence, EvidenceError> {
    let envelope_json: String = row.try_get("envelope_json").map_err(classify_sqlx_error)?;
    let envelope: QualificationEvidenceEnvelopeV1 =
        serde_json::from_str(&envelope_json).map_err(|error| {
            EvidenceError::Corrupt(format!(
                "qualification evidence envelope cannot be decoded: {error}"
            ))
        })?;
    envelope
        .validate()
        .map_err(|error| EvidenceError::Corrupt(format!("qualification envelope invalid: {error}")))?;
    let canonical = canonical_json(&envelope)?;
    if String::from_utf8(canonical.clone())
        .map_err(|error| EvidenceError::Serialization(error.to_string()))?
        != envelope_json
    {
        return Err(EvidenceError::Corrupt(
            "qualification evidence envelope is not canonical JSON".to_string(),
        ));
    }
    let payload_sha256 = Sha256Digest::for_bytes(&canonical_json(&envelope.payload)?);
    let stored_payload: String = row.try_get("payload_sha256").map_err(classify_sqlx_error)?;
    if payload_sha256.as_str() != stored_payload {
        return Err(EvidenceError::Corrupt(
            "qualification evidence payload digest differs from canonical payload".to_string(),
        ));
    }
    let envelope_sha256 = Sha256Digest::for_bytes(&canonical);
    let stored_envelope: String = row.try_get("envelope_sha256").map_err(classify_sqlx_error)?;
    if envelope_sha256.as_str() != stored_envelope {
        return Err(EvidenceError::Corrupt(
            "qualification evidence envelope digest differs from canonical envelope".to_string(),
        ));
    }
    let row_evidence_id: String = row.try_get("evidence_id").map_err(classify_sqlx_error)?;
    if row_evidence_id != envelope.evidence_id.as_str() {
        return Err(EvidenceError::Corrupt(
            "qualification evidence row identity differs from envelope".to_string(),
        ));
    }
    let row_schema: i64 = row.try_get("schema_version").map_err(classify_sqlx_error)?;
    let row_candidate: String = row.try_get("candidate_id").map_err(classify_sqlx_error)?;
    let row_commit: String = row.try_get("source_commit").map_err(classify_sqlx_error)?;
    let row_tree: String = row.try_get("source_tree").map_err(classify_sqlx_error)?;
    let row_claim: String = row.try_get("claim_class").map_err(classify_sqlx_error)?;
    let row_kind: String = row.try_get("receipt_kind").map_err(classify_sqlx_error)?;
    let row_role: String = row.try_get("issuer_role").map_err(classify_sqlx_error)?;
    let row_predecessor: Option<String> =
        row.try_get("predecessor_evidence_id").map_err(classify_sqlx_error)?;
    let row_target: Option<String> =
        row.try_get("target_evidence_id").map_err(classify_sqlx_error)?;
    let row_observed = read_u64_blob(row, "observed_at_ms")?;
    let row_expires = read_optional_u64_blob(row, "expires_at_ms")?;
    let row_asset_count: i64 = row.try_get("asset_count").map_err(classify_sqlx_error)?;
    if row_schema != i64::from(envelope.schema_version)
        || row_candidate != envelope.candidate.candidate_id
        || row_commit != envelope.candidate.source_commit
        || row_tree != envelope.candidate.source_tree
        || row_claim != envelope.claim_class.as_str()
        || row_kind != envelope.receipt_kind.as_str()
        || row_role != envelope.issuer_role.as_str()
        || row_predecessor.as_deref()
            != envelope.predecessor_evidence_id.as_ref().map(EvidenceId::as_str)
        || row_target.as_deref()
            != envelope.target_evidence_id.as_ref().map(EvidenceId::as_str)
        || row_observed != envelope.observed_unix_ms
        || row_expires != envelope.expires_unix_ms
        || row_asset_count != i64::try_from(envelope.asset_digests.len()).unwrap_or(-1)
    {
        return Err(EvidenceError::Corrupt(
            "qualification evidence projection differs from canonical envelope".to_string(),
        ));
    }
    Ok(StoredQualificationEvidence {
        seq: row.try_get("seq").map_err(classify_sqlx_error)?,
        envelope,
        issuer_principal_id: row
            .try_get("issuer_principal_id")
            .map_err(classify_sqlx_error)?,
        issuer_key_epoch: read_u64_blob(row, "issuer_key_epoch")?,
        issuer_signing_identity_sha256: Sha256Digest::parse(
            row.try_get::<String, _>("issuer_signing_identity_sha256")
                .map_err(classify_sqlx_error)?,
        )
        .map_err(EvidenceError::Corrupt)?,
        auth_message_id: row.try_get("auth_message_id").map_err(classify_sqlx_error)?,
        auth_sequence: read_u64_blob(row, "auth_sequence")?,
        auth_expires_at_ms: read_u64_blob(row, "auth_expires_at_ms")?,
        payload_sha256,
        envelope_sha256,
    })
}

fn verify_rows_integrity(rows: &[StoredQualificationEvidence]) -> Result<(), EvidenceError> {
    let by_id = rows
        .iter()
        .map(|row| (row.envelope.evidence_id.clone(), row))
        .collect::<BTreeMap<_, _>>();
    for row in rows {
        for (label, reference) in [
            ("predecessor", row.envelope.predecessor_evidence_id.as_ref()),
            ("target", row.envelope.target_evidence_id.as_ref()),
        ] {
            let Some(reference) = reference else {
                continue;
            };
            let referenced = by_id.get(reference).ok_or_else(|| {
                EvidenceError::Corrupt(format!(
                    "qualification {label} reference is missing from bounded chain"
                ))
            })?;
            if referenced.seq >= row.seq
                || referenced.envelope.candidate != row.envelope.candidate
                || referenced.envelope.claim_class != row.envelope.claim_class
            {
                return Err(EvidenceError::Corrupt(format!(
                    "qualification {label} reference violates lineage"
                )));
            }
        }
        let mut cursor = row;
        let mut visited = BTreeSet::new();
        for _ in 0..=QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES {
            if !visited.insert(cursor.envelope.evidence_id.clone()) {
                return Err(EvidenceError::Corrupt(
                    "qualification evidence predecessor cycle detected".to_string(),
                ));
            }
            let Some(predecessor) = cursor.envelope.predecessor_evidence_id.as_ref() else {
                break;
            };
            cursor = by_id.get(predecessor).ok_or_else(|| {
                EvidenceError::Corrupt(
                    "qualification evidence predecessor chain is incomplete".to_string(),
                )
            })?;
        }
        if cursor.envelope.predecessor_evidence_id.is_some()
            && visited.len() > QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES
        {
            return Err(EvidenceError::Corrupt(
                "qualification evidence predecessor traversal exhausted".to_string(),
            ));
        }
    }
    Ok(())
}

fn roles_have_distinct_principals(
    required_roles: &[EvidenceIssuerRoleV1],
    rows: &[StoredQualificationEvidence],
) -> bool {
    fn assign(
        index: usize,
        roles: &[EvidenceIssuerRoleV1],
        principals: &BTreeMap<EvidenceIssuerRoleV1, BTreeSet<String>>,
        used: &mut BTreeSet<String>,
    ) -> bool {
        if index == roles.len() {
            return true;
        }
        let Some(candidates) = principals.get(&roles[index]) else {
            return false;
        };
        for principal in candidates {
            if used.insert(principal.clone()) {
                if assign(index + 1, roles, principals, used) {
                    return true;
                }
                used.remove(principal);
            }
        }
        false
    }

    let mut principals = BTreeMap::<EvidenceIssuerRoleV1, BTreeSet<String>>::new();
    for row in rows {
        principals
            .entry(row.envelope.issuer_role)
            .or_default()
            .insert(row.issuer_principal_id.clone());
    }
    assign(
        0,
        required_roles,
        &principals,
        &mut BTreeSet::<String>::new(),
    )
}

fn read_u64_blob(row: &SqliteRow, column: &str) -> Result<u64, EvidenceError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(classify_sqlx_error)?;
    let bytes: [u8; 8] = bytes
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("{column} has invalid width")))?;
    Ok(u64::from_be_bytes(bytes))
}

fn read_optional_u64_blob(
    row: &SqliteRow,
    column: &str,
) -> Result<Option<u64>, EvidenceError> {
    let bytes: Option<Vec<u8>> = row.try_get(column).map_err(classify_sqlx_error)?;
    bytes
        .map(|bytes| {
            let bytes: [u8; 8] = bytes
                .try_into()
                .map_err(|_| EvidenceError::Corrupt(format!("{column} has invalid width")))?;
            Ok(u64::from_be_bytes(bytes))
        })
        .transpose()
}

fn validate_git_identity(value: &str, label: &str) -> Result<(), String> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(format!(
            "{label} must be a 40- or 64-character lowercase hexadecimal object id"
        ));
    }
    Ok(())
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}
