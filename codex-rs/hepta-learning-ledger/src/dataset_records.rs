//! Shared active-record resolution for the original writer and physical reader.
//! The caller validates the receipt before entering these pure helpers. Neither
//! a receipt's structural validity nor a resolved record supplies authorization.

use crate::DatasetSnapshotReceiptV3;
use crate::LearningLedger;
use crate::LedgerRecord;
use crate::ProductionLedgerError;

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
