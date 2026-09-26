use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;

use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;

pub const QUALIFICATION_CURSOR_MAX_PAGE_SIZE: usize = 256;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidenceCursorV1 {
    pub after_seq: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidenceCursorEntryV1 {
    pub seq: u64,
    pub evidence_id: String,
    pub receipt_kind: String,
    pub issuer_role: String,
    pub issuer_principal_id: String,
    pub envelope_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct QualificationEvidencePageV1 {
    pub entries: Vec<QualificationEvidenceCursorEntryV1>,
    pub next_cursor: Option<QualificationEvidenceCursorV1>,
}

impl HeptaEvidenceStore {
    /// Returns a stable ascending sequence page for one exact candidate/tree
    /// and claim class. The cursor is exclusive and cannot cross candidate or
    /// claim boundaries because those bindings are repeated in every query.
    pub async fn query_qualification_page(
        &self,
        candidate: &EvidenceCandidateV1,
        claim_class: EvidenceClaimClassV1,
        cursor: Option<&QualificationEvidenceCursorV1>,
        page_size: usize,
    ) -> Result<QualificationEvidencePageV1, EvidenceError> {
        candidate.validate().map_err(EvidenceError::InvalidRecord)?;
        if page_size == 0 || page_size > QUALIFICATION_CURSOR_MAX_PAGE_SIZE {
            return Err(EvidenceError::InvalidRecord(
                "qualification cursor page size must be between 1 and 256".to_string(),
            ));
        }
        let after_seq = cursor.map_or(0, |cursor| cursor.after_seq);
        let sql_limit = i64::try_from(page_size.saturating_add(1)).map_err(|_| {
            EvidenceError::InvalidRecord("qualification page size overflow".to_string())
        })?;
        let after_seq = i64::try_from(after_seq).map_err(|_| {
            EvidenceError::InvalidRecord("qualification cursor exceeds SQLite range".to_string())
        })?;
        let rows = sqlx::query(
            "SELECT seq, evidence_id, receipt_kind, issuer_role,
                    issuer_principal_id, envelope_sha256
             FROM qualification_evidence
             WHERE candidate_id = ?
               AND source_commit = ?
               AND source_tree = ?
               AND claim_class = ?
               AND seq > ?
             ORDER BY seq ASC
             LIMIT ?",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(claim_class.as_str())
        .bind(after_seq)
        .bind(sql_limit)
        .fetch_all(&self.pool)
        .await
        .map_err(classify_sqlx_error)?;

        let has_more = rows.len() > page_size;
        let mut entries = Vec::with_capacity(rows.len().min(page_size));
        for row in rows.into_iter().take(page_size) {
            let seq: i64 = row.try_get("seq").map_err(classify_sqlx_error)?;
            let seq = u64::try_from(seq).map_err(|_| {
                EvidenceError::Corrupt("qualification cursor encountered negative seq".to_string())
            })?;
            let envelope_sha256: String = row
                .try_get("envelope_sha256")
                .map_err(classify_sqlx_error)?;
            let envelope_sha256 = envelope_sha256.parse().map_err(|error| {
                EvidenceError::Corrupt(format!(
                    "qualification cursor encountered invalid envelope digest: {error}"
                ))
            })?;
            entries.push(QualificationEvidenceCursorEntryV1 {
                seq,
                evidence_id: row.try_get("evidence_id").map_err(classify_sqlx_error)?,
                receipt_kind: row.try_get("receipt_kind").map_err(classify_sqlx_error)?,
                issuer_role: row.try_get("issuer_role").map_err(classify_sqlx_error)?,
                issuer_principal_id: row
                    .try_get("issuer_principal_id")
                    .map_err(classify_sqlx_error)?,
                envelope_sha256,
            });
        }
        let next_cursor = if has_more {
            entries
                .last()
                .map(|entry| QualificationEvidenceCursorV1 {
                    after_seq: entry.seq,
                })
        } else {
            None
        };
        Ok(QualificationEvidencePageV1 {
            entries,
            next_cursor,
        })
    }
}
