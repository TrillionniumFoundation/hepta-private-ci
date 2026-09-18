use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::canonical::canonical_json;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

pub const QUALIFICATION_EVIDENCE_SCHEMA_VERSION: u32 = 1;
pub const QUALIFICATION_EVIDENCE_MAX_ENCODED_BYTES: usize = 256 * 1024;
pub const QUALIFICATION_EVIDENCE_MAX_ASSETS: usize = 64;
pub const QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES: usize = 256;
pub const QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS: usize = 512;
const MAX_IDENTIFIER_BYTES: usize = 128;
const MAX_CONDITIONS: usize = 64;
const MAX_CONDITION_BYTES: usize = 1024;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct EvidenceId(String);

impl EvidenceId {
    pub fn parse(value: impl Into<String>) -> Result<Self, EvidenceError> {
        let value = value.into();
        validate_identifier(&value, "evidence id")?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for EvidenceId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QualificationClaimClassV1 {
    AlgorithmFault,
    CandidateEvaluation,
    Conformance,
    Evaluation,
    IndependentDecision,
    LocalModelRuntime,
    LongitudinalEvaluation,
    UnlearningCompliance,
}

impl QualificationClaimClassV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::AlgorithmFault => "algorithm_fault",
            Self::CandidateEvaluation => "candidate_evaluation",
            Self::Conformance => "conformance",
            Self::Evaluation => "evaluation",
            Self::IndependentDecision => "independent_decision",
            Self::LocalModelRuntime => "local_model_runtime",
            Self::LongitudinalEvaluation => "longitudinal_evaluation",
            Self::UnlearningCompliance => "unlearning_compliance",
        }
    }

    pub const fn protocol_id(self) -> &'static str {
        match self {
            Self::AlgorithmFault => "AlgorithmFaultReceiptV1",
            Self::CandidateEvaluation => "CandidateEvaluationReceiptV1",
            Self::Conformance => "ConformanceReceiptV1",
            Self::Evaluation => "EvaluationReceiptV1",
            Self::IndependentDecision => "IndependentDecisionReceiptV1",
            Self::LocalModelRuntime => "LocalModelRuntimeReceiptV1",
            Self::LongitudinalEvaluation => "LongitudinalEvaluationReceiptV1",
            Self::UnlearningCompliance => "UnlearningComplianceReceiptV1",
        }
    }

    fn parse(value: &str) -> Result<Self, EvidenceError> {
        match value {
            "algorithm_fault" => Ok(Self::AlgorithmFault),
            "candidate_evaluation" => Ok(Self::CandidateEvaluation),
            "conformance" => Ok(Self::Conformance),
            "evaluation" => Ok(Self::Evaluation),
            "independent_decision" => Ok(Self::IndependentDecision),
            "local_model_runtime" => Ok(Self::LocalModelRuntime),
            "longitudinal_evaluation" => Ok(Self::LongitudinalEvaluation),
            "unlearning_compliance" => Ok(Self::UnlearningCompliance),
            _ => Err(EvidenceError::Corrupt(
                "qualification evidence contains an unknown claim class".into(),
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QualificationEvidenceRoleV1 {
    Generator,
    Evaluator,
    Reviewer,
    Selector,
    Loader,
    Operator,
    TerminalObserver,
}

impl QualificationEvidenceRoleV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Generator => "generator",
            Self::Evaluator => "evaluator",
            Self::Reviewer => "reviewer",
            Self::Selector => "selector",
            Self::Loader => "loader",
            Self::Operator => "operator",
            Self::TerminalObserver => "terminal_observer",
        }
    }

    fn parse(value: &str) -> Result<Self, EvidenceError> {
        match value {
            "generator" => Ok(Self::Generator),
            "evaluator" => Ok(Self::Evaluator),
            "reviewer" => Ok(Self::Reviewer),
            "selector" => Ok(Self::Selector),
            "loader" => Ok(Self::Loader),
            "operator" => Ok(Self::Operator),
            "terminal_observer" => Ok(Self::TerminalObserver),
            _ => Err(EvidenceError::Corrupt(
                "qualification evidence contains an unknown issuer role".into(),
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QualificationEvidenceDecisionV1 {
    Support,
    Conditional,
    Reject,
}

impl QualificationEvidenceDecisionV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Support => "support",
            Self::Conditional => "conditional",
            Self::Reject => "reject",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationCandidateV1 {
    pub candidate_id: String,
    pub source_commit: String,
    pub source_tree: String,
}

impl QualificationCandidateV1 {
    pub fn validate(&self) -> Result<(), EvidenceError> {
        validate_identifier(&self.candidate_id, "candidate id")?;
        validate_git_oid(&self.source_commit, "candidate source commit")?;
        validate_git_oid(&self.source_tree, "candidate source tree")
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedEvidenceIssuerV1 {
    pub principal_id: String,
    pub controller_id: String,
    pub signing_identity_digest: Sha256Digest,
    pub credential_chain_digest: Sha256Digest,
    pub verifying_key: [u8; 32],
    pub roles: Vec<QualificationEvidenceRoleV1>,
    pub authenticated_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub revoked_at_unix_ms: Option<u64>,
}

impl AuthenticatedEvidenceIssuerV1 {
    fn validate_at(&self, now: u64) -> Result<(), EvidenceError> {
        validate_identifier(&self.principal_id, "issuer principal")?;
        validate_identifier(&self.controller_id, "issuer controller")?;
        validate_digest(&self.signing_identity_digest, "signing identity digest")?;
        validate_digest(&self.credential_chain_digest, "credential chain digest")?;
        if self.roles.is_empty() || self.roles.len() > 7 {
            return Err(invalid("issuer roles must contain 1..=7 registered roles"));
        }
        let mut unique = BTreeSet::new();
        if self.roles.iter().any(|role| !unique.insert(*role)) {
            return Err(invalid("issuer roles contain a duplicate"));
        }
        if self.authenticated_at_unix_ms > now
            || now > self.expires_at_unix_ms
            || self.authenticated_at_unix_ms > self.expires_at_unix_ms
            || self.revoked_at_unix_ms.is_some_and(|at| now >= at)
        {
            return Err(invalid("authenticated issuer is outside its validity window"));
        }
        let key = VerifyingKey::from_bytes(&self.verifying_key)
            .map_err(|_| invalid("authenticated issuer has an invalid Ed25519 key"))?;
        if key.is_weak() {
            return Err(invalid("authenticated issuer has a weak Ed25519 key"));
        }
        if Sha256Digest::for_bytes(&self.verifying_key) != self.signing_identity_digest {
            return Err(invalid(
                "authenticated issuer signing identity does not match its verifying key",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidenceEnvelopeV1 {
    pub schema_version: u32,
    pub evidence_id: EvidenceId,
    pub candidate_id: String,
    pub source_commit: String,
    pub source_tree: String,
    pub claim_class: QualificationClaimClassV1,
    pub protocol_id: String,
    pub issuer_principal_id: String,
    pub issuer_controller_id: String,
    pub issuer_role: QualificationEvidenceRoleV1,
    pub signing_identity_digest: Sha256Digest,
    pub credential_chain_digest: Sha256Digest,
    pub verifying_key_hex: String,
    pub payload_digest: Sha256Digest,
    pub evidence_set_digest: Sha256Digest,
    pub predecessor_evidence_id: Option<EvidenceId>,
    pub observed_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub revokes_evidence_id: Option<EvidenceId>,
    pub supersedes_evidence_id: Option<EvidenceId>,
    pub asset_digests: Vec<Sha256Digest>,
    pub decision: QualificationEvidenceDecisionV1,
    pub conditions: Vec<String>,
    pub detached_signature_hex: String,
}

impl QualificationEvidenceEnvelopeV1 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, EvidenceError> {
        canonical_json(&UnsignedQualificationEvidenceEnvelopeV1 {
            schema_version: self.schema_version,
            evidence_id: &self.evidence_id,
            candidate_id: &self.candidate_id,
            source_commit: &self.source_commit,
            source_tree: &self.source_tree,
            claim_class: self.claim_class,
            protocol_id: &self.protocol_id,
            issuer_principal_id: &self.issuer_principal_id,
            issuer_controller_id: &self.issuer_controller_id,
            issuer_role: self.issuer_role,
            signing_identity_digest: &self.signing_identity_digest,
            credential_chain_digest: &self.credential_chain_digest,
            verifying_key_hex: &self.verifying_key_hex,
            payload_digest: &self.payload_digest,
            evidence_set_digest: &self.evidence_set_digest,
            predecessor_evidence_id: self.predecessor_evidence_id.as_ref(),
            observed_unix_ms: self.observed_unix_ms,
            expires_unix_ms: self.expires_unix_ms,
            revokes_evidence_id: self.revokes_evidence_id.as_ref(),
            supersedes_evidence_id: self.supersedes_evidence_id.as_ref(),
            asset_digests: &self.asset_digests,
            decision: self.decision,
            conditions: &self.conditions,
        })
    }

    pub fn candidate(&self) -> QualificationCandidateV1 {
        QualificationCandidateV1 {
            candidate_id: self.candidate_id.clone(),
            source_commit: self.source_commit.clone(),
            source_tree: self.source_tree.clone(),
        }
    }

    pub fn independent_decision_receipt(&self) -> Option<IndependentDecisionReceiptV1> {
        (self.claim_class == QualificationClaimClassV1::IndependentDecision).then(|| {
            IndependentDecisionReceiptV1 {
                decision_id: self.evidence_id.to_string(),
                candidate_id: self.candidate_id.clone(),
                role: self.issuer_role,
                principal_id: self.issuer_principal_id.clone(),
                signing_identity_digest: self.signing_identity_digest.clone(),
                evidence_set_digest: self.evidence_set_digest.clone(),
                decision: self.decision,
                conditions: self.conditions.clone(),
                expires_unix_ms: self.expires_unix_ms,
            }
        })
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UnsignedQualificationEvidenceEnvelopeV1<'a> {
    schema_version: u32,
    evidence_id: &'a EvidenceId,
    candidate_id: &'a str,
    source_commit: &'a str,
    source_tree: &'a str,
    claim_class: QualificationClaimClassV1,
    protocol_id: &'a str,
    issuer_principal_id: &'a str,
    issuer_controller_id: &'a str,
    issuer_role: QualificationEvidenceRoleV1,
    signing_identity_digest: &'a Sha256Digest,
    credential_chain_digest: &'a Sha256Digest,
    verifying_key_hex: &'a str,
    payload_digest: &'a Sha256Digest,
    evidence_set_digest: &'a Sha256Digest,
    predecessor_evidence_id: Option<&'a EvidenceId>,
    observed_unix_ms: u64,
    expires_unix_ms: u64,
    revokes_evidence_id: Option<&'a EvidenceId>,
    supersedes_evidence_id: Option<&'a EvidenceId>,
    asset_digests: &'a [Sha256Digest],
    decision: QualificationEvidenceDecisionV1,
    conditions: &'a [String],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IndependentDecisionReceiptV1 {
    pub decision_id: String,
    pub candidate_id: String,
    pub role: QualificationEvidenceRoleV1,
    pub principal_id: String,
    pub signing_identity_digest: Sha256Digest,
    pub evidence_set_digest: Sha256Digest,
    pub decision: QualificationEvidenceDecisionV1,
    pub conditions: Vec<String>,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredQualificationEvidence {
    pub seq: i64,
    pub envelope: QualificationEvidenceEnvelopeV1,
    pub record_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationEvidenceReferenceV1 {
    pub seq: i64,
    pub evidence_id: EvidenceId,
    pub candidate: QualificationCandidateV1,
    pub claim_class: QualificationClaimClassV1,
    pub protocol_id: String,
    pub issuer_principal_id: String,
    pub issuer_controller_id: String,
    pub issuer_role: QualificationEvidenceRoleV1,
    pub signing_identity_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub evidence_set_digest: Sha256Digest,
    pub decision: QualificationEvidenceDecisionV1,
    pub observed_unix_ms: u64,
    pub expires_unix_ms: u64,
}

impl From<&StoredQualificationEvidence> for QualificationEvidenceReferenceV1 {
    fn from(value: &StoredQualificationEvidence) -> Self {
        let envelope = &value.envelope;
        Self {
            seq: value.seq,
            evidence_id: envelope.evidence_id.clone(),
            candidate: envelope.candidate(),
            claim_class: envelope.claim_class,
            protocol_id: envelope.protocol_id.clone(),
            issuer_principal_id: envelope.issuer_principal_id.clone(),
            issuer_controller_id: envelope.issuer_controller_id.clone(),
            issuer_role: envelope.issuer_role,
            signing_identity_digest: envelope.signing_identity_digest.clone(),
            payload_digest: envelope.payload_digest.clone(),
            evidence_set_digest: envelope.evidence_set_digest.clone(),
            decision: envelope.decision,
            observed_unix_ms: envelope.observed_unix_ms,
            expires_unix_ms: envelope.expires_unix_ms,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EvidenceDisposition {
    Supported {
        evidence: Vec<QualificationEvidenceReferenceV1>,
    },
    Missing {
        missing_roles: Vec<QualificationEvidenceRoleV1>,
    },
    Conflicting {
        evidence_ids: Vec<EvidenceId>,
    },
    Expired {
        evidence_ids: Vec<EvidenceId>,
    },
    Revoked {
        evidence_ids: Vec<EvidenceId>,
    },
}

#[derive(Clone, Copy)]
pub struct QualificationEvidenceStore<'a> {
    inner: &'a HeptaEvidenceStore,
}

impl HeptaEvidenceStore {
    pub fn qualification(&self) -> QualificationEvidenceStore<'_> {
        QualificationEvidenceStore { inner: self }
    }
}

impl QualificationEvidenceStore<'_> {
    pub async fn append_receipt(
        &self,
        envelope: &QualificationEvidenceEnvelopeV1,
        authenticated_issuer: &AuthenticatedEvidenceIssuerV1,
    ) -> Result<EvidenceId, EvidenceError> {
        let now = u64::try_from(now_millis()?)
            .map_err(|_| EvidenceError::Unavailable("clock predates Unix epoch".into()))?;
        validate_for_append(envelope, authenticated_issuer, now)?;
        let payload = canonical_json(envelope)?;
        if payload.len() > QUALIFICATION_EVIDENCE_MAX_ENCODED_BYTES {
            return Err(invalid("qualification evidence exceeds the encoded receipt limit"));
        }
        let payload_json = String::from_utf8(payload.clone())
            .map_err(|error| EvidenceError::Serialization(error.to_string()))?;
        let record_sha256 = Sha256Digest::for_bytes(&payload);

        let mut transaction = self
            .inner
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        validate_links(&mut transaction, envelope).await?;

        let insert = sqlx::query(
            "INSERT INTO qualification_evidence (
                evidence_id, candidate_id, source_commit, source_tree,
                claim_class, protocol_id, issuer_principal_id, issuer_controller_id,
                issuer_role, signing_identity_sha256, credential_chain_sha256,
                payload_sha256, evidence_set_sha256, predecessor_evidence_id,
                observed_at_ms, expires_at_ms, revokes_evidence_id,
                supersedes_evidence_id, payload_json, record_sha256, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON CONFLICT DO NOTHING",
        )
        .bind(envelope.evidence_id.as_str())
        .bind(&envelope.candidate_id)
        .bind(&envelope.source_commit)
        .bind(&envelope.source_tree)
        .bind(envelope.claim_class.as_str())
        .bind(&envelope.protocol_id)
        .bind(&envelope.issuer_principal_id)
        .bind(&envelope.issuer_controller_id)
        .bind(envelope.issuer_role.as_str())
        .bind(envelope.signing_identity_digest.as_str())
        .bind(envelope.credential_chain_digest.as_str())
        .bind(envelope.payload_digest.as_str())
        .bind(envelope.evidence_set_digest.as_str())
        .bind(envelope.predecessor_evidence_id.as_ref().map(EvidenceId::as_str))
        .bind(u64_to_i64(envelope.observed_unix_ms, "observation timestamp")?)
        .bind(u64_to_i64(envelope.expires_unix_ms, "expiry timestamp")?)
        .bind(envelope.revokes_evidence_id.as_ref().map(EvidenceId::as_str))
        .bind(envelope.supersedes_evidence_id.as_ref().map(EvidenceId::as_str))
        .bind(&payload_json)
        .bind(record_sha256.as_str())
        .bind(now_millis()?)
        .execute(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;

        let row = sqlx::query(QUALIFICATION_SELECT_BY_ID)
            .bind(envelope.evidence_id.as_str())
            .fetch_one(&mut *transaction)
            .await
            .map_err(classify_sqlx_error)?;
        let stored = decode_qualification_row(&row)?;
        if stored.envelope != *envelope || stored.record_sha256 != record_sha256 {
            return Err(EvidenceError::IdempotencyConflict {
                record_id: envelope.evidence_id.to_string(),
            });
        }
        let _inserted = insert.rows_affected() == 1;
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(envelope.evidence_id.clone())
    }

    pub async fn query_claim(
        &self,
        candidate: &QualificationCandidateV1,
        claim_class: QualificationClaimClassV1,
    ) -> Result<Vec<QualificationEvidenceReferenceV1>, EvidenceError> {
        candidate.validate()?;
        let rows = sqlx::query(
            "SELECT seq, evidence_id, candidate_id, source_commit, source_tree,
                    claim_class, protocol_id, issuer_principal_id, issuer_controller_id,
                    issuer_role, signing_identity_sha256, credential_chain_sha256,
                    payload_sha256, evidence_set_sha256, predecessor_evidence_id,
                    observed_at_ms, expires_at_ms, revokes_evidence_id,
                    supersedes_evidence_id, payload_json, record_sha256
             FROM qualification_evidence
             WHERE candidate_id = ? AND source_commit = ? AND source_tree = ? AND claim_class = ?
             ORDER BY seq
             LIMIT 513",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(claim_class.as_str())
        .fetch_all(&self.inner.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.len() > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
            return Err(invalid("qualification claim query exceeds the bounded result limit"));
        }
        rows.iter()
            .map(decode_qualification_row)
            .map(|result| result.map(|stored| QualificationEvidenceReferenceV1::from(&stored)))
            .collect()
    }

    pub async fn verify_chain(
        &self,
        candidate: &QualificationCandidateV1,
        required_roles: &[QualificationEvidenceRoleV1],
        now_unix_ms: u64,
    ) -> Result<EvidenceDisposition, EvidenceError> {
        candidate.validate()?;
        if required_roles.is_empty() || required_roles.len() > 7 {
            return Err(invalid("required roles must contain 1..=7 registered roles"));
        }
        let mut unique_roles = BTreeSet::new();
        if required_roles
            .iter()
            .any(|role| !unique_roles.insert(*role))
        {
            return Err(invalid("required roles contain a duplicate"));
        }

        let rows = sqlx::query(
            "SELECT seq, evidence_id, candidate_id, source_commit, source_tree,
                    claim_class, protocol_id, issuer_principal_id, issuer_controller_id,
                    issuer_role, signing_identity_sha256, credential_chain_sha256,
                    payload_sha256, evidence_set_sha256, predecessor_evidence_id,
                    observed_at_ms, expires_at_ms, revokes_evidence_id,
                    supersedes_evidence_id, payload_json, record_sha256
             FROM qualification_evidence
             WHERE candidate_id = ? AND source_commit = ? AND source_tree = ?
             ORDER BY seq
             LIMIT 513",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .fetch_all(&self.inner.pool)
        .await
        .map_err(classify_sqlx_error)?;
        if rows.len() > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
            return Err(invalid("candidate evidence exceeds the bounded verification set"));
        }

        let stored = rows
            .iter()
            .map(decode_qualification_row)
            .collect::<Result<Vec<_>, _>>()?;
        let by_id = stored
            .iter()
            .map(|record| (record.envelope.evidence_id.clone(), record))
            .collect::<BTreeMap<_, _>>();

        for record in &stored {
            verify_predecessor_chain(record, &by_id)?;
        }

        let revoked = stored
            .iter()
            .filter(|record| record.envelope.observed_unix_ms <= now_unix_ms)
            .filter_map(|record| record.envelope.revokes_evidence_id.clone())
            .collect::<BTreeSet<_>>();
        let superseded = stored
            .iter()
            .filter(|record| record.envelope.observed_unix_ms <= now_unix_ms)
            .filter_map(|record| record.envelope.supersedes_evidence_id.clone())
            .collect::<BTreeSet<_>>();

        let mut selected = Vec::new();
        let mut missing = Vec::new();
        let mut expired = Vec::new();
        let mut revoked_required = Vec::new();
        let mut conflicts = Vec::new();

        for role in required_roles {
            let role_records = stored
                .iter()
                .filter(|record| record.envelope.issuer_role == *role)
                .filter(|record| record.envelope.observed_unix_ms <= now_unix_ms)
                .collect::<Vec<_>>();
            let mut supports = Vec::new();
            for record in role_records {
                let id = &record.envelope.evidence_id;
                if revoked.contains(id) {
                    revoked_required.push(id.clone());
                    continue;
                }
                if superseded.contains(id) {
                    continue;
                }
                if record.envelope.expires_unix_ms < now_unix_ms {
                    expired.push(id.clone());
                    continue;
                }
                match record.envelope.decision {
                    QualificationEvidenceDecisionV1::Reject => conflicts.push(id.clone()),
                    QualificationEvidenceDecisionV1::Support
                    | QualificationEvidenceDecisionV1::Conditional => supports.push(record),
                }
            }
            if let Some(latest) = supports.last() {
                selected.push(*latest);
            } else if !conflicts.iter().any(|id| {
                by_id
                    .get(id)
                    .is_some_and(|record| record.envelope.issuer_role == *role)
            }) {
                missing.push(*role);
            }
        }

        if !conflicts.is_empty() {
            conflicts.sort();
            conflicts.dedup();
            return Ok(EvidenceDisposition::Conflicting {
                evidence_ids: conflicts,
            });
        }
        if !revoked_required.is_empty() {
            revoked_required.sort();
            revoked_required.dedup();
            return Ok(EvidenceDisposition::Revoked {
                evidence_ids: revoked_required,
            });
        }
        if !expired.is_empty() && !missing.is_empty() {
            expired.sort();
            expired.dedup();
            return Ok(EvidenceDisposition::Expired {
                evidence_ids: expired,
            });
        }
        if !missing.is_empty() {
            return Ok(EvidenceDisposition::Missing {
                missing_roles: missing,
            });
        }

        for left in 0..selected.len() {
            for right in (left + 1)..selected.len() {
                let a = &selected[left].envelope;
                let b = &selected[right].envelope;
                if a.issuer_principal_id == b.issuer_principal_id
                    || a.issuer_controller_id == b.issuer_controller_id
                    || a.signing_identity_digest == b.signing_identity_digest
                {
                    return Ok(EvidenceDisposition::Conflicting {
                        evidence_ids: vec![a.evidence_id.clone(), b.evidence_id.clone()],
                    });
                }
            }
        }

        Ok(EvidenceDisposition::Supported {
            evidence: selected
                .into_iter()
                .map(QualificationEvidenceReferenceV1::from)
                .collect(),
        })
    }
}

const QUALIFICATION_SELECT_BY_ID: &str =
    "SELECT seq, evidence_id, candidate_id, source_commit, source_tree,
            claim_class, protocol_id, issuer_principal_id, issuer_controller_id,
            issuer_role, signing_identity_sha256, credential_chain_sha256,
            payload_sha256, evidence_set_sha256, predecessor_evidence_id,
            observed_at_ms, expires_at_ms, revokes_evidence_id,
            supersedes_evidence_id, payload_json, record_sha256
     FROM qualification_evidence WHERE evidence_id = ?";

async fn validate_links(
    transaction: &mut Transaction<'_, Sqlite>,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<(), EvidenceError> {
    if envelope.revokes_evidence_id.is_some() && envelope.supersedes_evidence_id.is_some() {
        return Err(invalid(
            "one qualification receipt cannot both revoke and supersede",
        ));
    }

    if let Some(predecessor) = envelope.predecessor_evidence_id.as_ref() {
        let prior = load_link(transaction, predecessor).await?;
        require_same_candidate(envelope, &prior, "predecessor")?;
        if prior.claim_class != envelope.claim_class || prior.issuer_role != envelope.issuer_role {
            return Err(invalid(
                "qualification predecessor must preserve claim class and issuer role",
            ));
        }
    }
    if let Some(target) = envelope.supersedes_evidence_id.as_ref() {
        let prior = load_link(transaction, target).await?;
        require_same_candidate(envelope, &prior, "supersession target")?;
        if prior.claim_class != envelope.claim_class
            || prior.issuer_role != envelope.issuer_role
            || prior.issuer_principal_id != envelope.issuer_principal_id
        {
            return Err(invalid(
                "qualification supersession must preserve class, role and principal",
            ));
        }
    }
    if let Some(target) = envelope.revokes_evidence_id.as_ref() {
        let prior = load_link(transaction, target).await?;
        require_same_candidate(envelope, &prior, "revocation target")?;
        let self_revocation = prior.issuer_principal_id == envelope.issuer_principal_id
            && prior.issuer_role == envelope.issuer_role;
        let authority_revocation = matches!(
            envelope.issuer_role,
            QualificationEvidenceRoleV1::Reviewer | QualificationEvidenceRoleV1::Operator
        );
        if !self_revocation && !authority_revocation {
            return Err(invalid(
                "qualification revocation requires the same issuer/role or reviewer/operator role",
            ));
        }
    }
    Ok(())
}

async fn load_link(
    transaction: &mut Transaction<'_, Sqlite>,
    id: &EvidenceId,
) -> Result<QualificationEvidenceEnvelopeV1, EvidenceError> {
    let row = sqlx::query(QUALIFICATION_SELECT_BY_ID)
        .bind(id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(classify_sqlx_error)?
        .ok_or_else(|| invalid(format!("qualification link target is missing: {id}")))?;
    Ok(decode_qualification_row(&row)?.envelope)
}

fn require_same_candidate(
    envelope: &QualificationEvidenceEnvelopeV1,
    prior: &QualificationEvidenceEnvelopeV1,
    label: &str,
) -> Result<(), EvidenceError> {
    if envelope.candidate_id != prior.candidate_id
        || envelope.source_commit != prior.source_commit
        || envelope.source_tree != prior.source_tree
    {
        return Err(invalid(format!(
            "qualification {label} belongs to a different exact candidate"
        )));
    }
    Ok(())
}

fn validate_for_append(
    envelope: &QualificationEvidenceEnvelopeV1,
    issuer: &AuthenticatedEvidenceIssuerV1,
    now: u64,
) -> Result<(), EvidenceError> {
    validate_envelope_shape(envelope)?;
    issuer.validate_at(now)?;
    if envelope.issuer_principal_id != issuer.principal_id
        || envelope.issuer_controller_id != issuer.controller_id
        || envelope.signing_identity_digest != issuer.signing_identity_digest
        || envelope.credential_chain_digest != issuer.credential_chain_digest
        || !issuer.roles.contains(&envelope.issuer_role)
    {
        return Err(invalid(
            "qualification receipt issuer does not match the authenticated host identity",
        ));
    }
    if envelope.observed_unix_ms < issuer.authenticated_at_unix_ms
        || envelope.observed_unix_ms > now
        || envelope.expires_unix_ms > issuer.expires_at_unix_ms
        || envelope.expires_unix_ms < now
    {
        return Err(invalid(
            "qualification receipt is outside the authenticated issuer validity window",
        ));
    }
    if envelope.verifying_key_hex != encode_hex(&issuer.verifying_key) {
        return Err(invalid(
            "qualification receipt verifying key differs from the authenticated issuer",
        ));
    }
    verify_embedded_signature(envelope)
}

fn validate_envelope_shape(
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<(), EvidenceError> {
    if envelope.schema_version != QUALIFICATION_EVIDENCE_SCHEMA_VERSION {
        return Err(invalid("unsupported qualification evidence schema version"));
    }
    EvidenceId::parse(envelope.evidence_id.as_str().to_string())?;
    envelope.candidate().validate()?;
    if envelope.protocol_id != envelope.claim_class.protocol_id() {
        return Err(invalid(
            "qualification claim class does not match its registered protocol",
        ));
    }
    validate_identifier(&envelope.issuer_principal_id, "issuer principal")?;
    validate_identifier(&envelope.issuer_controller_id, "issuer controller")?;
    validate_digest(&envelope.signing_identity_digest, "signing identity digest")?;
    validate_digest(&envelope.credential_chain_digest, "credential chain digest")?;
    validate_digest(&envelope.payload_digest, "payload digest")?;
    validate_digest(&envelope.evidence_set_digest, "evidence-set digest")?;
    if envelope.observed_unix_ms > envelope.expires_unix_ms
        || envelope.expires_unix_ms > i64::MAX as u64
    {
        return Err(invalid("qualification evidence validity window is invalid"));
    }
    if envelope.asset_digests.len() > QUALIFICATION_EVIDENCE_MAX_ASSETS {
        return Err(invalid("qualification evidence references too many assets"));
    }
    for digest in &envelope.asset_digests {
        validate_digest(digest, "asset digest")?;
    }
    if envelope.conditions.len() > MAX_CONDITIONS
        || envelope
            .conditions
            .iter()
            .any(|condition| condition.is_empty() || condition.len() > MAX_CONDITION_BYTES)
    {
        return Err(invalid("qualification evidence conditions exceed their bounds"));
    }
    if envelope.decision == QualificationEvidenceDecisionV1::Conditional
        && envelope.conditions.is_empty()
    {
        return Err(invalid("conditional evidence requires at least one condition"));
    }
    if envelope
        .predecessor_evidence_id
        .as_ref()
        .is_some_and(|id| id == &envelope.evidence_id)
        || envelope
            .revokes_evidence_id
            .as_ref()
            .is_some_and(|id| id == &envelope.evidence_id)
        || envelope
            .supersedes_evidence_id
            .as_ref()
            .is_some_and(|id| id == &envelope.evidence_id)
    {
        return Err(invalid("qualification evidence cannot link to itself"));
    }
    decode_hex_array::<32>(&envelope.verifying_key_hex, "verifying key")?;
    decode_hex_array::<64>(&envelope.detached_signature_hex, "detached signature")?;
    let encoded = canonical_json(envelope)?;
    if encoded.len() > QUALIFICATION_EVIDENCE_MAX_ENCODED_BYTES {
        return Err(invalid("qualification evidence exceeds the encoded receipt limit"));
    }
    Ok(())
}

fn verify_embedded_signature(
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<(), EvidenceError> {
    let key_bytes = decode_hex_array::<32>(&envelope.verifying_key_hex, "verifying key")?;
    if Sha256Digest::for_bytes(&key_bytes) != envelope.signing_identity_digest {
        return Err(invalid(
            "qualification evidence signing identity does not match its embedded key",
        ));
    }
    let key = VerifyingKey::from_bytes(&key_bytes)
        .map_err(|_| invalid("qualification evidence contains an invalid Ed25519 key"))?;
    if key.is_weak() {
        return Err(invalid(
            "qualification evidence contains a weak Ed25519 key",
        ));
    }
    let signature =
        Signature::from_bytes(&decode_hex_array::<64>(&envelope.detached_signature_hex, "signature")?);
    key.verify_strict(&envelope.signing_bytes()?, &signature)
        .map_err(|_| invalid("qualification evidence signature verification failed"))
}

fn verify_predecessor_chain(
    record: &StoredQualificationEvidence,
    by_id: &BTreeMap<EvidenceId, &StoredQualificationEvidence>,
) -> Result<(), EvidenceError> {
    let mut current = record.envelope.predecessor_evidence_id.as_ref();
    let mut seen = BTreeSet::new();
    let mut edges = 0_usize;
    while let Some(id) = current {
        edges += 1;
        if edges > QUALIFICATION_EVIDENCE_MAX_CHAIN_EDGES {
            return Err(invalid(
                "qualification predecessor traversal exceeds the chain limit",
            ));
        }
        if !seen.insert(id.clone()) {
            return Err(EvidenceError::Corrupt(
                "qualification predecessor chain contains a cycle".into(),
            ));
        }
        let prior = by_id.get(id).ok_or_else(|| {
            EvidenceError::Corrupt("qualification predecessor is missing from candidate set".into())
        })?;
        require_same_candidate(&record.envelope, &prior.envelope, "predecessor")?;
        current = prior.envelope.predecessor_evidence_id.as_ref();
    }
    Ok(())
}

fn decode_qualification_row(row: &SqliteRow) -> Result<StoredQualificationEvidence, EvidenceError> {
    let payload_json: String = row.try_get("payload_json").map_err(classify_sqlx_error)?;
    let envelope: QualificationEvidenceEnvelopeV1 = serde_json::from_str(&payload_json)
        .map_err(|error| EvidenceError::Corrupt(format!("invalid qualification receipt JSON: {error}")))?;
    validate_envelope_shape(&envelope)?;
    verify_embedded_signature(&envelope)?;
    let canonical = canonical_json(&envelope)?;
    if canonical.as_slice() != payload_json.as_bytes() {
        return Err(EvidenceError::Corrupt(
            "qualification receipt JSON is not canonical".into(),
        ));
    }
    let record_sha256 = Sha256Digest::parse(
        row.try_get::<String, _>("record_sha256")
            .map_err(classify_sqlx_error)?,
    )
    .map_err(EvidenceError::Corrupt)?;
    if Sha256Digest::for_bytes(&canonical) != record_sha256 {
        return Err(EvidenceError::Corrupt(
            "qualification receipt record digest mismatch".into(),
        ));
    }

    let row_claim = QualificationClaimClassV1::parse(
        &row.try_get::<String, _>("claim_class")
            .map_err(classify_sqlx_error)?,
    )?;
    let row_role = QualificationEvidenceRoleV1::parse(
        &row.try_get::<String, _>("issuer_role")
            .map_err(classify_sqlx_error)?,
    )?;
    let observed: i64 = row.try_get("observed_at_ms").map_err(classify_sqlx_error)?;
    let expires: i64 = row.try_get("expires_at_ms").map_err(classify_sqlx_error)?;
    if observed < 0 || expires < 0 {
        return Err(EvidenceError::Corrupt(
            "qualification timestamps are negative".into(),
        ));
    }
    let predecessor: Option<String> = row
        .try_get("predecessor_evidence_id")
        .map_err(classify_sqlx_error)?;
    let revokes: Option<String> = row
        .try_get("revokes_evidence_id")
        .map_err(classify_sqlx_error)?;
    let supersedes: Option<String> = row
        .try_get("supersedes_evidence_id")
        .map_err(classify_sqlx_error)?;

    let matches = row.try_get::<String, _>("evidence_id").map_err(classify_sqlx_error)?
        == envelope.evidence_id.as_str()
        && row.try_get::<String, _>("candidate_id").map_err(classify_sqlx_error)?
            == envelope.candidate_id
        && row.try_get::<String, _>("source_commit").map_err(classify_sqlx_error)?
            == envelope.source_commit
        && row.try_get::<String, _>("source_tree").map_err(classify_sqlx_error)?
            == envelope.source_tree
        && row_claim == envelope.claim_class
        && row.try_get::<String, _>("protocol_id").map_err(classify_sqlx_error)?
            == envelope.protocol_id
        && row.try_get::<String, _>("issuer_principal_id").map_err(classify_sqlx_error)?
            == envelope.issuer_principal_id
        && row.try_get::<String, _>("issuer_controller_id").map_err(classify_sqlx_error)?
            == envelope.issuer_controller_id
        && row_role == envelope.issuer_role
        && row.try_get::<String, _>("signing_identity_sha256").map_err(classify_sqlx_error)?
            == envelope.signing_identity_digest.as_str()
        && row.try_get::<String, _>("credential_chain_sha256").map_err(classify_sqlx_error)?
            == envelope.credential_chain_digest.as_str()
        && row.try_get::<String, _>("payload_sha256").map_err(classify_sqlx_error)?
            == envelope.payload_digest.as_str()
        && row.try_get::<String, _>("evidence_set_sha256").map_err(classify_sqlx_error)?
            == envelope.evidence_set_digest.as_str()
        && predecessor.as_deref() == envelope.predecessor_evidence_id.as_ref().map(EvidenceId::as_str)
        && u64::try_from(observed).ok() == Some(envelope.observed_unix_ms)
        && u64::try_from(expires).ok() == Some(envelope.expires_unix_ms)
        && revokes.as_deref() == envelope.revokes_evidence_id.as_ref().map(EvidenceId::as_str)
        && supersedes.as_deref() == envelope.supersedes_evidence_id.as_ref().map(EvidenceId::as_str);
    if !matches {
        return Err(EvidenceError::Corrupt(
            "qualification receipt projection differs from canonical payload".into(),
        ));
    }

    Ok(StoredQualificationEvidence {
        seq: row.try_get("seq").map_err(classify_sqlx_error)?,
        envelope,
        record_sha256,
    })
}

pub(crate) async fn verify_qualification_evidence_rows(
    pool: &SqlitePool,
) -> Result<(), EvidenceError> {
    let rows = sqlx::query(
        "SELECT seq, evidence_id, candidate_id, source_commit, source_tree,
                claim_class, protocol_id, issuer_principal_id, issuer_controller_id,
                issuer_role, signing_identity_sha256, credential_chain_sha256,
                payload_sha256, evidence_set_sha256, predecessor_evidence_id,
                observed_at_ms, expires_at_ms, revokes_evidence_id,
                supersedes_evidence_id, payload_json, record_sha256
         FROM qualification_evidence ORDER BY seq",
    )
    .fetch_all(pool)
    .await
    .map_err(classify_sqlx_error)?;
    let mut by_id = BTreeMap::new();
    for row in &rows {
        let decoded = decode_qualification_row(row)?;
        if by_id
            .insert(decoded.envelope.evidence_id.clone(), decoded)
            .is_some()
        {
            return Err(EvidenceError::Corrupt(
                "qualification evidence contains a duplicate identity".into(),
            ));
        }
    }
    for record in by_id.values() {
        if let Some(id) = record.envelope.predecessor_evidence_id.as_ref() {
            let prior = by_id.get(id).ok_or_else(|| {
                EvidenceError::Corrupt("qualification predecessor is missing".into())
            })?;
            require_same_candidate(&record.envelope, &prior.envelope, "predecessor")?;
        }
        for (label, link) in [
            ("revocation target", record.envelope.revokes_evidence_id.as_ref()),
            (
                "supersession target",
                record.envelope.supersedes_evidence_id.as_ref(),
            ),
        ] {
            if let Some(id) = link {
                let prior = by_id.get(id).ok_or_else(|| {
                    EvidenceError::Corrupt(format!("qualification {label} is missing"))
                })?;
                require_same_candidate(&record.envelope, &prior.envelope, label)?;
            }
        }
    }
    let refs = by_id.iter().map(|(id, value)| (id.clone(), value)).collect();
    for record in by_id.values() {
        verify_predecessor_chain(record, &refs)?;
    }
    Ok(())
}

fn validate_identifier(value: &str, label: &str) -> Result<(), EvidenceError> {
    if value.is_empty()
        || value.len() > MAX_IDENTIFIER_BYTES
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(invalid(format!("{label} has an invalid identifier")));
    }
    Ok(())
}

fn validate_git_oid(value: &str, label: &str) -> Result<(), EvidenceError> {
    if value.len() != 40
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(format!(
            "{label} must be exactly 40 lowercase hexadecimal characters"
        )));
    }
    Ok(())
}

fn validate_digest(value: &Sha256Digest, label: &str) -> Result<(), EvidenceError> {
    Sha256Digest::parse(value.as_str().to_string())
        .map(|_| ())
        .map_err(|error| invalid(format!("{label}: {error}")))
}

fn u64_to_i64(value: u64, label: &str) -> Result<i64, EvidenceError> {
    i64::try_from(value).map_err(|_| invalid(format!("{label} exceeds SQLite INTEGER range")))
}

fn encode_hex<const N: usize>(bytes: &[u8; N]) -> String {
    let mut encoded = String::with_capacity(N * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut encoded, "{byte:02x}").expect("writing to a String cannot fail");
    }
    encoded
}

fn decode_hex_array<const N: usize>(
    value: &str,
    label: &str,
) -> Result<[u8; N], EvidenceError> {
    if value.len() != N * 2
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(format!(
            "{label} must contain exactly {} lowercase hexadecimal characters",
            N * 2
        )));
    }
    let mut output = [0_u8; N];
    for (index, target) in output.iter_mut().enumerate() {
        let offset = index * 2;
        *target = u8::from_str_radix(&value[offset..offset + 2], 16)
            .map_err(|_| invalid(format!("{label} contains invalid hexadecimal")))?;
    }
    Ok(output)
}

fn invalid(message: impl Into<String>) -> EvidenceError {
    EvidenceError::InvalidRecord(message.into())
}
