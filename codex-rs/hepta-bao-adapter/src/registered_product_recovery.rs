//! Observer-only recovery of the original consumption and AuthBus reservation.
use super::*;

impl BaoFinalUseHost {
    /// Reconcile the original consumer and AuthBus operation identity. This
    /// method never fetches a secret and never invokes the consumer effect.
    pub async fn reconcile_consumption<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        operation_id: &str,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let _execution = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_execution(operation_id)
            .map_err(BaoProductHostError::Store)?;
        let mut row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        if row.state == BaoConsumptionStateV1::Succeeded {
            return row.receipt.ok_or(BaoProductHostError::Store(
                LeaseRegistryErrorV1::CorruptState,
            ));
        }
        if row.state == BaoConsumptionStateV1::Failed {
            return Err(BaoProductHostError::TerminalFailure(row));
        }
        let registration = self
            .consumers
            .get(&row.consumer_id)
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        if registration.configuration_sha256 != Some(row.consumer_configuration_sha256) {
            return Err(BaoProductHostError::ConsumerProfileRequired);
        }
        let stable_operation = StableId::new(operation_id.to_owned())
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState))?;
        let reservation = match row.reservation_id.as_deref() {
            Some(value) => {
                let reservation_id = StableId::new(value.to_owned()).map_err(|_| {
                    BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState)
                })?;
                Some(
                    authbus
                        .reservation(&reservation_id)
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?,
                )
            }
            None => {
                let time = authbus
                    .observe_trusted_time_attestation(
                        &evidence.trusted_time().map_err(BaoProductHostError::AuthBus)?,
                    )
                    .await
                    .map_err(|error| BaoProductHostError::AuthBus(error.into()))?;
                authbus
                    .seal_unreserved_operation(
                        &stable_operation, Digest32::from_array(row.effect_sha256), time,
                    )
                    .await
                    .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
            },
        };
        let Some(mut reservation) = reservation else {
            if matches!(
                row.state,
                BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
            ) {
                let terminal = abort_evidence(&row, "no_reservation", None);
                let terminal = registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .record_consumption_abort(
                        operation_id,
                        false,
                        "no_reservation",
                        terminal,
                    )
                    .map_err(BaoProductHostError::Store)?;
                return Err(BaoProductHostError::TerminalFailure(terminal));
            }
            return Err(BaoProductHostError::OutcomePending(row));
        };
        validate_reservation(&row, &reservation)?;
        {
            let mut owner = registry
                .lock()
                .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?;
            owner
                .mark_consumption_reserved(
                    operation_id,
                    reservation.reservation_id.as_str().to_owned(),
                )
                .map_err(BaoProductHostError::Store)?;
            match reservation.state {
                ReservationState::DispatchAttempted | ReservationState::Indeterminate => {
                    owner
                        .mark_consumption_dispatch_fenced(
                            operation_id,
                            reservation.reservation_id.as_str(),
                        )
                        .map_err(BaoProductHostError::Store)?;
                    if reservation.state == ReservationState::Indeterminate
                        && matches!(row.state,
                            BaoConsumptionStateV1::Claimed
                                | BaoConsumptionStateV1::Reserved
                                | BaoConsumptionStateV1::DispatchAttempted
                                | BaoConsumptionStateV1::DispatchFenced
                                | BaoConsumptionStateV1::DeliveryPrepared
                                | BaoConsumptionStateV1::Indeterminate)
                    {
                        owner
                            .mark_consumption_indeterminate(operation_id)
                            .map_err(BaoProductHostError::Store)?;
                    }
                }
                _ => {}
            }
            row = owner
                .consumption_result(operation_id)
                .map_err(BaoProductHostError::Store)?;
        }

        match reservation.state {
            ReservationState::Held => {
                if !matches!(
                    row.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    return Err(BaoProductHostError::Store(
                        LeaseRegistryErrorV1::ObservationMismatch,
                    ));
                }
                let time = authbus
                    .observe_trusted_time_attestation(
                        &evidence.trusted_time().map_err(BaoProductHostError::AuthBus)?,
                    )
                    .await
                    .map_err(|error| BaoProductHostError::AuthBus(error.into()))?;
                reservation = if time.wall_time_ms() >= reservation.expires_at_ms {
                    authbus
                        .reconcile_expired_reservation(
                            &reservation.reservation_id,
                            reservation.revision,
                            time,
                        )
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
                } else {
                    authbus
                        .cancel_reservation(
                            &reservation.reservation_id,
                            reservation.revision,
                            time,
                        )
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
                };
                let code = match reservation.state {
                    ReservationState::Expired => "reservation_expired",
                    ReservationState::Cancelled => "reservation_cancelled",
                    _ => {
                        return Err(BaoProductHostError::Store(
                            LeaseRegistryErrorV1::ObservationMismatch,
                        ));
                    }
                };
                let terminal = abort_evidence(&row, code, Some(&reservation));
                let terminal = registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .record_consumption_abort(operation_id, true, code, terminal)
                    .map_err(BaoProductHostError::Store)?;
                return Err(BaoProductHostError::TerminalFailure(terminal));
            }
            ReservationState::Cancelled | ReservationState::Expired => {
                if matches!(
                    row.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    let code = if reservation.state == ReservationState::Expired {
                        "reservation_expired"
                    } else {
                        "reservation_cancelled"
                    };
                    let terminal = abort_evidence(&row, code, Some(&reservation));
                    let terminal = registry
                        .lock()
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .record_consumption_abort(operation_id, true, code, terminal)
                        .map_err(BaoProductHostError::Store)?;
                    return Err(BaoProductHostError::TerminalFailure(terminal));
                }
            }
            ReservationState::Released => {
                // Only settle_terminal_row may adopt a released reservation,
                // after matching the original negative digest and zero cost.
            }
            ReservationState::DispatchAttempted
            | ReservationState::Indeterminate
            | ReservationState::Settled => {}
        }

        row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        if matches!(row.state,
            BaoConsumptionStateV1::DispatchFenced | BaoConsumptionStateV1::Indeterminate)
            && row.receipt.is_none()
            && matches!(reservation.state,
                ReservationState::DispatchAttempted | ReservationState::Indeterminate)
        {
            let mut owner = registry.lock()
                .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?;
            owner.record_delivery_abort(operation_id).map_err(BaoProductHostError::Store)?;
            row = owner.consumption_result(operation_id).map_err(BaoProductHostError::Store)?;
        }
        if matches!(
            row.state,
            BaoConsumptionStateV1::DeliveryPrepared | BaoConsumptionStateV1::Indeterminate
        ) && row.receipt.is_some()
        {
            let observer = registration
                .observer
                .as_ref()
                .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
            match observer(operation_id, row.semantic_sha256) {
                Ok(BaoConsumerObservationV1::Succeeded) => registry
                    .lock()
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .observe_consumption(operation_id, true)
                    .map_err(BaoProductHostError::Store)?,
                Ok(BaoConsumerObservationV1::NotAppliedWithEvidence { evidence_sha256 }) => {
                    registry
                        .lock()
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .observe_consumption_not_applied(operation_id, evidence_sha256)
                        .map_err(BaoProductHostError::Store)?;
                }
                Ok(BaoConsumerObservationV1::NotApplied | BaoConsumerObservationV1::Unknown)
                | Err(()) => return Err(BaoProductHostError::OutcomePending(row)),
            }
        }

        row = registry
            .lock()
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        match row.state {
            BaoConsumptionStateV1::ConsumerSucceeded
            | BaoConsumptionStateV1::ProviderFailed
            | BaoConsumptionStateV1::DeliveryAborted
            | BaoConsumptionStateV1::ConsumerNotApplied => {
                settle_terminal_row(authbus, registry, row, reservation, evidence).await
            }
            BaoConsumptionStateV1::Succeeded => row.receipt.ok_or(
                BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState),
            ),
            BaoConsumptionStateV1::Failed => {
                Err(BaoProductHostError::TerminalFailure(row))
            }
            _ => Err(BaoProductHostError::OutcomePending(row)),
        }
    }
}

async fn settle_terminal_row<E: BaoAuthBusEvidenceProvider>(
    authbus: &AuthBusAuthorityHost,
    registry: &Mutex<DurableLeaseRegistryV1>,
    row: BaoConsumptionOperationV1,
    reservation: QuotaReservation,
    evidence: &mut E,
) -> Result<BaoSecretReceipt, BaoProductHostError> {
    let terminal = Digest32::from_array(row.terminal_evidence_sha256.ok_or(
        BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState),
    )?);
    let (status, observed_cost, success) = match row.state {
        BaoConsumptionStateV1::ConsumerSucceeded => {
            (SettlementStatus::Completed, row.amount, true)
        }
        BaoConsumptionStateV1::ProviderFailed | BaoConsumptionStateV1::DeliveryAborted => (
            SettlementStatus::Completed,
            row.terminal_observed_cost.ok_or(BaoProductHostError::Store(
                LeaseRegistryErrorV1::CorruptState,
            ))?,
            false,
        ),
        BaoConsumptionStateV1::ConsumerNotApplied => (SettlementStatus::Rejected, 0, false),
        _ => {
            return Err(BaoProductHostError::Store(
                LeaseRegistryErrorV1::InvalidTransition,
            ));
        }
    };
    let expected_terminal_state = match status {
        SettlementStatus::Completed => ReservationState::Settled,
        SettlementStatus::Rejected => ReservationState::Released,
    };
    if matches!(reservation.state, ReservationState::Settled | ReservationState::Released) {
        if reservation.state != expected_terminal_state
            || reservation.terminal_evidence != Some(terminal)
            || reservation.observed_cost != Some(observed_cost)
        {
            return Err(BaoProductHostError::Store(
                LeaseRegistryErrorV1::ObservationMismatch,
            ));
        }
    } else {
        if !matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) {
            return Err(BaoProductHostError::OutcomePending(row));
        }
        crate::https_consumer::settle_observed(
            authbus,
            evidence,
            &reservation,
            status,
            observed_cost,
            terminal,
            if success { row.receipt.clone() } else { None },
        )
        .await
        .map_err(BaoProductHostError::AuthBus)?;
    }
    let mut owner = registry
        .lock()
        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?;
    if success {
        owner
            .settle_consumption(&row.operation_id)
            .map_err(BaoProductHostError::Store)
    } else {
        let terminal = owner
            .settle_consumption_failure(&row.operation_id)
            .map_err(BaoProductHostError::Store)?;
        Err(BaoProductHostError::TerminalFailure(terminal))
    }
}

fn validate_reservation(
    row: &BaoConsumptionOperationV1,
    reservation: &QuotaReservation,
) -> Result<(), BaoProductHostError> {
    if reservation.operation_id.as_str() != row.operation_id
        || reservation.amount != row.amount
        || reservation.effect_digest.into_array() != row.effect_sha256
    {
        return Err(BaoProductHostError::Store(
            LeaseRegistryErrorV1::ObservationMismatch,
        ));
    }
    Ok(())
}

pub(super) fn abort_evidence(
    row: &BaoConsumptionOperationV1,
    code: &str,
    reservation: Option<&QuotaReservation>,
) -> [u8; 32] {
    let reservation_id = reservation
        .map(|value| value.reservation_id.as_str())
        .unwrap_or("");
    let reservation_revision = reservation.map(|value| value.revision).unwrap_or(0);
    Digest32::of_bytes(
        &serde_json::to_vec(&(
            "hepta.bao.abort.v1",
            row.operation_id.as_str(),
            row.semantic_sha256,
            row.effect_sha256,
            code,
            reservation_id,
            reservation_revision,
        ))
        .unwrap_or_default(),
    )
    .into_array()
}
