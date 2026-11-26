//! sqlite runtime reconcile claim implementation.

use super::*;

impl BaoFinalUseHost {
    pub(super) async fn reconcile_sqlite_claim<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        owner: &SqliteBaoOwnerV1,
        claim: &SqliteReconciliationClaimV1,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let operation_id = claim.record.operation.operation_id.as_str();
        let mut row = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if let Some(result) = historical_result(row.operation.clone()) {
            return result;
        }
        let registration = self
            .consumers
            .get(&row.operation.consumer_id)
            .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
        if registration.configuration_sha256 != Some(row.operation.consumer_configuration_sha256) {
            return Err(BaoProductHostError::ConsumerProfileRequired);
        }
        let stable_operation = StableId::new(operation_id.to_owned()).map_err(|_| {
            BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
                "invalid durable operation identifier",
            ))
        })?;
        let reservation = match row.operation.reservation_id.as_deref() {
            Some(value) => {
                let reservation_id = StableId::new(value.to_owned()).map_err(|_| {
                    BaoProductHostError::SqliteStore(SqliteBaoOwnerErrorV1::CorruptState(
                        "invalid durable reservation identifier",
                    ))
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
                    Digest32::from_array(row.operation.effect_sha256),
                )
                .await
                .map_err(|error| BaoProductHostError::AuthBus(error.into()))?,
        };
        let Some(mut reservation) = reservation else {
            if matches!(
                row.operation.state,
                BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
            ) {
                let terminal_evidence = abort_evidence(&row.operation, "no_reservation", None);
                let terminal = owner
                    .abort_consumption_before_reservation(
                        operation_id,
                        row.revision,
                        terminal_evidence,
                        self.product_now()?,
                    )
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                return Err(BaoProductHostError::TerminalFailure(Box::new(
                    terminal.operation,
                )));
            }
            return Err(BaoProductHostError::OutcomePending(Box::new(row.operation)));
        };
        validate_sqlite_reservation(&row.operation, &reservation)?;

        if matches!(
            row.operation.state,
            BaoConsumptionStateV1::Claimed | BaoConsumptionStateV1::DispatchAttempted
        ) {
            row = owner
                .mark_consumption_reserved(
                    operation_id,
                    row.revision,
                    reservation.reservation_id.as_str().to_owned(),
                    reservation_evidence(b"hepta.bao.sqlite.recovery-reserved.v1", &reservation),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }
        if matches!(
            reservation.state,
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
        ) && matches!(
            row.operation.state,
            BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
        ) {
            row = owner
                .mark_consumption_dispatch_fenced(
                    operation_id,
                    row.revision,
                    reservation_evidence(
                        b"hepta.bao.sqlite.recovery-dispatch-fenced.v1",
                        &reservation,
                    ),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }
        if reservation.state == ReservationState::Indeterminate
            && row
                .operation
                .state
                .allows_transition_to(BaoConsumptionStateV1::Indeterminate)
        {
            row = owner
                .mark_consumption_indeterminate(
                    operation_id,
                    row.revision,
                    reservation_evidence(
                        b"hepta.bao.sqlite.recovery-indeterminate.v1",
                        &reservation,
                    ),
                    self.product_now()?,
                )
                .await
                .map_err(BaoProductHostError::SqliteStore)?;
        }

        match reservation.state {
            ReservationState::Held => {
                if !matches!(
                    row.operation.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    return Err(BaoProductHostError::SqliteStore(
                        SqliteBaoOwnerErrorV1::ObservationMismatch,
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
                        .cancel_reservation(&reservation.reservation_id, reservation.revision, time)
                        .await
                        .map_err(|error| BaoProductHostError::AuthBus(error.into()))?
                };
                let code = reservation_terminal_abort_code(reservation.state)?;
                let terminal_evidence = abort_evidence(&row.operation, code, Some(&reservation));
                let terminal = owner
                    .abort_consumption_before_dispatch(
                        operation_id,
                        row.revision,
                        code,
                        terminal_evidence,
                        self.product_now()?,
                    )
                    .await
                    .map_err(BaoProductHostError::SqliteStore)?;
                return Err(BaoProductHostError::TerminalFailure(Box::new(
                    terminal.operation,
                )));
            }
            ReservationState::Cancelled
            | ReservationState::Expired
            | ReservationState::Released => {
                if matches!(
                    row.operation.state,
                    BaoConsumptionStateV1::Reserved | BaoConsumptionStateV1::DispatchAttempted
                ) {
                    let code = reservation_terminal_abort_code(reservation.state)?;
                    let terminal_evidence =
                        abort_evidence(&row.operation, code, Some(&reservation));
                    let terminal = owner
                        .abort_consumption_before_dispatch(
                            operation_id,
                            row.revision,
                            code,
                            terminal_evidence,
                            self.product_now()?,
                        )
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                    return Err(BaoProductHostError::TerminalFailure(Box::new(
                        terminal.operation,
                    )));
                }
            }
            ReservationState::DispatchAttempted
            | ReservationState::Indeterminate
            | ReservationState::Settled => {}
        }

        row = owner
            .consumption_result(operation_id)
            .await
            .map_err(BaoProductHostError::SqliteStore)?;
        if matches!(
            row.operation.state,
            BaoConsumptionStateV1::DeliveryPrepared | BaoConsumptionStateV1::Indeterminate
        ) && row.operation.receipt.is_some()
        {
            let observer = registration
                .observer
                .as_ref()
                .ok_or(BaoProductHostError::ConsumerProfileRequired)?;
            match observer(operation_id, row.operation.semantic_sha256) {
                Ok(BaoConsumerObservationV1::Succeeded) => {
                    row = owner
                        .mark_consumption_succeeded(operation_id, row.revision, self.product_now()?)
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                }
                Ok(BaoConsumerObservationV1::NotAppliedWithEvidence { evidence_sha256 }) => {
                    row = owner
                        .mark_consumption_not_applied(
                            operation_id,
                            row.revision,
                            evidence_sha256,
                            self.product_now()?,
                        )
                        .await
                        .map_err(BaoProductHostError::SqliteStore)?;
                }
                Ok(BaoConsumerObservationV1::NotApplied | BaoConsumerObservationV1::Unknown)
                | Err(()) => {
                    return Err(BaoProductHostError::OutcomePending(Box::new(row.operation)));
                }
            }
        }

        match row.operation.state {
            BaoConsumptionStateV1::ConsumerSucceeded
            | BaoConsumptionStateV1::ProviderFailed
            | BaoConsumptionStateV1::ConsumerNotApplied => {
                settle_sqlite_terminal_row(self, authbus, owner, row, reservation, evidence).await
            }
            BaoConsumptionStateV1::Succeeded => {
                row.operation
                    .receipt
                    .ok_or(BaoProductHostError::SqliteStore(
                        SqliteBaoOwnerErrorV1::CorruptState("successful operation has no receipt"),
                    ))
            }
            BaoConsumptionStateV1::Failed => Err(BaoProductHostError::TerminalFailure(Box::new(
                row.operation,
            ))),
            _ => Err(BaoProductHostError::OutcomePending(Box::new(row.operation))),
        }
    }
}
