//! Original AuthBus ledger admission, never a physical whole-unit reservation.

use std::sync::Arc;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationRequest;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::controlled_aggregate::ControlledAggregateRegistration;

pub const CONTROLLED_LEDGER_UNIT: &str = "unit:controlled-whole-unit";
pub const CONTROLLED_LEDGER_ACTION: &str = "action:controlled-aggregate";

/// Supplies independently signed time; this host never receives the issuer key.
pub trait ControlledTrustedTimeProvider: Send + Sync {
    fn signed_time(&self) -> Result<SignedTrustedTimeAttestation, String>;
}

/// Exact original-ledger admission input. One ledger unit is charged; it is
/// accounting liability, not proof that CPU, memory or tasks were reserved.
#[derive(Clone, Debug)]
pub struct ControlledLedgerAdmission {
    pub quota_key: StableId,
    pub expected_quota_revision: u64,
    pub policy_revision: u64,
    pub expires_at_ms: u64,
}

/// Original-ledger funded declaration. The authoritative reservation ID is
/// installed before the caller derives its final operation and signed grant.
/// This value cannot be deserialized or used to reconstruct a native owner.
pub struct LedgerFundedControlledAggregate {
    pub(super) registration: ControlledAggregateRegistration,
    pub(super) funding: ControlledLedgerFunding,
}

impl LedgerFundedControlledAggregate {
    pub fn registration(&self) -> &ControlledAggregateRegistration {
        &self.registration
    }

    pub async fn reserve(
        mut registration: ControlledAggregateRegistration,
        owner: Arc<AuthBusAuthorityHost>,
        admission: ControlledLedgerAdmission,
        time_provider: Arc<dyn ControlledTrustedTimeProvider>,
    ) -> Result<Self, String> {
        let binding = &registration.0;
        if admission.policy_revision != binding.policy_generation.get()
            || admission.expected_quota_revision == 0
        {
            return Err("controlled funding policy or quota revision differs".to_owned());
        }
        let issuer = owner
            .settlement_issuer(
                &binding.settlement_issuer_id,
                Generation::new(binding.settlement_key_epoch).map_err(|e| e.to_string())?,
            )
            .await
            .map_err(|e| e.to_string())?;
        if issuer.revoked {
            return Err("controlled settlement issuer is unavailable".to_owned());
        }
        let quota = owner
            .quota_snapshot(&admission.quota_key)
            .await
            .map_err(|e| e.to_string())?;
        if quota.principal != binding.subject_id
            || quota.scope_digest != binding.scope_digest
            || quota.unit.as_str() != CONTROLLED_LEDGER_UNIT
        {
            return Err("controlled funding quota identity, scope or unit differs".to_owned());
        }
        let time = owner
            .observe_trusted_time_attestation(&time_provider.signed_time()?)
            .await
            .map_err(|e| e.to_string())?;
        let decision = owner
            .authorize(
                &binding.subject_id,
                &StableId::new(CONTROLLED_LEDGER_ACTION).map_err(|e| e.to_string())?,
                binding.scope_digest,
                admission.policy_revision,
                time.clone(),
            )
            .await
            .map_err(|e| e.to_string())?;
        let effect = effect_digest(&registration, &admission)?;
        let reservation = owner
            .reserve(
                &decision,
                ReservationRequest {
                    quota_key: admission.quota_key,
                    operation_id: binding.operation_id.clone(),
                    amount: 1,
                    effect_digest: effect,
                    expected_quota_revision: admission.expected_quota_revision,
                    expires_at_ms: admission.expires_at_ms,
                },
                time,
            )
            .await
            .map_err(|e| e.to_string())?;
        if reservation.state != ReservationState::Held {
            return Err(
                "controlled ledger reservation was already dispatched or retained".to_owned(),
            );
        }
        registration.0.reservation_id = reservation.reservation_id.clone();
        Ok(Self {
            registration,
            funding: ControlledLedgerFunding {
                owner,
                reservation,
                issuer_key: issuer.verifying_key.to_bytes(),
                issuer_id: issuer.issuer_id,
                issuer_epoch: issuer.key_epoch,
                time_provider,
            },
        })
    }
}

// The ledger derives its reservation ID from this effect. Its declaration is
// excluded only at that funding cut; every other plan field and admission input
// is fixed here. The final signed operation includes the actual returned ID.
pub(super) fn effect_digest(
    registration: &ControlledAggregateRegistration,
    admission: &ControlledLedgerAdmission,
) -> Result<Digest32, String> {
    let mut payload: serde_json::Value =
        serde_json::from_str(&registration.payload_json()?).map_err(|e| e.to_string())?;
    if payload
        .as_object_mut()
        .ok_or("controlled funding payload is not an object")?
        .remove("reservation_id")
        .is_none()
    {
        return Err("controlled funding payload lacks reservation identity".to_owned());
    }
    let bytes = serde_json::to_vec(&(
        "hepta.authbus.controlled-aggregate-ledger.v1",
        payload,
        CONTROLLED_LEDGER_ACTION,
        CONTROLLED_LEDGER_UNIT,
        admission.quota_key.as_str(),
        admission.policy_revision,
        admission.expected_quota_revision,
        admission.expires_at_ms,
        1_u64,
    ))
    .map_err(|e| e.to_string())?;
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) struct ControlledLedgerFunding {
    owner: Arc<AuthBusAuthorityHost>,
    reservation: QuotaReservation,
    issuer_id: StableId,
    issuer_epoch: Generation,
    issuer_key: [u8; 32],
    time_provider: Arc<dyn ControlledTrustedTimeProvider>,
}

impl ControlledLedgerFunding {
    pub(super) async fn retain_dispatch_liability(&self) -> Result<(), String> {
        let current = self
            .owner
            .reservation(&self.reservation.reservation_id)
            .await
            .map_err(|e| e.to_string())?;
        if current != self.reservation {
            return Err("controlled original ledger reservation changed".to_owned());
        }
        let issuer = self
            .owner
            .settlement_issuer(&self.issuer_id, self.issuer_epoch)
            .await
            .map_err(|e| e.to_string())?;
        if issuer.revoked || issuer.verifying_key.to_bytes() != self.issuer_key {
            return Err("controlled current settlement issuer differs".to_owned());
        }
        let time = self
            .owner
            .observe_trusted_time_attestation(&self.time_provider.signed_time()?)
            .await
            .map_err(|e| e.to_string())?;
        let dispatched = self
            .owner
            .mark_dispatch_attempted(
                &current.reservation_id,
                current.revision,
                current.effect_digest,
                time.clone(),
            )
            .await
            .map_err(|e| e.to_string())?;
        // Accounting has entered the sealed target, but no native whole-U
        // owner exists. Keep liability, never fabricate terminal evidence or
        // refund from a Child exit. Failure leaves DispatchAttempted retained.
        self.owner
            .mark_indeterminate(&dispatched.reservation_id, dispatched.revision, time)
            .await
            .map_err(|e| e.to_string())?;
        Ok(())
    }
}
