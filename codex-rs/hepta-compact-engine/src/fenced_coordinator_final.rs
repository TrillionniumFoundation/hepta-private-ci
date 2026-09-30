//! Closed-world, preflighted product boundary for the V2 checkpoint owner.
//!
//! The guarded coordinator performs continuous durable-manifest checks. This
//! outermost facade additionally verifies the complete signed manifest chain
//! and compares its final digest with durable state before the lower layer can
//! acquire or replace an owner lease. A stale chain therefore cannot cause a
//! durable fencing denial of service as a side effect of a rejected open.

#[path = "fenced_coordinator_guarded.rs"]
mod guarded;

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
use crate::recovery::{
    CompactionAdmissionReconciliationSummaryV1,
    CompactionClaimReconciliationSummaryV1, CompactionOperationStatusV1,
    CompactionRecoveryStartupSummaryV1, DurableCompactionOutboxClaimV2,
    RecoveryStoreV1,
};
use crate::{
    VerifiedCompactionPublicationV1, VerifiedCompactionTrustRegistryV1,
};

pub const MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2: &str =
    guarded::MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2;

const DEFAULT_RECOVERY_BATCH: u32 = 256;
const LEGACY_OUTBOX_CLAIM_SECONDS: u64 = 300;
const LEGACY_OUTBOX_WORKER_ID: &str = "legacy-product-worker";

#[derive(Clone)]
pub struct MemoryCheckpointCoordinatorV2 {
    inner: guarded::MemoryCheckpointCoordinatorV2,
    recovery: RecoveryStoreV1,
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
        let expected = verify_supplied_manifest_chain(
            owner_id,
            pinned_root_key,
            manifest_chain,
            now_unix_seconds,
        )?;
        let expected_manifest = expected.manifest_digest();
        let expected_root = expected.root_key_digest();
        let metadata = open_pool(database_url).await?;
        verify_durable_manifest_preflight(
            &metadata,
            owner_id,
            expected_manifest,
            expected_root,
        )
        .await?;

        let inner = guarded::MemoryCheckpointCoordinatorV2::open_with_manifest_chain(
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
        if inner.active_registry_digest() != expected_manifest {
            return Err(manifest_conflict(
                "opened coordinator differs from the preflighted manifest chain",
            ));
        }

        let recovery = RecoveryStoreV1::open(
            database_url,
            owner_id,
            expected_root,
            expected_manifest,
            Digest32::of_bytes(lease_token.as_bytes()),
            lease_epoch,
        )
        .await?;
        recovery.verify_local_state(now_unix_seconds).await?;
        let startup = recovery
            .reconcile_startup(now_unix_seconds, DEFAULT_RECOVERY_BATCH)
            .await?;
        require_safe_startup(startup)?;

        Ok(Self { inner, recovery })
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
        self.inner
            .renew_lease(lease_expires_at_unix_seconds, now_unix_seconds)
            .await?;
        self.recovery.verify_local_state(now_unix_seconds).await
    }

    pub async fn install_successor_manifest(
        &mut self,
        manifest_bytes: &[u8],
        now_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
        let digest = self
            .inner
            .install_successor_manifest(manifest_bytes, now_unix_seconds)
            .await?;
        self.recovery.set_manifest_digest(digest);
        self.recovery.verify_local_state(now_unix_seconds).await?;
        Ok(digest)
    }

    pub async fn publish_verified_checkpoint(
        &self,
        idempotency_key: &str,
        publication: &VerifiedCompactionPublicationV1,
        retain_source_until_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<CompactionPublicationReceiptV2, CompactionCoordinatorErrorV2> {
        let receipt = self
            .inner
            .publish_verified_checkpoint(
                idempotency_key,
                publication,
                retain_source_until_unix_seconds,
                now_unix_seconds,
            )
            .await?;
        let admissions = self
            .recovery
            .reconcile_admissions(now_unix_seconds, DEFAULT_RECOVERY_BATCH)
            .await?;
        require_safe_admissions(admissions)?;
        Ok(receipt)
    }

    pub async fn recover_current_checkpoint(
        &self,
        scope_id: &str,
        purpose_id: &str,
        now_unix_seconds: u64,
    ) -> Result<Option<VerifiedCompactionSelectionV2>, CompactionCoordinatorErrorV2> {
        let claims = self
            .recovery
            .reconcile_claims(now_unix_seconds, DEFAULT_RECOVERY_BATCH)
            .await?;
        require_safe_claims(claims)?;
        let admissions = self
            .recovery
            .reconcile_admissions(now_unix_seconds, DEFAULT_RECOVERY_BATCH)
            .await?;
        require_safe_admissions(admissions)?;
        self.inner
            .recover_current_checkpoint(scope_id, purpose_id, now_unix_seconds)
            .await
    }

    pub async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
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
        self.inner
            .release_source_retention(checkpoint_digest, now_unix_seconds)
            .await
    }

    /// Claim one event under an exact worker, token, owner generation and
    /// bounded deadline. This is the canonical product outbox boundary.
    pub async fn claim_next_outbox_for_worker(
        &self,
        now_unix_seconds: u64,
        worker_id: &str,
        claim_token: &str,
        claim_deadline_unix_seconds: u64,
    ) -> Result<Option<DurableCompactionOutboxClaimV2>, CompactionCoordinatorErrorV2> {
        self.recovery
            .claim_next_outbox(
                now_unix_seconds,
                worker_id,
                claim_token,
                claim_deadline_unix_seconds,
            )
            .await
    }

    /// Compatibility adapter. New callers must use
    /// `claim_next_outbox_for_worker` so worker and deadline are explicit.
    pub async fn claim_next_outbox(
        &self,
        now_unix_seconds: u64,
        claim_token: &str,
    ) -> Result<Option<DurableCompactionOutboxEventV1>, CompactionCoordinatorErrorV2> {
        let deadline = now_unix_seconds
            .checked_add(LEGACY_OUTBOX_CLAIM_SECONDS)
            .ok_or(CompactionCoordinatorErrorV2::Invalid(
                "outbox claim deadline overflow",
            ))?;
        Ok(self
            .claim_next_outbox_for_worker(
                now_unix_seconds,
                LEGACY_OUTBOX_WORKER_ID,
                claim_token,
                deadline,
            )
            .await?
            .map(|claim| claim.event))
    }

    pub async fn complete_outbox_claim(
        &self,
        claim: &DurableCompactionOutboxClaimV2,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.recovery
            .complete_outbox_claim(claim, delivered_at_unix_seconds)
            .await
    }

    /// Compatibility adapter for callers that received the legacy event type.
    pub async fn complete_outbox(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.recovery
            .complete_legacy_outbox(event, delivered_at_unix_seconds)
            .await
    }

    pub async fn reconcile_claims_bounded(
        &self,
        retry_at_unix_seconds: u64,
        limit: u32,
    ) -> Result<CompactionClaimReconciliationSummaryV1, CompactionCoordinatorErrorV2> {
        let summary = self
            .recovery
            .reconcile_claims(retry_at_unix_seconds, limit)
            .await?;
        require_safe_claims(summary)?;
        Ok(summary)
    }

    pub async fn reconcile_claims(
        &self,
        retry_at_unix_seconds: u64,
    ) -> Result<u64, CompactionCoordinatorErrorV2> {
        Ok(self
            .reconcile_claims_bounded(retry_at_unix_seconds, DEFAULT_RECOVERY_BATCH)
            .await?
            .requeued)
    }

    pub async fn reconcile_admissions(
        &self,
        now_unix_seconds: u64,
        limit: u32,
    ) -> Result<CompactionAdmissionReconciliationSummaryV1, CompactionCoordinatorErrorV2> {
        let summary = self
            .recovery
            .reconcile_admissions(now_unix_seconds, limit)
            .await?;
        require_safe_admissions(summary)?;
        Ok(summary)
    }

    pub async fn reconcile_startup(
        &self,
        now_unix_seconds: u64,
        limit: u32,
    ) -> Result<CompactionRecoveryStartupSummaryV1, CompactionCoordinatorErrorV2> {
        let summary = self
            .recovery
            .reconcile_startup(now_unix_seconds, limit)
            .await?;
        require_safe_startup(summary)?;
        Ok(summary)
    }

    /// Query the original idempotency identity after response loss. A caller
    /// must not mint a new operation key to infer whether publication committed.
    pub async fn query_operation(
        &self,
        idempotency_key: &str,
    ) -> Result<CompactionOperationStatusV1, CompactionCoordinatorErrorV2> {
        self.recovery.query_operation(idempotency_key).await
    }

    pub async fn verify_integrity(
        &self,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.inner.verify_integrity(now_unix_seconds).await?;
        self.recovery.verify_local_state(now_unix_seconds).await
    }
}

fn require_safe_startup(
    summary: CompactionRecoveryStartupSummaryV1,
) -> Result<(), CompactionCoordinatorErrorV2> {
    require_safe_claims(summary.claims)?;
    require_safe_admissions(summary.admissions)
}

fn require_safe_claims(
    summary: CompactionClaimReconciliationSummaryV1,
) -> Result<(), CompactionCoordinatorErrorV2> {
    if summary.quarantined_orphans != 0 {
        return Err(manifest_corrupt(
            "outbox contains claimed events without an authoritative claim lease",
        ));
    }
    Ok(())
}

fn require_safe_admissions(
    summary: CompactionAdmissionReconciliationSummaryV1,
) -> Result<(), CompactionCoordinatorErrorV2> {
    if summary.indeterminate != 0
        || summary.terminal_failure != 0
        || summary.quarantined != 0
    {
        return Err(manifest_corrupt(
            "publication admission recovery found an indeterminate or terminal state",
        ));
    }
    Ok(())
}

fn verify_supplied_manifest_chain(
    owner_id: &str,
    pinned_root_key: [u8; 32],
    manifest_chain: &[Vec<u8>],
    now_unix_seconds: u64,
) -> Result<VerifiedCompactionTrustRegistryV1, CompactionCoordinatorErrorV2> {
    if manifest_chain.is_empty() {
        return Err(CompactionCoordinatorErrorV2::Invalid(
            "at least one signed trust manifest is required",
        ));
    }
    let mut previous: Option<VerifiedCompactionTrustRegistryV1> = None;
    for manifest in manifest_chain {
        let registry =
            VerifiedCompactionTrustRegistryV1::verify(pinned_root_key, manifest)?;
        if registry.owner_id().as_str() != owner_id {
            return Err(CompactionCoordinatorErrorV2::Invalid(
                "signed manifest owner differs from the durable owner",
            ));
        }
        if let Some(prior) = &previous {
            registry.validate_successor_of(prior)?;
        } else if registry.manifest().sequence != 1
            || registry.manifest().predecessor_manifest_digest.is_some()
        {
            return Err(CompactionCoordinatorErrorV2::Invalid(
                "manifest chain must begin with the root generation",
            ));
        }
        previous = Some(registry);
    }
    let active = previous.ok_or(CompactionCoordinatorErrorV2::Invalid(
        "signed trust manifest chain is empty",
    ))?;
    active.validate_current_at(now_unix_seconds)?;
    Ok(active)
}

async fn verify_durable_manifest_preflight(
    pool: &SqlitePool,
    owner_id: &str,
    expected_manifest: Digest32,
    expected_root: Digest32,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let table_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM sqlite_master
         WHERE type = 'table'
           AND name IN (
             'compaction_manifest_log_v2',
             'active_compaction_manifest_v2'
           )",
    )
    .fetch_one(pool)
    .await
    .map_err(sql_error)?;
    if table_count == 0 {
        return Ok(());
    }
    if table_count != 2 {
        return Err(manifest_corrupt(
            "durable manifest schema is only partially materialized",
        ));
    }
    let row = sqlx::query(
        "SELECT a.manifest_digest, m.root_key_digest
         FROM active_compaction_manifest_v2 AS a
         JOIN compaction_manifest_log_v2 AS m
           ON m.owner_id = a.owner_id
          AND m.manifest_digest = a.manifest_digest
         WHERE a.owner_id = ?",
    )
    .bind(owner_id)
    .fetch_optional(pool)
    .await
    .map_err(sql_error)?;
    let Some(row) = row else {
        return Ok(());
    };
    let manifest: String = row.try_get("manifest_digest").map_err(sql_error)?;
    let root: String = row.try_get("root_key_digest").map_err(sql_error)?;
    if manifest != expected_manifest.to_string()
        || root != expected_root.to_string()
    {
        return Err(manifest_conflict(
            "supplied manifest chain is stale, forked or bound to another root",
        ));
    }
    Ok(())
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

fn manifest_corrupt(message: impl Into<String>) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Corrupt(
        message.into(),
    ))
}
