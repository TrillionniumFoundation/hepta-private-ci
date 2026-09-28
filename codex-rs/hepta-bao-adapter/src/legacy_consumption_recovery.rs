//! Requalify legacy success using only the original AuthBus identity. No client,
//! provider request or consumer callback is available at this boundary.
use super::*;

impl BaoFinalUseHost {
    pub(super) async fn reconcile_legacy_success<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        row: BaoConsumptionOperationV1,
        reservation: QuotaReservation,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        validate_reservation(&row, &reservation)?;
        let receipt = row.receipt.clone().ok_or(BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState))?;
        let terminal = Digest32::of_bytes(&serde_json::to_vec(&receipt)
            .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::CorruptState))?);
        match reservation.state {
            ReservationState::Settled => {
                if reservation.terminal_evidence != Some(terminal) || reservation.observed_cost != Some(row.amount) {
                    return Err(BaoProductHostError::Store(LeaseRegistryErrorV1::ObservationMismatch));
                }
            }
            ReservationState::DispatchAttempted | ReservationState::Indeterminate
                if row.state == BaoConsumptionStateV1::LegacyConsumerSucceeded => {
                crate::https_consumer::settle_observed(authbus, evidence, &reservation,
                    SettlementStatus::Completed, row.amount, terminal, Some(receipt)).await
                    .map_err(BaoProductHostError::AuthBus)?;
            }
            ReservationState::Held | ReservationState::Cancelled | ReservationState::Expired
            | ReservationState::Released | ReservationState::DispatchAttempted | ReservationState::Indeterminate => {
                return Err(BaoProductHostError::OutcomePending(row));
            }
        }
        crate::lease_lifecycle::lock_owner(registry).map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?
            .confirm_legacy_consumption(&row.operation_id, terminal.into_array())
            .map_err(BaoProductHostError::Store)
    }
}
