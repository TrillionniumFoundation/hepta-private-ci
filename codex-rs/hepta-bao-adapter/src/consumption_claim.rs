//! consumption claim implementation.

use super::*;

impl DurableLeaseRegistryV1 {
    /// Historical metadata only: this does not re-authorize delivery or replay.
    pub fn consumption_result(
        &self,
        operation_id: &str,
    ) -> Result<BaoConsumptionOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        self.state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)
    }

    pub(crate) fn claim_consumption(
        &mut self,
        operation: BaoConsumptionOperationV1,
    ) -> Result<Option<BaoConsumptionOperationV1>, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        validate_consumption(&operation)?;
        if operation.state != BaoConsumptionStateV1::Claimed
            || operation.reservation_id.is_some()
            || operation.receipt.is_some()
            || has_terminal(&operation)
        {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        if self.state.operations.contains_key(&operation.operation_id) {
            return Err(LeaseRegistryErrorV1::OperationConflict);
        }
        if let Some(existing) = self.state.consumptions.get(&operation.operation_id) {
            if !same_consumption_identity(existing, &operation) {
                return Err(LeaseRegistryErrorV1::OperationConflict);
            }
            return Ok(Some(existing.clone()));
        }
        let mut next = self.state.clone();
        if next.consumptions.len() >= MAX_RECORDS {
            return Err(LeaseRegistryErrorV1::CapacityExceeded);
        }
        next.consumptions
            .insert(operation.operation_id.clone(), operation);
        self.commit(next, CONTROL_RESERVE_BYTES)?;
        Ok(None)
    }

    pub(crate) fn mark_consumption_reserved(
        &mut self,
        operation_id: &str,
        reservation_id: String,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if !identifier(&reservation_id) {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if current
            .reservation_id
            .as_ref()
            .is_some_and(|id| *id != reservation_id)
        {
            return Err(LeaseRegistryErrorV1::OperationConflict);
        }
        if current.reservation_id.as_deref() == Some(reservation_id.as_str())
            && matches!(
                current.state,
                BaoConsumptionStateV1::Reserved
                    | BaoConsumptionStateV1::DispatchFenced
                    | BaoConsumptionStateV1::DeliveryPrepared
                    | BaoConsumptionStateV1::ConsumerSucceeded
                    | BaoConsumptionStateV1::ConsumerNotApplied
                    | BaoConsumptionStateV1::ProviderFailed
                    | BaoConsumptionStateV1::Indeterminate
                    | BaoConsumptionStateV1::Succeeded
                    | BaoConsumptionStateV1::Failed
            )
        {
            return Ok(());
        }
        if !matches!(
            current.state,
            BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
        ) || current.receipt.is_some()
            || has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        row.reservation_id = Some(reservation_id);
        row.state = BaoConsumptionStateV1::Reserved;
        self.commit(next, 0)
    }

    pub(crate) fn mark_consumption_dispatch_fenced(
        &mut self,
        operation_id: &str,
        reservation_id: &str,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if current.reservation_id.as_deref() != Some(reservation_id) {
            return Err(LeaseRegistryErrorV1::ObservationMismatch);
        }
        if matches!(
            current.state,
            BaoConsumptionStateV1::DispatchFenced
                | BaoConsumptionStateV1::DeliveryPrepared
                | BaoConsumptionStateV1::ConsumerSucceeded
                | BaoConsumptionStateV1::ConsumerNotApplied
                | BaoConsumptionStateV1::ProviderFailed
                | BaoConsumptionStateV1::Indeterminate
                | BaoConsumptionStateV1::Succeeded
                | BaoConsumptionStateV1::Failed
        ) {
            return Ok(());
        }
        if !matches!(
            current.state,
            BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
        ) || current.receipt.is_some()
            || has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        next.consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
            .state = BaoConsumptionStateV1::DispatchFenced;
        self.commit(next, 0)
    }

    pub(crate) fn enter_consumption(
        &mut self,
        operation_id: &str,
        receipt: BaoSecretReceipt,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        validate_receipt_for_request(&receipt, None)?;
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if current.receipt.as_ref() == Some(&receipt)
            && matches!(
                current.state,
                BaoConsumptionStateV1::DeliveryPrepared
                    | BaoConsumptionStateV1::ConsumerSucceeded
                    | BaoConsumptionStateV1::ConsumerNotApplied
                    | BaoConsumptionStateV1::Indeterminate
                    | BaoConsumptionStateV1::Succeeded
                    | BaoConsumptionStateV1::Failed
            )
        {
            return Ok(());
        }
        if current.state != BaoConsumptionStateV1::DispatchFenced
            || current.reservation_id.is_none()
            || current.receipt.is_some()
            || has_terminal(&current)
            || receipt.request_sha256 != current.request_sha256
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        row.receipt = Some(receipt);
        row.state = BaoConsumptionStateV1::DeliveryPrepared;
        self.commit(next, 0)
    }
}
