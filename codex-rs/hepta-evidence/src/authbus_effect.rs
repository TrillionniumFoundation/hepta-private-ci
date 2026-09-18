use codex_hepta_authbus::AuthorizationDecision;
use codex_hepta_authbus::AuthorizationRequest;
use codex_hepta_authbus::PolicyDecisionKind;
use codex_hepta_authbus::ReservationRecord;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_types::Digest32;

use crate::AuthBusControlError;
use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::ProviderEffectQualificationDispatchReceipt;
use crate::StoredProviderEffect;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedCostEvidence {
    pub amount: u64,
    pub evidence_digest: Digest32,
}

impl ObservedCostEvidence {
    pub fn validate(&self) -> bool {
        self.amount > 0 && !self.evidence_digest.is_zero()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusEffectDispatchReceipt {
    pub authorization: AuthorizationDecision,
    pub reservation: ReservationRecord,
    pub provider: ProviderEffectQualificationDispatchReceipt,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthBusEffectReconcileReceipt {
    pub provider_state: ProviderEffectState,
    pub reservation: ReservationRecord,
}

#[derive(Debug, thiserror::Error)]
pub enum AuthBusEffectError {
    #[error("AuthBus authorization denied")]
    AuthorizationDenied,
    #[error("AuthBus effect binding does not match the authorized request")]
    BindingMismatch,
    #[error("provider completion requires observed cost evidence")]
    ObservedCostRequired,
    #[error(transparent)]
    Control(#[from] AuthBusControlError),
    #[error(transparent)]
    Evidence(#[from] EvidenceError),
}

impl HeptaEvidenceStore {
    /// Qualification effect seam with a strict pre-effect ordering:
    ///
    /// 1. read the current policy head;
    /// 2. reserve quota while rechecking that policy head and quota revision;
    /// 3. enter the durable provider-effect facade.
    ///
    /// A completed provider acknowledgement does not release the reservation
    /// until reconcile_authbus_provider_effect receives separately observed
    /// cost evidence. Unknown/accepted outcomes retain the hold.
    pub async fn dispatch_provider_effect_with_authbus_qualification<
        A: ProviderEffectAdapter + ?Sized,
    >(
        &self,
        adapter: &A,
        authorization: &AuthorizationRequest,
        reservation: &ReservationRequest,
        intent: &ProviderEffectIntent,
        now_ms: u64,
    ) -> Result<AuthBusEffectDispatchReceipt, AuthBusEffectError> {
        let decision = self.authorize_authbus(authorization).await?;
        if decision.kind != PolicyDecisionKind::Allowed {
            return Err(AuthBusEffectError::AuthorizationDenied);
        }
        verify_effect_binding(&decision, authorization, reservation, intent)?;
        let held = self
            .reserve_authbus_quota(&decision, reservation, now_ms)
            .await?;
        let provider = match self
            .dispatch_provider_effect_qualification(adapter, intent)
            .await
        {
            Ok(receipt) => receipt,
            Err(error) => {
                let evidence = error_evidence("provider-dispatch-error", &error);
                let _ = self
                    .quarantine_authbus_reservation(&held.reservation_id, evidence)
                    .await;
                return Err(AuthBusEffectError::Evidence(error));
            }
        };
        let reservation = if provider.state == ProviderEffectState::Rejected {
            terminal_reservation_from_provider(self, &held, intent, /*cost*/ None).await?
        } else if provider.dispatch_claimed && !provider.dispatch_attempted {
            // A fresh fail-closed capability gate crossed no adapter boundary.
            // An imported/crash-window intent has dispatch_claimed=false and
            // therefore stays held instead of receiving this no-effect refund.
            let evidence = local_no_dispatch_evidence(intent, provider);
            self.cancel_authbus_reservation(&held.reservation_id, evidence)
                .await?
        } else {
            let evidence = provider_state_evidence(self, &intent.key, provider.state).await?;
            self.quarantine_authbus_reservation(&held.reservation_id, evidence)
                .await?
        };
        Ok(AuthBusEffectDispatchReceipt {
            authorization: decision,
            reservation,
            provider,
        })
    }

    /// Reconcile an already-reserved effect through provider-owned lookup.
    ///
    /// Rejected is a no-effect terminal and refunds the hold. Completed
    /// requires a separate observed-cost witness and settles exactly that
    /// amount. Accepted/unknown outcomes remain held in quarantine.
    pub async fn reconcile_authbus_provider_effect<A: ProviderEffectAdapter + ?Sized>(
        &self,
        adapter: &A,
        key: &ProviderEffectKey,
        reservation_id: &codex_hepta_types::StableId,
        cost: Option<&ObservedCostEvidence>,
    ) -> Result<AuthBusEffectReconcileReceipt, AuthBusEffectError> {
        let provider_state = match self
            .reconcile_provider_effect_with_adapter(adapter, key)
            .await
        {
            Ok(state) => state,
            Err(error) => {
                let evidence = error_evidence("provider-reconcile-error", &error);
                let _ = self
                    .quarantine_authbus_reservation(reservation_id, evidence)
                    .await;
                return Err(AuthBusEffectError::Evidence(error));
            }
        };
        let effect = self
            .get_provider_effect(key)
            .await?
            .ok_or_else(|| EvidenceError::Corrupt("provider effect disappeared".into()))?;
        let reservation = match provider_state {
            ProviderEffectState::Rejected => {
                let evidence = provider_terminal_digest(&effect, None)?;
                self.cancel_authbus_reservation(reservation_id, evidence)
                    .await?
            }
            ProviderEffectState::Completed => {
                let cost = cost.ok_or(AuthBusEffectError::ObservedCostRequired)?;
                if !cost.validate() {
                    return Err(AuthBusControlError::InvalidRequest(
                        "invalid observed cost evidence",
                    )
                    .into());
                }
                let evidence = provider_terminal_digest(&effect, Some(cost))?;
                self.settle_authbus_reservation(reservation_id, cost.amount, evidence)
                    .await?
            }
            ProviderEffectState::Pending
            | ProviderEffectState::Accepted
            | ProviderEffectState::Indeterminate => {
                let evidence = provider_state_digest(&effect);
                self.quarantine_authbus_reservation(reservation_id, evidence)
                    .await?
            }
        };
        Ok(AuthBusEffectReconcileReceipt {
            provider_state,
            reservation,
        })
    }
}

fn verify_effect_binding(
    decision: &AuthorizationDecision,
    authorization: &AuthorizationRequest,
    reservation: &ReservationRequest,
    intent: &ProviderEffectIntent,
) -> Result<(), AuthBusEffectError> {
    let payload = authorization.payload_digest.to_string();
    if decision.request_digest != authorization.digest()
        || reservation.authorization_digest != decision.request_digest
        || reservation.operation_id.as_str() != intent.key.as_str()
        || payload != intent.payload_sha256.as_str()
    {
        return Err(AuthBusEffectError::BindingMismatch);
    }
    Ok(())
}

async fn terminal_reservation_from_provider(
    store: &HeptaEvidenceStore,
    held: &ReservationRecord,
    intent: &ProviderEffectIntent,
    cost: Option<&ObservedCostEvidence>,
) -> Result<ReservationRecord, AuthBusEffectError> {
    let effect = store
        .get_provider_effect(&intent.key)
        .await?
        .ok_or_else(|| EvidenceError::Corrupt("provider effect disappeared".into()))?;
    match effect.state() {
        ProviderEffectState::Rejected => {
            let evidence = provider_terminal_digest(&effect, None)?;
            Ok(store
                .cancel_authbus_reservation(&held.reservation_id, evidence)
                .await?)
        }
        ProviderEffectState::Completed => {
            let cost = cost.ok_or(AuthBusEffectError::ObservedCostRequired)?;
            let evidence = provider_terminal_digest(&effect, Some(cost))?;
            Ok(store
                .settle_authbus_reservation(&held.reservation_id, cost.amount, evidence)
                .await?)
        }
        _ => {
            let evidence = provider_state_digest(&effect);
            Ok(store
                .quarantine_authbus_reservation(&held.reservation_id, evidence)
                .await?)
        }
    }
}

async fn provider_state_evidence(
    store: &HeptaEvidenceStore,
    key: &ProviderEffectKey,
    fallback: ProviderEffectState,
) -> Result<Digest32, EvidenceError> {
    Ok(store
        .get_provider_effect(key)
        .await?
        .map(|effect| provider_state_digest(&effect))
        .unwrap_or_else(|| {
            Digest32::of_bytes(
                format!("hepta.authbus.provider-state.v1\0{}\0{fallback:?}", key.as_str())
                    .as_bytes(),
            )
        }))
}

fn provider_state_digest(effect: &StoredProviderEffect) -> Digest32 {
    let mut bytes = b"hepta.authbus.provider-state.v1\0".to_vec();
    push_text(&mut bytes, effect.intent.intent.key.as_str());
    push_text(&mut bytes, effect.intent.intent.payload_sha256.as_str());
    bytes.push(provider_state_code(effect.state()));
    if let Some(ack) = effect.acknowledgements.last() {
        push_text(&mut bytes, ack.ack.provider_operation_id_sha256.as_str());
        bytes.push(match ack.ack.status {
            codex_hepta_contracts::ProviderEffectAckStatus::Accepted => 1,
            codex_hepta_contracts::ProviderEffectAckStatus::Completed => 2,
            codex_hepta_contracts::ProviderEffectAckStatus::Rejected => 3,
        });
        push_text(&mut bytes, ack.source.as_str());
        bytes.extend_from_slice(&ack.recorded_at_ms.to_be_bytes());
    }
    if let Some(uncertainty) = effect.uncertainties.last() {
        push_text(&mut bytes, &uncertainty.uncertainty.reason_code);
        bytes.extend_from_slice(&uncertainty.recorded_at_ms.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn provider_terminal_digest(
    effect: &StoredProviderEffect,
    cost: Option<&ObservedCostEvidence>,
) -> Result<Digest32, AuthBusEffectError> {
    if !effect.state().is_terminal() {
        return Err(AuthBusEffectError::BindingMismatch);
    }
    let ack = effect
        .acknowledgements
        .last()
        .ok_or_else(|| EvidenceError::Corrupt("terminal provider state has no ACK".into()))?;
    let mut bytes = b"hepta.authbus.provider-terminal.v1\0".to_vec();
    push_text(&mut bytes, ack.ack.key.as_str());
    push_text(&mut bytes, ack.ack.payload_sha256.as_str());
    push_text(&mut bytes, ack.ack.provider_operation_id_sha256.as_str());
    bytes.push(match ack.ack.status {
        codex_hepta_contracts::ProviderEffectAckStatus::Accepted => 1,
        codex_hepta_contracts::ProviderEffectAckStatus::Completed => 2,
        codex_hepta_contracts::ProviderEffectAckStatus::Rejected => 3,
    });
    push_text(&mut bytes, ack.source.as_str());
    if let Some(cost) = cost {
        if !cost.validate() {
            return Err(AuthBusEffectError::BindingMismatch);
        }
        bytes.extend_from_slice(&cost.amount.to_be_bytes());
        bytes.extend_from_slice(cost.evidence_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn local_no_dispatch_evidence(
    intent: &ProviderEffectIntent,
    receipt: ProviderEffectQualificationDispatchReceipt,
) -> Digest32 {
    let mut bytes = b"hepta.authbus.provider-not-dispatched.v1\0".to_vec();
    push_text(&mut bytes, intent.key.as_str());
    push_text(&mut bytes, intent.payload_sha256.as_str());
    bytes.push(u8::from(receipt.dispatch_claimed));
    bytes.push(u8::from(receipt.dispatch_attempted));
    bytes.push(provider_state_code(receipt.state));
    Digest32::of_bytes(&bytes)
}

fn error_evidence(domain: &str, error: &EvidenceError) -> Digest32 {
    let mut bytes = b"hepta.authbus.provider-error.v1\0".to_vec();
    push_text(&mut bytes, domain);
    push_text(&mut bytes, &error.to_string());
    Digest32::of_bytes(&bytes)
}

fn provider_state_code(state: ProviderEffectState) -> u8 {
    match state {
        ProviderEffectState::Pending => 0,
        ProviderEffectState::Accepted => 1,
        ProviderEffectState::Completed => 2,
        ProviderEffectState::Rejected => 3,
        ProviderEffectState::Indeterminate => 4,
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
