//! sqlite runtime settlement implementation.

use super::*;

pub(super) async fn settle_sqlite_terminal_row<E: BaoAuthBusEvidenceProvider>(
    host: &BaoFinalUseHost,
    authbus: &AuthBusAuthorityHost,
    owner: &SqliteBaoOwnerV1,
    row: SqliteConsumptionRecordV1,
    reservation: QuotaReservation,
    evidence: &mut E,
) -> Result<BaoSecretReceipt, BaoProductHostError> {
    let terminal = Digest32::from_array(row.operation.terminal_evidence_sha256.ok_or(
        BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
            "terminal evidence is missing",
        )),
    )?);
    let (status, observed_cost, success) = match row.operation.state {
        BaoConsumptionStateV1::ConsumerSucceeded => {
            (SettlementStatus::Completed, row.operation.amount, true)
        }
        BaoConsumptionStateV1::ProviderFailed => (
            SettlementStatus::Completed,
            row.operation
                .terminal_observed_cost
                .ok_or(BaoProductHostError::SqliteStore(
                    SqliteBaoOwnerErrorV1::CorruptState("provider terminal cost is missing"),
                ))?,
            false,
        ),
        BaoConsumptionStateV1::ConsumerNotApplied => (SettlementStatus::Rejected, 0, false),
        _ => {
            return Err(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::InvalidTransition,
            ));
        }
    };
    let expected_terminal_state = match status {
        SettlementStatus::Completed => ReservationState::Settled,
        SettlementStatus::Rejected => ReservationState::Released,
    };
    if matches!(
        reservation.state,
        ReservationState::Settled | ReservationState::Released
    ) {
        if reservation.state != expected_terminal_state
            || reservation.terminal_evidence != Some(terminal)
            || reservation.observed_cost != Some(observed_cost)
        {
            return Err(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::ObservationMismatch,
            ));
        }
    } else {
        if !matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) {
            return Err(BaoProductHostError::OutcomePending(Box::new(row.operation)));
        }
        crate::https_consumer::settle_observed(
            authbus,
            evidence,
            &reservation,
            status,
            observed_cost,
            terminal,
            if success {
                row.operation.receipt.clone()
            } else {
                None
            },
        )
        .await
        .map_err(BaoProductHostError::AuthBus)?;
    }
    let terminal_row = owner
        .settle_consumption_terminal(
            &row.operation.operation_id,
            row.revision,
            host.product_now()?,
        )
        .await
        .map_err(BaoProductHostError::SqliteStore)?;
    if success {
        terminal_row
            .operation
            .receipt
            .ok_or(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::CorruptState("successful operation has no receipt"),
            ))
    } else {
        Err(BaoProductHostError::TerminalFailure(Box::new(
            terminal_row.operation,
        )))
    }
}

pub(super) fn historical_result(
    operation: BaoConsumptionOperationV1,
) -> Option<Result<BaoSecretReceipt, BaoProductHostError>> {
    match operation.state.recovery_action() {
        BaoConsumptionRecoveryActionV1::ReturnHistoricalSuccess => {
            Some(operation.receipt.ok_or(BaoProductHostError::SqliteStore(
                SqliteBaoOwnerErrorV1::CorruptState("successful operation has no receipt"),
            )))
        }
        BaoConsumptionRecoveryActionV1::ReturnHistoricalFailure => Some(Err(
            BaoProductHostError::TerminalFailure(Box::new(operation)),
        )),
        BaoConsumptionRecoveryActionV1::SealOrBindReservation
        | BaoConsumptionRecoveryActionV1::CancelOrExpireReservation
        | BaoConsumptionRecoveryActionV1::BindLegacyReservation
        | BaoConsumptionRecoveryActionV1::ObserveOriginalOutcome
        | BaoConsumptionRecoveryActionV1::SettleTerminalEvidence => None,
    }
}

pub(super) fn historical_result_or_pending(
    operation: BaoConsumptionOperationV1,
) -> Result<BaoSecretReceipt, BaoProductHostError> {
    historical_result(operation.clone())
        .unwrap_or_else(|| Err(BaoProductHostError::OutcomePending(Box::new(operation))))
}

pub(super) async fn release_execution_claim_if_pending(
    owner: &SqliteBaoOwnerV1,
    claim: &SqliteReconciliationClaimV1,
) {
    if let Ok(record) = owner
        .consumption_result(&claim.record.operation.operation_id)
        .await
        && !record.operation.state.is_terminal()
    {
        let _ = owner
            .release_reconciliation_claim(
                &claim.worker_id,
                &claim.record.operation.operation_id,
                claim.claim_generation,
            )
            .await;
    }
}

pub(super) fn validate_sqlite_reservation(
    row: &BaoConsumptionOperationV1,
    reservation: &QuotaReservation,
) -> Result<(), BaoProductHostError> {
    if reservation.operation_id.as_str() != row.operation_id
        || reservation.amount != row.amount
        || reservation.effect_digest.into_array() != row.effect_sha256
    {
        return Err(BaoProductHostError::SqliteStore(
            SqliteBaoOwnerErrorV1::ObservationMismatch,
        ));
    }
    Ok(())
}

pub(super) fn reservation_terminal_abort_code(
    state: ReservationState,
) -> Result<&'static str, BaoProductHostError> {
    match state {
        ReservationState::Expired => Ok("reservation_expired"),
        ReservationState::Cancelled => Ok("reservation_cancelled"),
        ReservationState::Released => Ok("reservation_released"),
        ReservationState::Held
        | ReservationState::DispatchAttempted
        | ReservationState::Indeterminate
        | ReservationState::Settled => Err(BaoProductHostError::SqliteStore(
            SqliteBaoOwnerErrorV1::ObservationMismatch,
        )),
    }
}

pub(super) fn reservation_evidence(label: &[u8], reservation: &QuotaReservation) -> [u8; 32] {
    let mut bytes = Vec::with_capacity(256);
    push_evidence_part(&mut bytes, label);
    push_evidence_part(&mut bytes, reservation.reservation_id.as_str().as_bytes());
    push_evidence_part(&mut bytes, reservation.operation_id.as_str().as_bytes());
    push_evidence_part(&mut bytes, reservation.effect_digest.as_array());
    push_evidence_part(&mut bytes, &reservation.revision.to_be_bytes());
    push_evidence_part(&mut bytes, format!("{:?}", reservation.state).as_bytes());
    Digest32::of_bytes(&bytes).into_array()
}

pub(super) fn push_evidence_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

pub(super) fn clock_now_for_saga(clock: &Arc<dyn AuthorityClock>) -> Result<u64, BaoAuthBusError> {
    clock
        .now_unix_ms()
        .map_err(|_| BaoAuthBusError::Evidence("product authority clock unavailable"))
}

pub(super) fn recovery_error_digest(class: BaoProductErrorClassV1) -> [u8; 32] {
    Digest32::of_bytes(format!("hepta.bao.recovery-error.v1:{class:?}").as_bytes()).into_array()
}

pub(super) fn retry_delay_ms(base: u64, maximum: u64, attempt_count: u64) -> u64 {
    let exponent = u32::try_from(attempt_count.min(31)).unwrap_or(31);
    base.saturating_mul(1_u64.checked_shl(exponent).unwrap_or(u64::MAX))
        .min(maximum)
}

pub(super) fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}
