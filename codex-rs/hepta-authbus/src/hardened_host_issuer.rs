use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::AuthBusAuthorityHost;
use crate::AuthBusAuthorityError;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::IssuerRegistration;
use crate::IssuerRetirement;
use crate::IssuerSpec;
use crate::Settlement;
use crate::SettlementIssuerRegistration;
use crate::SignedSettlementEvidence;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeSample;

impl AuthBusAuthorityHost {
    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.enroll_issuer(purpose, spec).await
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner
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
        let _fence = self.write_fence.lock().await;
        self.inner
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
        let _fence = self.write_fence.lock().await;
        self.inner
            .retire_issuer_epoch(purpose, issuer_id, key_epoch, expected_revision)
            .await
    }

    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.observe_trusted_time_attestation(attestation).await
    }

    pub async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.message_issuer(issuer_id, key_epoch).await
    }

    pub async fn settlement_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<SettlementIssuerRegistration, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.settlement_issuer(issuer_id, key_epoch).await
    }

    /// Resolve the signed issuer ID and epoch from the durable registry while
    /// holding the sole-writer fence. The caller-supplied sealed handle is only
    /// an identity assertion and its key/state are never trusted for settlement.
    pub async fn settle(
        &self,
        issuer: &SettlementIssuerRegistration,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        if issuer.purpose() != IssuerPurpose::Settlement
            || issuer.issuer_id() != &evidence.claims.issuer_id
            || issuer.key_epoch() != evidence.claims.key_epoch
        {
            return Err(AuthBusAuthorityError::SettlementIssuerMismatch);
        }
        let resolved = self
            .inner
            .settlement_issuer(&evidence.claims.issuer_id, evidence.claims.key_epoch)
            .await?;
        self.inner.settle(&resolved, evidence, time).await
    }
}
