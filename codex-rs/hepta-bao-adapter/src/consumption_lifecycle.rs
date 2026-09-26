//! Metadata-only consumer operation saga in the existing lease writer.
//!
//! The state names intentionally distinguish durable identity, quota reservation
//! and the irreversible AuthBus dispatch fence. No state implies a later step.
use super::*;
use codex_hepta_types::Digest32;

const TERMINAL_SUCCESS: &str = "success";
const TERMINAL_PROVIDER_FAILURE: &str = "provider_failure";
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

    pub(crate) fn record_consumption_abort(
        &mut self,
        operation_id: &str,
        before_dispatch: bool,
        code: &str,
        evidence_sha256: [u8; 32],
    ) -> Result<BaoConsumptionOperationV1, LeaseRegistryErrorV1> {
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

fn set_terminal(
    row: &mut BaoConsumptionOperationV1,
    kind: &str,
    code: Option<&str>,
    evidence_sha256: [u8; 32],
    observed_cost: u64,
) {
    row.terminal_kind = Some(kind.to_owned());
    row.terminal_code = code.map(str::to_owned);
    row.terminal_evidence_sha256 = Some(evidence_sha256);
    row.terminal_observed_cost = Some(observed_cost);
}

fn has_terminal(row: &BaoConsumptionOperationV1) -> bool {
    row.terminal_kind.is_some()
        || row.terminal_code.is_some()
        || row.terminal_evidence_sha256.is_some()
        || row.terminal_observed_cost.is_some()
}

fn terminal_matches(
    row: &BaoConsumptionOperationV1,
    kind: &str,
    code: Option<&str>,
    evidence_sha256: [u8; 32],
    observed_cost: u64,
) -> bool {
    row.terminal_kind.as_deref() == Some(kind)
        && row.terminal_code.as_deref() == code
        && row.terminal_evidence_sha256 == Some(evidence_sha256)
        && row.terminal_observed_cost == Some(observed_cost)
}

fn same_consumption_identity(
    left: &BaoConsumptionOperationV1,
    right: &BaoConsumptionOperationV1,
) -> bool {
    left.operation_id == right.operation_id
        && left.semantic_sha256 == right.semantic_sha256
        && left.effect_sha256 == right.effect_sha256
        && left.request_sha256 == right.request_sha256
        && left.consumer_id == right.consumer_id
        && left.consumer_configuration_sha256 == right.consumer_configuration_sha256
        && left.amount == right.amount
}

fn receipt_digest(receipt: &BaoSecretReceipt) -> Result<[u8; 32], LeaseRegistryErrorV1> {
    let encoded = serde_json::to_vec(receipt).map_err(|_| LeaseRegistryErrorV1::InvalidInput)?;
    Ok(Digest32::of_bytes(&encoded).into_array())
}

fn provider_error_code(value: &str) -> bool {
    matches!(
        value,
        "provider_denied"
            | "provider_unavailable"
            | "not_found"
            | "response_too_large"
            | "invalid_response"
            | "version_mismatch"
            | "secret_digest_mismatch"
    )
}

fn validate_receipt_for_request(
    receipt: &BaoSecretReceipt,
    request_sha256: Option<[u8; 32]>,
) -> Result<(), LeaseRegistryErrorV1> {
    if request_sha256.is_some_and(|request| receipt.request_sha256 != request)
        || receipt.request_sha256 == [0; 32]
        || receipt.version == 0
        || receipt.secret_bytes > 1024 * 1024
        || receipt.response_sha256 == [0; 32]
        || receipt.secret_sha256 == [0; 32]
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    Ok(())
}

pub(super) fn validate_consumption(
    row: &BaoConsumptionOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    if !identifier(&row.operation_id)
        || !identifier(&row.consumer_id)
        || row.amount == 0
        || [
            row.semantic_sha256,
            row.effect_sha256,
            row.request_sha256,
            row.consumer_configuration_sha256,
        ]
        .contains(&[0; 32])
        || row
            .reservation_id
            .as_deref()
            .is_some_and(|id| !identifier(id))
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    if let Some(receipt) = &row.receipt {
        validate_receipt_for_request(receipt, Some(row.request_sha256))?;
    }

    let no_terminal = !has_terminal(row);
    let valid = match row.state {
        BaoConsumptionStateV1::Claimed => {
            row.reservation_id.is_none() && row.receipt.is_none() && no_terminal
        }
        BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchFenced => {
            row.reservation_id.is_some() && row.receipt.is_none() && no_terminal
        }
        BaoConsumptionStateV1::DeliveryPrepared => {
            row.reservation_id.is_some() && row.receipt.is_some() && no_terminal
        }
        BaoConsumptionStateV1::Indeterminate => row.reservation_id.is_some() && no_terminal,
        BaoConsumptionStateV1::ConsumerSucceeded | BaoConsumptionStateV1::Succeeded => {
            row.reservation_id.is_some()
                && row.receipt.is_some()
                && terminal_matches(
                    row,
                    TERMINAL_SUCCESS,
                    None,
                    receipt_digest(
                        row.receipt
                            .as_ref()
                            .ok_or(LeaseRegistryErrorV1::CorruptState)?,
                    )?,
                    row.amount,
                )
        }
        BaoConsumptionStateV1::ConsumerNotApplied => {
            row.reservation_id.is_some()
                && row.receipt.is_some()
                && row.terminal_kind.as_deref() == Some(TERMINAL_CONSUMER_NOT_APPLIED)
                && row.terminal_code.as_deref() == Some("consumer_not_applied")
                && row.terminal_evidence_sha256.is_some_and(|value| value != [0; 32])
                && row.terminal_observed_cost == Some(0)
        }
        BaoConsumptionStateV1::ProviderFailed => {
            row.reservation_id.is_some()
                && row.receipt.is_none()
                && row.terminal_kind.as_deref() == Some(TERMINAL_PROVIDER_FAILURE)
                && row
                    .terminal_code
                    .as_deref()
                    .is_some_and(provider_error_code)
                && row.terminal_evidence_sha256.is_some_and(|value| value != [0; 32])
                && row
                    .terminal_observed_cost
                    .is_some_and(|cost| cost != 0 && cost <= row.amount)
        }
        BaoConsumptionStateV1::Failed => validate_failed_terminal(row),
        BaoConsumptionStateV1::DispatchAttempted => row.receipt.is_none() && no_terminal,
    };
    if valid {
        Ok(())
    } else {
        Err(LeaseRegistryErrorV1::CorruptState)
    }
}

fn validate_failed_terminal(row: &BaoConsumptionOperationV1) -> bool {
    let evidence = row.terminal_evidence_sha256.is_some_and(|value| value != [0; 32]);
    match row.terminal_kind.as_deref() {
        Some(TERMINAL_PROVIDER_FAILURE) => {
            row.reservation_id.is_some()
                && row.receipt.is_none()
                && row
                    .terminal_code
                    .as_deref()
                    .is_some_and(provider_error_code)
                && evidence
                && row
                    .terminal_observed_cost
                    .is_some_and(|cost| cost != 0 && cost <= row.amount)
        }
        Some(TERMINAL_CONSUMER_NOT_APPLIED) => {
            row.reservation_id.is_some()
                && row.receipt.is_some()
                && row.terminal_code.as_deref() == Some("consumer_not_applied")
                && evidence
                && row.terminal_observed_cost == Some(0)
        }
        Some(TERMINAL_ABORTED_BEFORE_RESERVATION) => {
            row.reservation_id.is_none()
                && row.receipt.is_none()
                && row.terminal_code.as_deref() == Some("no_reservation")
                && evidence
                && row.terminal_observed_cost == Some(0)
        }
        Some(TERMINAL_ABORTED_BEFORE_DISPATCH) => {
            row.reservation_id.is_some()
                && row.receipt.is_none()
                && matches!(
                    row.terminal_code.as_deref(),
                    Some(
                        "reservation_cancelled"
                            | "reservation_released"
                            | "reservation_expired"
                    )
                )
                && evidence
                && row.terminal_observed_cost == Some(0)
        }
        _ => false,
    }
}

#[cfg(all(test, unix))]
#[path = "consumption_lifecycle_saga_tests.rs"]
mod saga_tests;
