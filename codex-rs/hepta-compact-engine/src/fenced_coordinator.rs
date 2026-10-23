//! Durable process fencing, anti-replay admission and source-retention fencing
//! for the canonical compaction checkpoint coordinator.

use std::str::FromStr;

use codex_hepta_types::Digest32;
use sqlx::sqlite::{
    SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous,
};
use sqlx::{Executor, Row, SqliteConnection, SqlitePool};

use crate::coordinator::{
    CompactionCoordinatorErrorV2, CompactionPublicationReceiptV2,
    MemoryCheckpointCoordinatorV2 as CoreCoordinator, VerifiedCompactionSelectionV2,
};
use crate::durable::{DurableCompactionError, DurableCompactionOutboxEventV1};
use crate::{
    CompactionTrustRoleV1, VerifiedCompactionPublicationV1,
    VerifiedCompactionTrustRegistryV1,
};

pub const MEMORY_CHECKPOINT_COORDINATOR_CALLER_V2: &str =
    "memory.checkpoint-coordinator.v2";

const FENCE_SCHEMA: &str = r#"
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS compaction_owner_fence_v2 (
    owner_id TEXT PRIMARY KEY NOT NULL,
    root_key_digest TEXT NOT NULL CHECK (length(root_key_digest) = 64),
    lease_token_digest TEXT NOT NULL CHECK (length(lease_token_digest) = 64),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    lease_expires_at_unix_seconds INTEGER NOT NULL CHECK (lease_expires_at_unix_seconds > 0),
    updated_at_unix_seconds INTEGER NOT NULL CHECK (updated_at_unix_seconds >= 0)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS compaction_manifest_log_v2 (
    owner_id TEXT NOT NULL,
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    predecessor_manifest_digest TEXT CHECK (
        predecessor_manifest_digest IS NULL OR length(predecessor_manifest_digest) = 64
    ),
    root_key_digest TEXT NOT NULL CHECK (length(root_key_digest) = 64),
    manifest_bytes BLOB NOT NULL CHECK (length(manifest_bytes) BETWEEN 1 AND 1048576),
    activated_at_unix_seconds INTEGER NOT NULL CHECK (activated_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, manifest_digest),
    UNIQUE (owner_id, sequence)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS active_compaction_manifest_v2 (
    owner_id TEXT PRIMARY KEY NOT NULL,
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    updated_at_unix_seconds INTEGER NOT NULL CHECK (updated_at_unix_seconds >= 0),
    FOREIGN KEY (owner_id, manifest_digest)
      REFERENCES compaction_manifest_log_v2(owner_id, manifest_digest) ON DELETE RESTRICT
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS compaction_nonce_reservations_v2 (
    owner_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (
        role IN ('retention-selector', 'semantic-generator', 'tokenizer', 'evaluator')
    ),
    key_id TEXT NOT NULL,
    trust_epoch INTEGER NOT NULL CHECK (trust_epoch > 0),
    nonce_digest TEXT NOT NULL CHECK (length(nonce_digest) = 64),
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    idempotency_key TEXT NOT NULL,
    reserved_at_unix_seconds INTEGER NOT NULL CHECK (reserved_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, role, key_id, trust_epoch, nonce_digest)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS compaction_publication_admissions_v2 (
    owner_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    archive_digest TEXT NOT NULL CHECK (length(archive_digest) = 64),
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    root_key_digest TEXT NOT NULL CHECK (length(root_key_digest) = 64),
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    publication_digest TEXT CHECK (
        publication_digest IS NULL OR length(publication_digest) = 64
    ),
    state TEXT NOT NULL CHECK (state IN ('reserved', 'committed')),
    retain_source_until_unix_seconds INTEGER NOT NULL CHECK (
        retain_source_until_unix_seconds >= 0
    ),
    reserved_at_unix_seconds INTEGER NOT NULL CHECK (reserved_at_unix_seconds >= 0),
    committed_at_unix_seconds INTEGER,
    released_at_unix_seconds INTEGER,
    PRIMARY KEY (owner_id, idempotency_key),
    UNIQUE (owner_id, checkpoint_digest)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS compaction_admission_checkpoint_v2
  ON compaction_publication_admissions_v2(owner_id, checkpoint_digest, state);
CREATE TRIGGER IF NOT EXISTS compaction_manifest_log_v2_no_update
BEFORE UPDATE ON compaction_manifest_log_v2 BEGIN
  SELECT RAISE(ABORT, 'signed compaction manifests are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_manifest_log_v2_no_delete
BEFORE DELETE ON compaction_manifest_log_v2 BEGIN
  SELECT RAISE(ABORT, 'signed compaction manifests are append-only');
END;
CREATE TRIGGER IF NOT EXISTS compaction_nonce_reservations_v2_no_update
BEFORE UPDATE ON compaction_nonce_reservations_v2 BEGIN
  SELECT RAISE(ABORT, 'compaction nonce reservations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_nonce_reservations_v2_no_delete
BEFORE DELETE ON compaction_nonce_reservations_v2 BEGIN
  SELECT RAISE(ABORT, 'compaction nonce reservations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS compaction_admission_identity_v2
BEFORE UPDATE ON compaction_publication_admissions_v2
WHEN NEW.owner_id != OLD.owner_id
 OR NEW.idempotency_key != OLD.idempotency_key
 OR NEW.request_digest != OLD.request_digest
 OR NEW.archive_digest != OLD.archive_digest
 OR NEW.checkpoint_digest != OLD.checkpoint_digest
 OR NEW.root_key_digest != OLD.root_key_digest
 OR NEW.manifest_digest != OLD.manifest_digest
 OR NEW.retain_source_until_unix_seconds != OLD.retain_source_until_unix_seconds
 OR NEW.reserved_at_unix_seconds != OLD.reserved_at_unix_seconds
 OR (OLD.state = 'committed' AND NEW.state != 'committed')
BEGIN
  SELECT RAISE(ABORT, 'compaction admission identity is immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_admission_v2_no_delete
BEFORE DELETE ON compaction_publication_admissions_v2 BEGIN
  SELECT RAISE(ABORT, 'compaction admissions are append-only');
END;
"#;

/// Product-facing durable checkpoint owner.
///
/// A live instance owns one expiring, monotonic lease. Every signed nonce is
/// durably reserved before the inner atomic publication transaction starts.
#[derive(Clone)]
pub struct MemoryCheckpointCoordinatorV2 {
    inner: CoreCoordinator,
    metadata: SqlitePool,
    pinned_root_key: [u8; 32],
    root_key_digest: Digest32,
    lease_token_digest: Digest32,
    lease_epoch: u64,
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
        validate_lease(
            lease_token,
            lease_epoch,
            lease_expires_at_unix_seconds,
            now_unix_seconds,
        )?;
        let root_key_digest = Digest32::of_bytes(&pinned_root_key);
        let lease_token_digest = Digest32::of_bytes(lease_token.as_bytes());
        let metadata = open_pool(database_url).await?;
        sqlx::raw_sql(FENCE_SCHEMA)
            .execute(&metadata)
            .await
            .map_err(sql_error)?;
        persist_manifest_chain(
            &metadata,
            owner_id,
            pinned_root_key,
            manifest_chain,
            now_unix_seconds,
        )
        .await?;
        acquire_fence(
            &metadata,
            owner_id,
            root_key_digest,
            lease_token_digest,
            lease_epoch,
            lease_expires_at_unix_seconds,
            now_unix_seconds,
        )
        .await?;
        let inner = CoreCoordinator::open_with_manifest_chain(
            database_url,
            owner_id,
            pinned_root_key,
            manifest_chain,
            now_unix_seconds,
        )
        .await?;
        let value = Self {
            inner,
            metadata,
            pinned_root_key,
            root_key_digest,
            lease_token_digest,
            lease_epoch,
        };
        value.verify_fence(now_unix_seconds).await?;
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
        if lease_expires_at_unix_seconds <= now_unix_seconds {
            return Err(CompactionCoordinatorErrorV2::Invalid(
                "renewed owner lease must expire in the future",
            ));
        }
        let changed = sqlx::query(
            "UPDATE compaction_owner_fence_v2
             SET lease_expires_at_unix_seconds = ?, updated_at_unix_seconds = ?
             WHERE owner_id = ? AND root_key_digest = ?
               AND lease_token_digest = ? AND lease_epoch = ?
               AND lease_expires_at_unix_seconds > ?
               AND lease_expires_at_unix_seconds <= ?",
        )
        .bind(to_i64(lease_expires_at_unix_seconds, "lease expiry")?)
        .bind(to_i64(now_unix_seconds, "lease update time")?)
        .bind(self.owner_id())
        .bind(self.root_key_digest.to_string())
        .bind(self.lease_token_digest.to_string())
        .bind(to_i64(self.lease_epoch, "lease epoch")?)
        .bind(to_i64(now_unix_seconds, "lease verification time")?)
        .bind(to_i64(lease_expires_at_unix_seconds, "lease expiry")?)
        .execute(&self.metadata)
        .await
        .map_err(sql_error)?
        .rows_affected();
        if changed != 1 {
            return Err(fenced("owner lease renewal lost its durable fence"));
        }
        Ok(())
    }

    pub async fn install_successor_manifest(
        &mut self,
        manifest_bytes: &[u8],
        now_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
        self.verify_fence(now_unix_seconds).await?;
        let mut candidate = self.inner.clone();
        let digest = candidate.install_successor_manifest(manifest_bytes, now_unix_seconds)?;
        let registry = VerifiedCompactionTrustRegistryV1::verify(
            self.pinned_root_key,
            manifest_bytes,
        )?;
        persist_one_manifest(
            &self.metadata,
            self.owner_id(),
            &registry,
            manifest_bytes,
            now_unix_seconds,
        )
        .await?;
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
        self.verify_fence(now_unix_seconds).await?;
        reserve_publication(
            &self.metadata,
            self.owner_id(),
            self.root_key_digest,
            self.active_registry_digest(),
            self.lease_token_digest,
            self.lease_epoch,
            idempotency_key,
            publication,
            retain_source_until_unix_seconds,
            now_unix_seconds,
        )
        .await?;
        let receipt = self
            .inner
            .publish_verified_checkpoint(
                idempotency_key,
                publication,
                retain_source_until_unix_seconds,
                now_unix_seconds,
            )
            .await?;
        finalize_publication(
            &self.metadata,
            self.owner_id(),
            idempotency_key,
            receipt.publication_digest,
            now_unix_seconds,
        )
        .await?;
        Ok(receipt)
    }

    pub async fn recover_current_checkpoint(
        &self,
        scope_id: &str,
        purpose_id: &str,
        now_unix_seconds: u64,
    ) -> Result<Option<VerifiedCompactionSelectionV2>, CompactionCoordinatorErrorV2> {
        self.verify_fence(now_unix_seconds).await?;
        let Some(selection) = self
            .inner
            .recover_current_checkpoint(scope_id, purpose_id, now_unix_seconds)
            .await?
        else {
            return Ok(None);
        };
        reconcile_admission(
            &self.metadata,
            self.owner_id(),
            selection.checkpoint_digest(),
            selection.publication_digest(),
            now_unix_seconds,
        )
        .await?;
        Ok(Some(selection))
    }

    pub async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, CompactionCoordinatorErrorV2> {
        self.verify_fence(revoked_at_unix_seconds).await?;
        self.inner
            .revoke_checkpoint(checkpoint_digest, reason_digest, revoked_at_unix_seconds)
            .await
    }

    /// Release the parent-source reservation only after the checkpoint is
    /// revoked, its outbox is settled, its retention deadline has elapsed and
    /// no live child checkpoint still depends on it.
    pub async fn release_source_retention(
        &self,
        checkpoint_digest: Digest32,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.verify_fence(now_unix_seconds).await?;
        let mut connection = self.metadata.acquire().await.map_err(sql_error)?;
        begin_immediate(&mut connection).await?;
        let result = release_source_retention_tx(
            &mut connection,
            self.owner_id(),
            checkpoint_digest,
            now_unix_seconds,
        )
        .await;
        finish_transaction(&mut connection, result).await
    }

    pub async fn claim_next_outbox(
        &self,
        now_unix_seconds: u64,
        claim_token: &str,
    ) -> Result<Option<DurableCompactionOutboxEventV1>, CompactionCoordinatorErrorV2> {
        self.verify_fence(now_unix_seconds).await?;
        self.inner
            .claim_next_outbox(now_unix_seconds, claim_token)
            .await
    }

    pub async fn complete_outbox(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.verify_fence(delivered_at_unix_seconds).await?;
        self.inner
            .complete_outbox(event, delivered_at_unix_seconds)
            .await
    }

    pub async fn reconcile_claims(
        &self,
        retry_at_unix_seconds: u64,
    ) -> Result<u64, CompactionCoordinatorErrorV2> {
        self.verify_fence(retry_at_unix_seconds).await?;
        self.inner.reconcile_claims(retry_at_unix_seconds).await
    }

    pub async fn verify_integrity(
        &self,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        self.verify_fence(now_unix_seconds).await?;
        self.inner.verify_integrity().await?;
        let result: String = sqlx::query_scalar("PRAGMA integrity_check")
            .fetch_one(&self.metadata)
            .await
            .map_err(sql_error)?;
        if result != "ok" {
            return Err(corrupt(
                "SQLite integrity_check rejected compaction metadata",
            ));
        }
        Ok(())
    }

    async fn verify_fence(
        &self,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        let row = sqlx::query(
            "SELECT root_key_digest, lease_token_digest, lease_epoch,
                    lease_expires_at_unix_seconds
             FROM compaction_owner_fence_v2 WHERE owner_id = ?",
        )
        .bind(self.owner_id())
        .fetch_optional(&self.metadata)
        .await
        .map_err(sql_error)?
        .ok_or_else(|| fenced("durable owner fence is absent"))?;
        let root: String = row.try_get("root_key_digest").map_err(sql_error)?;
        let token: String = row.try_get("lease_token_digest").map_err(sql_error)?;
        let epoch: i64 = row.try_get("lease_epoch").map_err(sql_error)?;
        let expires: i64 = row
            .try_get("lease_expires_at_unix_seconds")
            .map_err(sql_error)?;
        if root != self.root_key_digest.to_string()
            || token != self.lease_token_digest.to_string()
            || u64::try_from(epoch).ok() != Some(self.lease_epoch)
            || u64::try_from(expires)
                .ok()
                .is_none_or(|value| value <= now_unix_seconds)
        {
            return Err(fenced(
                "durable owner lease is stale, replaced or expired",
            ));
        }
        Ok(())
    }
}

async fn open_pool(database_url: &str) -> Result<SqlitePool, CompactionCoordinatorErrorV2> {
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

async fn persist_manifest_chain(
    pool: &SqlitePool,
    owner_id: &str,
    pinned_root_key: [u8; 32],
    chain: &[Vec<u8>],
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let mut previous: Option<VerifiedCompactionTrustRegistryV1> = None;
    for bytes in chain {
        let registry = VerifiedCompactionTrustRegistryV1::verify(pinned_root_key, bytes)?;
        if registry.owner_id().as_str() != owner_id {
            return Err(CompactionCoordinatorErrorV2::Invalid(
                "signed manifest owner differs from owner fence",
            ));
        }
        if let Some(prior) = &previous {
            registry.validate_successor_of(prior)?;
        }
        persist_one_manifest(pool, owner_id, &registry, bytes, now).await?;
        previous = Some(registry);
    }
    Ok(())
}

async fn persist_one_manifest(
    pool: &SqlitePool,
    owner_id: &str,
    registry: &VerifiedCompactionTrustRegistryV1,
    bytes: &[u8],
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let mut connection = pool.acquire().await.map_err(sql_error)?;
    begin_immediate(&mut connection).await?;
    let result = async {
        let existing = sqlx::query(
            "SELECT manifest_bytes, sequence, predecessor_manifest_digest,
                    root_key_digest
             FROM compaction_manifest_log_v2
             WHERE owner_id = ? AND manifest_digest = ?",
        )
        .bind(owner_id)
        .bind(registry.manifest_digest().to_string())
        .fetch_optional(&mut *connection)
        .await
        .map_err(sql_error)?;
        if let Some(row) = existing {
            let stored: Vec<u8> = row.try_get("manifest_bytes").map_err(sql_error)?;
            let sequence: i64 = row.try_get("sequence").map_err(sql_error)?;
            let predecessor: Option<String> = row
                .try_get("predecessor_manifest_digest")
                .map_err(sql_error)?;
            let root: String = row.try_get("root_key_digest").map_err(sql_error)?;
            if stored != bytes
                || u64::try_from(sequence).ok() != Some(registry.manifest().sequence)
                || predecessor
                    != registry
                        .manifest()
                        .predecessor_manifest_digest
                        .map(|value| value.to_string())
                || root != registry.root_key_digest().to_string()
            {
                return Err(corrupt("signed manifest identity drift"));
            }
        } else {
            sqlx::query(
                "INSERT INTO compaction_manifest_log_v2
                 (owner_id, manifest_digest, sequence,
                  predecessor_manifest_digest, root_key_digest, manifest_bytes,
                  activated_at_unix_seconds)
                 VALUES (?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(owner_id)
            .bind(registry.manifest_digest().to_string())
            .bind(to_i64(registry.manifest().sequence, "manifest sequence")?)
            .bind(
                registry
                    .manifest()
                    .predecessor_manifest_digest
                    .map(|value| value.to_string()),
            )
            .bind(registry.root_key_digest().to_string())
            .bind(bytes)
            .bind(to_i64(now, "manifest activation time")?)
            .execute(&mut *connection)
            .await
            .map_err(sql_error)?;
        }

        let active = sqlx::query(
            "SELECT manifest_digest, sequence FROM active_compaction_manifest_v2
             WHERE owner_id = ?",
        )
        .bind(owner_id)
        .fetch_optional(&mut *connection)
        .await
        .map_err(sql_error)?;
        match active {
            None => {
                if registry.manifest().sequence != 1
                    || registry.manifest().predecessor_manifest_digest.is_some()
                {
                    return Err(corrupt(
                        "active manifest history does not begin at sequence one",
                    ));
                }
                sqlx::query(
                    "INSERT INTO active_compaction_manifest_v2
                     (owner_id, manifest_digest, sequence, updated_at_unix_seconds)
                     VALUES (?, ?, 1, ?)",
                )
                .bind(owner_id)
                .bind(registry.manifest_digest().to_string())
                .bind(to_i64(now, "manifest activation time")?)
                .execute(&mut *connection)
                .await
                .map_err(sql_error)?;
            }
            Some(row) => {
                let active_digest: String = row.try_get("manifest_digest").map_err(sql_error)?;
                let active_sequence: i64 = row.try_get("sequence").map_err(sql_error)?;
                let active_sequence = u64::try_from(active_sequence)
                    .map_err(|_| corrupt("negative active manifest sequence"))?;
                if active_digest == registry.manifest_digest().to_string() {
                    if active_sequence != registry.manifest().sequence {
                        return Err(corrupt("active manifest sequence drift"));
                    }
                } else {
                    let predecessor_matches = registry
                        .manifest()
                        .predecessor_manifest_digest
                        .map(|value| value.to_string())
                        .is_some_and(|value| value == active_digest);
                    if active_sequence.checked_add(1) == Some(registry.manifest().sequence)
                        && predecessor_matches
                    {
                        let changed = sqlx::query(
                            "UPDATE active_compaction_manifest_v2
                             SET manifest_digest = ?, sequence = ?,
                                 updated_at_unix_seconds = ?
                             WHERE owner_id = ? AND manifest_digest = ?
                               AND sequence = ?",
                        )
                        .bind(registry.manifest_digest().to_string())
                        .bind(to_i64(registry.manifest().sequence, "manifest sequence")?)
                        .bind(to_i64(now, "manifest activation time")?)
                        .bind(owner_id)
                        .bind(active_digest)
                        .bind(to_i64(active_sequence, "active manifest sequence")?)
                        .execute(&mut *connection)
                        .await
                        .map_err(sql_error)?
                        .rows_affected();
                        if changed != 1 {
                            return Err(fenced("active manifest CAS lost"));
                        }
                    } else if registry.manifest().sequence > active_sequence {
                        return Err(corrupt(
                            "signed manifest history contains a gap or fork",
                        ));
                    }
                }
            }
        }
        Ok(())
    }
    .await;
    finish_transaction(&mut connection, result).await
}

#[allow(clippy::too_many_arguments)]
async fn acquire_fence(
    pool: &SqlitePool,
    owner_id: &str,
    root: Digest32,
    token: Digest32,
    epoch: u64,
    expires: u64,
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let mut connection = pool.acquire().await.map_err(sql_error)?;
    begin_immediate(&mut connection).await?;
    let result = async {
        let existing = sqlx::query(
            "SELECT root_key_digest, lease_token_digest, lease_epoch,
                    lease_expires_at_unix_seconds
             FROM compaction_owner_fence_v2 WHERE owner_id = ?",
        )
        .bind(owner_id)
        .fetch_optional(&mut *connection)
        .await
        .map_err(sql_error)?;
        match existing {
            None => {
                if epoch != 1 {
                    return Err(fenced("first owner lease must use epoch one"));
                }
                sqlx::query(
                    "INSERT INTO compaction_owner_fence_v2
                     (owner_id, root_key_digest, lease_token_digest, lease_epoch,
                      lease_expires_at_unix_seconds, updated_at_unix_seconds)
                     VALUES (?, ?, ?, ?, ?, ?)",
                )
                .bind(owner_id)
                .bind(root.to_string())
                .bind(token.to_string())
                .bind(to_i64(epoch, "lease epoch")?)
                .bind(to_i64(expires, "lease expiry")?)
                .bind(to_i64(now, "lease activation time")?)
                .execute(&mut *connection)
                .await
                .map_err(sql_error)?;
            }
            Some(row) => {
                let old_root: String = row.try_get("root_key_digest").map_err(sql_error)?;
                let old_token: String = row.try_get("lease_token_digest").map_err(sql_error)?;
                let old_epoch: i64 = row.try_get("lease_epoch").map_err(sql_error)?;
                let old_expires: i64 = row
                    .try_get("lease_expires_at_unix_seconds")
                    .map_err(sql_error)?;
                let old_epoch = u64::try_from(old_epoch)
                    .map_err(|_| corrupt("negative owner lease epoch"))?;
                let old_expires = u64::try_from(old_expires)
                    .map_err(|_| corrupt("negative owner lease expiry"))?;
                if old_root != root.to_string() {
                    return Err(fenced("root pin substitution at durable owner"));
                }
                if old_token == token.to_string() && old_epoch == epoch {
                    if expires < old_expires {
                        return Err(fenced("owner lease expiry cannot move backwards"));
                    }
                } else if old_expires > now || old_epoch.checked_add(1) != Some(epoch) {
                    return Err(fenced("live owner lease cannot be replaced"));
                }
                let changed = sqlx::query(
                    "UPDATE compaction_owner_fence_v2
                     SET lease_token_digest = ?, lease_epoch = ?,
                         lease_expires_at_unix_seconds = ?,
                         updated_at_unix_seconds = ?
                     WHERE owner_id = ? AND root_key_digest = ?
                       AND lease_token_digest = ? AND lease_epoch = ?
                       AND lease_expires_at_unix_seconds = ?",
                )
                .bind(token.to_string())
                .bind(to_i64(epoch, "lease epoch")?)
                .bind(to_i64(expires, "lease expiry")?)
                .bind(to_i64(now, "lease activation time")?)
                .bind(owner_id)
                .bind(old_root)
                .bind(old_token)
                .bind(to_i64(old_epoch, "old lease epoch")?)
                .bind(to_i64(old_expires, "old lease expiry")?)
                .execute(&mut *connection)
                .await
                .map_err(sql_error)?
                .rows_affected();
                if changed != 1 {
                    return Err(fenced("owner lease CAS lost"));
                }
            }
        }
        Ok(())
    }
    .await;
    finish_transaction(&mut connection, result).await
}

#[allow(clippy::too_many_arguments)]
async fn reserve_publication(
    pool: &SqlitePool,
    owner_id: &str,
    root: Digest32,
    manifest: Digest32,
    lease_token: Digest32,
    lease_epoch: u64,
    idempotency_key: &str,
    publication: &VerifiedCompactionPublicationV1,
    retain_source_until: u64,
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    if idempotency_key.trim().is_empty() || idempotency_key.len() > 128 {
        return Err(CompactionCoordinatorErrorV2::Invalid(
            "idempotency key must contain 1..=128 bytes",
        ));
    }
    let mut connection = pool.acquire().await.map_err(sql_error)?;
    begin_immediate(&mut connection).await?;
    let result = async {
        verify_fence_tx(
            &mut connection,
            owner_id,
            root,
            lease_token,
            lease_epoch,
            now,
        )
        .await?;
        let checkpoint_digest = publication.candidate().checkpoint().checkpoint_digest;
        let existing = sqlx::query(
            "SELECT request_digest, archive_digest, checkpoint_digest,
                    root_key_digest, manifest_digest,
                    retain_source_until_unix_seconds
             FROM compaction_publication_admissions_v2
             WHERE owner_id = ? AND idempotency_key = ?",
        )
        .bind(owner_id)
        .bind(idempotency_key)
        .fetch_optional(&mut *connection)
        .await
        .map_err(sql_error)?;
        if let Some(row) = existing {
            let request: String = row.try_get("request_digest").map_err(sql_error)?;
            let archive: String = row.try_get("archive_digest").map_err(sql_error)?;
            let checkpoint: String = row.try_get("checkpoint_digest").map_err(sql_error)?;
            let stored_root: String = row.try_get("root_key_digest").map_err(sql_error)?;
            let stored_manifest: String = row.try_get("manifest_digest").map_err(sql_error)?;
            let retain: i64 = row
                .try_get("retain_source_until_unix_seconds")
                .map_err(sql_error)?;
            if request != publication.request_digest().to_string()
                || archive != publication.archive_digest().to_string()
                || checkpoint != checkpoint_digest.to_string()
                || stored_root != root.to_string()
                || stored_manifest != manifest.to_string()
                || u64::try_from(retain).ok() != Some(retain_source_until)
            {
                return Err(fenced(
                    "idempotency key was reserved with different semantics",
                ));
            }
        } else {
            sqlx::query(
                "INSERT INTO compaction_publication_admissions_v2
                 (owner_id, idempotency_key, request_digest, archive_digest,
                  checkpoint_digest, root_key_digest, manifest_digest,
                  publication_digest, state,
                  retain_source_until_unix_seconds, reserved_at_unix_seconds,
                  committed_at_unix_seconds, released_at_unix_seconds)
                 VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'reserved', ?, ?, NULL, NULL)",
            )
            .bind(owner_id)
            .bind(idempotency_key)
            .bind(publication.request_digest().to_string())
            .bind(publication.archive_digest().to_string())
            .bind(checkpoint_digest.to_string())
            .bind(root.to_string())
            .bind(manifest.to_string())
            .bind(to_i64(retain_source_until, "source retention deadline")?)
            .bind(to_i64(now, "publication reservation time")?)
            .execute(&mut *connection)
            .await
            .map_err(sql_error)?;
        }

        for binding in publication.nonce_bindings() {
            let role = role_label(binding.role);
            let changed = sqlx::query(
                "INSERT OR IGNORE INTO compaction_nonce_reservations_v2
                 (owner_id, role, key_id, trust_epoch, nonce_digest,
                  request_digest, idempotency_key, reserved_at_unix_seconds)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(owner_id)
            .bind(role)
            .bind(binding.key_id.as_str())
            .bind(to_i64(binding.trust_epoch, "trust epoch")?)
            .bind(binding.nonce.to_string())
            .bind(publication.request_digest().to_string())
            .bind(idempotency_key)
            .bind(to_i64(now, "nonce reservation time")?)
            .execute(&mut *connection)
            .await
            .map_err(sql_error)?
            .rows_affected();
            if changed == 0 {
                let row = sqlx::query(
                    "SELECT request_digest, idempotency_key
                     FROM compaction_nonce_reservations_v2
                     WHERE owner_id = ? AND role = ? AND key_id = ?
                       AND trust_epoch = ? AND nonce_digest = ?",
                )
                .bind(owner_id)
                .bind(role)
                .bind(binding.key_id.as_str())
                .bind(to_i64(binding.trust_epoch, "trust epoch")?)
                .bind(binding.nonce.to_string())
                .fetch_one(&mut *connection)
                .await
                .map_err(sql_error)?;
                let request: String = row.try_get("request_digest").map_err(sql_error)?;
                let key: String = row.try_get("idempotency_key").map_err(sql_error)?;
                if request != publication.request_digest().to_string()
                    || key != idempotency_key
                {
                    return Err(fenced("signed compaction nonce replay detected"));
                }
            }
        }
        Ok(())
    }
    .await;
    finish_transaction(&mut connection, result).await
}

async fn finalize_publication(
    pool: &SqlitePool,
    owner_id: &str,
    idempotency_key: &str,
    publication_digest: Digest32,
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let changed = sqlx::query(
        "UPDATE compaction_publication_admissions_v2
         SET publication_digest = ?, state = 'committed',
             committed_at_unix_seconds = COALESCE(committed_at_unix_seconds, ?)
         WHERE owner_id = ? AND idempotency_key = ?
           AND (publication_digest IS NULL OR publication_digest = ?)",
    )
    .bind(publication_digest.to_string())
    .bind(to_i64(now, "publication commit time")?)
    .bind(owner_id)
    .bind(idempotency_key)
    .bind(publication_digest.to_string())
    .execute(pool)
    .await
    .map_err(sql_error)?
    .rows_affected();
    if changed != 1 {
        return Err(corrupt(
            "durable publication admission did not finalize exactly once",
        ));
    }
    Ok(())
}

async fn reconcile_admission(
    pool: &SqlitePool,
    owner_id: &str,
    checkpoint_digest: Digest32,
    publication_digest: Digest32,
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let row = sqlx::query(
        "SELECT idempotency_key, publication_digest, state
         FROM compaction_publication_admissions_v2
         WHERE owner_id = ? AND checkpoint_digest = ?",
    )
    .bind(owner_id)
    .bind(checkpoint_digest.to_string())
    .fetch_optional(pool)
    .await
    .map_err(sql_error)?
    .ok_or_else(|| corrupt("checkpoint has no root-bound publication admission"))?;
    let key: String = row.try_get("idempotency_key").map_err(sql_error)?;
    let stored: Option<String> = row.try_get("publication_digest").map_err(sql_error)?;
    let state: String = row.try_get("state").map_err(sql_error)?;
    if stored
        .as_ref()
        .is_some_and(|value| value != &publication_digest.to_string())
    {
        return Err(corrupt(
            "publication admission digest differs from checkpoint",
        ));
    }
    if state == "reserved" {
        finalize_publication(pool, owner_id, &key, publication_digest, now).await?;
    } else if state != "committed" {
        return Err(corrupt("unknown publication admission state"));
    }
    Ok(())
}

async fn release_source_retention_tx(
    connection: &mut SqliteConnection,
    owner_id: &str,
    checkpoint_digest: Digest32,
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let admission = sqlx::query(
        "SELECT publication_digest, retain_source_until_unix_seconds,
                released_at_unix_seconds, state
         FROM compaction_publication_admissions_v2
         WHERE owner_id = ? AND checkpoint_digest = ?",
    )
    .bind(owner_id)
    .bind(checkpoint_digest.to_string())
    .fetch_optional(&mut *connection)
    .await
    .map_err(sql_error)?
    .ok_or_else(|| corrupt("source retention admission is absent"))?;
    let publication: Option<String> = admission
        .try_get("publication_digest")
        .map_err(sql_error)?;
    let deadline: i64 = admission
        .try_get("retain_source_until_unix_seconds")
        .map_err(sql_error)?;
    let released: Option<i64> = admission
        .try_get("released_at_unix_seconds")
        .map_err(sql_error)?;
    let state: String = admission.try_get("state").map_err(sql_error)?;
    if released.is_some() {
        return Ok(());
    }
    if state != "committed"
        || u64::try_from(deadline).ok().is_none_or(|value| value > now)
    {
        return Err(fenced("source retention is not releasable yet"));
    }
    let publication = publication
        .ok_or_else(|| corrupt("committed admission lacks publication digest"))?;
    let revoked: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM compaction_checkpoint_revocations
         WHERE owner_id = ? AND checkpoint_digest = ?",
    )
    .bind(owner_id)
    .bind(checkpoint_digest.to_string())
    .fetch_one(&mut *connection)
    .await
    .map_err(sql_error)?;
    if revoked != 1 {
        return Err(fenced("source retention requires checkpoint revocation"));
    }
    let undelivered: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM compaction_outbox
         WHERE owner_id = ? AND publication_digest = ?
           AND state NOT IN ('delivered', 'terminal-failure')",
    )
    .bind(owner_id)
    .bind(publication)
    .fetch_one(&mut *connection)
    .await
    .map_err(sql_error)?;
    if undelivered != 0 {
        return Err(fenced("source retention waits for outbox settlement"));
    }
    let dependent: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM compaction_checkpoints child
         LEFT JOIN compaction_checkpoint_revocations revoked
           ON revoked.owner_id = child.owner_id
          AND revoked.checkpoint_digest = child.checkpoint_digest
         WHERE child.owner_id = ?
           AND child.predecessor_checkpoint_digest = ?
           AND revoked.checkpoint_digest IS NULL",
    )
    .bind(owner_id)
    .bind(checkpoint_digest.to_string())
    .fetch_one(&mut *connection)
    .await
    .map_err(sql_error)?;
    if dependent != 0 {
        return Err(fenced(
            "an unrevoked child still depends on the source checkpoint",
        ));
    }
    let changed = sqlx::query(
        "UPDATE compaction_publication_admissions_v2
         SET released_at_unix_seconds = ?
         WHERE owner_id = ? AND checkpoint_digest = ?
           AND released_at_unix_seconds IS NULL",
    )
    .bind(to_i64(now, "source release time")?)
    .bind(owner_id)
    .bind(checkpoint_digest.to_string())
    .execute(&mut *connection)
    .await
    .map_err(sql_error)?
    .rows_affected();
    if changed != 1 {
        return Err(fenced("source retention release CAS lost"));
    }
    Ok(())
}

async fn verify_fence_tx(
    connection: &mut SqliteConnection,
    owner_id: &str,
    root: Digest32,
    token: Digest32,
    epoch: u64,
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM compaction_owner_fence_v2
         WHERE owner_id = ? AND root_key_digest = ?
           AND lease_token_digest = ? AND lease_epoch = ?
           AND lease_expires_at_unix_seconds > ?",
    )
    .bind(owner_id)
    .bind(root.to_string())
    .bind(token.to_string())
    .bind(to_i64(epoch, "lease epoch")?)
    .bind(to_i64(now, "lease verification time")?)
    .fetch_one(&mut *connection)
    .await
    .map_err(sql_error)?;
    if count != 1 {
        return Err(fenced("publication lost its durable owner fence"));
    }
    Ok(())
}

async fn begin_immediate(
    connection: &mut SqliteConnection,
) -> Result<(), CompactionCoordinatorErrorV2> {
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut *connection)
        .await
        .map_err(sql_error)?;
    Ok(())
}

async fn finish_transaction<T>(
    connection: &mut SqliteConnection,
    result: Result<T, CompactionCoordinatorErrorV2>,
) -> Result<T, CompactionCoordinatorErrorV2> {
    match result {
        Ok(value) => {
            sqlx::query("COMMIT")
                .execute(&mut *connection)
                .await
                .map_err(sql_error)?;
            Ok(value)
        }
        Err(error) => {
            let _ = sqlx::query("ROLLBACK").execute(&mut *connection).await;
            Err(error)
        }
    }
}

fn validate_lease(
    token: &str,
    epoch: u64,
    expires: u64,
    now: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    if token.trim().is_empty() || token.len() > 256 || epoch == 0 || expires <= now {
        return Err(CompactionCoordinatorErrorV2::Invalid(
            "owner lease requires a non-empty token, non-zero epoch and future expiry",
        ));
    }
    Ok(())
}

fn role_label(role: CompactionTrustRoleV1) -> &'static str {
    match role {
        CompactionTrustRoleV1::RetentionSelector => "retention-selector",
        CompactionTrustRoleV1::SemanticGenerator => "semantic-generator",
        CompactionTrustRoleV1::Tokenizer => "tokenizer",
        CompactionTrustRoleV1::Evaluator => "evaluator",
    }
}

fn to_i64(value: u64, field: &'static str) -> Result<i64, CompactionCoordinatorErrorV2> {
    i64::try_from(value).map_err(|_| CompactionCoordinatorErrorV2::Invalid(field))
}

fn sql_error(error: sqlx::Error) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Sql(error))
}

fn fenced(message: &'static str) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Conflict(message.to_string()))
}

fn corrupt(message: &'static str) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Corrupt(message.to_string()))
}
