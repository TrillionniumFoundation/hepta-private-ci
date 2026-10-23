//! Final product guard for the V2 checkpoint coordinator.
//!
//! The reviewed fenced coordinator remains the implementation owner. This
//! wrapper adds a closed-world open boundary: the in-memory trust registry must
//! equal the durable active manifest before any product operation proceeds.
//! Artifact publication is additionally rechecked by the durable facade inside
//! the same `BEGIN IMMEDIATE` transaction that writes the checkpoint and outbox.

#[path = "fenced_coordinator.rs"]
mod original;

use std::str::FromStr;

use codex_hepta_types::Digest32;
use sqlx::sqlite::{
    SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous,
};
use sqlx::{Row, SqlitePool};

use crate::coordinator::{
    CompactionCoordinatorErrorV2, CompactionPublicationReceiptV2,
    VerifiedCompactionSelectionV2,
};
use crate::durable::{DurableCompactionError, DurableCompactionOutboxEventV1};
use crate::VerifiedCompactionPublicationV1;

pub const MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2: &str =
    original::MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2;

/// Closed-world product owner for durable compaction checkpoints.
///
/// The wrapped implementation still owns lease acquisition, nonce reservation,
/// admissions, source-retention release and all recovery behavior. This type
/// refuses to open or operate when a supplied manifest chain is older than the
/// durable active manifest for the owner.
#[derive(Clone)]
pub struct MemoryCheckpointCoordinatorV2 {
    inner: original::MemoryCheckpointCoordinatorV2,
    metadata: SqlitePool,
    root_key_digest: Digest32,
}

impl MemoryCheckpointCoordinatorV2 {
    #[allow(clippy::too_many_arguments)]
    pub async fn open(
        database_url: &str,
        owner_id: &str,
        pinned_root_key: [u8; 32],
        manifest_bytes: &[u8],
        lease_token: &str,
        lease_epoch: u64,
        lease_expires_at_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<Self, CompactionCoordinatorErrorV2> {
        Self::open_with_manifest_chain(
            database_url,
            owner_id,
            pinned_root_key,
            &[manifest_bytes.to_vec()],
            lease_token,
            lease_epoch,
            lease_expires_at_unix_seconds,
            now_unix_seconds,
        )
        .await
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn open_with_manifest_chain(
        database_url: &str,
        owner_id: &str,
        pinned_root_key: [u8; 32],
        manifest_chain: &[Vec<u8>],
        lease_token: &str,
        lease_epoch: u64,
        lease_expires_at_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<Self, CompactionCoordinatorErrorV2> {
        let inner = original::MemoryCheckpointCoordinatorV2::open_with_manifest_chain(
            database_url,
            owner_id,
            pinned_root_key,
            manifest_chain,
            lease_token,
            lease_epoch,
            lease_expires_at_unix_seconds,
            now_unix_seconds,
        )
        .await?;
        let value = Self {
            inner,
            metadata: open_pool(database_url).await?,
            root_key_digest: Digest32::of_bytes(&pinned_root_key),
        };
        value
            .verify_expected_active_manifest(value.inner.active_registry_digest())
            .await?;
        Ok(value)
    }

    #[must_use]
    pub fn owner_id(&self) -> &str {
        self.inner.owner_id()
    }

    #[must_use]
    pub fn active_registry_digest(&self) -> Digest32 {
        self.inner.active_registry_digest()
    }

    pub async fn renew_lease(
        &self,
        lease_expires_at_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        self.inner
            .renew_lease(lease_expires_at_unix_seconds, now_unix_seconds)
            .await
    }

    pub async fn install_successor_manifest(
        &mut self,
        manifest_bytes: &[u8],
        now_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        let mut candidate = self.inner.clone();
        let digest = candidate
            .install_successor_manifest(manifest_bytes, now_unix_seconds)
            .await?;
        self.verify_expected_active_manifest(digest).await?;
        self.inner = candidate;
        Ok(digest)
    }

    pub async fn publish_verified_checkpoint(
        &self,
        idempotency_key: &str,
        publication: &VerifiedCompactionPublicationV1,
        retain_source_until_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<CompactionPublicationReceiptV2, CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        self.inner
            .publish_verified_checkpoint(
                idempotency_key,
                publication,
                retain_source_until_unix_seconds,
                now_unix_seconds,
            )
            .await
    }

    pub async fn recover_current_checkpoint(
        &self,
        scope_id: &str,
        purpose_id: &str,
        now_unix_seconds: u64,
    ) -> Result<Option<VerifiedCompactionSelectionV2>, CompactionCoordinatorErrorV2> {
        let expected = self.active_registry_digest();
        self.verify_expected_active_manifest(expected).await?;
        let selection = self
            .inner
            .recover_current_checkpoint(scope_id, purpose_id, now_unix_seconds)
            .await?;
        self.verify_expected_active_manifest(expected).await?;
        Ok(selection)
    }

    pub async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        self.inner
            .revoke_checkpoint(
                checkpoint_digest,
                reason_digest,
                revoked_at_unix_seconds,
            )
            .await
    }

    pub async fn release_source_retention(
        &self,
        checkpoint_digest: Digest32,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        self.inner
            .release_source_retention(checkpoint_digest, now_unix_seconds)
            .await
    }

    pub async fn claim_next_outbox(
        &self,
        now_unix_seconds: u64,
        claim_token: &str,
    ) -> Result<Option<DurableCompactionOutboxEventV1>, CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        self.inner
            .claim_next_outbox(now_unix_seconds, claim_token)
            .await
    }

    pub async fn complete_outbox(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        self.inner
            .complete_outbox(event, delivered_at_unix_seconds)
            .await
    }

    pub async fn reconcile_claims(
        &self,
        retry_at_unix_seconds: u64,
    ) -> Result<u64, CompactionCoordinatorErrorV2> {
        self.verify_expected_active_manifest(self.active_registry_digest())
            .await?;
        self.inner.reconcile_claims(retry_at_unix_seconds).await
    }

    pub async fn verify_integrity(
        &self,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        let expected = self.active_registry_digest();
        self.verify_expected_active_manifest(expected).await?;
        self.inner.verify_integrity(now_unix_seconds).await?;
        self.verify_expected_active_manifest(expected).await
    }

    async fn verify_expected_active_manifest(
        &self,
        expected_manifest: Digest32,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        let row = sqlx::query(
            "SELECT a.manifest_digest, a.sequence,
                    m.root_key_digest
             FROM active_compaction_manifest_v2 AS a
             JOIN compaction_manifest_log_v2 AS m
               ON m.owner_id = a.owner_id
              AND m.manifest_digest = a.manifest_digest
             WHERE a.owner_id = ?",
        )
        .bind(self.owner_id())
        .fetch_optional(&self.metadata)
        .await
        .map_err(sql_error)?
        .ok_or_else(|| manifest_conflict("durable active trust manifest is absent"))?;
        let manifest: String = row.try_get("manifest_digest").map_err(sql_error)?;
        let sequence: i64 = row.try_get("sequence").map_err(sql_error)?;
        let root: String = row.try_get("root_key_digest").map_err(sql_error)?;
        if manifest != expected_manifest.to_string()
            || sequence <= 0
            || root != self.root_key_digest.to_string()
        {
            return Err(manifest_conflict(
                "supplied trust chain is stale, forked or bound to another root",
            ));
        }
        Ok(())
    }
}

async fn open_pool(
    database_url: &str,
) -> Result<SqlitePool, CompactionCoordinatorErrorV2> {
    let options = SqliteConnectOptions::from_str(database_url)
        .map_err(sql_error)?
        .create_if_missing(true)
        .foreign_keys(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full);
    SqlitePoolOptions::new()
        .max_connections(4)
        .connect_with(options)
        .await
        .map_err(sql_error)
}

fn sql_error(error: sqlx::Error) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Sql(error))
}

fn manifest_conflict(message: impl Into<String>) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Conflict(
        message.into(),
    ))
}
