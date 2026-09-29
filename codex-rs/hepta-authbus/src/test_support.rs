//! Explicit compatibility helpers for cross-crate source tests.
//! This module is absent from production builds.

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

impl AuthBusAuthorityHost {
    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.admin_port().enroll_issuer(purpose, spec).await
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.admin_port()
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
        self.admin_port()
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
        self.admin_port()
            .retire_issuer_epoch(purpose, issuer_id, key_epoch, expected_revision)
            .await
    }

    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        self.effect_port()
            .observe_trusted_time_attestation(attestation)
            .await
    }

    pub async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        self.read_port().message_issuer(issuer_id, key_epoch).await
    }

    pub async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.admin_port().create_policy(spec, time).await
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.admin_port()
            .replace_policy(spec, expected_revision, time)
            .await
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.admin_port()
            .revoke_policy(policy_id, expected_revision, time)
            .await
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        self.admin_port()
            .retire_policy(policy_id, expected_revision, retired_at_ms)
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
        self.effect_port()
            .authorize(principal, action, scope_digest, policy_revision, time)
            .await
    }

    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.admin_port().create_quota(spec, time).await
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.admin_port()
            .replace_quota(spec, expected_revision, time)
            .await
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.effect_port().reserve(decision, request, time).await
    }

    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.effect_port()
            .mark_dispatch_attempted(
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
        self.effect_port()
            .mark_indeterminate(reservation_id, expected_revision, time)
            .await
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.effect_port()
            .cancel_reservation(reservation_id, expected_revision, time)
            .await
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.effect_port()
            .reconcile_expired_reservation(reservation_id, expected_revision, time)
            .await
    }

    pub async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        self.effect_port().settle(evidence, time).await
    }

    pub async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        self.admin_port()
            .compact_terminal_reservations(older_than_ms, limit)
            .await
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.read_port().quota_snapshot(quota_key).await
    }

    pub async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.read_port().reservation(reservation_id).await
    }
}
