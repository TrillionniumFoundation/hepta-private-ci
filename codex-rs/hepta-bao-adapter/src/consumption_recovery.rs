//! Original-operation observation and settlement only. No provider client or
//! secret-fetch API is available in this recovery component.
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
        let _timing = self.metrics.recovery_timer();
        let _execution = crate::lease_lifecycle::lock_owner(registry)
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .enter_consumption_execution(operation_id)
            .map_err(BaoProductHostError::Store)?;
        let mut row = crate::lease_lifecycle::lock_owner(registry)
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
        let reservation = if row.reservation_id.is_some() {
            authbus.reservation_by_operation(&stable_operation).await
                .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
        } else {
            authbus.seal_unreserved_operation(&stable_operation, Digest32::from_array(row.effect_sha256))
                .await.map_err(|error| BaoProductHostError::AuthBus(error.into()))?
        };
        let Some(mut reservation) = reservation else {
            if matches!(
                row.state,
                BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
            ) {
                let terminal = abort_evidence(&row, "no_reservation", None);
                let terminal = crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .record_consumption_abort(
                        operation_id,
                        crate::lease_lifecycle::BaoAbortStage::BeforeReservation,
                        "no_reservation",
                        terminal,
                    )
                    .map_err(BaoProductHostError::Store)?;
                return Err(BaoProductHostError::TerminalFailure(terminal));
            }
            return Err(BaoProductHostError::OutcomePending(row));
        };
        validate_reservation(&row, &reservation)?;
        if row.state.phase() == crate::BaoConsumptionPhase::LegacyRequalification {
            return self.reconcile_legacy_success(authbus, registry, row, reservation, evidence).await;
        }
        {
            let mut owner = crate::lease_lifecycle::lock_owner(registry)
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
                        && owner.consumption_result(operation_id).map_err(BaoProductHostError::Store)?.state.phase()
                            == crate::BaoConsumptionPhase::Fenced
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
                let terminal = crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .record_consumption_abort(operation_id, crate::lease_lifecycle::BaoAbortStage::BeforeDispatch, code, terminal)
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
                    let terminal = crate::lease_lifecycle::lock_owner(registry)
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .record_consumption_abort(operation_id, crate::lease_lifecycle::BaoAbortStage::BeforeDispatch, code, terminal)
                        .map_err(BaoProductHostError::Store)?;
                    return Err(BaoProductHostError::TerminalFailure(terminal));
                }
            }
            ReservationState::Released => {
                if matches!(
                    row.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    let terminal = abort_evidence(&row, "reservation_released", Some(&reservation));
                    let terminal = crate::lease_lifecycle::lock_owner(registry)
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .record_consumption_abort(
                            operation_id,
                            crate::lease_lifecycle::BaoAbortStage::BeforeDispatch,
                            "reservation_released",
                            terminal,
                        )
                        .map_err(BaoProductHostError::Store)?;
                    return Err(BaoProductHostError::TerminalFailure(terminal));
                }
            }
            ReservationState::DispatchAttempted
            | ReservationState::Indeterminate
            | ReservationState::Settled => {}
        }

        row = crate::lease_lifecycle::lock_owner(registry)
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
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
                Ok(BaoConsumerObservationV1::Succeeded) => crate::lease_lifecycle::lock_owner(registry)
                    .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                    .observe_consumption(operation_id, true)
                    .map_err(BaoProductHostError::Store)?,
                Ok(BaoConsumerObservationV1::NotAppliedWithEvidence { evidence_sha256 }) => {
                    crate::lease_lifecycle::lock_owner(registry)
                        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                        .observe_consumption_not_applied(operation_id, evidence_sha256)
                        .map_err(BaoProductHostError::Store)?;
                }
                Ok(BaoConsumerObservationV1::NotApplied | BaoConsumerObservationV1::Unknown) => return Err(BaoProductHostError::OutcomePending(row)),
                Err(()) => {
                    self.metrics.observer_failed();
                    return Err(BaoProductHostError::OutcomePending(row));
                }
            }
        }

        row = crate::lease_lifecycle::lock_owner(registry)
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .consumption_result(operation_id)
            .map_err(BaoProductHostError::Store)?;
        match row.state {
            BaoConsumptionStateV1::ConsumerSucceeded
            | BaoConsumptionStateV1::ProviderFailed
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
        BaoConsumptionStateV1::ProviderFailed => (
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
    let mut owner = crate::lease_lifecycle::lock_owner(registry)
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
