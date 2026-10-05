//! consumption settlement implementation.

use super::*;

impl DurableLeaseRegistryV1 {
    pub(crate) fn settle_consumption(
        &mut self,
        operation_id: &str,
    ) -> Result<BaoSecretReceipt, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        let receipt = current
            .receipt
            .clone()
            .ok_or(LeaseRegistryErrorV1::CorruptState)?;
        if current.state == BaoConsumptionStateV1::Succeeded {
            return Ok(receipt);
        }
        if current.state != BaoConsumptionStateV1::ConsumerSucceeded
            || !terminal_matches(
                &current,
                TERMINAL_SUCCESS,
                None,
                receipt_digest(&receipt)?,
                current.amount,
            )
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        next.consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
            .state = BaoConsumptionStateV1::Succeeded;
        self.commit(next, 0)?;
        Ok(receipt)
    }

    pub(crate) fn settle_consumption_failure(
        &mut self,
        operation_id: &str,
    ) -> Result<BaoConsumptionOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if current.state == BaoConsumptionStateV1::Failed {
            return Ok(current);
        }
        if !matches!(
            current.state,
            BaoConsumptionStateV1::ProviderFailed | BaoConsumptionStateV1::ConsumerNotApplied
        ) || !has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        next.consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
            .state = BaoConsumptionStateV1::Failed;
        self.commit(next, 0)?;
        self.consumption_result(operation_id)
    }
}
