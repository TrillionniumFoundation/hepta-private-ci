//! Capability-scoped views of the sole AuthBus authority owner.
//!
//! The host owns storage, checkpoint publication and the single-writer fence.
//! Callers receive only the narrow borrowed port required by their role; none of
//! these values can outlive or reconstruct the owner.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AuthBusArchiveCapacitySnapshot;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;
use crate::AuthBusMaintenanceReport;
use crate::AuthBusOperationalSnapshot;
use crate::AuthBusSloPolicy;
use crate::AuthPolicy;
use crate::ExpiredReservationSweep;
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
use crate::SettlementIssuerRegistration;
use crate::SignedSettlementEvidence;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeSample;

#[derive(Clone, Copy)]
pub struct AuthBusAdminPort<'a> {
    host: &'a AuthBusAuthorityHost,
}

#[derive(Clone, Copy)]
pub struct AuthBusExecutionPort<'a> {
    host: &'a AuthBusAuthorityHost,
}

#[derive(Clone, Copy)]
pub struct AuthBusReadPort<'a> {
    host: &'a AuthBusAuthorityHost,
}

#[derive(Clone, Copy)]
pub struct AuthBusMaintenancePort<'a> {
    host: &'a AuthBusAuthorityHost,
}

impl AuthBusAuthorityHost {
    #[must_use]
    pub fn admin(&self) -> AuthBusAdminPort<'_> {
        AuthBusAdminPort { host: self }
    }

    #[must_use]
    pub fn execution(&self) -> AuthBusExecutionPort<'_> {
        AuthBusExecutionPort { host: self }
    }

    #[must_use]
    pub fn read(&self) -> AuthBusReadPort<'_> {
        AuthBusReadPort { host: self }
    }

    #[must_use]
    pub fn maintenance(&self) -> AuthBusMaintenancePort<'_> {
        AuthBusMaintenancePort { host: self }
    }
}

impl AuthBusAdminPort<'_> {
    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.host.enroll_issuer(purpose, spec).await
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.host
            .rotate_issuer(purpose, spec, expected_epoch, expected_revision)
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
            .revoke_issuer(purpose, issuer_id, key_epoch, expected_revision)
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
            .retire_issuer_epoch(purpose, issuer_id, key_epoch, expected_revision)
            .await
    }

    pub async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.host.create_policy(spec, time).await
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.host
            .replace_policy(spec, expected_revision, time)
            .await
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.host
            .revoke_policy(policy_id, expected_revision, time)
            .await
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        self.host
            .retire_policy(policy_id, expected_revision, retired_at_ms)
            .await
    }

    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.host.create_quota(spec, time).await
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.host.replace_quota(spec, expected_revision, time).await
    }
}

impl AuthBusExecutionPort<'_> {
    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        self.host
            .observe_trusted_time_attestation(attestation)
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
            .authorize(principal, action, scope_digest, policy_revision, time)
            .await
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host.reserve(decision, request, time).await
    }

    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .mark_dispatch_attempted(reservation_id, expected_revision, dispatch_digest, time)
            .await
    }

    pub async fn mark_indeterminate(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .mark_indeterminate(reservation_id, expected_revision, time)
            .await
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .cancel_reservation(reservation_id, expected_revision, time)
            .await
    }

    pub async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        self.host.settle(evidence, time).await
    }
}

impl AuthBusReadPort<'_> {
    pub async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        self.host.message_issuer(issuer_id, key_epoch).await
    }

    pub async fn settlement_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<SettlementIssuerRegistration, AuthBusAuthorityError> {
        self.host.settlement_issuer(issuer_id, key_epoch).await
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.host.quota_snapshot(quota_key).await
    }

    pub async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host.reservation(reservation_id).await
    }

    pub async fn operational_snapshot(
        &self,
        time: &TrustedTimeSample,
    ) -> Result<AuthBusOperationalSnapshot, AuthBusAuthorityError> {
        self.host.operational_snapshot(time).await
    }

    /// Read-only capacity diagnostics. This projection is not effect authority
    /// and never authorizes archive deletion.
    pub async fn archive_capacity_snapshot(
        &self,
        time: &TrustedTimeSample,
    ) -> Result<AuthBusArchiveCapacitySnapshot, AuthBusAuthorityError> {
        self.host.store.archive_capacity_snapshot(time).await
    }
}

impl AuthBusMaintenancePort<'_> {
    pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        self.host.sync_checkpoint().await
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.host
            .reconcile_expired_reservation(reservation_id, expected_revision, time)
            .await
    }

    pub async fn sweep_expired_reservations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<ExpiredReservationSweep, AuthBusAuthorityError> {
        self.host.sweep_expired_reservations(time, limit).await
    }

    pub async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        self.host
            .compact_terminal_reservations(older_than_ms, limit)
            .await
    }

    pub async fn maintenance_tick(
        &self,
        time: TrustedTimeSample,
        limit: u32,
        policy: AuthBusSloPolicy,
    ) -> Result<AuthBusMaintenanceReport, AuthBusAuthorityError> {
        self.host.maintenance_tick(time, limit, policy).await
    }
}
