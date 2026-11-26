//! consumption observation implementation.

use super::*;

impl DurableLeaseRegistryV1 {
    pub(crate) fn observe_consumption(
        &mut self,
        operation_id: &str,
        succeeded: bool,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if !succeeded {
            return self.mark_consumption_indeterminate(operation_id);
        }
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        let receipt = current
            .receipt
            .as_ref()
            .ok_or(LeaseRegistryErrorV1::InvalidTransition)?;
        let terminal = receipt_digest(receipt)?;
        if matches!(
            current.state,
            BaoConsumptionStateV1::ConsumerSucceeded | BaoConsumptionStateV1::Succeeded
        ) && terminal_matches(&current, TERMINAL_SUCCESS, None, terminal, current.amount)
        {
            return Ok(());
        }
        if !matches!(
            current.state,
            BaoConsumptionStateV1::DeliveryPrepared | BaoConsumptionStateV1::Indeterminate
        ) || has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        set_terminal(row, TERMINAL_SUCCESS, None, terminal, row.amount);
        row.state = BaoConsumptionStateV1::ConsumerSucceeded;
        self.commit(next, 0)
    }

    pub(crate) fn observe_consumption_not_applied(
        &mut self,
        operation_id: &str,
        evidence_sha256: [u8; 32],
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if evidence_sha256 == [0; 32] {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if matches!(
            current.state,
            BaoConsumptionStateV1::ConsumerNotApplied | BaoConsumptionStateV1::Failed
        ) && terminal_matches(
            &current,
            TERMINAL_CONSUMER_NOT_APPLIED,
            Some("consumer_not_applied"),
            evidence_sha256,
            0,
        ) {
            return Ok(());
        }
        if !matches!(
            current.state,
            BaoConsumptionStateV1::DeliveryPrepared | BaoConsumptionStateV1::Indeterminate
        ) || current.receipt.is_none()
            || has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        set_terminal(
            row,
            TERMINAL_CONSUMER_NOT_APPLIED,
            Some("consumer_not_applied"),
            evidence_sha256,
            0,
        );
        row.state = BaoConsumptionStateV1::ConsumerNotApplied;
        self.commit(next, 0)
    }

    pub(crate) fn mark_consumption_indeterminate(
        &mut self,
        operation_id: &str,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if current.state == BaoConsumptionStateV1::Indeterminate {
            return Ok(());
        }
        if !matches!(
            current.state,
            BaoConsumptionStateV1::DispatchFenced | BaoConsumptionStateV1::DeliveryPrepared
        ) || current.reservation_id.is_none()
            || has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        next.consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?
            .state = BaoConsumptionStateV1::Indeterminate;
        self.commit(next, 0)
    }

    pub(crate) fn record_provider_failure(
        &mut self,
        operation_id: &str,
        error_code: &str,
        evidence_sha256: [u8; 32],
        observed_cost: u64,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if !provider_error_code(error_code) || evidence_sha256 == [0; 32] || observed_cost == 0 {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if matches!(
            current.state,
            BaoConsumptionStateV1::ProviderFailed | BaoConsumptionStateV1::Failed
        ) && terminal_matches(
            &current,
            TERMINAL_PROVIDER_FAILURE,
            Some(error_code),
            evidence_sha256,
            observed_cost,
        ) {
            return Ok(());
        }
        if current.state != BaoConsumptionStateV1::DispatchFenced
            || current.receipt.is_some()
            || has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        set_terminal(
            row,
            TERMINAL_PROVIDER_FAILURE,
            Some(error_code),
            evidence_sha256,
            observed_cost,
        );
        row.state = BaoConsumptionStateV1::ProviderFailed;
        self.commit(next, 0)
    }

    pub(crate) fn record_consumption_abort(
        &mut self,
        operation_id: &str,
        before_dispatch: bool,
        code: &str,
        evidence_sha256: [u8; 32],
    ) -> Result<BaoConsumptionOperationV1, LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        if evidence_sha256 == [0; 32]
            || !matches!(
                code,
                "no_reservation"
                    | "reservation_cancelled"
                    | "reservation_released"
                    | "reservation_expired"
            )
        {
            return Err(LeaseRegistryErrorV1::InvalidInput);
        }
        let kind = if before_dispatch {
            TERMINAL_ABORTED_BEFORE_DISPATCH
        } else {
            TERMINAL_ABORTED_BEFORE_RESERVATION
        };
        let current = self
            .state
            .consumptions
            .get(operation_id)
            .cloned()
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        if current.state == BaoConsumptionStateV1::Failed
            && terminal_matches(&current, kind, Some(code), evidence_sha256, 0)
        {
            return Ok(current);
        }
        let valid = if before_dispatch {
            matches!(
                current.state,
                BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
            ) && current.reservation_id.is_some()
        } else {
            matches!(
                current.state,
                BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
            ) && current.reservation_id.is_none()
        };
        if !valid || current.receipt.is_some() || has_terminal(&current) {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        let row = next
            .consumptions
            .get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        set_terminal(row, kind, Some(code), evidence_sha256, 0);
        row.state = BaoConsumptionStateV1::Failed;
        self.commit(next, 0)?;
        self.consumption_result(operation_id)
    }
}
