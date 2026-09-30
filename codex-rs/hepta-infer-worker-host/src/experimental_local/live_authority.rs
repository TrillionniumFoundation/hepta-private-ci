use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::native::NativeAuthorityObservation;
use serde::Deserialize;
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use super::LocalFuture;
use super::LocalWorkerError;
use super::TrustedClock;
use super::VerifiedResourceGrant;
use super::digest;
use super::validate_digest;
use super::validate_identity;

pub const AUTHORITY_SNAPSHOT_SCHEMA_VERSION: u32 = 1;
pub const DEFAULT_AUTHORITY_MAX_AGE_MS: u64 = 5_000;
pub const DEFAULT_AUTHORITY_POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Independently observed authority state. The provider witness authenticates
/// the source; `snapshot_digest` binds every semantic field below.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TrustedAuthoritySnapshot {
    pub schema_version: u32,
    pub issuer: String,
    pub grant_id: String,
    pub worker_subject: String,
    pub worker_generation: u64,
    pub authority_epoch: u64,
    pub revocation_revision: u64,
    pub revocation_head_digest: String,
    pub revoked_grant_ids: BTreeSet<String>,
    pub grant_witness_digest: String,
    pub provider_witness_digest: String,
    pub observed_at_unix_ms: u64,
    pub snapshot_digest: String,
}

impl TrustedAuthoritySnapshot {
    pub fn expected_snapshot_digest(&self) -> Result<String, LocalWorkerError> {
        let encoded = serde_json::to_vec(&(
            "hepta.local-live-authority-snapshot.v1",
            self.schema_version,
            &self.issuer,
            &self.grant_id,
            &self.worker_subject,
            self.worker_generation,
            self.authority_epoch,
            self.revocation_revision,
            &self.revocation_head_digest,
            &self.revoked_grant_ids,
            &self.grant_witness_digest,
            &self.provider_witness_digest,
            self.observed_at_unix_ms,
        ))
        .map_err(|_| LocalWorkerError::Authority("authority snapshot encoding".to_string()))?;
        Ok(digest(&encoded))
    }

    pub(super) fn to_native(&self) -> NativeAuthorityObservation {
        NativeAuthorityObservation {
            issuer: self.issuer.clone(),
            grant_id: self.grant_id.clone(),
            authority_epoch: self.authority_epoch,
            revocation_revision: self.revocation_revision,
            revocation_head_digest: self.revocation_head_digest.clone(),
            grant_witness_digest: self.grant_witness_digest.clone(),
            authority_snapshot_digest: self.snapshot_digest.clone(),
            observed_at_unix_ms: self.observed_at_unix_ms,
            revoked: self.revoked_grant_ids.contains(&self.grant_id),
        }
    }
}

/// Product composition must implement this port with a protected, monotonic
/// authority source. A model driver must not implement it for its own grant.
pub trait TrustedAuthorityProvider: Send + Sync {
    fn observe<'a>(
        &'a self,
        grant: &'a VerifiedResourceGrant,
    ) -> LocalFuture<'a, TrustedAuthoritySnapshot>;
}

#[derive(Clone, Debug)]
struct AuthorityWatermark {
    authority_epoch: u64,
    revision: u64,
    head_digest: String,
    snapshot_digest: String,
    observed_at_unix_ms: u64,
    revoked: bool,
}

#[derive(Clone)]
pub(super) struct LiveAuthorityMonitor<C> {
    provider: Arc<dyn TrustedAuthorityProvider>,
    clock: C,
    grant: VerifiedResourceGrant,
    maximum_age_ms: u64,
    poll_interval: Duration,
    watermark: Arc<Mutex<Option<AuthorityWatermark>>>,
    last_failure: Arc<Mutex<Option<String>>>,
    last_snapshot: Arc<Mutex<Option<TrustedAuthoritySnapshot>>>,
}

impl<C> LiveAuthorityMonitor<C>
where
    C: TrustedClock + Clone,
{
    pub(super) fn new(
        provider: Arc<dyn TrustedAuthorityProvider>,
        clock: C,
        grant: &VerifiedResourceGrant,
    ) -> Result<Self, LocalWorkerError> {
        grant.ensure_current(&clock, grant.worker_subject(), grant.worker_generation())?;
        Ok(Self {
            provider,
            clock,
            grant: grant.clone(),
            maximum_age_ms: DEFAULT_AUTHORITY_MAX_AGE_MS,
            poll_interval: DEFAULT_AUTHORITY_POLL_INTERVAL,
            watermark: Arc::new(Mutex::new(None)),
            last_failure: Arc::new(Mutex::new(None)),
            last_snapshot: Arc::new(Mutex::new(None)),
        })
    }

    pub(super) fn bind_deadline(
        &self,
        requested_deadline_ms: u64,
    ) -> Result<super::TrustedDeadline, LocalWorkerError> {
        self.grant.bind_deadline(&self.clock, requested_deadline_ms)
    }

    pub(super) async fn require_current(
        &self,
    ) -> Result<TrustedAuthoritySnapshot, LocalWorkerError> {
        let snapshot = self.provider.observe(&self.grant).await?;
        *self
            .last_snapshot
            .lock()
            .map_err(|_| LocalWorkerError::ResourceStatePoisoned)? = Some(snapshot.clone());
        match self.validate_snapshot(&snapshot) {
            Ok(()) => {
                *self
                    .last_failure
                    .lock()
                    .map_err(|_| LocalWorkerError::ResourceStatePoisoned)? = None;
                Ok(snapshot)
            }
            Err(error) => {
                *self
                    .last_failure
                    .lock()
                    .map_err(|_| LocalWorkerError::ResourceStatePoisoned)? =
                    Some(error.to_string());
                Err(error)
            }
        }
    }

    pub(super) async fn cancel_when_invalid(&self, cancellation: &CancellationToken) {
        loop {
            tokio::select! {
                _ = cancellation.cancelled() => return,
                _ = tokio::time::sleep(self.poll_interval) => {}
            }
            if self.require_current().await.is_err() {
                cancellation.cancel();
                return;
            }
        }
    }

    pub(super) fn last_failure(&self) -> Option<String> {
        self.last_failure
            .lock()
            .ok()
            .and_then(|value| value.clone())
    }

    pub(super) fn last_snapshot(&self) -> Option<TrustedAuthoritySnapshot> {
        self.last_snapshot
            .lock()
            .ok()
            .and_then(|value| value.clone())
    }

    fn validate_snapshot(
        &self,
        snapshot: &TrustedAuthoritySnapshot,
    ) -> Result<(), LocalWorkerError> {
        let claims = self.grant.claims();
        validate_identity(&snapshot.issuer, "live authority issuer")?;
        validate_identity(&snapshot.grant_id, "live authority grant")?;
        validate_identity(&snapshot.worker_subject, "live authority subject")?;
        for (value, field) in [
            (&snapshot.revocation_head_digest, "live revocation head"),
            (&snapshot.grant_witness_digest, "live grant witness"),
            (&snapshot.provider_witness_digest, "live provider witness"),
            (&snapshot.snapshot_digest, "live authority snapshot"),
        ] {
            validate_digest(value, field)?;
        }
        for grant_id in &snapshot.revoked_grant_ids {
            validate_identity(grant_id, "live revoked grant")?;
        }
        if snapshot.schema_version != AUTHORITY_SNAPSHOT_SCHEMA_VERSION
            || snapshot.issuer != claims.issuer
            || snapshot.grant_id != claims.grant_id
            || snapshot.worker_subject != claims.worker_subject
            || snapshot.worker_generation != claims.worker_generation
            || snapshot.authority_epoch != claims.authority_epoch
            || snapshot.revocation_revision < claims.revocation_revision
            || snapshot.grant_witness_digest != self.grant.witness_digest()
            || snapshot.observed_at_unix_ms == 0
            || snapshot.expected_snapshot_digest()? != snapshot.snapshot_digest
        {
            return Err(LocalWorkerError::StaleAuthorityFrontier);
        }
        let expected_head = digest(
            &serde_json::to_vec(&(
                "hepta.local-resource-revocations.v1",
                snapshot.authority_epoch,
                snapshot.revocation_revision,
                &snapshot.revoked_grant_ids,
            ))
            .map_err(|_| LocalWorkerError::Authority(
                "live revocation frontier encoding".to_string(),
            ))?,
        );
        if expected_head != snapshot.revocation_head_digest
            || (snapshot.revocation_revision == claims.revocation_revision
                && snapshot.revocation_head_digest != claims.revocation_head_digest)
        {
            return Err(LocalWorkerError::StaleAuthorityFrontier);
        }
        let revoked = snapshot.revoked_grant_ids.contains(&claims.grant_id);
        self.grant.ensure_current(
            &self.clock,
            &snapshot.worker_subject,
            snapshot.worker_generation,
        )?;
        let now_ms = self.clock.now_ms()?;
        if snapshot.observed_at_unix_ms > now_ms
            || now_ms.saturating_sub(snapshot.observed_at_unix_ms) > self.maximum_age_ms
        {
            return Err(LocalWorkerError::StaleAuthorityFrontier);
        }

        let mut watermark = self
            .watermark
            .lock()
            .map_err(|_| LocalWorkerError::ResourceStatePoisoned)?;
        if let Some(previous) = watermark.as_ref()
            && (snapshot.authority_epoch < previous.authority_epoch
                || (snapshot.authority_epoch == previous.authority_epoch
                    && snapshot.revocation_revision < previous.revision)
                || snapshot.observed_at_unix_ms < previous.observed_at_unix_ms
                || (snapshot.authority_epoch == previous.authority_epoch
                    && snapshot.revocation_revision == previous.revision
                    && snapshot.revocation_head_digest != previous.head_digest)
                || (snapshot.observed_at_unix_ms == previous.observed_at_unix_ms
                    && snapshot.snapshot_digest != previous.snapshot_digest)
                || (previous.revoked && !revoked))
        {
            return Err(LocalWorkerError::StaleAuthorityFrontier);
        }
        *watermark = Some(AuthorityWatermark {
            authority_epoch: snapshot.authority_epoch,
            revision: snapshot.revocation_revision,
            head_digest: snapshot.revocation_head_digest.clone(),
            snapshot_digest: snapshot.snapshot_digest.clone(),
            observed_at_unix_ms: snapshot.observed_at_unix_ms,
            revoked,
        });
        if revoked {
            return Err(LocalWorkerError::GrantRevoked);
        }
        Ok(())
    }
}

#[cfg(test)]
pub(super) struct PinnedAuthorityProvider {
    snapshot: TrustedAuthoritySnapshot,
}

#[cfg(test)]
impl PinnedAuthorityProvider {
    pub(super) fn new<C: TrustedClock>(
        grant: &VerifiedResourceGrant,
        clock: &C,
    ) -> Result<Self, LocalWorkerError> {
        let claims = grant.claims();
        let mut snapshot = TrustedAuthoritySnapshot {
            schema_version: AUTHORITY_SNAPSHOT_SCHEMA_VERSION,
            issuer: claims.issuer.clone(),
            grant_id: claims.grant_id.clone(),
            worker_subject: claims.worker_subject.clone(),
            worker_generation: claims.worker_generation,
            authority_epoch: claims.authority_epoch,
            revocation_revision: claims.revocation_revision,
            revocation_head_digest: claims.revocation_head_digest.clone(),
            revoked_grant_ids: BTreeSet::new(),
            grant_witness_digest: grant.witness_digest().to_string(),
            provider_witness_digest: digest(b"test-only-pinned-authority-provider"),
            observed_at_unix_ms: clock.now_ms()?,
            snapshot_digest: String::new(),
        };
        snapshot.snapshot_digest = snapshot.expected_snapshot_digest()?;
        Ok(Self { snapshot })
    }
}

#[cfg(test)]
impl TrustedAuthorityProvider for PinnedAuthorityProvider {
    fn observe<'a>(
        &'a self,
        _grant: &'a VerifiedResourceGrant,
    ) -> LocalFuture<'a, TrustedAuthoritySnapshot> {
        let snapshot = self.snapshot.clone();
        Box::pin(async move { Ok(snapshot) })
    }
}
