use sqlx::Row;

use crate::MatrixDispatchReceipt;
use crate::MatrixDurableError;
use crate::MatrixDurableStore;
use crate::MatrixEventId;
use crate::MatrixTransactionId;

impl MatrixDurableStore {
    /// Find the canonical dispatch receipt bound to a homeserver event without
    /// inventing a second index owner. This is used only to make delayed sync
    /// and transport observations idempotent after terminal archival.
    pub async fn matrix_dispatch_receipt_for_event(
        &self,
        event_id: &MatrixEventId,
    ) -> Result<Option<MatrixDispatchReceipt>, MatrixDurableError> {
        let row = sqlx::query(
            "SELECT stable_txn_id FROM matrix_dispatch_ledger
             WHERE accepted_event_id = ? OR observed_event_id = ?
             UNION ALL
             SELECT stable_txn_id FROM matrix_dispatch_archive
             WHERE accepted_event_id = ? OR observed_event_id = ?
             LIMIT 1",
        )
        .bind(event_id.as_str())
        .bind(event_id.as_str())
        .bind(event_id.as_str())
        .bind(event_id.as_str())
        .fetch_optional(self.sqlite_pool())
        .await
        .map_err(|_| MatrixDurableError::Unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let txn = MatrixTransactionId::parse(
            &row.try_get::<String, _>("stable_txn_id")
                .map_err(|_| MatrixDurableError::Corrupt)?,
        )
        .map_err(|_| MatrixDurableError::Corrupt)?;
        self.matrix_dispatch_receipt(&txn).await
    }
}
