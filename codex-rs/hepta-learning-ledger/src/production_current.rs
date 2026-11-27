//! Read-only CURRENT from the original durable ledger and witness handles.

use super::*;

impl LedgerWriter {
    /// Re-read the original durable ledger and its independent witness.
    /// Both must still contain the exact acknowledged history held by this
    /// owner. This is a bounded read, not recovery or renewed authorization.
    /// Segmented custody requires its own complete CURRENT protocol.
    pub fn read_current_durable_snapshot(
        &mut self,
    ) -> Result<LedgerSnapshot, ProductionLedgerError> {
        let ledger = match &mut self.backend {
            LedgerBackend::Durable(ledger) => ledger,
            LedgerBackend::Segmented(_) => {
                return Err(ProductionLedgerError::Binding(
                    "original durable dataset custody required",
                ));
            }
        };
        let before = self.witness.read_current_frontier()?;
        let snapshot = ledger.read_current_snapshot()?;
        let after = self.witness.read_current_frontier()?;
        if before != after || after != frontier_from_records(snapshot.records()) {
            return Err(ProductionLedgerError::Binding(
                "original dataset ledger/witness CURRENT differs",
            ));
        }
        Ok(snapshot)
    }
}
