use codex_hepta_authbus::EffectAdmissionRequest;
use codex_hepta_authbus::Reservation;
use codex_hepta_authbus::ReservationReconcileOutcome;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_types::Digest32;

use crate::AuthBusControlError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::ProviderEffectQualificationDispatchReceipt;

#[derive(Debug, thiserror::Error)]
pub enum AuthBusProviderEffectError {
    #[error(transparent)]
    Control(#[from] AuthBusControlError),
    #[error(transparent)]
    Evidence(#[from] EvidenceError),
    #[error("completed provider effect requires observed cost before quota can settle")]
    ObservedCostRequired,
    #[error("AuthBus operation identity must equal the provider effect idempotency key")]
    OperationBindingMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusProviderEffectReceipt {
    pub provider_state: ProviderEffectState,
    pub dispatch_claimed: bool,
    pub dispatch_attempted: bool,
    pub reservation: Reservation,
}

/// Qualification facade that enforces the AuthBus control order:
///
/// 1. current policy authorization and quota reservation commit atomically;
/// 2. the reservation becomes in-flight only after the current policy revision
///    is rechecked immediately before the provider seam;
/// 3. provider dispatch runs through the existing durable effect journal;
/// 4. rejected effects release quota only from terminal provider evidence;
///    completed/unknown effects stay quarantined until observed cost or a
///    provider-owned reconciliation closes them.
///
/// The older raw provider qualification method remains an internal substrate
/// and must not be product-composed as an effect adapter.
impl HeptaEvidenceStore {
    pub async fn dispatch_provider_effect_guarded_qualification<
        A: ProviderEffectAdapter + ?Sized,
    >(
        &self,
        adapter: &A,
        intent: &ProviderEffectIntent,
        admission: &EffectAdmissionRequest,
    ) -> Result<AuthBusProviderEffectReceipt, AuthBusProviderEffectError> {
        if admission.operation_id.as_str() != intent.key.as_str() {
            return Err(AuthBusProviderEffectError::OperationBindingMismatch);
        }
        let admitted = self.authorize_and_reserve(admission).await?;
        let reservation = self
            .begin_reserved_effect(admitted.reservation.reservation_id, &admission.operation_id)
            .await?;
        let dispatch = self
            .dispatch_provider_effect_qualification(adapter, intent)
            .await;
        match dispatch {
            Ok(receipt) => {
                self.close_guarded_dispatch(intent, reservation, receipt)
                    .await
            }
            Err(error) => {
                let evidence = provider_evidence_digest(
                    intent,
                    ProviderEffectState::Indeterminate,
                    false,
                    true,
                );
                let _ = self
                    .quarantine_reservation(reservation.reservation_id, evidence)
                    .await;
                Err(error.into())
            }
        }
    }

    pub async fn reconcile_provider_effect_guarded_qualification<
        A: ProviderEffectAdapter + ?Sized,
    >(
        &self,
        adapter: &A,
        key: &ProviderEffectKey,
        reservation_id: Digest32,
        observed_cost: Option<u64>,
        terminal_evidence: Digest32,
    ) -> Result<Reservation, AuthBusProviderEffectError> {
        let reservation = self.reservation(reservation_id).await?;
        if reservation.operation_id.as_str() != key.as_str() {
            return Err(AuthBusProviderEffectError::OperationBindingMismatch);
        }
        let state = self
            .reconcile_provider_effect_with_adapter(adapter, key)
            .await?;
        match state {
            ProviderEffectState::Completed => {
                let observed_cost =
                    observed_cost.ok_or(AuthBusProviderEffectError::ObservedCostRequired)?;
                Ok(self
                    .reconcile_reservation(
                        reservation_id,
                        ReservationReconcileOutcome::Settled {
                            observed_cost,
                            terminal_evidence,
                        },
                    )
                    .await?)
            }
            ProviderEffectState::Rejected => Ok(self
                .reconcile_reservation(
                    reservation_id,
                    ReservationReconcileOutcome::NotApplied { terminal_evidence },
                )
                .await?),
            ProviderEffectState::Pending
            | ProviderEffectState::Accepted
            | ProviderEffectState::Indeterminate => {
                let reservation = self.reservation(reservation_id).await?;
                if reservation.state == codex_hepta_authbus::ReservationState::InFlight {
                    Ok(self
                        .quarantine_reservation(reservation_id, terminal_evidence)
                        .await?)
                } else {
                    Ok(reservation)
                }
            }
        }
    }

    async fn close_guarded_dispatch(
        &self,
        intent: &ProviderEffectIntent,
        reservation: Reservation,
        receipt: ProviderEffectQualificationDispatchReceipt,
    ) -> Result<AuthBusProviderEffectReceipt, AuthBusProviderEffectError> {
        let evidence = provider_evidence_digest(
            intent,
            receipt.state,
            receipt.dispatch_claimed,
            receipt.dispatch_attempted,
        );
        let reservation = match receipt.state {
            ProviderEffectState::Rejected => {
                let quarantined = self
                    .quarantine_reservation(reservation.reservation_id, evidence)
                    .await?;
                self.reconcile_reservation(
                    quarantined.reservation_id,
                    ReservationReconcileOutcome::NotApplied {
                        terminal_evidence: evidence,
                    },
                )
                .await?
            }
            ProviderEffectState::Completed
            | ProviderEffectState::Pending
            | ProviderEffectState::Accepted
            | ProviderEffectState::Indeterminate => {
                self.quarantine_reservation(reservation.reservation_id, evidence)
                    .await?
            }
        };
        Ok(AuthBusProviderEffectReceipt {
            provider_state: receipt.state,
            dispatch_claimed: receipt.dispatch_claimed,
            dispatch_attempted: receipt.dispatch_attempted,
            reservation,
        })
    }
}

fn provider_evidence_digest(
    intent: &ProviderEffectIntent,
    state: ProviderEffectState,
    dispatch_claimed: bool,
    dispatch_attempted: bool,
) -> Digest32 {
    let mut bytes = b"hepta.authbus.provider-effect-terminal.v1\0".to_vec();
    push(&mut bytes, intent.key.as_str());
    push(&mut bytes, intent.payload_sha256.as_str());
    bytes.push(match state {
        ProviderEffectState::Pending => 0,
        ProviderEffectState::Accepted => 1,
        ProviderEffectState::Completed => 2,
        ProviderEffectState::Rejected => 3,
        ProviderEffectState::Indeterminate => 4,
    });
    bytes.push(u8::from(dispatch_claimed));
    bytes.push(u8::from(dispatch_attempted));
    Digest32::of_bytes(&bytes)
}

fn push(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
