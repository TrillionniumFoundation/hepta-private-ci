//! Storage-v3 successes lacked the current terminal tuple. Preserve the original
//! success category, identity and receipt, but require original AuthBus evidence
//! before returning a v4 terminal result. Never infer from a mutable lease row.
use super::*;

pub(in crate::lease_lifecycle) fn migrate_legacy_consumption(
    row: &mut BaoConsumptionOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    if !has_terminal(row) {
        row.state = match row.state {
            BaoConsumptionStateV1::ConsumerSucceeded => BaoConsumptionStateV1::LegacyConsumerSucceeded,
            BaoConsumptionStateV1::Succeeded => BaoConsumptionStateV1::LegacySucceeded,
            other => other,
        };
    }
    // Partially populated or inconsistent terminal tuples are corruption, not
    // evidence that migration may fill the missing facts.
    validate_consumption(row)
}

impl DurableLeaseRegistryV1 {
    /// Called only after the host verifies or settles the original reservation.
    pub(crate) fn confirm_legacy_consumption(
        &mut self,
        operation_id: &str,
        terminal: [u8; 32],
    ) -> Result<BaoSecretReceipt, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self.consumption_result(operation_id)?;
        let receipt = current.receipt.clone().ok_or(LeaseRegistryErrorV1::CorruptState)?;
        if current.state.phase() != BaoConsumptionPhase::LegacyRequalification
            || receipt_digest(&receipt)? != terminal
        {
            return Err(LeaseRegistryErrorV1::ObservationMismatch);
        }
        let mut next = self.state.clone();
        let row = next.consumptions.get_mut(operation_id).ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        set_terminal(row, TERMINAL_SUCCESS, None, terminal, row.amount);
        row.state = BaoConsumptionStateV1::Succeeded;
        self.commit(next, 0)?;
        Ok(receipt)
    }
}
