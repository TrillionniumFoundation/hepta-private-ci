use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;
use crate::AuthPolicy;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::IssuerRegistration;
use crate::IssuerRetirement;
use crate::IssuerSpec;
use crate::PolicyDecision;
use crate::PolicySpec;
use crate::QuotaReservation;
use crate::QuotaSnapshot;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::Settlement;
use crate::SignedSettlementEvidence;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeSample;

/// Administrative authority for issuer, policy and quota configuration.
pub struct AuthBusAdminPort<'host> {
    pub(crate) host: &'host AuthBusAuthorityHost,
}

/// Minimum capability required by one registered external-effect adapter.
#[derive(Clone, Copy)]
pub struct AuthBusEffectPort<'host> {
    pub(crate) host: &'host AuthBusAuthorityHost,
}

/// Observation-only access to AuthBus authority state.
#[derive(Clone, Copy)]
pub struct AuthBusReadPort<'host> {
    pub(crate) host: &'host AuthBusAuthorityHost,
}

/// Converts an enrolled caller into the bounded AuthBus effect capability.
/// Production implementations expose only `AuthBusEffectPort` here.
pub trait AsAuthBusEffectPort {
    fn as_authbus_effect_port(&self) -> AuthBusEffectPort<'_>;
}

impl AsAuthBusEffectPort for AuthBusEffectPort<'_> {
    fn as_authbus_effect_port(&self) -> AuthBusEffectPort<'_> {
        AuthBusEffectPort { host: self.host }
    }
}

#[cfg(feature = "test-support")]
impl AsAuthBusEffectPort for AuthBusAuthorityHost {
    fn as_authbus_effect_port(&self) -> AuthBusEffectPort<'_> {
        self.effect_port()
    }
}

impl AuthBusAdminPort<'_> {
    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.host.enroll_issuer_inner(purpose, spec).await
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.host
            .rotate_issuer_inner(purpose, spec, expected_epoch, expected_revision)
            .await
    }

    pub async fn revoke_issuer(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.host
            .revoke_issuer_inner(purpose, issuer_id, key_epoch, expected_revision)
            .await
    }

    pub async fn retire_issuer_epoch(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRetirement, AuthBusAuthorityError> {
        self.host
            .retire_issuer_epoch_inner(purpose, issuer_id, key_epoch, expected_revision)
            .await
    }

    pub async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.host.create_policy_inner(spec, time).await
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.host
            .replace_policy_inner(spec, expected_revision, time)
            .await
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.host
            .revoke_policy_inner(policy_id, expected_revision, time)
            .await
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        self.host
            .retire_policy_inner(policy_id, expected_revision, retired_at_ms)
            .await
    }

    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.host.create_quota_inner(spec, time).await
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.host
            .replace_quota_inner(spec, expected_revision, time)
            .await
    }

    pub async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        self.host
            .compact_terminal_reservations_inner(older_than_ms, limit)
            .await
    }
}

impl AuthBusEffectPort<'_> {
    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        self.host
            .observe_trusted_time_attestation_inner(attestation)
            .await
    }

    pub async fn authorize(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        self.host
            .authorize_inner(principal, action, scope_digest, policy_revision, time)
            .await
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host.reserve_inner(decision, request, time).await
    }

    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .mark_dispatch_attempted_inner(
                reservation_id,
                expected_revision,
                dispatch_digest,
                time,
            )
            .await
    }

    pub async fn mark_indeterminate(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .mark_indeterminate_inner(reservation_id, expected_revision, time)
            .await
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .cancel_reservation_inner(reservation_id, expected_revision, time)
            .await
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .reconcile_expired_reservation_inner(reservation_id, expected_revision, time)
            .await
    }

    pub async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        self.host.settle_inner(evidence, time).await
    }
}

impl AuthBusReadPort<'_> {
    pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        self.host.sync_checkpoint().await
    }

    pub async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        self.host.message_issuer_inner(issuer_id, key_epoch).await
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.host.quota_snapshot_inner(quota_key).await
    }

    pub async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host.reservation_inner(reservation_id).await
    }
}
