//! final use host recovery implementation.

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
        let started = Instant::now();
        let result = async {
            let _execution = registry
                .lock()
                .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                .enter_consumption_execution(operation_id)
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
                return Err(BaoProductHostError::TerminalFailure(Box::new(row)));
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
                None => authbus
                    .seal_unreserved_operation(
                        &stable_operation,
                        Digest32::from_array(row.effect_sha256),
                    )
                    .await
                    .map_err(|error| BaoProductHostError::AuthBus(error.into()))?,
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
                        .record_consumption_abort(operation_id, false, "no_reservation", terminal)
                        .map_err(BaoProductHostError::Store)?;
                    return Err(BaoProductHostError::TerminalFailure(Box::new(terminal)));
                }
                return Err(BaoProductHostError::OutcomePending(Box::new(row)));
            };
            validate_reservation(&row, &reservation).map_err(BaoProductHostError::Store)?;
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
                            && owner
                                .consumption_result(operation_id)
                                .map_err(BaoProductHostError::Store)?
                                .state
                                .recovery_action()
                                == BaoConsumptionRecoveryActionV1::ObserveOriginalOutcome
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
                            &evidence
                                .trusted_time()
                                .map_err(BaoProductHostError::AuthBus)?,
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
                    return Err(BaoProductHostError::TerminalFailure(Box::new(terminal)));
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
                        return Err(BaoProductHostError::TerminalFailure(Box::new(terminal)));
                    }
                }
                ReservationState::Released => {
                    if matches!(
                        row.state,
                        BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                    ) {
                        let terminal =
                            abort_evidence(&row, "reservation_released", Some(&reservation));
                        let terminal = registry
                            .lock()
                            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
                            .record_consumption_abort(
                                operation_id,
                                true,
                                "reservation_released",
                                terminal,
                            )
                            .map_err(BaoProductHostError::Store)?;
                        return Err(BaoProductHostError::TerminalFailure(Box::new(terminal)));
                    }
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
                    Ok(
                        BaoConsumerObservationV1::NotApplied | BaoConsumerObservationV1::Unknown,
                    )
                    | Err(()) => return Err(BaoProductHostError::OutcomePending(Box::new(row))),
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
                | BaoConsumptionStateV1::ConsumerNotApplied => {
                    settle_terminal_row(authbus, registry, row, reservation, evidence).await
                }
                BaoConsumptionStateV1::Succeeded => row.receipt.ok_or(BaoProductHostError::Store(
                    LeaseRegistryErrorV1::CorruptState,
                )),
                BaoConsumptionStateV1::Failed => {
                    Err(BaoProductHostError::TerminalFailure(Box::new(row)))
                }
                _ => Err(BaoProductHostError::OutcomePending(Box::new(row))),
            }
        }
        .await;
        self.record_recovery_metric(started, &result);
        result
    }
}
