//! Shared active-record resolution for the original writer and physical reader.
//! The caller validates the receipt before entering these pure helpers. Neither
//! a receipt's structural validity nor a resolved record supplies authorization.

use crate::DatasetSnapshotReceiptV3;
use crate::LearningLedger;
use crate::LedgerRecord;
use crate::LedgerSnapshot;
use crate::ProductionLedgerError;
use crate::verify_dataset_snapshot_receipt_v3;

impl LedgerSnapshot {
    /// Pure data lookup through a freshly replayed index. Only the actual owner
    /// can establish this snapshot's current source and authorization; callers
    /// must verify the Evaluator signature separately before materializing it.
    pub fn read_dataset_records(
        &self,
        receipt: &DatasetSnapshotReceiptV3,
        now: u64,
    ) -> Result<Vec<LedgerRecord>, ProductionLedgerError> {
        if self.records().len() > 4096 || receipt.snapshot.source_record_digests.len() > 4096 {
            return Err(ProductionLedgerError::Binding(
                "dataset materialization bound",
            ));
        }
        verify_dataset_snapshot_receipt_v3(receipt, now)?;
        let ledger = LearningLedger::from_snapshot(self.clone())?;
        LearningLedger::require_active_dataset_sources(&ledger, receipt)?;
        Ok(
            LearningLedger::resolve_active_dataset_records(&ledger, receipt)?
                .into_iter()
                .cloned()
                .collect(),
        )
    }
}

impl LearningLedger {
    pub(crate) fn require_active_dataset_sources(
        &self,
        receipt: &DatasetSnapshotReceiptV3,
    ) -> Result<(), ProductionLedgerError> {
        for digest in &receipt.snapshot.source_record_digests {
            if self.active_record_by_digest(digest)?.is_none() {
                return Err(ProductionLedgerError::Binding(
                    "dataset source revoked, corrected or unavailable",
                ));
            }
        }
        Ok(())
    }

    pub(crate) fn resolve_active_dataset_records(
        &self,
        receipt: &DatasetSnapshotReceiptV3,
    ) -> Result<Vec<&LedgerRecord>, ProductionLedgerError> {
        let mut records = receipt
            .snapshot
            .source_record_digests
            .iter()
            .map(|digest| {
                self.active_record_by_digest(digest)?
                    .ok_or(ProductionLedgerError::Binding("dataset source unavailable"))
            })
            .collect::<Result<Vec<_>, ProductionLedgerError>>()?;
        records.sort_unstable_by_key(|record| record.sequence);
        Ok(records)
    }
}
