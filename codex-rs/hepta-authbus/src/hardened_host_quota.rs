use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::AuthBusAuthorityHost;
use crate::AuthBusAuthorityError;
use crate::ExpiredReservationSweep;
use crate::PolicyDecision;
use crate::QuotaReservation;
use crate::QuotaSnapshot;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::TrustedTimeSample;

impl AuthBusAuthorityHost {
    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.create_quota(spec, time).await
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.replace_quota(spec, expected_revision, time).await
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.reserve(decision, request, time).await
    }

    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
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
        let _fence = self.write_fence.lock().await;
        self.inner
            .mark_indeterminate(reservation_id, expected_revision, time)
            .await
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
            .cancel_reservation(reservation_id, expected_revision, time)
            .await
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
            .reconcile_expired_reservation(reservation_id, expected_revision, time)
            .await
    }

    pub async fn reconcile_expired_reservations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<ExpiredReservationSweep, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        let sweep = self
            .maintenance
            .reconcile_expired_reservations(time, limit)
            .await?;
        self.inner.sync_checkpoint().await?;
        Ok(sweep)
    }

    pub async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
            .compact_terminal_reservations(older_than_ms, limit)
            .await
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.quota_snapshot(quota_key).await
    }

    pub async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.reservation(reservation_id).await
    }
}
