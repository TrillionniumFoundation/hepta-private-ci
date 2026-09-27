//! Metadata-only consumer operation saga in the existing lease writer.
//!
//! The state names intentionally distinguish durable identity, quota reservation
//! and the irreversible AuthBus dispatch fence. No state implies a later step.
use super::*;
use codex_hepta_types::Digest32;

#[path = "consumption_validation.rs"]
mod validation;
use validation::{has_terminal, receipt_digest, provider_error_code,
    same_consumption_identity, set_terminal, terminal_matches, validate_receipt_for_request};
pub(super) use validation::{migrate_schema_three_consumptions, validate_consumption};


const TERMINAL_SUCCESS: &str = "success";
const TERMINAL_PROVIDER_FAILURE: &str = "provider_failure";
const TERMINAL_DELIVERY_ABORTED: &str = "delivery_aborted";
const TERMINAL_CONSUMER_NOT_APPLIED: &str = "consumer_not_applied";
const TERMINAL_ABORTED_BEFORE_RESERVATION: &str = "aborted_before_reservation";
const TERMINAL_ABORTED_BEFORE_DISPATCH: &str = "aborted_before_dispatch";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretReceipt {
    pub request_sha256: [u8; 32],
    pub response_sha256: [u8; 32],
    pub secret_sha256: [u8; 32],
    pub version: u64,
    pub secret_bytes: usize,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoConsumptionStateV1 {
    Claimed,
    Reserved,
    DispatchFenced,
    DeliveryPrepared,
    ConsumerSucceeded,
    ConsumerNotApplied,
    ProviderFailed,
    DeliveryAborted,
    Indeterminate,
    Succeeded,
    Failed,
    /// Schema-3 compatibility only. New operations never enter this state.
    DispatchAttempted,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoConsumptionOperationV1 {
    pub operation_id: String,
    pub semantic_sha256: [u8; 32],
    pub effect_sha256: [u8; 32],
    pub request_sha256: [u8; 32],
    pub consumer_id: String,
    pub consumer_configuration_sha256: [u8; 32],
    pub amount: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reservation_id: Option<String>,
    pub state: BaoConsumptionStateV1,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub receipt: Option<BaoSecretReceipt>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_kind: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_code: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_evidence_sha256: Option<[u8; 32]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub terminal_observed_cost: Option<u64>,
}

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
                    | BaoConsumptionStateV1::DeliveryAborted
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
                | BaoConsumptionStateV1::DeliveryAborted
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
        let amount = row.amount;
        set_terminal(row, TERMINAL_SUCCESS, None, terminal, amount);
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
        if !provider_error_code(error_code)
            || evidence_sha256 == [0; 32]
            || observed_cost == 0
        {
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

    /// Close a discontinued read whose durable delivery preparation never
    /// committed. This proves no consumer entry, NOT no provider request. Charge
    /// the full reserved request amount; never refund or redispatch this read.
    /// The caller must hold the operation execution/recovery exclusion guard.
    pub(crate) fn record_delivery_abort(
        &mut self,
        operation_id: &str,
    ) -> Result<(), LeaseRegistryErrorV1> {
        self.ensure_writable()?;
        let current = self.state.consumptions.get(operation_id)
            .cloned().ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        let terminal = Digest32::of_bytes(
            &serde_json::to_vec(&(
                "hepta.bao.delivery-not-prepared.v1",
                &current.operation_id, current.semantic_sha256,
                current.effect_sha256, &current.reservation_id, current.amount,
            )).map_err(|_| LeaseRegistryErrorV1::InvalidInput)?
        ).into_array();
        if matches!(current.state, BaoConsumptionStateV1::DeliveryAborted | BaoConsumptionStateV1::Failed)
            && terminal_matches(&current, TERMINAL_DELIVERY_ABORTED,
                Some("delivery_not_prepared"), terminal, current.amount)
        {
            return Ok(());
        }
        if !matches!(current.state, BaoConsumptionStateV1::DispatchFenced | BaoConsumptionStateV1::Indeterminate)
            || current.reservation_id.is_none() || current.receipt.is_some() || has_terminal(&current)
        {
            return Err(LeaseRegistryErrorV1::InvalidTransition);
        }
        let mut next = self.state.clone();
        let row = next.consumptions.get_mut(operation_id)
            .ok_or(LeaseRegistryErrorV1::OperationNotFound)?;
        let amount = row.amount;
        set_terminal(row, TERMINAL_DELIVERY_ABORTED,
            Some("delivery_not_prepared"), terminal, amount);
        row.state = BaoConsumptionStateV1::DeliveryAborted;
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
            BaoConsumptionStateV1::ProviderFailed
                | BaoConsumptionStateV1::DeliveryAborted
                | BaoConsumptionStateV1::ConsumerNotApplied
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

#[cfg(all(test, unix))]
#[path = "consumption_lifecycle_saga_tests.rs"]
mod saga_tests;
