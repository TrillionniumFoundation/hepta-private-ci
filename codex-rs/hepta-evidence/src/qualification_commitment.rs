//! Read-only full-admission commitments. A digest is not a signature or an
//! external publication acknowledgement. Recovery publication must bind it.

use codex_hepta_contracts::Sha256Digest;

use crate::EvidenceError;
use crate::EvidenceId;
use crate::HeptaEvidenceStore;
use crate::qualification::authenticated_row_sha256;
use crate::qualification::qualification_select;
use crate::schema_validation::classify_sqlx_error;

impl HeptaEvidenceStore {
    pub async fn qualification_record_commitment(
        &self,
        evidence_id: &EvidenceId,
    ) -> Result<Option<Sha256Digest>, EvidenceError> {
        let statement = qualification_select!("WHERE evidence_id = ?");
        let row = sqlx::query(statement)
            .bind(evidence_id.as_str())
            .fetch_optional(&self.pool)
            .await
            .map_err(classify_sqlx_error)?;
        row.as_ref().map(authenticated_row_sha256).transpose()
    }
}
