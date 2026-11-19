//! Check a fresh Notes read against facts retained by the original source.
//! No new history, caller-supplied sequence, receipt or permission is created.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;

use super::ProductionDurableWriter;
use super::ProductionWriterError;
use crate::LocalReconcileOutcome;
use crate::NotesDocumentState;
use crate::production_notes::NotesTerminalReceipt;

// Bound returned records and Rust parsing work, not arbitrary SQLite query
// execution time. The product caller also retains its original time budget.
const PAGE_SIZE: i64 = 64;
const MAX_READ_FLOOR_ROWS: usize = 1024;

impl ProductionDurableWriter {
    /// Reject a document older than this original owner's known committed
    /// Notes results, or conflicting content at an already committed revision.
    /// Call only after fresh, nonce-correlated I/O for the attached target.
    /// This does not authenticate an arbitrary supplied document as a real read.
    ///
    /// Read-only keyset pages from the existing journal survive reattachment.
    /// Every candidate request/receipt is revalidated; Rust u64 comparisons
    /// preserve revisions above SQLite integer/float precision. More than
    /// 1024 matching records returns an error instead of ignoring history.
    ///
    /// This assumes the original verified, immutable source journal. It adds
    /// no independent protected Current or whole-database corruption oracle.
    /// Source and destination restored together, external edits without source
    /// receipts, and report delivery after this check remain separate gates.
    /// No event is appended and no dispatch, retirement or retry is authorized.
    pub async fn validate_notes_document_read(
        &self,
        document: &NotesDocumentState,
    ) -> Result<(), ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        document
            .target
            .validate()
            .map_err(ProductionWriterError::Invalid)?;
        Sha256Digest::parse(document.text_sha256.as_str())
            .map_err(ProductionWriterError::Invalid)?;
        self.verify_authority().await?;
        self.lease.verify_current().await?;
        let mut transaction = self
            .store
            .begin_checkpoint_barrier()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        let checked = async {
            self.lease.require_current_transaction(&mut transaction).await?;
            let mut cursor = (String::new(), 0_i64);
            let mut seen = BTreeMap::new();
            let mut count = 0_usize;
            loop {
                let rows: Vec<(String, i64, String, String, String, String, String)> = sqlx::query_as(
                    "SELECT e.lease_id, e.event_sequence, e.occurrence_key,
                            b.payload_json, b.payload_sha256, e.payload_json, e.payload_sha256
                     FROM cognitive_local_events e
                     JOIN cognitive_operation_ledger o
                       ON o.lease_id = e.lease_id AND o.operation_id = e.occurrence_key
                     JOIN cognitive_local_outbox b
                       ON b.lease_id = e.lease_id AND b.occurrence_key = e.occurrence_key
                     WHERE o.destination_id = ? AND b.topic IN (?, ?)
                       AND e.event_kind = 'reconcile_committed'
                       AND (e.lease_id > ? OR (e.lease_id = ? AND e.event_sequence > ?))
                     ORDER BY e.lease_id, e.event_sequence LIMIT ?",
                )
                .bind(document.target.destination_id())
                .bind(crate::NOTES_REPLACE_TOPIC_V1)
                .bind(crate::NOTES_FENCE_TOPIC_V1)
                .bind(&cursor.0).bind(&cursor.0).bind(cursor.1).bind(PAGE_SIZE)
                .fetch_all(&mut *transaction).await
                .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
                if rows.is_empty() {
                    break;
                }
                count += rows.len();
                if count > MAX_READ_FLOOR_ROWS {
                    return Err(ProductionWriterError::Durability(
                        "Notes read floor history exceeds its bounded scan; observation unavailable".into(),
                    ));
                }
                for (lease, sequence, operation, payload, payload_digest, receipt, receipt_digest) in rows {
                    cursor = (lease, sequence);
                    if Sha256Digest::for_bytes(payload.as_bytes()).as_str() != payload_digest
                        || Sha256Digest::for_bytes(receipt.as_bytes()).as_str() != receipt_digest
                    {
                        return Err(ProductionWriterError::Invalid(
                            "Notes read floor original request or receipt digest mismatch".into(),
                        ));
                    }
                    let request: serde_json::Value = serde_json::from_str(&payload)
                        .map_err(|error| ProductionWriterError::Invalid(error.to_string()))?;
                    if request["operation_id"].as_str() != Some(operation.as_str()) {
                        return Err(ProductionWriterError::Invalid(
                            "Notes read floor operation differs from its original journal".into(),
                        ));
                    }
                    let terminal = NotesTerminalReceipt::from_json(&payload, &receipt)
                        .map_err(ProductionWriterError::Invalid)?;
                    if terminal.outcome() != LocalReconcileOutcome::Committed {
                        return Err(ProductionWriterError::Invalid(
                            "Notes read floor event is not an applied or fenced result".into(),
                        ));
                    }
                    let (target, revision, text_sha256) = terminal.document_state()
                        .map_err(ProductionWriterError::Invalid)?;
                    if target != document.target {
                        return Err(ProductionWriterError::Invalid(
                            "Notes read floor target differs from its original destination".into(),
                        ));
                    }
                    if seen.insert(revision, text_sha256.clone()).is_some_and(|old| old != text_sha256) {
                        return Err(ProductionWriterError::Invalid(
                            "original Notes history contains conflicting content at one revision".into(),
                        ));
                    }
                }
            }
            if let Some((&revision, text_sha256)) = seen.last_key_value()
                && (document.revision < revision
                    || (document.revision == revision && document.text_sha256 != *text_sha256))
            {
                return Err(ProductionWriterError::Invalid(
                    "Notes document regresses the original owner's committed read floor".into(),
                ));
            }
            self.lease.require_current_transaction(&mut transaction).await?;
            Ok(())
        }.await;
        transaction
            .rollback()
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        self.verify_authority().await?;
        checked
    }
}
