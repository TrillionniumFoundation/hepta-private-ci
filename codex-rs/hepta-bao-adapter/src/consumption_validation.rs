//! consumption validation implementation.

use super::*;

pub(super) fn is_default<T>(value: &T) -> bool
where
    T: Default + PartialEq,
{
    value == &T::default()
}

pub(in super::super) fn migrate_schema_three_consumptions(
    rows: &mut BTreeMap<String, BaoConsumptionOperationV1>,
    migration_revision: u64,
) -> Result<(), LeaseRegistryErrorV1> {
    for row in rows.values_mut() {
        if matches!(
            row.state,
            BaoConsumptionStateV1::ConsumerSucceeded | BaoConsumptionStateV1::Succeeded
        ) && !has_terminal(row)
        {
            let receipt = row
                .receipt
                .as_ref()
                .ok_or(LeaseRegistryErrorV1::CorruptState)?;
            validate_receipt_for_request(receipt, Some(row.request_sha256))?;
            let terminal = receipt_digest(receipt)?;
            let amount = row.amount;
            set_terminal(row, TERMINAL_SUCCESS, None, terminal, amount);
        }
        if row.created_revision == 0 {
            row.created_revision = migration_revision.max(1);
        }
        if row.updated_revision == 0 {
            row.updated_revision = row.created_revision;
        }
        validate_consumption(row)?;
    }
    Ok(())
}

pub(super) fn set_terminal(
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

pub(super) fn has_terminal(row: &BaoConsumptionOperationV1) -> bool {
    row.terminal_kind.is_some()
        || row.terminal_code.is_some()
        || row.terminal_evidence_sha256.is_some()
        || row.terminal_observed_cost.is_some()
}

pub(super) fn terminal_matches(
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

pub(super) fn same_consumption_identity(
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

pub(super) fn receipt_digest(receipt: &BaoSecretReceipt) -> Result<[u8; 32], LeaseRegistryErrorV1> {
    let encoded = serde_json::to_vec(receipt).map_err(|_| LeaseRegistryErrorV1::InvalidInput)?;
    Ok(Digest32::of_bytes(&encoded).into_array())
}

pub(super) fn provider_error_code(value: &str) -> bool {
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

pub(super) fn validate_receipt_for_request(
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

pub(in super::super) fn validate_consumption(
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
                && row
                    .terminal_evidence_sha256
                    .is_some_and(|value| value != [0; 32])
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
                && row
                    .terminal_evidence_sha256
                    .is_some_and(|value| value != [0; 32])
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

pub(super) fn validate_failed_terminal(row: &BaoConsumptionOperationV1) -> bool {
    let evidence = row
        .terminal_evidence_sha256
        .is_some_and(|value| value != [0; 32]);
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
                    Some("reservation_cancelled" | "reservation_released" | "reservation_expired")
                )
                && evidence
                && row.terminal_observed_cost == Some(0)
        }
        _ => false,
    }
}
