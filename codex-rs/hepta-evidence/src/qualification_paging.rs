use serde::Deserialize;
use serde::Serialize;

use crate::EvidenceCandidateV1;
use crate::EvidenceClaimClassV1;
use crate::EvidenceError;
use crate::EvidenceReferenceV1;
use crate::HeptaEvidenceStore;
use crate::QUALIFICATION_EVIDENCE_MAX_QUERY_RESULTS;
use crate::qualification::QUALIFICATION_COLUMNS;
use crate::qualification::checked_qualification_reference;
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
    /// `after_seq` is an exclusive cursor returned by the previous page. It
    /// must name a row of this exact candidate/tree/class, not another query.
    /// This is a live append-only traversal, NOT a historical snapshot proof.
    /// Limits are fail-closed to the same 512-row bound as the legacy
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
        let mut transaction = self.pool.begin().await.map_err(classify_sqlx_error)?;
        if after_seq != 0 {
            let cursor_matches: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM qualification_evidence
                 WHERE seq = ? AND candidate_id = ? AND source_commit = ?
                   AND source_tree = ? AND claim_class = ?",
            )
            .bind(after_seq)
            .bind(&candidate.candidate_id)
            .bind(&candidate.source_commit)
            .bind(&candidate.source_tree)
            .bind(claim_class.as_str())
            .fetch_one(&mut *transaction)
            .await
            .map_err(classify_sqlx_error)?;
            if cursor_matches != 1 {
                return Err(EvidenceError::InvalidRecord(
                    "qualification cursor does not belong to this exact selector".to_string(),
                ));
            }
        }
        // Check the page byte bound in SQLite before materializing envelope JSON.
        let largest: i64 = sqlx::query_scalar(
            "SELECT COALESCE(MAX(payload_bytes), 0) FROM (
                SELECT length(CAST(envelope_json AS BLOB)) AS payload_bytes
                FROM qualification_evidence
                WHERE candidate_id = ? AND source_commit = ? AND source_tree = ?
                  AND claim_class = ? AND seq > ? ORDER BY seq ASC LIMIT ?
             )",
        )
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(claim_class.as_str())
        .bind(after_seq)
        .bind(fetch_limit)
        .fetch_one(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;
        if largest > crate::QUALIFICATION_EVIDENCE_MAX_RECEIPT_BYTES as i64 {
            return Err(EvidenceError::Corrupt(
                "qualification page contains an oversized envelope".to_string(),
            ));
        }
        let rows = sqlx::query(&format!(
            "SELECT {QUALIFICATION_COLUMNS} FROM qualification_evidence
             WHERE candidate_id = ? AND source_commit = ? AND source_tree = ?
               AND claim_class = ? AND seq > ? ORDER BY seq ASC LIMIT ?"
        ))
        .bind(&candidate.candidate_id)
        .bind(&candidate.source_commit)
        .bind(&candidate.source_tree)
        .bind(claim_class.as_str())
        .bind(after_seq)
        .bind(fetch_limit)
        .fetch_all(&mut *transaction)
        .await
        .map_err(classify_sqlx_error)?;

        let has_more = rows.len() > limit;
        let mut decoded = rows
            .iter()
            .take(limit)
            .map(|row| checked_qualification_reference(row, candidate, claim_class))
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
        transaction.commit().await.map_err(classify_sqlx_error)?;
        Ok(QualificationEvidencePageV1 {
            evidence: decoded.drain(..).map(|(_, reference)| reference).collect(),
            next_after_seq,
        })
    }
}

#[cfg(test)]
#[path = "qualification_paging_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "qualification_paging_boundary_tests.rs"]
mod boundary_tests;
