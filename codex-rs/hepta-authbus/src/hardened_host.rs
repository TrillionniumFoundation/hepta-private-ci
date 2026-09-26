use std::path::Path;
use std::path::PathBuf;

use crate::AuthBusAlertKind;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthBusHealthSnapshot;
use crate::AuthBusMaintenanceReport;
use crate::AuthBusSloThresholds;
use crate::owner::AuthorityOwnerGuard;

#[path = "hardened_host_issuer.rs"]
mod issuer;
#[path = "hardened_host_policy.rs"]
mod policy;
#[path = "hardened_host_quota.rs"]
mod quota;

const STARTUP_SWEEP_LIMIT: u32 = 256;

/// The only exported writer for durable AuthBus authority state.
///
/// A process-lifetime owner fence is acquired before SQLite or the external
/// checkpoint is opened. The historical implementation is private and can only
/// be reached through this wrapper, so callers cannot bypass the fence.
pub struct AuthBusAuthorityHost {
    inner: crate::host::AuthBusAuthorityHost,
    maintenance: AuthBusAuthorityStore,
    _owner: AuthorityOwnerGuard,
    write_fence: tokio::sync::Mutex<()>,
}

impl AuthBusAuthorityHost {
    pub async fn open(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        let owner = AuthorityOwnerGuard::acquire(database_path, owner_id)?;
        let inner = crate::host::AuthBusAuthorityHost::open(
            database_path,
            checkpoint_path,
            owner_id,
        )
        .await?;
        let maintenance = AuthBusAuthorityStore::open(database_path).await?;
        let host = Self {
            inner,
            maintenance,
            _owner: owner,
            write_fence: tokio::sync::Mutex::new(()),
        };
        host.recover_expired_on_startup().await?;
        host.inner.sync_checkpoint().await?;
        Ok(host)
    }

    async fn recover_expired_on_startup(&self) -> Result<(), AuthBusAuthorityError> {
        let Some(time) = self.maintenance.last_trusted_time().await? else {
            return Ok(());
        };
        loop {
            let sweep = self
                .maintenance
                .reconcile_expired_reservations(time.clone(), STARTUP_SWEEP_LIMIT)
                .await?;
            if sweep.scanned() < STARTUP_SWEEP_LIMIT {
                break;
            }
        }
        Ok(())
    }

    pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.sync_checkpoint().await
    }

    pub async fn health_snapshot(
        &self,
        observed_at_ms: u64,
    ) -> Result<AuthBusHealthSnapshot, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        self.inner.sync_checkpoint().await?;
        self.maintenance.health_snapshot(observed_at_ms).await
    }

    /// One bounded authority-worker cycle. Product ownership must invoke this
    /// at startup and periodically; each transaction has an explicit bound.
    pub async fn maintenance_tick(
        &self,
        time: crate::TrustedTimeSample,
        sweep_limit: u32,
        compact_before_ms: u64,
        compact_limit: u32,
        observed_at_ms: u64,
        thresholds: AuthBusSloThresholds,
    ) -> Result<AuthBusMaintenanceReport, AuthBusAuthorityError> {
        let _fence = self.write_fence.lock().await;
        let sweep = self
            .maintenance
            .reconcile_expired_reservations(time, sweep_limit)
            .await?;
        let compacted_terminal_reservations = self
            .inner
            .compact_terminal_reservations(compact_before_ms, compact_limit)
            .await?;
        let health = self.maintenance.health_snapshot(observed_at_ms).await?;
        let alerts: Vec<AuthBusAlertKind> = health.alerts(observed_at_ms, thresholds);
        self.inner.sync_checkpoint().await?;
        Ok(AuthBusMaintenanceReport {
            sweep,
            compacted_terminal_reservations,
            health,
            alerts,
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        })
    }
}
