use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::sqlite::SqliteRow;

use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceError;
use crate::EvidenceId;
use crate::EvidenceReceiptKindV1;
use crate::EvidenceReferenceV1;
use crate::HeptaEvidenceStore;
use crate::QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS;
use crate::qualification_envelope_bytes;
use crate::schema_validation::classify_sqlx_error;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidencePageV1 {
    pub evidence: Vec<EvidenceReferenceV1>,
    pub next_after_seq: Option<u64>,
}

impl HeptaEvidenceStore {
    /// Query one stable page of qualification references in append sequence order.
    ///
    /// `after_seq` is an exclusive cursor returned by the previous page. The
    /// cursor is stable because qualification rows are append-only and `seq` is
    /// immutable. Limits are fail-closed to the same 512-row bound as the legacy
    /// compatibility query. This API does not weaken full-chain verification:
    /// callers that need a disposition must continue to use `verify_chain`.
    pub async fn query_qualification_claim_page(
        &self,
        candidate: &EvidenceCandidateV1,
        claim_class: EvidenceClaimClassV1,
        after_seq: Option<u64>,
        limit: usize,
    ) -> Result<QualificationEvidencePageV1, EvidenceError> {
        candidate.validate().map_err(EvidenceError::InvalidRecord)?;
        if limit == 0 || limit > QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS {
            return Err(EvidenceError::InvalidRecord(
                "qualification evidence page limit must be between 1 and 512".to_string(),
            ));
        }
        let after_seq = after_seq.unwrap_or(0);
        let after_seq = i64::try_from(after_seq).map_err(|_| {
            EvidenceError::InvalidRecord(
                "qualification evidence cursor exceeds the SQLite sequence domain".to_string(),
            )
        })?;
        let fetch_limit = i64::try_from(limit + 1)
            .map_err(|_| EvidenceError::InvalidRecord("query bound overflow".to_string()))?;
        let rows = sqlx::query(
            "SELECT seq, evidence_id, candidate_id, source_commit, source_tree,
                    claim_class, receipt_kind, issuer_role, issuer_principal_id,
                    payload_sha256, envelope_sha256, predecessor_evidence_id,
                    target_evidence_id, observed_at_ms, expires_at_ms, envelope_json
             FROM qualification_evidence
             WHERE candidate_id = ? AND source_commit = ? AND source_tree = ?
               AND claim_class = ? AND seq > ?
             ORDER BY seq ASC
             LIMIT ?",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(claim_class.as_str())
        .bind(after_seq)
        .bind(fetch_limit)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;

        let has_more = rows.len() > limit;
        let mut decoded = rows
            .iter()
            .take(limit)
            .map(|row| decode_reference(row, candidate, claim_class))
            .collect::<Result<Vec<_>, _>>()?;
        let next_after_seq = if has_more {
            decoded
                .last()
                .map(|(seq, _)| u64::try_from(*seq))
                .transpose()
                .map_err(|_| {
                    EvidenceError::Corrupt(
                        "qualification evidence sequence is negative".to_string(),
                    )
                })?
        } else {
            None
        };
        Ok(QualificationEvidencePageV1 {
            evidence: decoded.drain(..).map(|(_, reference)| reference).collect(),
            next_after_seq,
        })
    }
}

fn decode_reference(
    row: &SqliteRow,
    expected_candidate: &EvidenceCandidateV1,
    expected_claim: EvidenceClaimClassV1,
) -> Result<(i64, EvidenceReferenceV1), EvidenceError> {
    let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
    if seq <= 0 {
        return Err(EvidenceError::Corrupt(
            "qualification evidence sequence must be positive".to_string(),
        ));
    }
    let envelope_json: String = row.try_get("envelope_json").map_err(classify_sqlx_error)?;
    let envelope: crate::QualificationEvidenceEnvelopeV1 =
        serde_json::from_str(&envelope_json).map_err(|error| {
            EvidenceError::Corrupt(format!(
                "qualification evidence envelope cannot be decoded: {error}"
            ))
        })?;
    let canonical = qualification_envelope_bytes(&envelope)?;
    if canonical.as_slice() != envelope_json.as_bytes() {
        return Err(EvidenceError::Corrupt(
            "qualification evidence envelope is not canonical JSON".to_string(),
        ));
    }
    let envelope_sha256 = Sha256Digest::for_bytes(&canonical);
    let stored_envelope = parse_digest(row, "envelope_sha256")?;
    let payload_sha256 = parse_digest(row, "payload_sha256")?;
    let evidence_id: String = row.try_get("evidence_id").map_err(classify_sqlx_error)?;
    let candidate_id: String = row.try_get("candidate_id").map_err(classify_sqlx_error)?;
    let source_commit: String = row.try_get("source_commit").map_err(classify_sqlx_error)?;
    let source_tree: String = row.try_get("source_tree").map_err(classify_sqlx_error)?;
    let claim_class: String = row.try_get("claim_class").map_err(classify_sqlx_error)?;
    let receipt_kind: String = row.try_get("receipt_kind").map_err(classify_sqlx_error)?;
    let issuer_role: String = row.try_get("issuer_role").map_err(classify_sqlx_error)?;
    let predecessor: Option<String> = row
        .try_get("predecessor_evidence_id")
        .map_err(classify_sqlx_error)?;
    let target: Option<String> = row
        .try_get("target_evidence_id")
        .map_err(classify_sqlx_error)?;
    let observed_unix_ms = read_u64_blob(row, "observed_at_ms")?;
    let expires_unix_ms = read_optional_u64_blob(row, "expires_at_ms")?;

    if envelope.candidate != *expected_candidate
        || envelope.claim_class != expected_claim
        || evidence_id != envelope.evidence_id.as_str()
        || candidate_id != envelope.candidate.candidate_id
        || source_commit != envelope.candidate.source_commit
        || source_tree != envelope.candidate.source_tree
        || claim_class != envelope.claim_class.as_str()
        || receipt_kind != receipt_kind_str(envelope.receipt_kind)
        || issuer_role != envelope.issuer_role.as_str()
        || predecessor.as_deref()
            != envelope
                .predecessor_evidence_id
                .as_ref()
                .map(EvidenceId::as_str)
        || target.as_deref()
            != envelope.target_evidence_id.as_ref().map(EvidenceId::as_str)
        || observed_unix_ms != envelope.observed_unix_ms
        || expires_unix_ms != envelope.expires_unix_ms
        || envelope_sha256 != stored_envelope
    {
        return Err(EvidenceError::Corrupt(
            "qualification evidence page projection differs from its canonical envelope"
                .to_string(),
        ));
    }

    Ok((
        seq,
        EvidenceReferenceV1 {
            evidence_id: envelope.evidence_id,
            claim_class: envelope.claim_class,
            receipt_kind: envelope.receipt_kind,
            issuer_role: envelope.issuer_role,
            issuer_principal_id: row
                .try_get("issuer_principal_id")
                .map_err(classify_sqlx_error)?,
            payload_sha256,
            envelope_sha256,
            predecessor_evidence_id: envelope.predecessor_evidence_id,
            target_evidence_id: envelope.target_evidence_id,
            observed_unix_ms: envelope.observed_unix_ms,
            expires_unix_ms: envelope.expires_unix_ms,
        },
    ))
}

fn parse_digest(row: &SqliteRow, column: &str) -> Result<Sha256Digest, EvidenceError> {
    Sha256Digest::parse(
        row.try_get::<String, _>(column)
            .map_err(classify_sqlx_error)?,
    )
    .map_err(EvidenceError::Corrupt)
}

fn read_u64_blob(row: &SqliteRow, column: &str) -> Result<u64, EvidenceError> {
    let bytes: Vec<u8> = row.try_get(column).map_err(classify_sqlx_error)?;
    let bytes: [u8; 8] = bytes
        .try_into()
        .map_err(|_| EvidenceError::Corrupt(format!("{column} has invalid width")))?;
    Ok(u64::from_be_bytes(bytes))
}

fn read_optional_u64_blob(row: &SqliteRow, column: &str) -> Result<Option<u64>, EvidenceError> {
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

fn receipt_kind_str(kind: EvidenceReceiptKindV1) -> &'static str {
    match kind {
        EvidenceReceiptKindV1::Evidence => "evidence",
        EvidenceReceiptKindV1::Correction => "correction",
        EvidenceReceiptKindV1::Revocation => "revocation",
    }
}

#[cfg(test)]
#[path = "qualification_paging_tests.rs"]
mod tests;
